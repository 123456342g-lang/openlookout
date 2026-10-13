"""通用“执行层”：代码 / 桌面 / 文档三类执行器，像场景一样声明式注册；决策核心只挑执行器，本地（tier0）代码负责执行，
LLM 只在“没有任何执行器认识的新情况”时出一份任务说明（spec），真正动手的仍然是这里的确定性代码。

共同约束（全部直接做、全部可还原、不问）：
  - 每个执行器声明 risk（safe|medium|high）和 reversible；产出的 Action 走同一套 引擎闸门（价值闸/dry_run/verify/回滚/信任账本）。
  - 做不到“可还原”的 spec 一律拒绝（plan 返回 None），不会降级成“问你”。
  - 代码执行器：沙箱副本里写入+编译/跑检查（dry-run）→ 通过才改真文件；改前备份（带哈希）；撤销=还原备份，但你之后又改过的话不覆盖，另存 .undo_restored。
  - 桌面执行器：优先 API → CLI(白名单) → 文件操作；鼠标键盘只作最后手段，且只在你空闲足够久时用，每步前检查，一有输入立刻中止并撤销已做的步骤。
  - 文档执行器：只写草稿到固定目录，不覆盖原件、不覆盖已有草稿、没有任何发送能力（带收件人/发送字段的 spec 直接拒绝）。
"""
from __future__ import annotations
import hashlib, os, py_compile, shutil, subprocess, sys, tempfile, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .framework import Action

RISK_ORDER = {"safe": 0, "medium": 1, "high": 2}


def _sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


@dataclass
class Task:
    kind: str                   # code | desktop | document
    goal: str
    spec: dict = field(default_factory=dict)
    novel: bool = False         # 没有现成执行器认识：允许问一次 LLM 来产出 spec
    value_s: float = 120.0      # 预计为用户省下的秒数（进价值闸）


class Executor:
    name = "base"; kind = ""; risk = "safe"; reversible = "full"
    def can(self, task: Task) -> bool: return task.kind == self.kind
    def risk_for(self, task: Task) -> str: return self.risk
    def plan(self, task: Task) -> Action | None: raise NotImplementedError


class ExecutorRegistry:
    def __init__(self): self.items: dict[str, Executor] = {}; self.llm_calls = 0
    def register(self, ex: Executor): self.items[ex.name] = ex; return ex
    def pick(self, task: Task) -> Executor | None:
        c = [e for e in self.items.values() if e.can(task)]
        return min(c, key=lambda e: RISK_ORDER[e.risk_for(task)]) if c else None      # 多个都能做时，选风险最低的
    def action_for(self, task: Task, llm: Callable[[Task], dict] | None = None) -> Action | None:
        ex = self.pick(task)
        if ex is None and task.novel and llm:                    # 只有全新的情况才用 LLM，且它只出 spec，不执行
            self.llm_calls += 1
            spec = llm(task) or {}
            task = Task(spec.get("kind", task.kind), task.goal, spec.get("spec", {}), False, task.value_s)
            ex = self.pick(task)
        if ex is None: return None
        a = ex.plan(task)
        if a is not None:
            a.value_s = task.value_s; a.kind = f"exec:{ex.name}"; a.reason = a.reason or f"{ex.name} 执行器"
        return a


