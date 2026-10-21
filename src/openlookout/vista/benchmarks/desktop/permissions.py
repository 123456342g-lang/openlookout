"""按风险分级的写操作授权（2026-10-13）。

上一版 `fix/offer-consent` 把**所有** offer 都做成「必须点头才执行」。那治好了
「不问就动手」，但同时把「精灵记一下自己的笔记」「截个图」也变成了要打断用户的事 ——
问一次「我可以记一下吗」比不问更糟。这里改回三级：

    低风险 / 无风险 → 直接做，不问
    中风险         → 批量闸门：同一轮攒一批，一次点头全放行，带 TTL
    高风险         → 强制一次闸门，每次都问，绝不合并

分级不新造一套 effect 语义：`vista.core.contracts.Effect` 仍然是唯一事实来源，
本模块只在它之上加一层**策略**（`TOOL_TIER` 覆盖表 + 由 Effect 派生的默认值）。
换句话说 Effect 说「这件事动了机器」，RiskTier 说「动了机器里有多要紧的东西」。

配置在 ``SPRITE_HOME/permissions.json``，四种取值都真的生效：

    {"low": "auto", "medium": "batch", "high": "each", "batch_window_s": 7200}

闸门落在 `session.DesktopSession._handler` —— 所有 desktop_* 工具唯一的分发点。
提议的呈现与点头仍然走 `help.publish` → GUI 气泡 → `live.on_choice` 那条已验证的链，
没有另造一套交互。点头之后执行的是**提议里逐条列出的那几个操作**，不是再让模型
重新决定一遍：批准的是清单本身，不是「下次它想干什么」。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from sprite.i18n import t
from vista.core.contracts import Effect

HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))
CONFIG = HOME / "permissions.json"
# 已批准、尚未执行的批次。GUI 是独立进程，所以必须落盘才能被它读到。
PENDING = HOME / "perceive" / "pending_batches.jsonl"


class RiskTier(StrEnum):
    """风险级别。注意这不是 effect：effect 描述「动了什么」，tier 描述「有多要紧」。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Mode(StrEnum):
    AUTO = "auto"      # 直接做，不问
    ASK = "ask"        # 每次都问（不合并）
    EACH = "each"      # 同上；配置里 low 写 ask、medium/high 写 each 是同一件事
    BATCH = "batch"    # 同轮合并成一次提议

    @property
    def per_call(self) -> bool:
        """True = 每次单独问；False = 可以攒批。"""
        return self in {Mode.ASK, Mode.EACH}


# 由 Effect 派生的默认档。只有 Effect 说不动任何东西时才自动放行；
# ENVIRONMENT 一律至少要过闸 —— 具体是问还是攒批，由下面的覆盖表决定。
_EFFECT_DEFAULT: dict[Effect, RiskTier] = {
    Effect.NONE: RiskTier.LOW,
    Effect.ANNOTATION: RiskTier.LOW,
    Effect.MEMORY: RiskTier.LOW,
    Effect.ENVIRONMENT: RiskTier.MEDIUM,
    Effect.SUBMISSION: RiskTier.MEDIUM,
}

