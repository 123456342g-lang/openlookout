"""小精灵核心逻辑（无 GUI、仅标准库）。

流程：扫描 -> 事件 -> 触发规则 -> dry-run 校验 -> 安全策略 -> apply(带撤销日志) -> 事后校验 -> 消息。
"""
from __future__ import annotations
import hashlib, json, re, sys, time, uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lookout.insight.closed_loop import catalog as C  # noqa: E402
from .decide import Brain  # noqa: E402
from . import voice, tiers  # noqa: E402
from .framework import Engine, Registry  # noqa: E402
from .fork import load_events as fork_load  # noqa: E402

SAFE_OPS = {"mkdir", "move", "copy", "write"}   # 没有 delete：永远不删除用户数据


# ------------------------------------------------------------------ 扫描 / 事件
def snapshot(root: Path, depth: int = 2) -> dict:
    out = {}
    def walk(d, lvl):
        try: it = list(d.iterdir())
        except OSError: return
        for p in it:
            if p.name.startswith((".", "~$")) or p.name.endswith((".tmp", ".crdownload", ".part")):
                continue
            try: st = p.stat()
            except OSError: continue
            if p.is_dir():
                out[str(p.relative_to(root))] = ("d", st.st_mtime, 0)
                if lvl < depth and not p.name.startswith("_"): walk(p, lvl + 1)
            else:
                out[str(p.relative_to(root))] = ("f", st.st_mtime, st.st_size)
    walk(root, 0)
    return out


def diff(old: dict, new: dict) -> list[dict]:
    ev = [dict(kind="created", path=k, type=v[0]) for k, v in new.items() if k not in old]
    ev += [dict(kind="modified", path=k, type=v[0]) for k, v in new.items() if k in old and old[k] != v and v[0] == "f"]
    ev += [dict(kind="removed", path=k) for k in old if k not in new]
    return ev


# ------------------------------------------------------------------ 规则
class FillNewSeriesDir(C.Intervention):
    """新建的编号目录（如 lab7）是空的、且上一期（lab6）有子目录结构 -> 补齐子目录和 README。"""
    def plan(self, root, target=None, **kw):
        t = root / target
        m = re.match(r"^(.*?)(\d+)$", t.name)
        if not (t.is_dir() and m and m.group(1)) or any(t.iterdir()):
            return []
        prev = [d for d in t.parent.iterdir() if d.is_dir() and d != t and (mm := re.match(r"^(.*?)(\d+)$", d.name))
                and mm.group(1) == m.group(1) and int(mm.group(2)) < int(m.group(2))]
        if not prev: return []
        last = max(prev, key=lambda d: int(re.search(r"(\d+)$", d.name).group(1)))
        rel = t.relative_to(root)
        ops = [dict(op="mkdir", dst=str(rel / s.name)) for s in sorted(last.iterdir()) if s.is_dir() and not s.name.startswith(("_", "."))]
        ops.append(dict(op="write", dst=str(rel / "README.md"),
                        content=f"# {t.name}\n\n由 OpenLookout 小精灵按 {last.name} 的结构创建（可撤销）。\n"))
        return ops


FILL = FillNewSeriesDir("fill_series", "新编号目录补齐结构", {}, 0, 0.1, "artifact")


def _settled(root: Path, snap: dict, now: float, settle: float, rels):
    return all(now - snap[r][1] >= settle for r in rels if r in snap)


def propose(rule: str, root: Path, events: list, snap: dict, now: float, cfg: dict):
    """返回 [(intervention, kwargs, 触发路径, 文案)]；只做触发判断，不动磁盘。"""
    settle = cfg["settle_s"]
    out = []
    if rule == "scaffold":
        for e in events:
            if e["kind"] == "created" and e["type"] == "d" and re.search(r"\d+$", Path(e["path"]).name):
                if True:   # 目录必须为空才会动手（见 FillNewSeriesDir.plan），无需等待
                    nm = Path(e["path"]).name
                    out.append((FILL, dict(target=e["path"]), [e["path"]], f"给新建的「{nm}」建好了子文件夹和说明文件"))
    elif rule == "dedupe":
        item = C.BY_ID["dedupe"]
        fs = [e["path"] for e in events if e["kind"] in ("created", "modified") and e.get("type") == "f" and "/" not in e["path"].replace("\\", "/")]
        if fs and _settled(root, snap, now, settle, fs):
            out.append((item, {}, fs, "把下载里重复的文件移到了「_dupes」（没有删除）"))
    elif rule == "versioning":
        item = C.BY_ID["versioning"]
        fs = [e["path"] for e in events if e["kind"] in ("created", "modified") and e.get("type") == "f"]
        if fs and _settled(root, snap, now, settle, fs):
            groups = {}
            for p in C._files(root):
                if p.name.startswith("~$"): continue
                groups.setdefault((p.parent, C.base_stem(p.name), p.suffix.lower()), []).append(p)
            if any(len(v) >= 3 and any(str(f.relative_to(root)) in fs for f in v) for v in groups.values()):
                out.append((item, {}, fs, "把一堆「最终/副本」的同名报告按时间编成了 v01、v02…"))
    return out


