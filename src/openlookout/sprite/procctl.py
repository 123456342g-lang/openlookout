"""真实进程动作：只“挂起/恢复”，从不结束进程。带持久日志、数量与内存上限、硬性黑名单，精灵退出/崩溃时由看门狗自动恢复。
后端可替换：WinBackend（ctypes NtSuspendProcess/NtResumeProcess，真实 Windows）、PosixBackend（SIGSTOP/SIGCONT，Linux/mac 测试用）。
live=False（干跑）时不做任何系统调用，只记录“将会挂起谁”。"""
from __future__ import annotations
import atexit, json, os, re, subprocess, sys, time
from pathlib import Path

DENY_NAMES = {"system", "idle", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost", "dwm", "explorer", "fontdrvhost", "sihost", "taskhostw",
              "ctfmon", "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "runtimebroker", "audiodg", "msmpeng", "nissrv", "securityhealthservice",
              "python", "pythonw", "python3", "py", "pyw", "cmd", "powershell", "pwsh", "conhost", "wt", "windowsterminal", "openconsole", "bash", "sh", "zsh", "ssh", "sshd",
              "code", "cursor", "notepad", "notepad++", "winword", "excel", "powerpnt", "pycharm64", "idea64", "devenv", "sublime_text", "typora", "obsidian", "wps", "et", "wpp",
              "sprite", "eat_memory", "openlookout", "docker", "dockerd", "postgres", "mysqld", "mongod", "redis-server", "vmmem", "vmmemwsl"}
DENY_RE = re.compile(r"(defender|antivirus|security|firewall|avast|kaspersky|norton|mcafee|huorong|火绒|360|driver|vpn|input|ime)", re.I)


class PosixBackend:
    def suspend(self, pid): import signal; os.kill(pid, signal.SIGSTOP); return True
    def resume(self, pid): import signal; os.kill(pid, signal.SIGCONT); return True
    def ident(self, pid):
        try: return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]        # starttime
        except Exception: return None
    def alive(self, pid): return self.ident(pid) is not None
    def name(self, pid):
        try: return open(f"/proc/{pid}/comm").read().strip().lower()
        except Exception: return None


class WinBackend:
    def _open(self, pid, access):
        import ctypes; return ctypes.windll.kernel32.OpenProcess(access, False, pid)
    def suspend(self, pid):
        import ctypes
        h = self._open(pid, 0x0800)
        if not h: return False
        r = ctypes.windll.ntdll.NtSuspendProcess(h); ctypes.windll.kernel32.CloseHandle(h); return r == 0
    def resume(self, pid):
        import ctypes
        h = self._open(pid, 0x0800)
        if not h: return False
        r = ctypes.windll.ntdll.NtResumeProcess(h); ctypes.windll.kernel32.CloseHandle(h); return r == 0
    def ident(self, pid):
        import ctypes
        from ctypes import wintypes as W
        h = self._open(pid, 0x1000)
        if not h: return None
        c, e, k, u = (W.FILETIME() for _ in range(4))
        ok = ctypes.windll.kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)); ctypes.windll.kernel32.CloseHandle(h)
        return (c.dwHighDateTime << 32 | c.dwLowDateTime) if ok else None
    def alive(self, pid): return self.ident(pid) is not None
    def name(self, pid):
        import ctypes
        h = self._open(pid, 0x1000)
        if not h: return None
        buf = ctypes.create_unicode_buffer(1024); n = ctypes.c_ulong(1024)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)); ctypes.windll.kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower().removesuffix(".exe") if ok else None
    def trim(self, pid):
        import ctypes
        h = self._open(pid, 0x0500)
        if not h: return False
        r = ctypes.windll.psapi.EmptyWorkingSet(h); ctypes.windll.kernel32.CloseHandle(h); return bool(r)


def default_backend(): return WinBackend() if os.name == "nt" else PosixBackend()


def own_chain() -> set:
    """本进程及其所有祖先（启动精灵的终端/bat 等）：永不挂起。"""
    out = {os.getpid()}
    try:
        import psutil
        p = psutil.Process(); out |= {a.pid for a in p.parents()}
    except Exception: out.add(os.getppid())
    return out


