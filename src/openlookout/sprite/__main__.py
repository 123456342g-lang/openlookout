"""python -m sprite [--no-gui] [--home DIR] [--once] [--undo ID] [--kill|--resume]"""
import argparse, subprocess, sys, time
from pathlib import Path
from . import config
from .core import Sprite


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sprite")
    ap.add_argument("--home"); ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--once", action="store_true"); ap.add_argument("--undo"); ap.add_argument("--list", action="store_true"); ap.add_argument("--say", nargs=2, metavar=("项目", "看法")); ap.add_argument("--tell", nargs=2, metavar=("项目路径", "你对代理说的话/纠正"))
    ap.add_argument("--kill", action="store_true"); ap.add_argument("--resume", action="store_true")
    a = ap.parse_args(argv)
    home = Path(a.home) if a.home else config.data_dir()
    home.mkdir(parents=True, exist_ok=True)
    if a.kill: (home / "KILL").write_text("stop"); print("已停用（删除 KILL 文件或 --resume 恢复）"); return
    if a.resume: (home / "KILL").unlink(missing_ok=True); print("已恢复"); return
    cfg = config.load(home)
    probe = world = reg = None
    if cfg.get("resource_watch", True):
        from . import defaults
        probe, world, reg = defaults.build(cfg, home)
    s = Sprite(cfg, home, probe=probe, world=world, registry=reg)
    if a.say: s.hear(a.say[0], a.say[1]); print("记下了（作为参考证据，不是命令）"); return
    if a.tell:
        import json as _j, datetime as _d
        with (s.home / "behavior.jsonl").open("a", encoding="utf-8") as f: f.write(_j.dumps(dict(ts=_d.datetime.now().isoformat(timespec="seconds"), kind="instruction", project=a.tell[0], text=a.tell[1], source="user"), ensure_ascii=False) + "\n")
        print("记下了（重复出现、跨天、够可信时才会变成长期约定）"); return
    if a.list:
        for x in s.messages():
            if x.get("kind") == "action": print(x["id"], x["ts"], x["status"], x["text"])
        return
    if a.undo: print("已撤销" if s.undo(a.undo) else "找不到可撤销的记录"); return
    if cfg.get("recorder") and sys.platform == "win32":
        rec = Path(__file__).resolve().parent.parent / "recorder_win" / "record_win.py"
        subprocess.Popen([sys.executable, str(rec), "--out", str(home / "events.jsonl")] +
                         [x for r in cfg["watch"] for x in ("--watch", str(Path(r).expanduser()))])
    if a.once: print(s.tick()); return
    if a.no_gui:
        s.on_message = lambda m: print("🧚", m["text"], "|", " / ".join(m["options"])) if m.get("kind") == "say" else None
        while True: s.tick(); time.sleep(cfg["poll_s"])
    from .gui import run_gui
    run_gui(s, cfg["bubble_seconds"], cfg["poll_s"])

if __name__ == "__main__":
    main()