# ------------------------------------------------------------------ 安全策略
class Refused(Exception):
    pass


def policy_check(root: Path, ops: list, cfg: dict):
    if not ops: raise Refused("空计划")
    if len(ops) > cfg["max_ops_per_action"]: raise Refused("动作太多")
    for o in ops:
        if o["op"] not in SAFE_OPS: raise Refused(f"不允许的操作 {o['op']}")
    C._check(root, ops)          # 不出根目录、不覆盖、源存在


def _hashes(root: Path, ops):
    return {o["src"]: hashlib.sha256((root / o["src"]).read_bytes()).hexdigest() for o in ops if o["op"] == "move"}


def verify_applied(root: Path, ops, before_hashes, journal: Path) -> bool:
    """“verified” 的含义：撤销日志存在，所有 move 的源已不在、目标在且字节不变，其余目标都存在。"""
    if not journal.exists(): return False
    for o in ops:
        if o["op"] == "move":
            if (root / o["src"]).exists() or not (root / o["dst"]).exists(): return False
            if hashlib.sha256((root / o["dst"]).read_bytes()).hexdigest() != before_hashes[o["src"]]: return False
        elif not (root / o["dst"]).exists(): return False
    return True


# ------------------------------------------------------------------ 精灵
def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)


def in_quiet(cfg, now: datetime) -> bool:
    q = cfg.get("quiet_hours")
    if not q: return False
    a, b, t = _hm(q[0]), _hm(q[1]), now.hour * 60 + now.minute
    return (a <= t < b) if a < b else (t >= a or t < b)


