"""通用的“重复造轮子”证据提供者：把“正在自己写的东西”与“外部已有能力”（可插拔、可核实的 CapabilityIndex）比对。
没有任何写死的能力类别：描述来自文件自身（文件名、顶部注释/文档字符串、顶层定义名），候选来自索引，是否算数完全由可核实的事实（许可证/活跃度/采用度/相关度）和“通用性”特征决定。
它只产出“证据事件”，交给通用的约定学习器（conventions.py）去推断/落地约定，本身不落规则。"""
from __future__ import annotations
import ast, os, re, time
from pathlib import Path
from .capability import tokens, VerifierPolicy, stem

LANG = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".rs": "rust", ".java": "java"}
SKIP = {"node_modules", ".git", "venv", ".venv", "vendor", "third_party", "tests", "test", "__pycache__", "dist", "build", "examples", "docs", "scripts"}
THEME = "duplicate-effort"
THEME_TEXT = "新建通用模块前，先核实是否已有成熟的外部方案（许可证友好、仍在维护、被广泛使用）；确要自研，请在说明里写明现成方案为什么不合适。"
HELPER = '''#!/usr/bin/env python3
"""写新模块前的预检：python scripts/lookup_existing.py "你要做的事" [语言]  （只用标准库，联网查 GitHub，查不到不阻塞）"""
import json, sys, urllib.parse, urllib.request
q = sys.argv[1] if len(sys.argv) > 1 else ""; lang = sys.argv[2] if len(sys.argv) > 2 else ""
url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q + (f" language:{lang}" if lang else ""), "sort": "stars", "per_page": 6})
try:
    for r in json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lookup-existing"}), timeout=15).read())["items"]:
        print(f"{r['full_name']:40} {(r.get('license') or {}).get('spdx_id')!s:14} {r['stargazers_count']:>7}★  更新 {r['pushed_at'][:10]}  {'[已归档]' if r['archived'] else ''}")
except Exception as e:
    print("查询失败（可忽略，但请写明为什么不用现成方案）:", e)
'''


def describe(path: Path):
    """tier0：从文件自身生成“它在做什么”的短语 + 若干通用性特征。"""
    text = path.read_text("utf-8", "ignore")
    head = []
    try:
        tree = ast.parse(text) if path.suffix == ".py" else None
        doc = ast.get_docstring(tree) if tree else None
        if doc: head.append(doc.split("\n")[0])
        defs = [n.name for n in (tree.body if tree else []) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    except SyntaxError: defs = re.findall(r"(?:function|class|def|func)\s+([A-Za-z_]\w+)", text)
    for l in text.splitlines()[:8]:
        l = l.strip()
        if l.startswith(("#", "//", "/*", "*")): head.append(l.lstrip("#/* "))
    phrase_toks = tokens(path.stem) or tokens(" ".join(head))
    phrase = " ".join(sorted(phrase_toks))
    lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith(("#", "//"))]
    imports = re.findall(r"^\s*(?:from|import)\s+([\w.]+)|require\(['\"]([^'\"]+)['\"]\)|from ['\"]([^'\"]+)['\"]", text, re.M)
    mods = [next(x for x in t if x) for t in imports if any(t)]
    return dict(phrase=phrase, lines=len(lines), imports=mods, defs=defs, text=text)


def coupling(proj: Path, info: dict) -> float:
    """导入里有多少是本项目自己的模块：越高越像“业务专用”，不是通用能力。"""
    if not info["imports"]: return 0.0
    local = 0
    for m in info["imports"]:
        top = m.lstrip(".").split(".")[0].split("/")[0]
        if m.startswith(".") or (proj / top).exists() or (proj / f"{top}.py").exists() or any((proj / s / f"{top}.py").exists() or (proj / s / top).exists() for s in ("src", "app", "lib")): local += 1
    return local / len(info["imports"])


