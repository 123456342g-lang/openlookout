"""通用的“发现问题 → 自己判断 → 直接做（全部可还原）→ 一行汇报+撤销 → 从结果里学”框架。没有“询问”流程。
新场景只需要“注册”：一个检测器（状态 -> 问题）+ 一个动作提供者（问题 -> 带类型的候选动作）；执行层也是注册的（见 executors.py）。

问题 Problem：kind / severity / evidence / need（要缓解多少）/ recheck（现在还剩多少，<=0 即已解除）
动作 Action：risk、reversible(full|regen|partial|none)、relief（回收量）、dry_run()、run()、verify()、undo()
判断 Judge：
  - 有 recheck 的问题：打开后直到 recheck<=0 才关闭；检测器可以只边沿报一次，Engine 负责挂起未解除问题并每轮继续推进
  - 现在已解除（recheck<=0）-> 什么都不做、不出声；解除后可有短冷却防抖动
  - 某一轮找不到安全动作 -> 不关闭、不长冷却，下一轮再试（让空闲观察等条件长出来）
  - high 或 不能完全还原 -> 不做；要做就得先重新设计成可还原形式
  - 其余：按回收量从大到小，价值闸 + dry_run + 范围上限 + 信任度 -> 直接做，verify 失败即回滚
  - 一解除立刻停手；单项回收不到需求的 5% 不做
学习 Ledger：每类动作记 成功/失败/被撤销；撤销>=2 或失败>=3 停用。
"""
from __future__ import annotations
import json, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Problem:
    kind: str
    severity: float                  # 0..1
    evidence: str
    need: float = 0.0
    unit: str = ""
    key: str = ""
    ctx: dict = field(default_factory=dict)
    recheck: Callable[[], float] = None   # 现在还剩多少需要缓解（<=0 表示已解除）；没有则按一次性处理


@dataclass
class Action:
    kind: str                        # 动作类型（信任账本按它统计）
    name: str
    risk: str                        # safe | medium | high
    reversible: str                  # full | partial | none
    relief: float = 0.0
    blast_items: int = 1
    blast_bytes: int = 0
    reason: str = ""
    dry_run: Callable[[], bool] = lambda: True
    run: Callable[[], dict] = lambda: {}
    verify: Callable[[dict], bool] = lambda r: True
    undo: Callable[[dict], None] = lambda r: None
    done_text: Callable[[list], str] = lambda items: "做了点事"
    ask_text: str = ""                                 # 已弃用（不再询问），仅为兼容
    done_short: Callable[[list], str] = None          # 一行短汇报（<=约20字）
    value_s: float | None = None                      # 预计为你省下/避免的“用户秒数”；None 则按缓解占比估
    later: str | None = None                          # “你迟早得自己做这件事”的证据（有则价值×1.5）
    token_usd: float = 0.0                            # 这个动作本身预计花的 token 钱
    ask_ok: bool = False                              # 已弃用：不再有“问后执行”，不可还原的一律不做
    confident: bool = False                           # medium 风险的动作，只有“有逐字节副本/可完整撤销”这类硬证据时才直接做；否则不做（不问）
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    result: dict | None = None


@dataclass
class Scenario:
    name: str
    detect: Callable[[object], list]                  # world -> [Problem]
    propose: Callable[[Problem, object], list]        # problem, world -> [Action]
    group_text: Callable[[list, Problem], str] = None # 详细汇报（展开时看）
    group_short: Callable[[list, Problem], str] = None # 一行短汇报
    auto_caps: dict = field(default_factory=lambda: dict(items=200, bytes=8 * 2**30))
    observe: Callable[[object], None] = None          # 每次状态更新都会调用（做状态驱动的恢复等）


class Registry:
    def __init__(self): self.scenarios: dict[str, Scenario] = {}; self.executors = None
    def register_executor(self, ex):
        from .executors import ExecutorRegistry
        if self.executors is None: self.executors = ExecutorRegistry()
        return self.executors.register(ex)
    def register(self, s: Scenario): self.scenarios[s.name] = s; return s


class Ledger:
    def __init__(self, path: Path):
        self.f = Path(path); self.d = json.loads(self.f.read_text("utf-8")) if self.f.exists() else {}
    def _save(self): self.f.write_text(json.dumps(self.d, ensure_ascii=False), "utf-8")
    def rec(self, kind, what):
        e = self.d.setdefault(kind, dict(ok=0, failed=0, undone=0)); e[what] += 1; self._save()
    def trust(self, kind) -> str:
        e = self.d.get(kind, {})
        if e.get("undone", 0) >= 3 or e.get("failed", 0) >= 3: return "off"
        if e.get("undone", 0) >= 2: return "off"
        return "auto"


@dataclass
class Outcome:
    problem: Problem
    scenario: str
    acted: list = field(default_factory=list)       # Action（含 result）
    asks: list = field(default_factory=list)        # 永远为空（兼容旧字段）
    skipped: list = field(default_factory=list)     # (Action, 原因)
    relieved: float = 0.0
    text_done: str = ""
    text_short: str = ""
    text_ask: str = ""