class JournaledController:
    def __init__(self, home: Path, backend=None, live=True, max_n=6, max_rss_mb=4096, allow_only=None, spawn_watchdog=True, extra_deny=(), log=None):
        self.home = Path(home); self.be = backend or default_backend(); self.live = live; self.max_n, self.max_rss = max_n, max_rss_mb
        self.allow_only = set(allow_only) if allow_only is not None else None; self.spawn = spawn_watchdog and live
        self.deny = DENY_NAMES | {x.lower() for x in extra_deny}; self.protect_pids = own_chain()
        self.jf = self.home / "suspended.json"; self.would = []; self._dry = {}; self.refused = []; self.log = log or (lambda *a: None)
        self._wd = None
        if live: atexit.register(self.resume_all)

    # ---- 日志（持久，崩溃后也能恢复）
    def _load(self) -> dict:
        try: return json.loads(self.jf.read_text("utf-8")) if self.jf.exists() else {}
        except Exception: return {}
    def _save(self, d):
        tmp = self.jf.with_suffix(".tmp"); tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8"); os.replace(tmp, self.jf)

    @property
    def suspended(self) -> dict:
        d = {int(k): v for k, v in self._load().items()} if self.live else {}
        d.update(self._dry); return d

    def _refuse(self, pid, why): self.refused.append((pid, why)); self.log(f"拒绝挂起 {pid}：{why}"); return False

    def suspend(self, pid, name=None, rss_mb=0, **kw) -> bool:
        pid = int(pid); nm = (name or self.be.name(pid) or "").lower().removesuffix(".exe")
        if pid in self.protect_pids: return self._refuse(pid, "是精灵自己/它的启动者")
        if not nm: return self._refuse(pid, "查不到进程名")
        if nm in self.deny or DENY_RE.search(nm): return self._refuse(pid, f"{nm} 在硬性黑名单")
        if self.allow_only is not None and pid not in self.allow_only: return self._refuse(pid, "不在允许名单（测试限制）")
        cur = self._load() if self.live else self._dry
        if str(pid) in cur or pid in cur: return True
        if len(cur) >= self.max_n: return self._refuse(pid, f"已挂起 {len(cur)} 个，达到数量上限")
        if sum(v.get("rss_mb", 0) for v in cur.values()) + rss_mb > self.max_rss: return self._refuse(pid, "累计内存上限")
        if not self.live:
            self._dry[pid] = dict(name=nm, rss_mb=rss_mb, ts=time.time()); self.would.append((pid, nm, rss_mb)); self.log(f"[干跑] 将会挂起 {nm}#{pid}（{rss_mb:.0f}MB）"); return True
        ident = self.be.ident(pid)
        if ident is None: return self._refuse(pid, "进程已不存在")
        d = self._load(); d[str(pid)] = dict(name=nm, ident=str(ident), rss_mb=rss_mb, ts=time.time(), owner=os.getpid()); self._save(d)       # 先记日志再动手
        ok = False
        try: ok = bool(self.be.suspend(pid))
        finally:
            if not ok: d = self._load(); d.pop(str(pid), None); self._save(d)
        if ok: self._ensure_watchdog()
        return ok

    def resume(self, pid, **kw) -> bool:
        pid = int(pid)
        if not self.live: self._dry.pop(pid, None); return True
        d = self._load(); e = d.get(str(pid))
        if e is None: return True
        ok = True
        if self.be.alive(pid) and str(self.be.ident(pid)) == e["ident"]: ok = bool(self.be.resume(pid))          # PID 被复用就不碰
        if ok: d = self._load(); d.pop(str(pid), None); self._save(d)
        return ok

    def resume_all(self) -> int:
        n = 0
        for pid in list(self._load()):
            n += bool(self.resume(int(pid)))
        self._dry.clear(); return n

    def trim(self, pid):
        if not self.live: return True
        fn = getattr(self.be, "trim", None); return bool(fn(pid)) if fn else True

    # ---- 看门狗：精灵退出/崩溃（含被强杀）就恢复全部
    def _ensure_watchdog(self):
        if not self.spawn or (self._wd and self._wd.poll() is None): return
        flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0       # DETACHED_PROCESS | CREATE_NO_WINDOW
        exe = sys.executable
        if os.name == "nt" and exe.lower().endswith("python.exe") and (Path(exe).with_name("pythonw.exe")).exists(): exe = str(Path(exe).with_name("pythonw.exe"))
        pkg_root = str(Path(__file__).resolve().parent.parent)
        self._wd = subprocess.Popen([exe, "-m", "sprite.procctl", "--watch", str(os.getpid()), "--journal", str(self.jf)], cwd=pkg_root, creationflags=flags,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **({} if os.name == "nt" else dict(start_new_session=True)))


def pending(home: Path) -> list:
    """当前被本精灵挂起、尚未恢复的 pid 列表。只读日志，不做任何系统调用（给评估/撤销用）。"""
    return sorted(_read_journal(Path(home)))


def _read_journal(home: Path) -> dict:
    f = Path(home) / "suspended.json"
    try: return {int(k): v for k, v in json.loads(f.read_text("utf-8")).items()} if f.exists() else {}
    except Exception: return {}


def resume_from_journal(journal: Path, backend=None) -> int:
    c = JournaledController(Path(journal).parent, backend, live=True, spawn_watchdog=False); c.jf = Path(journal)
    atexit.unregister(c.resume_all); return c.resume_all()


def _alive(pid):
    be = default_backend(); return be.alive(pid)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--watch", type=int); ap.add_argument("--journal", required=True); ap.add_argument("--resume-all", action="store_true"); a = ap.parse_args(argv)
    if a.resume_all: print("已恢复", resume_from_journal(Path(a.journal)), "个进程"); return
    while _alive(a.watch): time.sleep(2)
    resume_from_journal(Path(a.journal))


if __name__ == "__main__":
    main()