def manifest_names(proj: Path) -> set:
    out = set()
    for f in ("requirements.txt", "requirements-dev.txt"):
        if (proj / f).exists():
            for l in (proj / f).read_text("utf-8", "ignore").splitlines():
                m = re.match(r"\s*([A-Za-z0-9_.\-]+)", l)
                if m and not l.strip().startswith("#"): out.add(m.group(1).lower())
    if (proj / "package.json").exists():
        import json
        try: j = json.loads((proj / "package.json").read_text("utf-8", "ignore")); out |= {k.lower() for k in {**j.get("dependencies", {}), **j.get("devDependencies", {})}}
        except Exception: pass
    if (proj / "pyproject.toml").exists():
        out |= set(re.findall(r'"([A-Za-z0-9_.\-]+)\s*(?:[<>=!~\[;,"])', (proj / "pyproject.toml").read_text("utf-8", "ignore")))
    return {re.sub(r"[-_.]", "", x) for x in out}


def already_covered(proj: Path, info: dict, cand) -> bool:
    """项目已经依赖/导入了这个候选（或其同名包）。"""
    names = manifest_names(proj) | {re.sub(r"[-_.]", "", m.split(".")[0].lower()) for m in info["imports"]}
    base = re.sub(r"[-_.]", "", cand.name.split("/")[-1].lower())
    return base in names or any(base.startswith(n) and len(n) >= 4 for n in names) or any(n in base and len(n) >= 5 for n in names)


class ReinventionProvider:
    """world 每次状态更新时调用 events(world)，返回新的证据事件（每个文件只评估一次）。"""
    def __init__(self, index, verifier: VerifierPolicy | None = None, projects_getter=lambda w: [], min_lines=60, settle_s=600, max_coupling=0.3):
        self.index, self.verifier, self.projects, self.min_lines, self.settle, self.max_coupling = index, verifier or VerifierPolicy(), projects_getter, min_lines, settle_s, max_coupling
        self.seen = set(); self.cache = {}

    def events(self, world) -> list:
        now = world.env.now; out = []
        for proj in map(Path, self.projects(world)):
            if not proj.is_dir(): continue
            for f in sorted(proj.rglob("*")):
                if not f.is_file() or f.suffix not in LANG or str(f) in self.seen: continue
                rel = f.relative_to(proj).parts
                if set(rel[:-1]) & SKIP: continue
                try: st = f.stat()
                except OSError: continue
                if now - st.st_mtime < self.settle: continue                   # 还在写，下次再看（不标记 seen）
                self.seen.add(str(f))
                info = describe(f)
                if info["lines"] < self.min_lines or not info["phrase"]: continue                # 体量不够/说不清在做什么
                if coupling(proj, info) > self.max_coupling: continue                           # 业务耦合高：专用代码，不是通用能力
                if re.search(r"(?i)(wrapper|adapter|thin|shim|binding)", info["text"][:500]): continue
                if tokens(proj.name) & set(info["phrase"].split()) and len(tokens(proj.name)) >= 1: continue   # 项目本身就是做这件事的
                lang = LANG[f.suffix]
                key = (info["phrase"], lang)
                if key not in self.cache: self.cache[key] = self.index.search(info["phrase"], lang)
                good = []
                for c in self.cache[key]:
                    ok, why = self.verifier.check(c, info["phrase"])
                    if ok and not already_covered(proj, info, c): good.append((c, why))
                    elif ok: good = []; break                                                    # 已经在用成熟方案
                if not good: continue
                best = good[0]
                out.append(dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), kind="reinvention", theme=THEME, theme_text=THEME_TEXT, project=str(proj),
                                source="detector", strength=1.0, helper=dict(path="scripts/lookup_existing.py", content=HELPER),
                                text=f"自写“{info['phrase']}”（{f.relative_to(proj)}，{info['lines']} 行）；已核实的现成方案：{best[0].name}（{best[1]}）",
                                examples=[dict(name=c.name, why=w) for c, w in good[:3]]))
        return out
