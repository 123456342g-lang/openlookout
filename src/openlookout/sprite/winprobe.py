"""真实 Windows 进程探针（分层降级）：
 L1 psutil（可选，pip install psutil）：进程、父进程、cpu_times、工作集、cwd、命令行。
 L2 ctypes（无需任何依赖）：EnumWindows/GetForegroundWindow 得到 窗口标题/可见/前台；音频会话用 pycaw（可选）否则标记“未知”。
 L3 tasklist /v /fo csv（兜底）：名称/PID/内存/窗口标题/CPU 时间，没有父进程信息。
每一层缺失时对应字段是“未知”，分类器遇到未知一律保守（不动）。
空闲时间 idle_s 靠 CpuTracker 在连续快照间比较 CPU 时间得到：只有观察过足够久才会声称“空闲了多久”。
所有 OS 调用都隔离在可替换的后端对象里，测试用假后端。"""
from __future__ import annotations
import csv, ctypes, io, os, re, subprocess, sys
from .sysstate import Proc, Snapshot

UNSAVED_MARKS = ("*", "●", "未保存", "unsaved", "Untitled", "无标题")


def memory():
    """{total, available, used, frac}，单位 MB，跨平台同一口径。可用内存是所有判断的基准，所以单列一个函数。"""
    if os.name == "nt":
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        m = MS(); m.l = ctypes.sizeof(MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)): raise OSError("GlobalMemoryStatusEx 失败")
        total, avail = m.tp / 2**20, m.ap / 2**20
    else:
        info = {}
        for line in open("/proc/meminfo"):
            k, _, rest = line.partition(":")
            info[k] = float(rest.split()[0])
        total, avail = info["MemTotal"] / 1024, info["MemAvailable"] / 1024
    return {"total": total, "available": avail, "used": total - avail, "frac": (avail / total) if total else 0.0}


def session_of(pid) -> int:
    """进程所在的 Windows 会话号；查不到当 0（服务会话）——保守，等于被判成系统进程。"""
    if os.name != "nt": return 0
    import ctypes
    sid = ctypes.c_ulong()
    return sid.value if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)) else 0


def _pe_subsystem(path) -> int | None:
    """PE 头 OptionalHeader 里的 Subsystem：2=窗口程序，3=控制台程序。读不到返回 None。"""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"MZ": return None
            f.seek(0x3C); pe = int.from_bytes(f.read(4), "little")
            if pe <= 0: return None
            f.seek(pe)
            if f.read(4) != b"PE\0\0": return None
            f.seek(pe + 0x5C)                                   # COFF 头 20 + OptionalHeader 内偏移 68（PE32/PE32+ 同）
            return int.from_bytes(f.read(2), "little")
    except Exception: return None


_SUB_CACHE: dict = {}
def is_console(path) -> bool:
    """是不是控制台程序。同一路径只读一次头（几百个进程通常只对应十几个 exe）。"""
    k = str(path)
    if k not in _SUB_CACHE: _SUB_CACHE[k] = (_pe_subsystem(path) == 3)
    return _SUB_CACHE[k]


def _username(p) -> str:
    """属主（DOMAIN\\user）。取不到返回 ""，调用方据此判定“权限不足/受保护”。"""
    try: return p.username() or ""
    except Exception: return ""


def _exe(p) -> str:
    try: return p.exe() or ""
    except Exception: return ""


def _create(p) -> float:
    """进程创建时间。取不到返回 0.0——decide 会把 create=0 视为“已存活足够久”，
    但真正决定能不能动的是 idle_s/rss 等其他门，缺一个时间戳不该让整个进程从观察中消失。"""
    try: return float(p.create_time())
    except Exception: return 0.0


def _current_user() -> str:
    try:
        import getpass
        u = getpass.getuser()
        return u if "\\" in u else f"{os.environ.get('USERDOMAIN', '')}\\{u}"
    except Exception: return ""


