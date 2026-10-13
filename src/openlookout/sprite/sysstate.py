"""系统状态探针：内存/磁盘/进程。仅标准库（Windows 用 ctypes）；装了 psutil 就能看到进程（可选依赖，pip install psutil）。
FakeProbe 用于模拟与测试。"""
from __future__ import annotations
import json, os, shutil, sys, time
from dataclasses import dataclass, field
from pathlib import Path

# 合格判定的门槛。改这里等于改“什么样的后台进程可以被挂起”——宁可漏做，不可错做，所以都偏保守。
DEFAULTS = dict(min_idle_s=300.0, min_rss_mb=150.0, max_cpu_pct=1.0, min_age_s=60.0,
                max_net_kb=0.0, idle_scale=1.0)


@dataclass
class Proc:
    pid: int
    name: str
    rss_mb: float
    idle_s: float = 0          # 连续低 CPU 的秒数
    parent_alive: bool = True
    has_window: bool = False
    foreground_tree: bool = False   # 属于当前前台窗口的进程树
    title: str = ""
    cmdline: str = ""
    cwd: str = ""
    audio: bool | None = False   # None=未知（没装 pycaw）
    children: int = 0
    suspended: bool = False
    busy_s: float = 0            # 连续高 CPU 的秒数
    not_responding: bool | None = None   # 窗口无响应（未知为 None）
    ppid: int | None = None      # 父进程（tasklist 兜底层拿不到 -> None）
    session: int = 1             # Windows 会话号；0 = 服务会话，一律不动
    username: str = ""           # 属主；不是当前用户说明是别的账户/服务
    openable: bool = True        # 能不能拿到 PROCESS_QUERY 句柄；拿不到 = 受保护
    cpu_pct: float = 0.0         # 采样区间内的平均 CPU 占用
    console: bool | None = None  # None=没装 pycaw 之外的信息缺失；True=控制台程序（终端/命令行）
    create: float = 0.0          # 进程创建时间（epoch），用于“刚起来的进程”判断


@dataclass
class Snapshot:
    t: float
    mem_total_mb: float
    mem_avail_mb: float
    disks: dict                 # 路径 -> (total_gb, free_gb)
    procs: list = field(default_factory=list)
    foreground_name: str = ""


class RealProbe:
    def __init__(self, disks=None, clock=None):
        import time
        self.clock = clock or time.time; self.fg = ""; self.win = None
        if os.name == "nt" or os.environ.get("SPRITE_FORCE_WINPROBE"):
            from .winprobe import WinProbe
            self.win = WinProbe(self.clock)
        self.disks = disks or ([os.path.expanduser("~")] if os.name != "nt" else [os.environ.get("SystemDrive", "C:") + "\\"])

    def _mem(self):
        if os.name == "nt":
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.tp / 2**20, m.ap / 2**20
        info = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        return info["MemTotal"] / 1024, info["MemAvailable"] / 1024

    def _procs(self):
        if self.win is not None:
            procs, self.fg = self.win.procs(); return procs
        try: import psutil
        except ImportError: return []
        out = []
        for p in psutil.process_iter(["pid", "name", "memory_info", "ppid", "cmdline", "cwd"]):
            try:
                i = p.info
                out.append(Proc(i["pid"], (i["name"] or "").lower().removesuffix(".exe"), i["memory_info"].rss / 2**20,
                                cmdline=" ".join(i["cmdline"] or []), cwd=i["cwd"] or "", parent_alive=psutil.pid_exists(i["ppid"])))
            except Exception: continue
        return out        # idle_s / has_window / foreground_tree 需要窗口与 CPU 历史，真实版在 Windows 上补（未验证）

    def snapshot(self) -> Snapshot:
        t, a = self._mem()
        pr = self._procs()
        return Snapshot(self.clock(), t, a, {d: tuple(x / 2**30 for x in shutil.disk_usage(d)[:1] + shutil.disk_usage(d)[2:]) for d in self.disks}, pr, self.fg)


