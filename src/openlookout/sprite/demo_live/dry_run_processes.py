"""干跑：只观察、只打印“如果压力来了，精灵会挂起哪些真实进程、为什么不碰其它的”。不挂起、不改动任何东西。
python -m sprite.demo_live.dry_run_processes [--seconds 75]"""
from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path
from .. import risk as R
from ..sysstate import RealProbe
from ..procctl import JournaledController, own_chain
from .common import DEMO_IDLE_SCALE, home_dir


def evaluate(procs, ctrl) -> tuple:
    would, kept = [], []
    for p in procs:
        rk = R.classify_proc(p, our_pid=os.getpid())
        if rk.level == "safe" and p.rss_mb >= 100:
            ok = ctrl.suspend(p.pid, name=p.name, rss_mb=p.rss_mb)           # 干跑控制器：只记录，也会应用黑名单/数量/内存上限
            (would if ok else kept).append((p, rk.reason if ok else "控制器拒绝：" + (ctrl.refused[-1][1] if ctrl.refused else "")))
        else: kept.append((p, rk.reason))
    return would, kept


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--seconds", type=float, default=75); a = ap.parse_args(argv)
    R.PROC_IDLE_SCALE = DEMO_IDLE_SCALE
    try: import psutil  # noqa
    except ImportError: print("提示：没有安装 psutil（pip install psutil）。没有它读不到进程命令行，浏览器后台标签进程无法识别，精灵就不会挂起任何进程。")
    probe = RealProbe(); t0 = time.time(); n = 0
    print(f"观察 {a.seconds:.0f} 秒（需要先看到进程“持续空闲”才会算空闲）……", flush=True)
    while True:
        snap = probe.snapshot(); n += 1
        if time.time() - t0 >= a.seconds: break
        time.sleep(5)
    ctrl = JournaledController(home_dir(), live=False, max_n=6, max_rss_mb=4096)
    would, kept = evaluate(snap.procs, ctrl)
    out = [f"前台程序：{snap.foreground_name or '未知'}；共 {len(snap.procs)} 个进程；采样 {n} 次", "", f"【如果现在内存告急，会挂起（不是结束）这 {len(would)} 个】"]
    for p, why in sorted(would, key=lambda x: -x[0].rss_mb): out.append(f"  {p.name}#{p.pid}  {p.rss_mb:.0f}MB  空闲 {p.idle_s:.0f}s  —— {why}")
    if not would: out.append("  （无。没有找到长时间空闲、无窗口、非前台、非播放的后台进程——这是正常且安全的结果）")
    out += ["", "【内存占用最大的 12 个进程，以及为什么不动它们】"]
    for p, why in sorted(kept, key=lambda x: -x[0].rss_mb)[:12]: out.append(f"  {p.name}#{p.pid}  {p.rss_mb:.0f}MB  —— {why}")
    out += ["", "上面只是预演，什么都没有动。确认没问题再用 run_demo.bat --live。"]
    txt = "\n".join(out); print(txt); (home_dir() / "dry_run_processes.txt").write_text(txt, "utf-8")


if __name__ == "__main__":
    main()