class Engine:
    def __init__(self, registry: Registry, home: Path, clock=time.time, meter=None, gate=None):
        self.reg, self.home, self.clock, self.meter = registry, Path(home), clock, meter
        self.gate = dict(ratio=2.0, min_value_s=20.0, usd_to_s=3000.0, risk_s=600.0, interrupt_s=8.0, harm_s=900.0, later_mult=1.5, min_gain_frac=0.05)
        if gate: self.gate.update(gate)
        self.ledger = Ledger(self.home / "ledger.json"); self.log = self.home / "judgments_actions.jsonl"
        self.live: dict[str, Action] = {}
        # 仅用于「无 recheck 的一次性问题」防抖；有 recheck 的未解除问题不走长冷却
        self.cooldown_s = 600.0; self.cool: dict = {}; self.cool_sev: dict = {}
        # 未解除问题挂起表：key -> (Scenario, Problem)。检测器可只边沿上报一次，由这里持续推进到解除。
        self.open: dict[str, tuple] = {}
        self.next_batch: dict[str, float] = {}
        self.batch_interval_s = 15.0   # 刚做过一批后，稍等再批，避免空转刷盘
        self.retry_interval_s = 5.0    # 本轮没找到安全动作：更快重试（等观察条件成熟）
        self.resolved_cool_s = 30.0    # 真正解除后的短冷却，防抖动
        self.executors = None

    def _log(self, **kw):
        kw["ts"] = self.clock()
        with self.log.open("a", encoding="utf-8") as f: f.write(json.dumps(kw, ensure_ascii=False, default=str) + "\n")

    def _okey(self, sc: Scenario, pb: Problem) -> str:
        return f"{sc.name}:{pb.key or pb.kind}"

    def step(self, world) -> list:
        """状态更新时调用：检测器上报/刷新问题；有 recheck 的问题挂起直到解除，每轮继续推进。"""
        outs = []
        now = self.clock()
        for sc in self.reg.scenarios.values():
            if sc.observe: sc.observe(world)
            for pb in sc.detect(world):
                key = self._okey(sc, pb)
                if pb.need > 0 and pb.recheck:
                    # 未解除问题：挂起（或用更新的 severity/need/recheck 覆盖）
                    try:
                        if float(pb.recheck()) <= 0:
                            continue  # 现在已解除：不挂起、不出声
                    except Exception:
                        pass
                    if now < self.cool.get(key, 0) and pb.severity <= self.cool_sev.get(key, 0):
                        continue  # 刚解除后的短冷却
                    self.open[key] = (sc, pb)
                else:
                    outs.append(self.handle(sc, pb, world))
            # 推进本场景下所有未解除问题（即使本轮 detect 为空）
            for key in list(self.open):
                sc2, pb = self.open[key]
                if sc2.name != sc.name:
                    continue
                left = 0.0
                try:
                    left = float(pb.recheck()) if pb.recheck else 0.0
                except Exception:
                    left = pb.need
                if left <= 0:
                    self._log(problem=pb.kind, key=key, decision="resolved")
                    self.open.pop(key, None); self.next_batch.pop(key, None)
                    self.cool[key] = now + self.resolved_cool_s; self.cool_sev[key] = pb.severity
                    continue
                if now < self.next_batch.get(key, 0):
                    continue
                # 把最新 need 同步成 recheck 读数，便于价值估算
                pb.need = max(pb.need, left)
                out = self.handle(sc2, pb, world)
                outs.append(out)
                try:
                    left2 = float(pb.recheck()) if pb.recheck else 0.0
                except Exception:
                    left2 = left - out.relieved
                if left2 <= 0:
                    self._log(problem=pb.kind, key=key, decision="resolved_after_act")
                    self.open.pop(key, None); self.next_batch.pop(key, None)
                    self.cool[key] = self.clock() + self.resolved_cool_s; self.cool_sev[key] = pb.severity
                else:
                    # 有动作或没动作：问题仍挂着；没动作更快重试
                    gap = self.batch_interval_s if out.acted else self.retry_interval_s
                    self.next_batch[key] = self.clock() + gap
        return outs

    def estimate(self, a: Action, pb: Problem, will_report=True) -> dict:
        """价值闸：value（用户秒数）vs cost（token钱、风险、打扰）。只有价值明显大于成本才动手。"""
        g = self.gate
        if a.value_s is not None: v = a.value_s
        elif pb.need > 0: v = pb.severity * g["harm_s"] * min(1.0, a.relief / pb.need)
        else: v = pb.severity * 120.0
        later = bool(a.later)
        if later: v *= g["later_mult"]
        cost = a.token_usd * g["usd_to_s"] + {"safe": 0.05, "medium": 0.3, "high": 1.0}.get(a.risk, 1.0) * g["risk_s"] * (0.2 if a.reversible in ("full", "regen") else 1.0) * 0.1 + (g["interrupt_s"] if will_report else 0)
        ok = v >= g["min_value_s"] and v >= g["ratio"] * cost
        return dict(value_s=round(v, 1), cost_s=round(cost, 1), later=a.later, ok=ok)

    def handle(self, sc: Scenario, pb: Problem, world) -> Outcome:
        """全部直接做、全部可还原。有压力才动；按回收量从大到小；压力一解除立刻停手。不在这里对未解除问题做长冷却。"""
        out = Outcome(pb, sc.name)
        now = self.clock(); ck = (sc.name, pb.kind)
        if pb.need > 0 and pb.recheck and pb.recheck() <= 0:
            self._log(problem=pb.kind, decision="no_pressure"); return out
        # 仅「无 recheck 且 need>0」的一次性压力型问题保留旧冷却；普通任务（need=0）不冷却
        if not pb.recheck and pb.need > 0 and self.cooldown_s and now < self.cool.get(ck, 0) and pb.severity <= self.cool_sev.get(ck, 0):
            return out
        cands = sc.propose(pb, world)
        cands.sort(key=lambda a: (a.risk == "high", -a.relief, a.blast_bytes))
        remaining = pb.need
        floor = pb.need * self.gate.get("min_gain_frac", 0.05) if pb.need else 0
        for a in cands:
            tr = self.ledger.trust(a.kind)
            if a.risk == "high" or a.reversible not in ("full", "regen"):
                out.skipped.append((a, "高风险或不能还原：不做")); continue
            if a.risk == "medium" and not a.confident:
                out.skipped.append((a, "拿不准（没有硬证据）：不做，也不打扰你")); continue
            if tr != "auto":
                out.skipped.append((a, "这类动作多次失败/被撤销，已停用")); continue
            if pb.need > 0:
                if pb.recheck: remaining = min(remaining, pb.recheck())
                if remaining <= 0:
                    out.skipped.append((a, "问题已缓解，不多做")); continue
            est = self.estimate(a, pb)
            if not est["ok"]:
                out.skipped.append((a, f"价值不够（价值≈{est['value_s']}s，成本≈{est['cost_s']}s）：不做")); self._log(problem=pb.kind, action=a.name, decision="skip_low_value", **est); continue
            if pb.need > 0 and a.relief and a.value_s is None and a.relief < floor:
                out.skipped.append((a, "边际收益太小：不做")); continue
            if a.blast_items > sc.auto_caps["items"] or a.blast_bytes > sc.auto_caps["bytes"]:
                out.skipped.append((a, "影响范围超过上限：不做")); continue
            if not a.dry_run():
                out.skipped.append((a, "dry-run 没通过")); continue
            try:
                a.result = a.run()
                if not a.verify(a.result):
                    a.undo(a.result); self.ledger.rec(a.kind, "failed"); out.skipped.append((a, "事后校验失败，已还原")); continue
            except Exception as e:
                try: a.undo(a.result or {})
                except Exception: pass
                self.ledger.rec(a.kind, "failed"); out.skipped.append((a, f"执行出错已回滚：{type(e).__name__}")); continue
            self.ledger.rec(a.kind, "ok"); self.live[a.id] = a
            out.acted.append(a); remaining -= a.relief
            self._log(problem=pb.kind, action=a.name, kind=a.kind, risk=a.risk, decision="auto", reason=a.reason, **est)
        if pb.need and pb.recheck: remaining = min(remaining, pb.recheck())
        out.relieved = pb.need - max(remaining, 0) if pb.need else 0
        # 一次性压力型问题才写长冷却；未解除挂起问题由 step/open 管；普通任务不写
        if out.acted and not pb.recheck and pb.need > 0:
            self.cool[ck] = now + self.cooldown_s; self.cool_sev[ck] = pb.severity
        if out.acted:
            out.text_done = (sc.group_text(out.acted, pb) if sc.group_text else "；".join(a.done_text([a]) for a in out.acted))
            out.text_short = (sc.group_short(out.acted, pb) if sc.group_short else
                              ("、".join((a.done_short or a.done_text)([a]) for a in out.acted[:2]) + ("等" if len(out.acted) > 2 else "")))
        for a, why in out.skipped: self._log(problem=pb.kind, action=a.name, kind=a.kind, risk=a.risk, decision="skip", reason=why)
        return out

    def undo(self, action_id: str) -> bool:
        a = self.live.pop(action_id, None)
        if not a: return False
        a.undo(a.result or {}); self.ledger.rec(a.kind, "undone"); self._log(action=a.name, decision="undo"); return True

    def do_task(self, task, llm=None, severity=0.5) -> Outcome:
        """决策核心：任务 -> 选执行器 -> 同一套闸门。"""
        ex = self.reg.executors
        a = ex.action_for(task, llm) if ex else None
        if a is None: self._log(task=task.goal, decision="no_executor"); return Outcome(Problem("task:" + task.kind, severity, task.goal), "task:" + task.kind)
        sc = Scenario("task:" + task.kind, lambda w: [], lambda pb, w: [a], auto_caps=dict(items=200, bytes=8 * 2**30))
        out = self.handle(sc, Problem("task:" + task.kind, severity, task.goal), None)
        return out