class FakeProbe:
    def __init__(self, snaps=None): self.snaps = list(snaps or []); self.i = 0; self.last = None
    def push(self, s): self.snaps.append(s)
    def snapshot(self):
        if self.i < len(self.snaps): self.last = self.snaps[self.i]; self.i += 1
        return self.last


class ProcController:
    """真实控制器（Windows，ctypes；未在真实 Windows 验证）：挂起/恢复/收缩工作集。不提供 kill。"""
    def suspend(self, pid, **kw):
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x800, False, pid)
        if not h: return False
        r = ctypes.windll.ntdll.NtSuspendProcess(h); ctypes.windll.kernel32.CloseHandle(h); return r == 0
    def resume(self, pid):
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x800, False, pid)
        if not h: return False
        r = ctypes.windll.ntdll.NtResumeProcess(h); ctypes.windll.kernel32.CloseHandle(h); return r == 0
    def set_priority(self, pid, level):
        import ctypes
        cls = {"low": 0x00004000, "normal": 0x00000020}[level]            # BELOW_NORMAL / NORMAL
        h = ctypes.windll.kernel32.OpenProcess(0x0200 | 0x0400, False, pid)
        if not h: return None
        prev = ctypes.windll.kernel32.GetPriorityClass(h); ctypes.windll.kernel32.SetPriorityClass(h, cls); ctypes.windll.kernel32.CloseHandle(h)
        return {0x4000: "low", 0x20: "normal"}.get(prev, "normal")
    def trim(self, pid):
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x0500, False, pid)
        if not h: return False
        r = ctypes.windll.psapi.EmptyWorkingSet(h); ctypes.windll.kernel32.CloseHandle(h); return bool(r)


class FakeController:
    def __init__(self): self.suspended = set(); self.calls = []; self.prio = {}; self.startup = {}; self.muted = set()
    def set_priority(self, pid, level): prev = self.prio.get(pid, "normal"); self.prio[pid] = level; self.calls.append(("prio", pid, level)); return prev
    def startup_disable(self, name): self.startup[name] = False; self.calls.append(("startup_off", name)); return True
    def startup_enable(self, name): self.startup[name] = True; self.calls.append(("startup_on", name)); return True
    def mute(self, app): self.muted.add(app); self.calls.append(("mute", app)); return True
    def unmute(self, app): self.muted.discard(app); self.calls.append(("unmute", app)); return True
    def suspend(self, pid, **kw): self.suspended.add(pid); self.calls.append(("suspend", pid)); return True
    def resume(self, pid): self.suspended.discard(pid); self.calls.append(("resume", pid)); return True
    def trim(self, pid): self.calls.append(("trim", pid)); return True


