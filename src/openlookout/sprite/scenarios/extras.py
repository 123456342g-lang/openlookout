"""两个“只靠注册”加入的小场景，用来证明框架通用：核心代码一行没改。
1) log_runaway：日志文件短时间暴涨 -> 压缩进隔离区（正被写入的文件不碰）
2) desktop_pile：桌面散落文件过多 -> 按类型归到“整理/”，并写还原映射"""
from __future__ import annotations
import json, shutil
from pathlib import Path
from ..framework import Problem, Action, Scenario

EXT = {"图片": {".png", ".jpg", ".jpeg", ".gif", ".webp"}, "文档": {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}, "安装包": {".exe", ".msi", ".zip"}}


def log_runaway(log_dir: Path, grow_mb=200):
    last = {}
    def detect(w):
        out = []
        for p in Path(log_dir).glob("*.log"):
            sz = p.stat().st_size; prev = last.get(p, sz); last[p] = sz
            if (sz - prev) / 2**20 >= grow_mb:
                out.append(Problem("log_runaway", 0.6, f"{p.name} 短时间涨了 {(sz-prev)/2**20:.0f}MB", key=str(p), ctx=dict(path=p)))
        return out
    def propose(pb, w):
        p = pb.ctx["path"]
        if str(p) in w.env.open_paths:
            return [Action("log:open", p.name, "high", "none", reason="正在被程序写入")]
        size = p.stat().st_size
        def run(): return dict(id=w.q.put(p, "日志")["id"])
        return [Action("log_quarantine", f"压缩 {p.name}", "safe", "full", blast_bytes=size, reason="未被占用的暴涨日志",
                       run=run, verify=lambda r: r["id"] in {e["id"] for e in w.q.held()} and not p.exists(),
                       undo=lambda r: w.q.restore(r["id"]),
                       done_text=lambda xs: f"把暴涨的日志 {p.name}（{size/2**20:.0f}MB）压缩收进了隔离区")]
    return Scenario("log_runaway", detect, propose)


def desktop_pile(desktop: Path, min_files=15):
    def loose(): return [p for p in Path(desktop).iterdir() if p.is_file() and p.suffix.lower() not in (".lnk", ".url", ".ini")]
    state = {"armed": True}
    def detect(w):
        n = len(loose())
        if n >= min_files and state["armed"]:
            state["armed"] = False; return [Problem("desktop_pile", 0.4, f"桌面散落 {n} 个文件", key="desktop")]
        if n < min_files: state["armed"] = True
        return []
    def propose(pb, w):
        moves = []
        for p in loose():
            if w.env.now - p.stat().st_mtime < 86400 or str(p) in w.env.open_paths: continue       # 最近动过/占用的不碰
            cat = next((c for c, ex in EXT.items() if p.suffix.lower() in ex), "其他")
            moves.append((p, Path(desktop) / "整理" / cat / p.name))
        def run():
            done = []
            for a, b in moves:
                if b.exists(): continue
                b.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(a), str(b)); done.append((str(a), str(b)))
            (Path(desktop) / "整理" / "_还原映射.json").write_text(json.dumps(done, ensure_ascii=False, indent=1), "utf-8")
            return dict(done=done)
        def undo(r):
            for a, b in reversed(r["done"]):
                if Path(b).exists() and not Path(a).exists(): shutil.move(b, a)
            (Path(desktop) / "整理" / "_还原映射.json").unlink(missing_ok=True)
        return [Action("desktop_tidy", f"整理桌面 {len(moves)} 个文件", "safe", "full", blast_items=len(moves), reason="只移动、有还原映射",
                       dry_run=lambda: bool(moves), run=run, verify=lambda r: all(Path(b).exists() and not Path(a).exists() for a, b in r["done"]), undo=undo,
                       done_text=lambda xs: f"把桌面上 {len(moves)} 个散落文件按类型收进了「整理」（有还原映射）")]
    return Scenario("desktop_pile", detect, propose)
