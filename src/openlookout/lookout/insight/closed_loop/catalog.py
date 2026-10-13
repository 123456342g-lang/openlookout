"""Intervention catalog: concrete, reversible, safely executable actions.

Every item has
  - ``precondition(stats, cells)``  detector on behavior stats (no file access)
  - ``plan(root)`` / ``dry_run(root)``  list of file ops, nothing touched
  - ``apply(root, journal)``  executes ops inside ``root`` only, writes undo journal
  - ``undo(journal)``  exact inverse, newest-first
  - ``signature``  measurable cost signature: which cost types it should reduce
    (nominal fraction) -> used to pick the cells to measure in a switchback trial.

Safety: ops never leave ``root``, never delete user data (dedupe MOVES to ``_dupes``),
never overwrite (a colliding destination aborts the plan), no network, no shell exec.
"""
from __future__ import annotations
import hashlib, json, os, re, shutil
from pathlib import Path
from dataclasses import dataclass, field

COST_TYPES = ["retry", "back", "redo", "idle", "aband"]


# ---------------------------------------------------------------- file-op engine
class PlanError(Exception):
    pass


def _inside(root: Path, p: Path):
    root = root.resolve(); p = p.resolve()
    if root != p and root not in p.parents:
        raise PlanError(f"path escapes root: {p}")


def _check(root: Path, ops):
    seen_dst = set()
    for o in ops:
        for k in ("src", "dst"):
            if o.get(k):
                _inside(root, root / o[k])
        if o["op"] in ("move", "copy", "write") and o.get("dst"):
            d = root / o["dst"]
            if d.exists() or o["dst"] in seen_dst:
                raise PlanError(f"destination exists/duplicated: {o['dst']}")
            seen_dst.add(o["dst"])
        if o["op"] in ("move", "copy") and not (root / o["src"]).exists():
            raise PlanError(f"missing source: {o['src']}")


def _ensure_parents(root, dst, done):
    missing = []
    d = (root / dst).parent
    while d != root and not d.exists():
        missing.append(d); d = d.parent
    for d in reversed(missing):
        d.mkdir(); done.append(dict(op="mkdir", dst=str(d.relative_to(root))))


def execute(root, ops, journal_path):
    root = Path(root); _check(root, ops)
    done = []
    try:
        for o in ops:
            if o["op"] == "mkdir":
                if (root / o["dst"]).exists():
                    continue
                _ensure_parents(root, o["dst"], done)
                (root / o["dst"]).mkdir(); done.append(o)
                continue
            _ensure_parents(root, o["dst"], done)
            if o["op"] == "move":
                shutil.move(str(root / o["src"]), str(root / o["dst"]))
            elif o["op"] == "copy":
                shutil.copy2(root / o["src"], root / o["dst"])
            elif o["op"] == "write":
                (root / o["dst"]).write_text(o["content"], encoding="utf-8")
            done.append(o)
    except Exception:
        _undo_ops(root, done)
        raise
    Path(journal_path).write_text(json.dumps(dict(root=str(root), ops=done), ensure_ascii=False), encoding="utf-8")
    return done


def _undo_ops(root, done):
    root = Path(root)
    for o in reversed(done):
        if o["op"] == "mkdir":
            try: (root / o["dst"]).rmdir()
            except OSError: pass
        elif o["op"] == "move":
            shutil.move(str(root / o["dst"]), str(root / o["src"]))
        elif o["op"] in ("copy", "write"):
            try: (root / o["dst"]).unlink()
            except FileNotFoundError: pass


def undo(journal_path):
    j = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    _undo_ops(j["root"], j["ops"])
    Path(journal_path).unlink()
    return len(j["ops"])


# ---------------------------------------------------------------- name helpers
_MARK = re.compile(r"(最终版?|终稿|定稿|修改版?|副本|复制|final|copy|new|latest|v\d+|\(\d+\)|（\d+）|[_\- ]\d{4}[-_]?\d{2}[-_]?\d{2}|[_\- ]?\d+$)", re.I)


def base_stem(name):
    s = Path(name).stem
    prev = None
    while prev != s:
        prev = s; s = _MARK.sub("", s).strip(" _-")
    return s or Path(name).stem