# ---------------------------------------------------------------- 合格判定
# 纯函数 decide(rec, ctx, cfg) -> None（合格）或拒绝理由字符串。顺序即优先级：
# 越靠前的门越硬（“自己人/系统/受保护”），越靠后越依赖观察（“忙不忙/内存多大/有没有网络”）。
# 网络门故意放最后：前面的门没过就不该去做 IO 统计（test_network_gate_is_lazy）。
def decide(r, c, cfg=None):
    """r=进程记录(dict)，c=本机上下文(dict)。返回 None=合格，否则返回拒绝理由。"""
    k = {**DEFAULTS, **(cfg or {})}
    pid = r["pid"]
    if pid == c["self_pid"] or pid in c["own_tree"]: return "host"
    if r.get("ppid") in c["sprite_ancestors"]: return "host"                       # 直接父进程就是精灵的宿主
    if not r.get("session"): return "system"                                       # 会话 0 = 服务/系统
    if r.get("session") != c["session"]: return "system"
    if r.get("username") and c.get("username") and r["username"].lower() != c["username"].lower(): return "system"
    if pid == c.get("shell"): return "system"                                      # 桌面外壳（explorer）
    if not r.get("openable", True): return "protected"                             # 拿不到句柄 = 权限不足
    if pid == c.get("fg"): return "foreground"
    if c.get("audio", ...) is None: return "audio_unknown"                         # 不知道有没有在放声音 -> 全都不合格
    if pid in c["audio"]: return "audio"
    w = c["windows"].get(pid)
    if w:
        if w.get("unsaved"): return "unsaved"
        if w.get("console"): return "terminal"
        if w.get("visible"): return "window"
    if pid in c.get("console", ()): return "terminal"
    # 祖先有可见窗口 = 它是某个前台应用的一部分（浏览器渲染进程这种），不动。
    # 但如果祖先链里出现精灵自己的宿主，说明这进程是跟着精灵一起被拉起来的，不算“宿主应用”。
    anc = _chain(r.get("ppid"), c["parents"])
    if not (set(anc) & c["sprite_ancestors"]):
        for a in anc:
            aw = c["windows"].get(a)
            if aw and (aw.get("visible") or aw.get("unsaved")): return "host_app"
    if r.get("children"): return "has_children"
    if r.get("idle_s", 0.0) < k["min_idle_s"] * k["idle_scale"]: return "busy"
    if r.get("cpu_pct", 0.0) > k["max_cpu_pct"]: return "busy"
    if c["now"] - r.get("create", c["now"]) < k["min_age_s"]: return "young"        # 刚起来的进程可能正在初始化
    if r.get("rss_mb", 0.0) < k["min_rss_mb"]: return "small"                      # 回收不划算
    net = c.get("net")
    if net is not None and net(pid) > k["max_net_kb"]: return "network"
    return None


def _chain(ppid, parents):
    """从直接父进程往上走，返回有序列表（近 -> 远）。parents 里查不到就停。"""
    out, seen = [], set()
    p = ppid
    while p and p not in seen:
        out.append(p); seen.add(p); p = parents.get(p)
    return out


