"""现场演示：真实内存探针 + 真实进程挂起（--live）/干跑（默认）+ 只在沙箱里的文件清理，走真实 GUI。
python -m sprite.demo_live.live [--live] [--sandbox DIR] [--home DIR] [--no-gui]"""
from __future__ import annotations
import argparse, atexit, json, os, signal, sys, time
from pathlib import Path
from .. import config, risk as R
from ..core import Sprite
from ..framework import Registry, Problem, Scenario
from ..pressure import PressureDetector
from ..quarantine import Quarantine
from ..risk import Env
from ..scenarios import resource
from ..sysstate import RealProbe
from ..procctl import JournaledController
from .common import sandbox_root, home_dir, load_demo_cfg, warn_gb, DEMO_IDLE_SCALE, BIG_MB, MARK, mem_now


def detector(total_mb, dc) -> PressureDetector:
    w = warn_gb(total_mb, dc) * 1024 / total_mb
    return PressureDetector(mem_warn=w, mem_crit=min(0.10, w * 0.5), disk_warn=0.0, disk_crit=0.0, disk_crit_gb=0)      # 磁盘告警在演示里关闭：只由“内存爆炸”触发


def sandbox_scenario(det, world_getter=None) -> Scenario:
    """演示场景：内存告急（真实压力）时才评估沙箱里能清的东西；压力一解除/没有压力就什么都不做、不出声；按回收量从大到小，够了就停。
    （真实使用中文件清理由磁盘压力触发；演示里为了一次触发看到全流程而绑在内存告急上。）"""
    def pressured(w):
        s = w.refresh() if getattr(w, "refresh", None) else w.snap
        return s.mem_avail_mb / s.mem_total_mb < det.p["mem_warn"]
    def detect(w):
        out = []
        for p in det.update(w.snap):
            if p.kind != "mem": continue
            def rc(w=w):
                if not pressured(w): return 0.0                                                  # 没压力：不清理
                return max(0.0, 0.15 - sum(e["stored"] for e in w.q.held()) / 2**30)             # 已隔离够 0.15GB 就停手
            out.append(Problem("sandbox", p.level / 2, "内存告急，顺便看看沙箱里能清的东西", need=0.15, unit="GB", key=f"sandbox:{p.level}", recheck=rc))
        return out
    return Scenario("sandbox_cleanup", detect, resource.propose, resource.group_text, resource.group_short)


def build(home: Path, sandbox: Path, live: bool, log=print, allow_only=None):
    dc = load_demo_cfg(home); sb = Path(sandbox)
    if not (sb / MARK).exists():
        from .stage_demo import stage; stage(sb)
    prov = json.loads((sb / "provenance.json").read_text("utf-8")) if (sb / "provenance.json").exists() else {}
    bk = sb / "Backup"
    def find_copy(p):
        from ..quarantine import sha
        for c in bk.glob("*") if bk.is_dir() else []:
            if c.name == p.name and c.stat().st_size == p.stat().st_size and sha(c) == sha(p): return c
    cache = [sb / "BrowserCache"] + [Path(x) for x in dc.get("extra_cache_dirs", [])]
    env = Env(now=time.time(), temp_dirs=[sb / "Temp"], browser_cache_dirs=cache, pkg_cache_dirs=[sb / "PipCache"], user_dirs=[sb / "Documents"],
              downloads=sb / "Downloads", provenance=lambda p: prov.get(str(p)), find_copy=find_copy, big_mb=BIG_MB)
    R.PROC_IDLE_SCALE = DEMO_IDLE_SCALE
    ctrl = JournaledController(home, live=live, max_n=dc["max_suspend"], max_rss_mb=dc["max_suspend_mb"], allow_only=allow_only, log=log)
    world = resource.World(env=env, q=Quarantine(sb / ".sprite_quarantine"), ctrl=ctrl, home=home)
    total, _ = mem_now()
    reg = Registry(); reg.register(resource.make(detector(total, dc))); reg.register(sandbox_scenario(detector(total, dc)))
    try:   # 通用“先调查再动手”：烦人的黑窗/陈旧进程。默认只调查并写理解记录（干跑）；demo 配置 annoyance_apply=true 且 --live 才真动手
        from ..scenarios import annoyance; asc, _ = annoyance.build(home, live=live, apply_real=bool(dc.get("annoyance_apply", False)), log=log); reg.register(asc)
    except Exception as e: log("annoyance 场景加载失败：", repr(e))
    try:   # 网络传感器/执行器插件（非主脑）；network_apply=true 且 --live 才真动手；理解默认 novel
        from ..scenarios import network as netsc
        nsc, _ = netsc.build(home, live=live, apply_real=bool(dc.get("network_apply", False)), log=log,
                                   novel_from_env=bool(dc.get("novel_from_env", True)))
        reg.register(nsc)
    except Exception as e: log("network 场景加载失败：", repr(e))
    try:   # 僵局传感器插件；定性默认 novel；stalemate_apply=true 且 --live 才真动手
        from ..scenarios import stalemate as stsc
        ssc, _ = stsc.build(home, live=live, apply_real=bool(dc.get("stalemate_apply", False)), log=log,
                                   novel_from_env=bool(dc.get("novel_from_env", True)))
        reg.register(ssc)
    except Exception as e: log("stalemate 场景加载失败：", repr(e))
    cfg = json.loads(json.dumps(config.DEFAULTS)); cfg.update(watch={}, quiet_hours=None, poll_s=3.0, bubble_seconds=40, resource_watch=True, recorder=False, daily_cap=50)
    s = Sprite(cfg, home, probe=RealProbe(), world=world, registry=reg); s.dry = not live
    return s, ctrl, dc