# 覆盖表：Effect 说「动了机器」，这里说「动的是哪一种机器」。
#
# 逐条理由（都是核实过实现，不是照抄工具描述）：
#   desktop_undo            恢复而非破坏。桌面归类错了、进程被误挂起，撤回是**唯一**
#                           的正确动作；给它加闸门等于「出事时反而不许救」。
#   desktop_trim            减工作集，进程照常运行，缺的页需要时自己换回来，
#                           不丢任何东西，工具描述里也明说不需要撤销。→ 低
#   desktop_capture_evidence 只往 sprite 自己的 perceive/homework_evidence 写
#                           PNG+JSON，用 ``xb``/``x`` 独占新建，碰不到用户文件。→ 低
#   desktop_write_deliverable 只往 deliverables 写裸文件名，后缀限 md/txt/csv，
#                           ``xb`` 独占新建且不覆盖（已实测，见 test_risk_tier.py）。
#                           产出目录、可撤回，但确实是往外送东西 → 中
#   desktop_reclaim         只把 risk 引擎判 safe+quarantine 的**可再生**项
#                           （temp/浏览器与包缓存/回收站）移进隔离区，逐项二次
#                           核对、先写撤回日志、restore_quarantine 可完整还原
#                           （actions.py: reclaim）。10-14 实测它被钉在 HIGH 的
#                           后果：C 盘只剩 0.5GB 还先弹问，用户点头后任务又因
#                           别的链路失败没清成。可逆安全项问了比不问更糟 → 低
#   desktop_tidy            一次最多搬动 200 个用户文件。
#   desktop_suspend/_end_process  动用户正在用的进程。
#   basic_shell             任意命令行，4000 字符。
#                           ↑ 这四个是「强制一次闸门」，每次都问、绝不合并。
TOOL_TIER: dict[str, RiskTier] = {
    "desktop_undo": RiskTier.LOW,
    "desktop_trim": RiskTier.LOW,
    "desktop_capture_evidence": RiskTier.LOW,
    "desktop_write_deliverable": RiskTier.MEDIUM,
    "desktop_reclaim": RiskTier.LOW,
    "desktop_tidy": RiskTier.HIGH,
    "desktop_suspend": RiskTier.HIGH,
    "desktop_end_process": RiskTier.HIGH,
    "basic_shell": RiskTier.HIGH,
}

# 需要 session 额外上下文（当前画面）才能跑的工具不能被暂存后离线执行：
# 批准时是在 GUI 进程里逐条重放的，那时没有 current_visual。
_NEEDS_LIVE_VISUAL = frozenset({"desktop_capture_evidence"})

_LABEL_KEYS: dict[str, str] = {
    "desktop_write_deliverable": "label_write",
    "desktop_reclaim": "label_reclaim",
    "desktop_tidy": "label_tidy",
    "desktop_suspend": "label_suspend",
    "desktop_end_process": "label_end",
    "desktop_trim": "label_trim",
    "desktop_undo": "label_undo",
    "basic_shell": "label_shell",
    "desktop_capture_evidence": "label_capture",
}


@dataclass(frozen=True)
class Policy:
    """用户可调的松紧。三个取值都真的改变行为，没有装饰性字段。"""

    low: Mode = Mode.AUTO
    medium: Mode = Mode.BATCH
    high: Mode = Mode.ASK
    # 默认 2 小时：气泡只在屏 120s，但用户可能正好没看屏幕——错过气泡不该
    # 等于拒绝（10-14 实测：清理提议过期后只能看对话历史，没地方补点，C 盘
    # 最后他自己清）。清单冻结不放大授权，执行前仍有现场核对（issue #26）。
    batch_window_s: int = 7200

    def mode_for(self, tier: RiskTier) -> Mode:
        return {RiskTier.LOW: self.low, RiskTier.MEDIUM: self.medium, RiskTier.HIGH: self.high}[tier]

    def to_json(self) -> dict[str, Any]:
        return {"low": self.low.value, "medium": self.medium.value,
                "high": self.high.value, "batch_window_s": self.batch_window_s}


def _mode(raw: Any, fallback: Mode) -> Mode:
    try:
        return Mode(str(raw))
    except ValueError:
        return fallback


def load_policy(path: Path | None = None) -> Policy:
    """读 permissions.json。文件不存在或坏了就回落到默认档，绝不因为配置问题把闸门关掉。"""
    target = path or CONFIG
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Policy()
    if not isinstance(raw, dict):
        return Policy()
    window = raw.get("batch_window_s", 7200)
    return Policy(
        low=_mode(raw.get("low"), Mode.AUTO),
        medium=_mode(raw.get("medium"), Mode.BATCH),
        high=_mode(raw.get("high"), Mode.ASK),
        batch_window_s=int(window) if isinstance(window, (int, float)) and window > 0 else 7200,
    )