# ------------------------------------------------------------------ 代码执行器
class CodeExecutor(Executor):
    name = "code"; kind = "code"; risk = "medium"
    def __init__(self, allowed_roots, backup_dir, timeout_s=60, max_copy_mb=50):
        self.roots = [Path(r).resolve() for r in allowed_roots]; self.backup = Path(backup_dir); self.timeout = timeout_s; self.max_mb = max_copy_mb

    def _inside(self, p: Path) -> bool:
        p = p.resolve(); return any(p == r or r in p.parents for r in self.roots)

    def plan(self, task):
        sp = task.spec; path = Path(sp["path"]); root = Path(sp.get("root", path.parent))
        if not (self._inside(path) and self._inside(root) and (root.resolve() == path.resolve().parent or root.resolve() in path.resolve().parents)): return None
        new = sp["content"].encode("utf-8"); h = _sha(new); checks = sp.get("checks", [])           # checks: [argv,...] 在沙箱副本里跑
        rel = path.resolve().relative_to(root.resolve()); holder = {}

        def dry():
            size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.is_dir() else 0
            if size > self.max_mb * 2**20: return False
            sb = Path(tempfile.mkdtemp(prefix="sprite_code_")); holder["sb"] = sb
            try:
                shutil.copytree(root, sb / "p", ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"), dirs_exist_ok=True)
                t = sb / "p" / rel; t.parent.mkdir(parents=True, exist_ok=True); t.write_bytes(new)
                if t.suffix == ".py": py_compile.compile(str(t), doraise=True, cfile=str(sb / "x.pyc"))
                env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "HOME", "LANG")}
                for argv in checks:
                    argv = [sys.executable if a == "{python}" else a for a in argv]
                    r = subprocess.run(argv, cwd=sb / "p", env=env, capture_output=True, timeout=self.timeout)
                    if r.returncode != 0: return False
                return True
            except Exception: return False
            finally: shutil.rmtree(sb, ignore_errors=True)

        def run():
            bid = f"{int(time.time()*1000)}_{h[:8]}"; bk = self.backup / bid / "orig"; had = path.exists()
            bk.parent.mkdir(parents=True, exist_ok=True)
            if had: shutil.copy2(path, bk)
            tmp = path.with_name(path.name + ".sprite_tmp"); tmp.write_bytes(new); os.replace(tmp, path)       # 原子替换
            return dict(backup=str(bk) if had else None, had=had, path=str(path), sha=h)
        def verify(r):
            ok = path.read_bytes() == new
            if ok and path.suffix == ".py":
                try: compile(path.read_text('utf-8'), str(path), 'exec')
                except Exception: ok = False
            return ok
        def undo(r):
            p = Path(r["path"])
            if p.exists() and _sha(p.read_bytes()) != r["sha"]:        # 你之后又改过：不覆盖，旧版本另存
                if r["backup"]: shutil.copy2(r["backup"], p.with_name(p.name + ".undo_restored"))
                return
            if r["had"]: shutil.copy2(r["backup"], p)
            elif p.exists(): p.unlink()
        return Action("code", f"改 {path.name}", "medium", "full", blast_items=1, blast_bytes=len(new), confident=True, dry_run=dry, run=run, verify=verify, undo=undo,
                      done_text=lambda xs: f"改了 {path.name}（沙箱里检查通过，已备份，可撤销）：{task.goal}", done_short=lambda xs: f"改了 {path.name}，可撤销")


# ------------------------------------------------------------------ 桌面执行器
class Backend:
    """一种操作途径：run(params)->token；undo(token)。"""
    def __init__(self, run, undo): self.run, self.undo = run, undo


PREF = ["api", "cli", "file", "input"]            # 优先级：越前越好；input（鼠标键盘）是最后手段