class CpuTracker:
    """连续快照间 CPU 时间几乎不变 => 空闲；返回已经空闲的秒数（从首次观察起算，不会凭空多算）。"""
    def __init__(self, eps_frac=0.005): self.last = {}; self.idle_since = {}; self.busy_since = {}; self.eps = eps_frac
    def update(self, pid, cpu_s, t) -> float:
        prev = self.last.get(pid); self.last[pid] = (cpu_s, t)
        if prev is None: self.idle_since[pid] = None; return 0.0
        dt = max(t - prev[1], 1e-6); busy = (cpu_s - prev[0]) / dt
        if busy > 0.9: self.busy_since.setdefault(pid, prev[1])
        else: self.busy_since.pop(pid, None)
        if busy > self.eps: self.idle_since[pid] = None; return 0.0
        if self.idle_since.get(pid) is None: self.idle_since[pid] = prev[1]
        return t - self.idle_since[pid]
    def forget(self, alive): 
        for p in list(self.last):
            if p not in alive: self.last.pop(p, None); self.idle_since.pop(p, None); self.busy_since.pop(p, None)


class CtypesWindows:
    """窗口信息后端（Windows）：返回 {pid: [(title, visible)]} 与前台 pid。"""
    def windows(self):
        import ctypes
        from ctypes import wintypes as W
        u = ctypes.WinDLL("user32", use_last_error=True); out = {}
        cb_t = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def cb(h, _):
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
            pid = W.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if buf.value: out.setdefault(pid.value, []).append((buf.value, bool(u.IsWindowVisible(h))))
            return True
        u.EnumWindows(cb_t(cb), 0); return out
    def hung_pids(self):
        import ctypes
        from ctypes import wintypes as W
        u = ctypes.WinDLL("user32", use_last_error=True); out = set(); cb_t = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def cb(h, _):
            if u.IsWindowVisible(h) and u.IsHungAppWindow(h):
                pid = W.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid)); out.add(pid.value)
            return True
        u.EnumWindows(cb_t(cb), 0); return out
    def foreground_pid(self):
        import ctypes
        from ctypes import wintypes as W
        u = ctypes.WinDLL("user32", use_last_error=True); pid = W.DWORD(); u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid)); return pid.value or None


class PycawAudio:
    """音频会话（可选依赖 pycaw）：返回正在出声的 pid 集合；没装/失败就返回 None（=未知）。
    为什么不用 ctypes 手搓 COM：IAudioSessionManager2 要走 IMMDeviceEnumerator->GetDefaultAudioEndpoint
    ->Activate->GetSessionEnumerator 一整条链，vtable 索引和 COM 生命周期（CoInitialize/CoTaskMemFree）
    错一处就是 E_POINTER 或 access violation，很难查。pycaw 就是这条链的成熟封装，装它更划算。"""
    def active_pids(self):
        try:
            from pycaw.pycaw import AudioUtilities
            return {s.ProcessId for s in AudioUtilities.GetAllSessions() if s.State == 1 and s.ProcessId}
        except Exception: return None


def parse_tasklist(csv_text: str):
    """tasklist /v /fo csv 的解析（兜底层）。列：映像名称,PID,会话名,会话#,内存使用,状态,用户名,CPU 时间,窗口标题。语言不同列名不同，按位置取。"""
    rows = list(csv.reader(io.StringIO(csv_text)))[1:]; out = []
    for r in rows:
        if len(r) < 9: continue
        try:
            mem = float(re.sub(r"[^\d]", "", r[4]) or 0) / 1024; h, m, s = (int(x) for x in r[7].split(":"))
        except ValueError: continue
        out.append(dict(name=r[0].lower().removesuffix(".exe"), pid=int(r[1]), rss_mb=mem, cpu_s=h * 3600 + m * 60 + s, title="" if r[8] == "N/A" else r[8]))
    return out