def eat_memory(mb: int, chunk_mb: int = 16):
    """真实占用内存（每页都写一下，确保占住物理内存）。返回持有者；del 即释放。"""
    chunks = []
    for _ in range(max(1, mb // chunk_mb)):
        b = bytearray(chunk_mb * 2**20); b[::4096] = b"\x01" * len(b[::4096]); chunks.append(b)
    return chunks


def assess(home=None, warmup=1.0, only_pids=None, cfg=None, probe=None):
    """只评估、不动手：返回 {pressure, memory, candidates, rejected, own_tree}。
    candidates 是合格且按内存从大到小排序的进程；rejected 是 pid -> 拒绝理由。"""
    from . import winprobe
    home = Path(home) if home else Path(os.environ.get("SPRITE_HOME", ".")) / "sysstate"
    home.mkdir(parents=True, exist_ok=True)
    mem = winprobe.memory()
    pressure = "critical" if mem["frac"] < 0.10 else "low" if mem["frac"] < 0.20 else "ok"
    pr = probe or winprobe.WinProbe(time.time)
    first = {p.pid: p for p in pr.procs()[0]}                     # 第一次快照只用来建立 CPU 基线
    if warmup > 0: time.sleep(warmup)
    procs, _ = pr.procs()                                        # 第二次才有真实 idle_s / cpu_pct
    me = winprobe.session_of(os.getpid()) or 1
    own = procctl_own_tree()
    shell = next((p.pid for p in procs if p.name == "explorer"), None)
    console = {p.pid for p in procs if p.console}
    ctx = dict(now=time.time(), self_pid=os.getpid(), own_tree=own, sprite_ancestors=set(own) - {os.getpid()},
               session=me, username=_cur_user(), shell=shell, console=console,
               fg=next((p.pid for p in procs if p.foreground_tree), None),
               audio=({p.pid for p in procs if p.audio} if procs and procs[0].audio is not None else None),
               parents={p.pid: p.ppid for p in procs if p.ppid},
               windows={p.pid: {"visible": p.has_window, "unsaved": any(m in (p.title or "") for m in winprobe.UNSAVED_MARKS),
                                "console": bool(p.console)} for p in procs if p.has_window or p.title},
               net=_net_kb)
    k = {**DEFAULTS, **(cfg or {})}
    cands, rej = [], {}
    for p in sorted(procs, key=lambda x: -x.rss_mb):
        if only_pids and p.pid not in set(only_pids): continue
        r = dict(pid=p.pid, ppid=p.ppid, name=p.name, session=p.session, username=p.username, create=p.create or 0.0,
                 rss_mb=p.rss_mb, cpu_pct=p.cpu_pct, children=p.children, openable=p.openable, idle_s=p.idle_s)
        r["create"] = p.create
        why = decide(r, ctx, k)
        if why: rej[str(p.pid)] = why
        else: cands.append(dict(pid=p.pid, name=p.name, rss_mb=p.rss_mb, idle_s=p.idle_s))
    return dict(pressure=pressure, memory=mem, candidates=cands, rejected=rej,
                own_tree=sorted(own), total_seen=len(procs), first_snapshot=len(first))


def _cur_user():
    from . import winprobe
    return winprobe._current_user()


def procctl_own_tree():
    from . import procctl
    return procctl.own_chain()


def _net_kb(pid):
    """进程的实时网络速率（KB/s）。psutil 不直接给，用系统总量近似：拿不到就当 0（这一项本来就最宽松）。"""
    try:
        import psutil
        n = psutil.net_io_counters()
        return float(getattr(n, "bytes_sent", 0) + getattr(n, "bytes_recv", 0)) / 1024.0
    except Exception: return 0.0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="sprite.sysstate", description="内存告急：评估哪些闲置后台进程可以挂起（只挂起，不结束）")
    ap.add_argument("--assess", action="store_true", help="只评估并打印结果，绝不动任何进程（默认行为）")
    ap.add_argument("--live", action="store_true", help="真的挂起；没有内存压力时拒绝执行")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--home")
    ap.add_argument("--warmup", type=float, default=1.0, help="两次快照之间的观察秒数（决定 idle_s 可信度）")
    ap.add_argument("--pids", help="逗号分隔，只处理这些 pid（测试/演练用）")
    ap.add_argument("--max-n", type=int, default=6); ap.add_argument("--max-rss-mb", type=float, default=4096)
    a = ap.parse_args(argv)
    home = Path(a.home) if a.home else Path(os.environ.get("SPRITE_HOME", ".")) / "sysstate"
    only = [int(x) for x in a.pids.split(",")] if a.pids else None
    out = assess(home=home, warmup=a.warmup, only_pids=only)
    if a.live:
        if out["pressure"] == "ok":                       # 没有压力就不动（状态变化驱动，不是定时清理）
            out["suspended"] = 0
            out["refused"] = "当前没有内存压力，不做任何事"
            print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else f"内存 {out['memory']['available']/1024:.1f}GB 可用，没有压力，不动。")
            return 2
        from . import procctl
        ctl = procctl.JournaledController(home, live=True, max_n=a.max_n, max_rss_mb=a.max_rss_mb, allow_only=only)
        done = []
        for c in out["candidates"]:
            if ctl.suspend(c["pid"], c["name"], c["rss_mb"]): done.append(c)
        out["suspended"] = len(done); out["did"] = done
        print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else
              (f"已挂起 {len(done)} 个闲置后台进程（共 {sum(c['rss_mb'] for c in done):.0f}MB）。撤销：python -m sprite.procctl --journal {home/'suspended.json'} --resume-all" if done else "没有合格的后台进程。"))
        return 0
    print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else
          f"内存 {out['memory']['available']/1024:.1f}/{out['memory']['total']/1024:.1f}GB 可用（压力={out['pressure']}）；"
          f"合格 {len(out['candidates'])} 个，不合格 {len(out['rejected'])} 个。")
    for c in out["candidates"][:10]: print(f"  可挂起 {c['name']}#{c['pid']} {c['rss_mb']:.0f}MB 空闲 {c['idle_s']/60:.0f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