class DesktopExecutor(Executor):
    name = "desktop"; kind = "desktop"; risk = "safe"
    def __init__(self, backends: dict, idle: Callable[[], float] = lambda: 0.0, idle_needed=120.0, input_break_s=2.0, cli_allow=()):
        self.be, self.idle, self.need_idle, self.brk, self.cli_allow = backends, idle, idle_needed, input_break_s, set(cli_allow)

    def _choose(self, step):
        for via in PREF:
            if via in step and via in self.be:
                if via == "cli" and step["cli"].get("argv", [""])[0] not in self.cli_allow: continue
                if "undo" not in step[via]: continue                  # 不能还原的做法不采用
                return via
        return None

    def risk_for(self, task):
        ch = [self._choose(s) for s in task.spec.get("steps", [])]
        return "medium" if "input" in ch else "safe"

    def plan(self, task):
        steps = task.spec.get("steps", []); ch = [self._choose(s) for s in steps]
        if not steps or None in ch: return None                          # 有一步没有可还原途径：整个任务不做
        uses_input = "input" in ch
        def dry():
            if uses_input and self.idle() < self.need_idle: return False       # 鼠标键盘只在你空闲时
            return True
        def run():
            done = []; last_idle = self.idle() if uses_input else None
            try:
                for s, via in zip(steps, ch):
                    if via == "input":
                        cur = self.idle()
                        if cur < self.brk or cur < (last_idle or 0) - 1: raise RuntimeError("检测到你在操作，已中止")       # 一有输入立刻中止
                        last_idle = cur
                    tok = self.be[via].run(s[via]); done.append((via, s[via], tok))
            except Exception:
                self._rollback(done); raise
            return dict(done=done)
        def verify(r): return len(r["done"]) == len(steps)
        def undo(r): self._rollback(r["done"])
        return Action("desktop", task.goal, "medium" if uses_input else "safe", "full", blast_items=len(steps), confident=True, dry_run=dry, run=run, verify=verify, undo=undo,
                      done_text=lambda xs: f"{task.goal}（{'/'.join(sorted(set(ch)))}，可撤销）", done_short=lambda xs: f"{task.goal[:14]}，可撤销")

    def _rollback(self, done):
        for via, params, tok in reversed(done):
            try: self.be[via].undo((params, tok))
            except Exception: pass


# ------------------------------------------------------------------ 文档执行器
FORBIDDEN_KEYS = {"send", "to", "cc", "bcc", "recipients", "email", "post", "publish", "upload"}


class DocumentExecutor(Executor):
    name = "document"; kind = "document"; risk = "safe"
    def __init__(self, drafts_dir): self.dir = Path(drafts_dir)

    def can(self, task): return task.kind == "document" and not (FORBIDDEN_KEYS & {k.lower() for k in task.spec})       # 带发送意图的不接

    def plan(self, task):
        sp = task.spec; name = Path(sp["name"]).name
        if not name or name.startswith("."): return None
        body = sp["content"].encode("utf-8"); h = _sha(body); box = {}
        def target():
            stem, suf = Path(name).stem, Path(name).suffix; p = self.dir / name; i = 2
            while p.exists(): p = self.dir / f"{stem}_v{i}{suf}"; i += 1               # 永不覆盖已有文件（含原件、旧草稿）
            return p
        def dry(): return self.dir.resolve() == target().resolve().parent
        def run():
            self.dir.mkdir(parents=True, exist_ok=True); p = target(); p.write_bytes(body); box["p"] = p; return dict(path=str(p))
        def verify(r): return Path(r["path"]).read_bytes() == body
        def undo(r):
            p = Path(r["path"])
            if p.exists() and _sha(p.read_bytes()) == h:
                tr = self.dir / ".trash"; tr.mkdir(exist_ok=True); shutil.move(str(p), str(tr / f"{int(time.time())}_{p.name}"))      # 进回收目录，不直接删
        return Action("document", f"写草稿 {name}", "safe", "full", blast_items=1, blast_bytes=len(body), dry_run=dry, run=run, verify=verify, undo=undo,
                      done_text=lambda xs: f"写了草稿「{name}」放在 {self.dir.name}（没发送、没动原件）", done_short=lambda xs: f"写好草稿 {name[:14]}")


def default_registry(home: Path, allowed_code_roots=(), drafts_dir=None, backends=None, idle=lambda: 0.0, cli_allow=()) -> ExecutorRegistry:
    r = ExecutorRegistry(); home = Path(home)
    r.register(CodeExecutor(allowed_code_roots, home / "code_backups"))
    r.register(DesktopExecutor(backends or {}, idle, cli_allow=cli_allow))
    r.register(DocumentExecutor(drafts_dir or home / "drafts"))
    return r
