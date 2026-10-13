"""在 xvfb 里跑真实 GUI 的全流程并截图（测试用，不是给用户跑的）：
真实内存分配 → 真实压力检测 → 真实挂起（只针对本脚本起的假浏览器子进程）→ 沙箱清理 → 一个批量问题 → 同意 → 撤销。
xvfb-run -a -s "-screen 0 1100x700x24" python -m sprite.demo_live.headless_shots OUTDIR"""
from __future__ import annotations
import json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
os.environ["SPRITE_FORCE_WINPROBE"] = "1"; os.environ["SPRITE_DEMO_ASSUME_PRESENT"] = "1"


def main(out: Path):
    import tkinter as tk
    from PIL import ImageGrab, ImageDraw, ImageFont
    from .. import risk as R
    from . import live, stage_demo, common
    from .eat_memory import Eater
    from ..gui import SpriteWindow
    out.mkdir(parents=True, exist_ok=True); tmp = Path(tempfile.mkdtemp(prefix="live_demo_"))
    sb, home = tmp / "sandbox", tmp / "home"; home.mkdir(); stage_demo.stage(sb)
    def spawn(name, mb=220, spin=False):
        link = tmp / "bin" / name; link.parent.mkdir(exist_ok=True)
        if not link.exists(): link.symlink_to(sys.executable)
        code = f"b=bytearray({mb}*2**20); b[::4096]=b'x'*len(range(0,len(b),4096))\nimport time\n" + ("while True: pass" if spin else "time.sleep(600)")
        return subprocess.Popen([str(link), "-c", code, "--type=renderer"])
    names = {}; procs = []
    for nm, kw in (("chrome", {}), ("chrome", {}), ("chrome", dict(spin=True)), ("code", {}), ("python", {})):
        p = spawn(nm, **kw); procs.append(p); names[p.pid] = nm + (" (忙)" if kw.get("spin") else "")
    time.sleep(2.5)
    total, avail = common.mem_now()
    (home / "demo_live.json").write_text(json.dumps(dict(mem_warn_gb=(avail - 700) / 1024, extra_cache_dirs=[], max_suspend=6, max_suspend_mb=4096)))
    s, ctrl, dc = live.build(home, sb, live=True, log=lambda *a: None, allow_only={p.pid for p in procs}); R.PROC_IDLE_SCALE = 0.004
    live.presence_hook(s, every=1.0)
    import queue
    q = queue.Queue(); s.on_message = lambda m: q.put(m) if m.get("kind") == "say" else None
    root = tk.Tk(); root.geometry("1100x700+0+0"); root.configure(bg="#eef2f3"); root.title("live demo")
    board = tk.Label(root, text="", justify="left", anchor="nw", font=("Noto Sans CJK SC", 12), bg="#eef2f3"); board.place(x=20, y=20)
    w = SpriteWindow(root, home, lambda i, ok=False: s.respond(i if not ok else 0), lambda aid: (s.undo(aid), s.respond(0)), lambda: s.respond(None, kind="ignore"))
    w.sx, w.sy = 900, 520; w.redraw()
    st = dict(step=0, t0=time.time(), eater=None, shots=0, phase="idle", ask_seen=False, done_seen=False, log=[])
    def state(pid):
        try: return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
        except Exception: return "?"
    def refresh(note=""):
        c = stage_demo.check(sb); mem = common.mem_now()
        lines = ["【真实环境（本脚本起的假浏览器进程；精灵只允许动它们）】", f"可用内存 {mem[1]/1024:.1f}GB / {mem[0]/1024:.1f}GB，告警阈值 < {dc['mem_warn_gb'] or (avail-700)/1024:.1f}GB 且 eat 已占用 {st['eater'].held_mb if st['eater'] else 0}MB", ""]
        for p in procs: lines.append(f"  pid {p.pid:<7} {names[p.pid]:<12} 状态 {'T=已挂起' if state(p.pid)=='T' else '运行中'}")
        lines += ["", f"沙箱：可自动清理 {c['safe_moved']}/{c['safe_total']} 已收进隔离区 | 有硬证据的大文件 {c['risky_moved']}/{c['risky_total']} 已处理 | 陷阱完好 {c['traps_intact']}/{c['traps_total']}", f"阶段：{st['phase']} {note}"]
        board.config(text="\n".join(lines))
    def shot(tag):
        refresh(); w.win.deiconify(); w.win.lift(); w.redraw()
        for _ in range(6): root.update(); time.sleep(0.15)
        im = ImageGrab.grab(bbox=(0, 0, 1100, 700), xdisplay=os.environ.get("DISPLAY")); f = out / f"live_demo_{st['shots']:02d}_{tag}.png"; im.save(f); st["shots"] += 1; print("截图", f, flush=True)
    def loop():
        try: s.tick()
        except Exception as e: print("tick error", e)
        try:
            while True: w.show(q.get_nowait(), 60)
        except queue.Empty: pass
        w.set_state(s.mood); el = time.time() - st["t0"]
        if st["phase"] == "idle" and el > 14: shot("idle_before"); st["eater"] = Eater(1.5, 1100); st["phase"] = "eating"; st["t1"] = time.time()
        elif st["phase"] == "eating":
            grew = sum(st["eater"].step() for _ in range(4))
            if not grew: shot("memory_exploded"); st["phase"] = "waiting_ask"
        elif st["phase"] == "waiting_ask" and w.msg and w.msg.get("action_id"):
            time.sleep(0.6); shot("report_bubble"); w._click(("detail", None)); shot("report_detail"); st["phase"] = "waiting_done"
        elif st["phase"] == "waiting_done":
            shot("done_with_undo"); aid = w.msg["action_id"]; s.undo(aid); s.respond(0); w.hide(False); st["phase"] = "after_undo"; st["t3"] = time.time()
        elif st["phase"] == "after_undo" and time.time() - st["t3"] > 1: shot("after_undo"); st["phase"] = "end"; root.after(300, root.quit); return
        elif time.time() - st["t0"] > 150: shot("timeout"); root.quit(); return
        root.after(700, loop)
    root.after(200, loop)
    try: root.mainloop()
    finally:
        st["eater"] and st["eater"].release()
        for p in procs:
            try: os.kill(p.pid, signal.SIGCONT); p.kill(); p.wait(5)
            except Exception: pass
    final = stage_demo.check(sb); print("最终：", json.dumps(final, ensure_ascii=False)); (out / "live_demo_result.json").write_text(json.dumps(dict(final=final, phase=st["phase"], messages=[m for m in s.messages() if m["kind"] in ("say", "action", "undo")]), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/openlookout/demo_private"))
