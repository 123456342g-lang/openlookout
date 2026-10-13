"""带撤销日志的文件操作执行器（在 catalog 的基础上多一个 append：给已有文件追加一段，撤销时还原原字节）。
只有 mkdir/move/copy/write/append，没有删除用户数据的操作。"""
from __future__ import annotations
import base64, json, shutil
from pathlib import Path
from lookout.insight.closed_loop import catalog as C


def execute(root, ops, journal_path):
    root = Path(root); C._check(root, ops)
    done = []
    try:
        for o in ops:
            if o["op"] == "append":
                p = root / o["dst"]; C._inside(root, p)
                orig = p.read_bytes() if p.exists() else None
                p.parent.mkdir(parents=True, exist_ok=True)
                if orig is None: p.write_text(o["content"], encoding="utf-8")
                else: p.write_bytes(orig + o["content"].encode("utf-8"))
                done.append(dict(o, orig=None if orig is None else base64.b64encode(orig).decode()))
                continue
            if o["op"] == "mkdir":
                if (root / o["dst"]).exists(): continue
                C._ensure_parents(root, o["dst"], done); (root / o["dst"]).mkdir(); done.append(o); continue
            C._ensure_parents(root, o["dst"], done)
            if o["op"] == "move": shutil.move(str(root / o["src"]), str(root / o["dst"]))
            elif o["op"] == "copy": shutil.copy2(root / o["src"], root / o["dst"])
            elif o["op"] == "write": (root / o["dst"]).write_text(o["content"], encoding="utf-8")
            done.append(o)
    except Exception:
        _undo(root, done); raise
    Path(journal_path).write_text(json.dumps(dict(root=str(root), ops=done), ensure_ascii=False), encoding="utf-8")
    return done


def _undo(root, done):
    root = Path(root)
    for o in reversed(done):
        if o["op"] == "append":
            p = root / o["dst"]
            if o["orig"] is None: p.unlink(missing_ok=True)
            else: p.write_bytes(base64.b64decode(o["orig"]))
        else:
            C._undo_ops(root, [o])


def undo(journal_path):
    j = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    _undo(j["root"], j["ops"]); Path(journal_path).unlink()
    return len(j["ops"])