def _files(root: Path, depth=1):
    out = []
    for p in sorted(root.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            out.append(p)
        elif p.is_dir() and depth > 0 and not p.name.startswith(("_", ".")):
            out += _files(p, depth - 1)
    return out


# ---------------------------------------------------------------- interventions
@dataclass
class Intervention:
    id: str
    name: str
    signature: dict            # cost_type -> nominal fractional reduction
    burden_s: float            # seconds/day of attention while being tested
    risk: float                # 0..1 rough chance of unwanted side effect
    pattern: str               # which behaviour pattern its precondition needs
    doc: str = ""

    # ---- precondition on behaviour stats (see pool.pattern_stats)
    def precondition(self, stats, cells):
        ctxs = {c for c, _ in cells}
        ev = sum(stats["pattern"][self.pattern].get(c, 0) for c in ctxs)
        exp = 0.0
        for c, t in cells:
            exp += stats["daily_cost"].get((c, t), 0.0) * self.signature.get(t, 0.0)
        applicable = ev > 0 and exp > self.burden_s * 0.25
        return dict(item=self.id, evidence=int(ev), expected_saving_s_day=float(exp), applicable=bool(applicable))

    # ---- file plan
    def plan(self, root, **kw):  # pragma: no cover - overridden
        return []

    def dry_run(self, root, **kw):
        ops = self.plan(Path(root), **kw)
        _check(Path(root), ops)
        return ops

    def apply(self, root, journal, **kw):
        return execute(root, self.dry_run(root, **kw), journal)

    undo = staticmethod(undo)


class ReportVersioning(Intervention):
    def plan(self, root, **kw):
        groups = {}
        for p in _files(root):
            groups.setdefault((p.parent, base_stem(p.name), p.suffix.lower()), []).append(p)
        ops = []
        for (par, base, ext), fs in sorted(groups.items(), key=lambda x: str(x[0])):
            if len(fs) < 2: continue
            fs.sort(key=lambda p: (p.stat().st_mtime, p.name))
            for i, p in enumerate(fs, 1):
                new = f"{base}_v{i:02d}{ext}"
                if p.name != new:
                    ops.append(dict(op="move", src=str(p.relative_to(root)), dst=str((par / new).relative_to(root))))
        return ops


class SeriesScaffold(Intervention):
    def plan(self, root, **kw):
        series = {}
        for d in sorted(root.iterdir()):
            m = re.match(r"^(.*?)(\d+)$", d.name)
            if d.is_dir() and m and m.group(1):
                series.setdefault(m.group(1), []).append((int(m.group(2)), d, len(m.group(2))))
        ops = []
        for pref, xs in sorted(series.items()):
            if len(xs) < 2: continue
            xs.sort(); n, last, w = xs[-1]
            new = f"{pref}{n + 1:0{w}d}"
            ops.append(dict(op="mkdir", dst=new))
            for sub in sorted(q for q in last.iterdir() if q.is_dir()):
                ops.append(dict(op="mkdir", dst=f"{new}/{sub.name}"))
            ops.append(dict(op="write", dst=f"{new}/README.md",
                            content=f"# {new}\n\nScaffolded from {last.name} by OpenLookout (undo-able).\n"))
        return ops


class ScriptGenerator(Intervention):
    def plan(self, root, steps=None, name="repeat_steps", **kw):
        steps = steps or ["# TODO: list the repeated manual steps, one shell command per line"]
        body = ("#!/usr/bin/env python3\n\"\"\"Generated runbook. Prints steps; executes only with --yes.\"\"\"\n"
                "import subprocess, sys\nSTEPS = " + json.dumps(steps, ensure_ascii=False) + "\n"
                "for s in STEPS:\n    print('>', s)\n    if '--yes' in sys.argv and not s.startswith('#'):\n"
                "        subprocess.run(s, shell=True, check=True)\n")
        return [dict(op="write", dst=f"{name}.py", content=body)]


class DownloadDedupe(Intervention):
    def plan(self, root, **kw):
        by = {}
        for p in _files(root, depth=0):
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            by.setdefault(h, []).append(p)
        ops = []
        for h, fs in sorted(by.items()):
            if len(fs) < 2: continue
            fs.sort(key=lambda p: (p.stat().st_mtime, p.name))
            for p in fs[1:]:
                ops.append(dict(op="move", src=p.name, dst=f"_dupes/{p.name}"))
        return ops


class TemplateCreator(Intervention):
    def plan(self, root, **kw):
        groups = {}
        for p in _files(root):
            groups.setdefault((base_stem(p.name), p.suffix.lower()), []).append(p)
        ops = []
        for (base, ext), fs in sorted(groups.items()):
            if len(fs) < 2: continue
            latest = max(fs, key=lambda p: (p.stat().st_mtime, p.name))
            ops.append(dict(op="copy", src=str(latest.relative_to(root)), dst=f"_templates/{base}_template{ext}"))
        return ops


class AppLauncher(Intervention):
    def plan(self, root, apps=("appA", "appB"), name=None, **kw):
        a, b = apps; name = name or f"launch_{a}_{b}"
        sh = f"#!/bin/sh\n# opens {a} and {b} together (edit the commands)\n{a} &\n{b} &\n"
        cmd = f"@echo off\r\nrem opens {a} and {b} together (edit the commands)\r\nstart \"\" {a}\r\nstart \"\" {b}\r\n"
        return [dict(op="write", dst=f"{name}.sh", content=sh), dict(op="write", dst=f"{name}.cmd", content=cmd)]


# signature = nominal reduction per cost type if the item applies (a *prior*, not truth)
CATALOG = [
    ReportVersioning("versioning", "重复报告自动命名/版本化", {"redo": 0.70, "retry": 0.05}, 20, 0.25, "artifact"),
    SeriesScaffold("scaffold", "编号任务系列目录脚手架", {"redo": 0.40, "idle": 0.30, "aband": 0.15}, 25, 0.15, "artifact"),
    ScriptGenerator("script_gen", "重复手工步骤脚本生成", {"retry": 0.60, "redo": 0.30}, 35, 0.35, "repeat"),
    DownloadDedupe("dedupe", "下载去重", {"redo": 0.50, "retry": 0.20}, 15, 0.20, "artifact"),
    TemplateCreator("template", "模板创建", {"redo": 0.40, "idle": 0.40, "aband": 0.30}, 25, 0.15, "artifact"),
    AppLauncher("launcher", "应用切换快捷启动器", {"back": 0.70, "idle": 0.30, "aband": 0.20}, 20, 0.15, "alternate"),
]
BY_ID = {c.id: c for c in CATALOG}