class WinProbe:
    def __init__(self, clock, psutil_mod=None, windows=None, audio=None, tasklist=None, disks=None, mem=None):
        import time
        self.clock = clock or time.time; self.cpu = CpuTracker()
        try: self.ps = psutil_mod if psutil_mod is not None else __import__("psutil")
        except ImportError: self.ps = None
        self.win = windows if windows is not None else (CtypesWindows() if os.name == "nt" else None)
        self.audio = audio if audio is not None else (PycawAudio() if os.name == "nt" else None)
        self.tasklist = tasklist or self._tasklist; self.layer = "psutil" if self.ps else ("tasklist" if os.name == "nt" or tasklist else "none")

    def _tasklist(self):
        return subprocess.run(["tasklist", "/v", "/fo", "csv"], capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout

    def procs(self):
        t = self.clock(); wins = {}; fg = None; audible = None
        try: wins = self.win.windows() if self.win else {}; fg = self.win.foreground_pid() if self.win else None
        except Exception: wins, fg = {}, None
        try: hung = self.win.hung_pids() if (self.win and hasattr(self.win, "hung_pids")) else None
        except Exception: hung = None
        try: audible = self.audio.active_pids() if self.audio else None
        except Exception: audible = None
        raw = []
        if self.ps:
            prev = dict(self.cpu.last)                       # 上一次的 (cpu_s, t)，用来算区间平均 CPU
            for p in self.ps.process_iter():
                try:
                    with p.oneshot():
                        ct = p.cpu_times(); cpu_s = ct.user + ct.system
                        d = dict(pid=p.pid, name=p.name().lower().removesuffix(".exe"), rss_mb=p.memory_info().rss / 2**20,
                                 cpu_s=cpu_s, ppid=p.ppid(), cmd=" ".join(p.cmdline() or []), cwd=(p.cwd() if hasattr(p, "cwd") else ""),
                                 children=len(p.children()))
                        pv = prev.get(p.pid)
                        d["cpu_pct"] = (max(0.0, cpu_s - pv[0]) / max(t - pv[1], 1e-6) * 100.0) if pv else 0.0
                        d["username"] = _username(p)
                        d["exe"] = _exe(p)
                        d["create"] = _create(p)
                        raw.append(d)
                except Exception: continue
            alive = {r["pid"] for r in raw}
        else:
            raw = [dict(r, ppid=None, cmd="", cwd="", children=0, cpu_pct=0.0, username="", exe="", create=0.0) for r in (parse_tasklist(self.tasklist()) if self.layer == "tasklist" else [])]
            alive = {r["pid"] for r in raw}
        me = session_of(os.getpid()) or 1
        for r in raw:
            r["session"] = session_of(r["pid"]) or 0
            # openable 只表示“拿不到属主（权限不足）”。username 缺失时仍保持 True：
            # 真正的兜底是 session/黑名单/窗口等门，不能因为一个字段缺失就把所有进程判成受保护。
            r["openable"] = True
        user = _current_user()
        # 前台进程树：前台 pid 及其祖先、后代
        parent = {r["pid"]: r["ppid"] for r in raw}
        def anc(pid):
            s = set()
            while pid in parent and pid not in s: s.add(pid); pid = parent[pid]
            return s
        fgtree = set()
        if fg:
            for r in raw:
                a = anc(r["pid"])
                if fg in a or r["pid"] in anc(fg): fgtree.add(r["pid"])
        out = []
        for r in raw:
            ws = wins.get(r["pid"], [])
            title = next((x for x, vis in ws if vis), ws[0][0] if ws else r.get("title", ""))
            idle = self.cpu.update(r["pid"], r["cpu_s"], t)
            out.append(Proc(r["pid"], r["name"], r["rss_mb"], idle_s=idle,
                            parent_alive=(r["ppid"] in alive) if r["ppid"] is not None else True,        # 未知时当作“父进程还在”，不会被当成残留
                            has_window=any(v for _, v in ws), foreground_tree=r["pid"] in fgtree or r["pid"] == fg, title=title or "",
                            busy_s=(t - self.cpu.busy_since[r["pid"]]) if r["pid"] in self.cpu.busy_since else 0.0,
                            not_responding=(r["pid"] in hung) if hung is not None else None,
                            cmdline=r["cmd"], cwd=r["cwd"] or "", audio=(None if audible is None else r["pid"] in audible), children=r["children"],
                            ppid=r["ppid"], session=r["session"], username=r["username"], openable=r["openable"], cpu_pct=r["cpu_pct"],
                            console=is_console(r["exe"]) if r["exe"] else None, create=r["create"]))
        self.cpu.forget(alive)
        return out, (next((p.name for p in out if p.pid == fg), "") if fg else "")