class Sprite:
    def __init__(self, cfg: dict, home: Path, clock=time.time, probe=None, world=None, registry=None):
        self.cfg, self.home, self.clock = cfg, Path(home), clock
        self.probe, self.world, self.groups = probe, world, {}; self.merged = {}
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "journals").mkdir(exist_ok=True)
        self.log = self.home / "messages.jsonl"
        self.state_f = self.home / "state.json"
        self.state = json.loads(self.state_f.read_text("utf-8")) if self.state_f.exists() else {"seen": [], "rejected": []}
        self.snaps: dict[str, dict] = {}
        self.pending: dict[str, tuple] = {}     # 等待“稳定”的事件
        self.on_message = lambda m: None
        self.mood = "idle"                      # idle / observing / working / thinking
        self.brain = Brain(self.home, tuple(cfg["quiet_hours"]) if cfg.get("quiet_hours") else ("00:00", "00:00"))
        self.registry = registry or Registry()
        self.engine = Engine(self.registry, self.home, clock=lambda: self.clock())
        self.router = tiers.Router(self.home, clock=lambda: self.clock(), daily_tokens=cfg.get("daily_tokens", 20000), daily_usd=cfg.get("daily_usd", 0.05))
        if self.world is not None:
            self.world.router = self.router
            if probe is not None and getattr(self.world, 'refresh', None) is None:
                try: self.world.refresh = probe.snapshot
                except Exception: pass
        self.pending_say = None                 # 当前挂在气泡里、等用户回应的话
        self.use_llm = bool(cfg.get("voice_llm", False))
        self._buckets = set()

    # --- 开关
    def killed(self) -> bool:
        return (self.home / "KILL").exists() or not self.cfg.get("enabled", True)

    def actions_today(self) -> int:
        day = datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")
        n = 0
        for m in self.messages():
            if m.get("status") in ("done", "undone") and m["ts"][:10] == day and m.get("kind") == "action": n += 1
        return n

    def messages(self):
        if not self.log.exists(): return []
        return [json.loads(l) for l in self.log.read_text("utf-8").splitlines() if l.strip()]

    def _emit(self, **m):
        m.setdefault("ts", datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"))
        with self.log.open("a", encoding="utf-8") as f: f.write(json.dumps(m, ensure_ascii=False) + "\n")
        self.on_message(m)
        return m

    def _save(self):
        self.state_f.write_text(json.dumps(self.state, ensure_ascii=False), "utf-8")

    # --- 一次扫描
    def tick(self) -> list:
        if self.killed(): return []
        made = []
        now = self.clock()
        saw = False
        for rawroot, rules in self.cfg["watch"].items():
            root = Path(rawroot).expanduser()
            if not root.is_dir(): continue
            new = snapshot(root, self.cfg["max_depth"])
            old = self.snaps.get(str(root))
            self.snaps[str(root)] = new
            key = str(root)
            ev = diff(old, new) if old is not None else []     # 第一次只建基线，不动手
            buf = self.pending.setdefault(key, [])
            saw = saw or bool(ev)
            self._record_work(root, ev, now)
            buf.extend(e for e in ev if e["kind"] != "removed")
            if not buf: continue
            if in_quiet(self.cfg, datetime.fromtimestamp(now)): continue   # 静默：先攒着
            if self.actions_today() >= self.cfg["daily_cap"]: continue
            events, remain = list(buf), []
            for rule in rules:
                for item, kw, trig, text in propose(rule, root, events, new, now, self.cfg):
                    m = self._try(root, item, kw, trig, text)
                    if m: made.append(m)
                    if self.actions_today() >= self.cfg["daily_cap"]: break
            # 还没稳定的事件继续留着，稳定后重试；稳定且无事可做的丢弃
            for e in events:
                if e["path"] in new and now - new[e["path"]][1] < self.cfg["settle_s"]: remain.append(e)
            self.pending[key] = remain
        self.observe_system(now)
        self.mood = "thinking" if self.pending_say else ("observing" if saw else "idle")
        if not self.pending_say:
            m = self.speak_if_needed(datetime.fromtimestamp(now))
            if m: made.append(m); self.mood = "thinking"
        return made

    def observe_system(self, now):
        """系统状态变化 -> 通用框架（检测问题→判断→安全就做/危险才问一次）。"""
        if not (self.probe and self.world and self.registry.scenarios): return
        try:   # 用户对代理/工具说过的话（--tell 或活动流）-> 约定学习器的证据
            bj = self.home / "behavior.jsonl"; self.world.instructions = [e for e in fork_load(bj) if e.get("kind") in ("instruction", "correction")] if bj.exists() else []
        except Exception: pass
        self.world.snap = self.probe.snapshot(); self.world.env.now = now; self.world.env.running = self.world.snap.procs
        for out in self.engine.step(self.world):
            ts = datetime.fromtimestamp(now).isoformat(timespec="seconds")
            if getattr(self, "dry", False) and out.acted: out.text_short = "【干跑·没真动】" + (out.text_short or out.text_done)
            if not out.acted: continue          # 没做事就不出声、不记“压力”噪声
            lines = [dict(ts=ts, project="系统", kind="pressure", what=out.problem.evidence, scenario=out.scenario)]
            if out.acted:
                gid = uuid.uuid4().hex[:8]; self.groups[gid] = [a.id for a in out.acted]
                lines.append(dict(ts=ts, project="系统", kind="action", what=out.text_short or out.text_done, detail=out.text_done, id=gid, urgent=True))
                self._emit(id=gid, kind="action", status="done", rule=out.scenario, text=out.text_short or out.text_done, detail=out.text_done, group=True, verified=True)
            with (self.home / "behavior.jsonl").open("a", encoding="utf-8") as f:
                for l in lines: f.write(json.dumps(l, ensure_ascii=False) + "\n")

    def speak_if_needed(self, now: datetime):
        """是否开口、说什么，全部交给 Brain 的统一决策；这里只负责把话变成消息。"""
        d = self.brain.decide(now)
        if not d.speak: return None
        c = d.cand
        if self.use_llm and getattr(self, "router", None):
            cloud = tiers.mimo_cloud()
            text = self.router.phrase(c.topic, c.facts, c.project, now.isoformat(), value_s=c.v * 600, local_compose=voice.local,
                                      llm_compose=lambda t, f, p, s: (lambda r: (r[0].strip()[:110], r[1], r[2]))(cloud(voice.SYSTEM, json.dumps(dict(topic=t, project=("项目A" if p else None), facts={k: v for k, v in f.items() if not k.startswith("_")}), ensure_ascii=False).replace(p or "\0", "项目A"))))
            text = text.replace("项目A", c.project or "")
        else: text = voice.compose(c.topic, c.facts, c.project, now.isoformat(), False)
        self.brain.mark_spoken(d, now, text)
        self.pending_say = dict(topic=c.topic, key=c.facts.get("key") if c.topic == "challenge" else None)
        return self._emit(id=uuid.uuid4().hex[:8], kind="say", status="open", topic=c.topic, text=text, detail=voice.detail(c.topic, c.facts),
                          options=c.options, action_id=c.facts.get("id"), rationale=d.rationale)

    def _record_work(self, root: Path, events, now):
        """把文件改动折算成“投入”事件（每项目每 10 分钟记 10 分钟），供岔路检测用。"""
        lines = []
        for e in events:
            if e["kind"] == "removed" or e.get("type") != "f": continue
            proj = Path(e["path"]).parts[0] if len(Path(e["path"]).parts) > 1 else root.name
            b = (str(root), proj, int(now // 600))
            if b in self._buckets: continue
            self._buckets.add(b)
            lines.append(json.dumps(dict(ts=datetime.fromtimestamp(now).isoformat(timespec="seconds"), project=proj, kind="work", minutes=10), ensure_ascii=False))
        if lines:
            with (self.home / "behavior.jsonl").open("a", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")

    def respond(self, idx=None, kind=None):
        """用户点了某个选项(idx)，或关掉气泡(None)。关系预算据此升降。"""
        if not self.pending_say: return
        now = datetime.fromtimestamp(self.clock()); p = self.pending_say
        self.brain.feedback(kind or ("engage" if idx is not None else "dismiss"), now, key=p["key"], choice=idx)
        self.pending_say = None; self.mood = "idle"

    def hear(self, project: str, text: str, source="user"):
        """听到用户/外部的看法：只作为证据记入行为流，不会被当成命令。"""
        from .situation import parse_claim
        e = dict(ts=datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"), project=project, kind="opinion",
                 claim=parse_claim(text), source=source, text=text)
        with (self.home / "behavior.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def _try(self, root: Path, item, kw, trig, text):
        try:
            ops = item.plan(root, **kw)                       # 1. 计划
            fp = hashlib.sha1(json.dumps([str(root), item.id, ops], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if fp in self.state["seen"] or fp in self.state["rejected"]: return None
            before = snapshot(root, 99)
            policy_check(root, ops, self.cfg)                 # 2. 安全策略
            ops = item.dry_run(root, **kw)                    # 3. dry-run，必须不改磁盘
            if snapshot(root, 99) != before: raise Refused("dry-run 改动了磁盘")
        except (C.PlanError, Refused, OSError):
            return None
        if not ops: return None
        mid = uuid.uuid4().hex[:8]
        journal = self.home / "journals" / f"{mid}.json"
        hs = _hashes(root, ops)
        self.mood = "working"
        try:
            C.execute(root, ops, journal)                     # 4. 应用（失败自动回滚）
        except Exception as e:
            return self._emit(id=mid, kind="error", status="failed", text=f"我试了但没成功，已还原（{type(e).__name__}）")
        ok = verify_applied(root, ops, hs, journal)           # 5. 事后校验
        if not ok:
            C.undo(journal)
            return self._emit(id=mid, kind="error", status="failed", text="我做完检查没通过，已全部还原")
        self.state["seen"].append(fp); self._save()
        first = Path(ops[0].get("dst") or ops[0].get("src"))
        proj = first.parts[0] if len(first.parts) > 1 else root.name
        with (self.home / "behavior.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"), project=proj, kind="action", what=text, id=mid), ensure_ascii=False) + "\n")
        return self._emit(id=mid, kind="action", status="done", rule=item.id, text=text,
                          root=str(root), journal=str(journal), fp=fp, n_ops=len(ops), verified=True)

    # --- 撤销
    def undo(self, mid: str) -> bool:
        if mid in self.merged:           # 已并入后来的一次批量处理：撤销那一次就包含它
            t = self.merged.pop(mid); return self.undo(t) if t in self.groups else True
        if mid in self.groups:
            ok = all([self.engine.undo(i) for i in self.groups.pop(mid)])
            self._emit(id=mid, kind="undo", status="undone", text="好的，已还原")
            self._mark(mid, "undone"); return ok
        for m in self.messages():
            if m["id"] == mid and m.get("kind") == "action" and m["status"] == "done":
                j = Path(m["journal"])
                if not j.exists(): return False
                C.undo(j)
                self.state["rejected"].append(m["fp"]); self._save()   # 撤销过的不再重做
                self._emit(id=mid, kind="undo", status="undone", text="好的，已撤销", rule=m["rule"])
                self._mark(mid, "undone")
                return True
        return False

    def _mark(self, mid, status):
        ms = self.messages()
        for m in ms:
            if m["id"] == mid and m.get("kind") == "action": m["status"] = status
        self.log.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in ms), "utf-8")