def save_policy(policy: Policy, path: Path | None = None) -> Path:
    target = path or CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(policy.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def tier_of(tool: str, spec: Any = None) -> RiskTier:
    """这个工具属于哪一档。显式覆盖优先，否则由 Effect 派生。"""
    if tool in TOOL_TIER:
        return TOOL_TIER[tool]
    effect = getattr(spec, "effect", Effect.NONE)
    return _EFFECT_DEFAULT.get(Effect(effect), RiskTier.MEDIUM)


def describe(tool: str, arguments: dict[str, Any] | None) -> str:
    """提议里给用户看的那一行。必须说清**具体要动什么**，不能只说「要写文件」。"""
    args = arguments or {}
    key = _LABEL_KEYS.get(tool)
    label = t(key) if key else tool
    if tool == "desktop_write_deliverable":
        return t("with_value", label=label, value=args.get("name"))
    if tool in {"desktop_suspend", "desktop_end_process"}:
        return t("with_pid", label=label, pid=args.get("pid"))
    if tool == "basic_shell":
        command = " ".join(str(args.get("command") or "").split())
        return t("with_value", label=label, value=command[:120])
    if tool == "desktop_tidy":
        return t("tidy_count", label=label, n=args.get("max_items", 200))
    if tool == "desktop_capture_evidence":
        return t("with_value", label=label, value=args.get("label"))
    if tool == "desktop_undo":
        return t("undo_recorded", label=label)
    return label


@dataclass
class Item:
    """批次里的一条：一个工具 + 它的参数。批准后按这条原样重放。"""

    tool: str
    arguments: dict[str, Any]
    tier: RiskTier
    text: str

    def to_json(self) -> dict[str, Any]:
        return {"tool": self.tool, "arguments": self.arguments,
                "tier": self.tier.value, "text": self.text}


@dataclass
class Verdict:
    """闸门对一次工具调用的裁决。"""

    allow: bool
    reason: str = ""
    item: Item | None = None


@dataclass
class Gate:
    """一轮之内的授权状态。

    刻意做成普通对象而不是全局单例：闸门是**每个 session 一份**的，
    这样「同一轮合并」才有确定的边界，也便于测试直接构造。
    """

    policy: Policy = field(default_factory=load_policy)
    # tier -> 当前攒着的批次。高风险永远不进这里（绝不合并）。
    batches: dict[str, Batch] = field(default_factory=dict)
    published: list[dict] = field(default_factory=list)
    publish: Callable[[dict], None] | None = None

    def admit(self, tool: str, arguments: dict[str, Any], spec: Any = None) -> Verdict:
        """这个工具现在能不能跑。不能跑的话，理由和要暂存的条目一并给出。"""
        # Effect.NONE 是唯一无条件放行的档：只读的东西没有任何可逆性风险，
        # 哪怕用户把 low 设成 ask 也不该问 —— 「我可以看一下吗」比不问更糟。
        effect = getattr(spec, "effect", None)
        if effect is Effect.NONE:
            return Verdict(True)
        tier = tier_of(tool, spec)
        mode = self.policy.mode_for(tier)
        if mode is Mode.AUTO:
            return Verdict(True)
        if tool in _NEEDS_LIVE_VISUAL:
            # 没有当前画面就没法在批准后重放，直接放行并说明原因，
            # 免得截图这种只读性质的动作卡死整个证据链。
            return Verdict(True, "需要当前画面，无法离线重放，直接放行")
        item = Item(tool=tool, arguments=dict(arguments or {}), tier=tier, text=describe(tool, arguments))
        if mode.per_call:
            proposal = self._single(item)
            self._emit(proposal)
            return Verdict(False, "这个动作需要他点头，已发成带「好的/不用」按钮的提议；他点头前不要执行，也不要再用对话追问一遍。", item)
        # BATCH：登记进本轮同档批次，等回合边界一次性征求同意。
        self.batches.setdefault(tier.value, Batch(tier)).add(item)
        return Verdict(False, "已登记到这一轮的批次里，等本轮结束合并成一条带按钮的提议；不要在对话里另行追问。", item)

    def _single(self, item: Item) -> dict:
        return {"items": [item.to_json()], "risk": item.tier.value,
                "text": _proposal_text([item], item.tier)}

    def flush(self) -> list[dict]:
        """回合边界调用：把攒着的批次变成提议。返回本次发出的提议列表。

        高风险从来不在 ``batches`` 里，所以这里发出的每条提议都只含同档操作；
        同档同轮的多条会合成一条 —— 这就是「批量闸门」。
        """
        out: list[dict] = []
        for key in sorted(self.batches):
            batch = self.batches.pop(key)
            if not batch.items:
                continue
            proposal = {"items": [i.to_json() for i in batch.items],
                        "risk": batch.tier.value,
                        "text": _proposal_text(batch.items, batch.tier)}
            out.append(self._emit(proposal))
        return out

    def _emit(self, proposal: dict) -> dict:
        # 必须返回盖了时间戳的那一份：TTL 判定读的就是 ``t``，
        # 把没盖章的原件交给调用方会让每一条提议一出生就「已过期」。
        proposal = dict(proposal, t=time.time())
        self.published.append(proposal)
        if self.publish is not None:
            self.publish(proposal)
        return proposal

    def open_batches(self) -> list[Batch]:
        return [self.batches[key] for key in sorted(self.batches)]


@dataclass
class Batch:
    """同一轮里同档操作的集合。"""

    tier: RiskTier
    items: list[Item] = field(default_factory=list)

    def add(self, item: Item) -> None:
        # 同一工具 + 同一份参数不重复登记：模型重试不该让提议里出现两条一样的。
        if not any(i.tool == item.tool and i.arguments == item.arguments for i in self.items):
            self.items.append(item)


def _proposal_text(items: list[Item], tier: RiskTier) -> str:
    """气泡里给用户看的话：只讲要做什么，不出现内部分级词。

    ``tier`` 仍保留在签名里（调用方按档产生提议），但 medium/high/风险
    这类机制术语是给系统看的，写进气泡就会被原样念给用户（10-14 实测
    "我要做这 2 件medium风险的事"），一律不出口。
    """
    lines = [f"{i.text}" for i in items]
    if len(lines) == 1:
        return t("proposal_one", line=lines[0], ask=t("proposal_start"))
    numbered = "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1))
    return t("proposal_many", n=len(lines), lines=numbered, ask=t("proposal_together"))


# ── 落盘：GUI 是另一个进程，批准与执行都在那边 ───────────────────────────────

def append_pending(proposal: dict, path: Path | None = None) -> None:
    target = path or PENDING
    target.parent.mkdir(parents=True, exist_ok=True)
    row = dict(proposal, id=f"batch-{time.time_ns()}", state="pending", t=time.time(),
               expires_t=time.time() + load_policy().batch_window_s)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def pending_batches(path: Path | None = None) -> list[dict]:
    target = path or PENDING
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [json.loads(line) for line in lines if line.strip() and _parses(line)]


def _parses(line: str) -> bool:
    try:
        json.loads(line)
    except ValueError:
        return False
    return True


def expired(batch: dict, policy: Policy | None = None) -> bool:
    """TTL：过期的批次提议不能再被拿来执行。

    这是批量闸门唯一的刹车。一次点头放行 3 份产出没问题，
    但不能让那份授权在补点窗口（默认 2 小时，issue #26）之后还能被用来写第 4 份。
    """
    window = (policy or load_policy()).batch_window_s
    try:
        return time.time() - float(batch.get("t", 0)) > window
    except (TypeError, ValueError):
        return True


def execute(batch: dict, policy: Policy | None = None) -> list[dict]:
    """按提议里逐条列出的操作原样执行 —— 批准的是清单，不是「模型下次想干什么」。

    TTL 过期直接拒绝，一条都不做。
    """
    from . import actions

    if expired(batch, policy):
        return [{"tool": "*", "success": False, "text": "批次提议已过期，没有执行任何操作。"}]
    done: list[dict] = []
    for row in batch.get("items") or []:
        tool = str(row.get("tool") or "")
        handler, _spec = actions.SPECS.get(tool, (None, None))
        if handler is None or tool in _NEEDS_LIVE_VISUAL:
            done.append({"tool": tool, "success": False,
                         "text": "该操作无法在批准后执行，已跳过。"})
            continue
        try:
            reply = handler(row.get("arguments") or {})
            done.append({"tool": tool, "success": bool(reply.success), "text": str(reply.text)[:300]})
        except Exception as exc:
            done.append({"tool": tool, "success": False,
                         "text": f"执行异常（{type(exc).__name__}），结果未确认。"})
    return done