def main(argv=None):
    try: _main(argv)
    except SystemExit: raise
    except BaseException:
        import traceback; (home_dir() / "demo_live.log").open("a", encoding="utf-8").write(time.strftime("%H:%M:%S ") + "崩溃：\n" + traceback.format_exc() + "\n"); raise


def _main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true"); ap.add_argument("--sandbox"); ap.add_argument("--home"); ap.add_argument("--no-gui", action="store_true"); a = ap.parse_args(argv)
    home = Path(a.home) if a.home else home_dir(); home.mkdir(parents=True, exist_ok=True); sb = Path(a.sandbox) if a.sandbox else sandbox_root()
    logf = home / "demo_live.log"
    def log(*x):
        line = time.strftime("%H:%M:%S ") + " ".join(map(str, x))
        with logf.open("a", encoding="utf-8") as f: f.write(line + "\n")
        try: print(line, flush=True)
        except Exception: pass
    s, ctrl, dc = build(home, sb, a.live, log); presence_hook(s)
    left = ctrl.resume_all() if a.live else 0
    log(f"启动：{'真实挂起模式（--live）' if a.live else '干跑模式（不会真的挂起任何进程）'}；沙箱={sb}；home={home}" + (f"；上次遗留挂起已恢复 {left} 个" if left else ""))
    total, avail = mem_now(); log(f"内存 {total/1024:.1f}GB，当前可用 {avail/1024:.1f}GB，告警阈值：可用 < {warn_gb(total, dc):.1f}GB")
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
        if sig:
            try: signal.signal(sig, lambda *_: (ctrl.resume_all(), os._exit(0)))
            except Exception: pass
    stop = home / "STOP_DEMO"
    if a.no_gui:
        s.on_message = lambda m: log("💬", m.get("text"), "|", " / ".join(m.get("options") or [])) if m.get("kind") in ("say", "action") else None
        while not stop.exists(): s.tick(); time.sleep(cfg_poll(s))
        ctrl.resume_all(); return
    from ..gui import run_gui
    run_gui(s, 40, 3.0, should_quit=lambda: stop.exists())
    ctrl.resume_all()


def user_idle_s() -> float:
    """距离你上次键盘/鼠标输入多少秒（Windows GetLastInputInfo；真实信号）。其它系统：环境变量 SPRITE_DEMO_ASSUME_PRESENT=1 视为在场（测试用），否则视为不在。"""
    if os.name == "nt":
        import ctypes
        class LII(ctypes.Structure): _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = LII(); li.cbSize = ctypes.sizeof(li)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)): return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0
        return 1e9
    return 0.0 if os.environ.get("SPRITE_DEMO_ASSUME_PRESENT") else 1e9


def presence_hook(s, idle=user_idle_s, every=45.0):
    """你正在用电脑时，给小精灵一条“在场”的行为证据（否则它会认为你不在、不打扰）。"""
    orig = s.tick; last = [0.0]
    def tick():
        now = time.time()
        if now - last[0] >= every and idle() < 30:
            last[0] = now
            with (s.home / "behavior.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), project="演示", kind="work", minutes=1)) + "\n")
        return orig()
    s.tick = tick


def cfg_poll(s): return s.cfg.get("poll_s", 3.0)


if __name__ == "__main__":
    main()
