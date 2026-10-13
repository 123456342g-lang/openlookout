"""隐性教练：工作方式模式账本与自衰减（issue #18）。

本模块**只有纯函数**：不读屏、不调模型、不碰网络，所有状态迁移由确定性
代码完成，模型只负责两件判断不了的事——「刚发生的这件事算不算某条模式的
证据」与「教练话怎么措辞」。判断通过既有 companion 决策的自由文本通道
回流（topic 约定 + state/evidence 锚点），不改任何工具 schema。

四态生命周期
------------
- observing 观察中：只攒实例（时间 + 具体事件锚点），不说话。7 天窗口外
  的实例过期淡忘；一个从未开口的模式实例全部过期后整条淡忘。
- spoken 已说：开口一次，等 outcomes.jsonl 的结果回流。
- retired 已退休/已掌握：用户采纳，或观察到他自己已经改用此法。画像的一
  部分，**永不再提**。
- cooldown 冷却：被拒/没接/超时无回应，实例清零；spoken_at 保留，工程上
  保证同一条模式不会再说第二次（新摩擦从新 id 重新攒）。

开口资格（工程硬条件，不是提示词愿望）
--------------------------------------
state == observing 且从未开口 且 7 天内实例 >= 2。

topic 约定（companion schema 的 topic 是自由文本，maxLength=24）
---------------------------------------------------------------
- ``coach:<id>`` + kind=quiet       安静记一个实例，锚点写 state/evidence
- ``coach:<id>`` + kind=companion/offer   一次教练开口
- ``coach^<id>`` + kind=quiet       观察到用户已自发改用同法 → 直接退休

id 为 1~18 位稳定小写短名（``[a-z0-9][a-z0-9_-]{0,17}``），同一摩擦永远
用同一个 id；``coach:`` 前缀占 6 字符，总共不超过 24。

账本渲染在 GUIDE.md 的机器围栏块 ``<!-- coach:auto -->`` 里：模型可以全量
write_guide 覆盖整份文件，brain 在 save/restore_guide 处剥离/合并，块不丢。
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterable

# ── 账本参数（issue #18 验收口径） ──────────────────────────────────
INSTANCE_TTL_DAYS = 7.0          # 实例 7 天过期淡忘
MIN_INSTANCES = 2                # 攒够 2 个实例才有资格开口
MAX_ANCHOR = 120                 # 单条锚点留多长（锚点是一句话，不是调查报告）
MAX_INSTANCES_KEPT = 20          # 每模式最多留多少条实例（留最新的）
MAX_SEEN_OUTCOMES = 500          # 已处理 outcome id 去重表上限
MAX_BLOCKED = 50                 # 被工程闸拦掉的违规开口记录上限（供 #15 度量）
MAX_NOTE = 200

# 只在操作流断点/失败刚发生/等待时刻允许教练话；用户虽在但已停手这么久，
# 心跳轮才算「等待时刻」（away 由 brain 用 watching.DEFAULTS 另行排除）。
WAIT_IDLE_S = 30.0

OBSERVING, SPOKEN, RETIRED, COOLDOWN = "observing", "spoken", "retired", "cooldown"
STATES = (OBSERVING, SPOKEN, RETIRED, COOLDOWN)

TOPIC_PREFIX = "coach:"
ADOPT_PREFIX = "coach^"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,17}$")

BLOCK_OPEN = "<!-- coach:auto -->"
BLOCK_CLOSE = "<!-- /coach:auto -->"
_META_PREFIX = "<!-- coach-meta: "
_BLOCK_RE = re.compile(
    r"[ \t]*" + re.escape(BLOCK_OPEN) + r".*?" + re.escape(BLOCK_CLOSE) + r"[ \t]*\n?",
    re.DOTALL,
)
_HEADER_RE = re.compile(
    r"^- \[(?P<id>[^\]]+)\] state=(?P<state>[a-z]+) "
    r"spoken_at=(?P<spoken>-?\d+) updated=(?P<updated>\d+)"
    r"(?: instances=(?P<instances>\d+))?(?:｜(?P<note>.*))?$"
)
_INSTANCE_RE = re.compile(r"^  - t=(?P<t>-?\d+)｜(?P<anchor>.*)$")
_ISO_DAY = 86400.0


# ── 账本构造 ────────────────────────────────────────────────────────
def new_ledger() -> dict:
    """空账本。结构是普通 dict，可直接 json 序列化。"""
    return {"patterns": {}, "seen_outcomes": [], "blocked": []}


def _get(ledger: dict, pattern_id: str) -> dict | None:
    return ledger.setdefault("patterns", {}).get(pattern_id)


def _touch(pattern: dict, now: float) -> dict:
    pattern["updated_at"] = float(now)
    return pattern


def valid_id(pattern_id: str) -> bool:
    """id 规则：稳定小写短名，<=18 字符（coach: + id <= topic maxLength 24）。"""
    return bool(_ID_RE.match(str(pattern_id or "")))


def _clean_anchor(anchor: str) -> str:
    text = re.sub(r"\s+", " ", str(anchor or "")).replace("｜", "/").strip()
    return text[:MAX_ANCHOR]


def fresh_instances(pattern: dict, now: float, *, ttl_days: float = INSTANCE_TTL_DAYS) -> list[dict]:
    """7 天窗口内、且时间不晚于 now 的实例（容忍记录器时钟轻微未来漂移）。"""
    cutoff = float(now) - ttl_days * _ISO_DAY
    return [ins for ins in pattern.get("instances", [])
            if isinstance(ins.get("t"), (int, float)) and cutoff <= ins["t"] <= now + 5]


def prune(ledger: dict, now: float, *, ttl_days: float = INSTANCE_TTL_DAYS) -> dict:
    """自衰减：过期实例淡忘；从未开口的观察中模式实例掉光就整条淡忘。

    spoken/retired/cooldown 是有结论的历史（说过什么、用户掌握了什么、被拒
    过什么），不靠实例存活，保留；其中 cooldown/spoken 的过期实例同样清掉。
    """
    now = float(now)
    dead = []
    for pattern_id, pattern in ledger.get("patterns", {}).items():
        fresh = fresh_instances(pattern, now, ttl_days=ttl_days)
        if len(fresh) != len(pattern.get("instances", [])):
            pattern["instances"] = fresh
        ever_spoken = bool(pattern.get("spoken_at"))
        if pattern.get("state") == OBSERVING and not fresh and not ever_spoken:
            dead.append(pattern_id)
    for pattern_id in dead:
        del ledger["patterns"][pattern_id]
    seen = ledger.setdefault("seen_outcomes", [])
    if len(seen) > MAX_SEEN_OUTCOMES:
        del seen[:-MAX_SEEN_OUTCOMES]
    blocked = ledger.setdefault("blocked", [])
    if len(blocked) > MAX_BLOCKED:
        del blocked[:-MAX_BLOCKED]
    return ledger


# ── 实例与状态迁移（确定性） ────────────────────────────────────────
def add_instance(ledger: dict, pattern_id: str, now: float, anchor: str) -> bool:
    """记一个观察实例（不说话）。

    - retired：已掌握的模式永不复活，拒记。
    - cooldown：旧实例已清零；新摩擦按「重新观察」处理，但 spoken_at 保留，
      所以它永远拿不回开口资格（同一条模式不说第二次）。
    - 锚点为空拒记——没有具体事件锚点的实例不允许进账本。
    """
    if not valid_id(pattern_id):
        return False
    anchor = _clean_anchor(anchor)
    if not anchor:
        return False
    now = float(now)
    patterns = ledger.setdefault("patterns", {})
    pattern = patterns.get(pattern_id)
    if pattern is None:
        pattern = {"id": pattern_id, "state": OBSERVING, "instances": [],
                   "spoken_at": None, "updated_at": now, "note": ""}
        patterns[pattern_id] = pattern
    if pattern["state"] == RETIRED:
        return False
    if pattern["state"] == COOLDOWN:
        pattern["state"] = OBSERVING
        pattern["instances"] = []
        pattern["note"] = "冷却后重新观察；开口资格不恢复"
    instances = pattern.setdefault("instances", [])
    instances.append({"t": now, "anchor": anchor})
    if len(instances) > MAX_INSTANCES_KEPT:
        del instances[:-MAX_INSTANCES_KEPT]
    _touch(pattern, now)
    return True


def can_speak(ledger: dict, pattern_id: str, now: float,
              *, ttl_days: float = INSTANCE_TTL_DAYS,
              min_instances: int = MIN_INSTANCES) -> tuple[bool, str]:
    """开口资格是工程硬条件。返回 (是否可以, 原因码)。"""
    pattern = _get(ledger, pattern_id)
    if pattern is None:
        return False, "unknown_pattern"
    state = pattern.get("state")
    if state == RETIRED:
        return False, "retired"
    if pattern.get("spoken_at"):
        # spoken（等结果中）与 cooldown（被拒/没接）都不许重说。
        return False, "already_spoken" if state == SPOKEN else "muted_after_cooldown"
    if state != OBSERVING:
        return False, f"state_{state}"
    count = len(fresh_instances(pattern, now, ttl_days=ttl_days))
    if count == 0:
        return False, "no_fresh_instance"
    if count < min_instances:
        return False, "below_threshold"
    return True, "eligible"


def mark_spoken(ledger: dict, pattern_id: str, now: float, note: str = "") -> bool:
    """observing（资格满足）→ spoken。其余迁移一律拒绝。"""
    pattern = _get(ledger, pattern_id)
    if pattern is None or pattern.get("state") != OBSERVING or pattern.get("spoken_at"):
        return False
    ok, _reason = can_speak(ledger, pattern_id, now)
    if not ok:
        return False
    now = float(now)
    pattern["state"] = SPOKEN
    pattern["spoken_at"] = now
    pattern["note"] = str(note or "")[:MAX_NOTE]
    _touch(pattern, now)
    return True


def retire(ledger: dict, pattern_id: str, now: float, note: str = "") -> bool:
    """→ retired：采纳，或观察到用户已自发改用同法。retired 是终态。

    observing 也可以直接退休（没说过，但他本来就会——同样记进「已掌握」）。
    """
    pattern = _get(ledger, pattern_id)
    if pattern is None or pattern.get("state") == RETIRED:
        return pattern is not None
    pattern["state"] = RETIRED
    if note:
        pattern["note"] = str(note)[:MAX_NOTE]
    _touch(pattern, float(now))
    return True


def cooldown(ledger: dict, pattern_id: str, now: float, note: str = "") -> bool:
    """spoken → cooldown：被拒/没接/超时无回应；实例清零，开口资格不恢复。"""
    pattern = _get(ledger, pattern_id)
    if pattern is None or pattern.get("state") != SPOKEN:
        return False
    pattern["state"] = COOLDOWN
    pattern["instances"] = []
    if note:
        pattern["note"] = str(note)[:MAX_NOTE]
    _touch(pattern, float(now))
    return True


_LEGAL = {
    (OBSERVING, SPOKEN): mark_spoken,
    (SPOKEN, RETIRED): retire,
    (OBSERVING, RETIRED): retire,
    (SPOKEN, COOLDOWN): cooldown,
}


def transition(ledger: dict, pattern_id: str, to_state: str, now: float, note: str = "") -> bool:
    """显式迁移入口：只接受四态中的合法边，非法边抛 ValueError（造数据测试用）。"""
    if to_state not in STATES:
        raise ValueError(f"unknown state: {to_state!r}")
    pattern = _get(ledger, pattern_id)
    if pattern is None:
        raise ValueError(f"unknown pattern: {pattern_id!r}")
    if pattern.get("state") == to_state:
        return True
    fn = _LEGAL.get((pattern["state"], to_state))
    if fn is None:
        raise ValueError(f"illegal transition {pattern['state']} -> {to_state} for {pattern_id!r}")
    if not fn(ledger, pattern_id, now, note):
        raise ValueError(f"transition rejected {pattern['state']} -> {to_state} for {pattern_id!r}")
    return True


# ── outcomes.jsonl 回流 ─────────────────────────────────────────────
_OUTCOME_TO_COOLDOWN = {"rejected", "ignored", "unanswered"}
_OUTCOME_TO_RETIRED = {"accepted"}
_OUTCOME_NOTE = {
    "accepted": "用户采纳",
    "rejected": "用户拒绝",
    "ignored": "摆出选项后超时未选（明确不要）",
    "unanswered": "超时无回应",
    "acknowledged": "用户看见/关掉气泡",
    "responded": "用户打字回话（态度不明，保持 spoken）",
}


def apply_outcome(ledger: dict, *, event_id, topic: str, outcome: str, now: float) -> str | None:
    """消费一行 outcomes.jsonl（只处理 coach 开口）。

    accepted → retired；rejected/ignored/unanswered（超时无回应）→ cooldown；
    acknowledged/responded 态度不明，保持 spoken。同一 event_id 只处理一次。
    返回迁移后的状态；非 coach/重复/无模式返回 None。
    """
    topic = str(topic or "")
    if not topic.startswith(TOPIC_PREFIX):
        return None
    pattern_id = topic[len(TOPIC_PREFIX):]
    if not valid_id(pattern_id):
        return None
    seen = ledger.setdefault("seen_outcomes", [])
    if event_id is not None and str(event_id) in seen:
        return None
    pattern = _get(ledger, pattern_id)
    if pattern is None:
        # 结果先于/脱离账本到达（重启丢过状态等）：不凭空造模式，只记账防重放。
        if event_id is not None:
            seen.append(str(event_id))
        return None
    outcome = str(outcome or "")
    note = _OUTCOME_NOTE.get(outcome, outcome)
    if outcome in _OUTCOME_TO_RETIRED:
        retire(ledger, pattern_id, now, note)
    elif outcome in _OUTCOME_TO_COOLDOWN:
        cooldown(ledger, pattern_id, now, note)
    if event_id is not None and str(event_id) not in seen:
        seen.append(str(event_id))
    prune(ledger, now)
    return pattern["state"]


# ── companion 决策自由文本通道 ──────────────────────────────────────
def parse_topic(topic: str, kind: str) -> tuple[str, str] | None:
    """解析决策 topic 约定。返回 (verb, id)，verb ∈ observe/speak/adopt。

    - coach:<id> + quiet                 → observe（记实例）
    - coach:<id> + companion/offer       → speak（教练开口）
    - coach^<id> + quiet                 → adopt（观察到用户已自改用，退休）
    其余（普通话题、格式错、id 超长、动词与 kind 不匹配）一律 None。
    """
    topic, kind = str(topic or "").strip(), str(kind or "").strip()
    if topic.startswith(ADOPT_PREFIX):
        pattern_id = topic[len(ADOPT_PREFIX):]
        return ("adopt", pattern_id) if kind == "quiet" and valid_id(pattern_id) else None
    if topic.startswith(TOPIC_PREFIX):
        pattern_id = topic[len(TOPIC_PREFIX):]
        if not valid_id(pattern_id):
            return None
        if kind == "quiet":
            return "observe", pattern_id
        if kind in ("companion", "offer"):
            return "speak", pattern_id
    return None


def decision_anchor(decision: dict) -> str:
    """从既有决策字段里取「具体事件锚点」：state → next_step.evidence → activity。"""
    step = decision.get("next_step") or {}
    for value in (decision.get("state"), step.get("evidence") if isinstance(step, dict) else None,
                  decision.get("activity")):
        anchor = _clean_anchor(value)
        if anchor:
            return anchor
    return ""


def apply_decisions(ledger: dict, decisions: Iterable[dict], now: float, *, surface: bool) -> list[dict]:
    """消费一批新的 companion 决策（brain 每轮后调用），返回被工程闸拦下的记录。

    surface 表示这轮是否处在允许教练开口的时刻（断点/等待；不在流中、未离开、
    非回话轮）。observe/adopt 不挑时刻；speak 必须 surface 且资格满足，否则记
    一条 blocked（模型已经说了，代码拦不住气泡，但绝不替它迁移状态，且留下
    重复说教的度量证据）。
    """
    blocked: list[dict] = []
    for decision in decisions:
        parsed = parse_topic(decision.get("topic"), decision.get("kind"))
        if parsed is None:
            continue
        verb, pattern_id = parsed
        if verb == "observe":
            add_instance(ledger, pattern_id, float(decision.get("t") or now),
                         decision_anchor(decision))
        elif verb == "adopt":
            if _get(ledger, pattern_id) is not None:
                retire(ledger, pattern_id, float(decision.get("t") or now),
                       "观察到用户已自发改用同法：" + decision_anchor(decision))
        else:  # speak
            ok, reason = can_speak(ledger, pattern_id, now)
            if not surface:
                ok, reason = False, "not_a_breakpoint"
            if ok and mark_spoken(ledger, pattern_id, now, str(decision.get("say") or "")[:MAX_NOTE]):
                continue
            ledger.setdefault("blocked", []).append(
                {"t": float(now), "id": pattern_id, "reason": reason})
            blocked.append(ledger["blocked"][-1])
    prune(ledger, now)
    return blocked


# ── 开口时刻闸（流中/无断点不开口） ─────────────────────────────────
def surface_allowed(*, boundary: bool = False, settled: bool = False,
                    in_flow: bool = False, away: bool = False,
                    reply_pending: bool = False) -> tuple[bool, str]:
    """这一轮是否存在教练话可以出现的时刻。

    允许：行为事件边界（timing fire，已过 settle）或人在但停手的等待时刻。
    禁止：回话轮（这轮只为回答他）、离开、操作流中。优先级按「别打扰」排。
    """
    if reply_pending:
        return False, "reply_pending"
    if in_flow:
        return False, "in_flow"
    if away:
        return False, "away"
    if boundary:
        return True, "boundary"
    if settled:
        return True, "settled"
    return False, "no_breakpoint"


def eligible_patterns(ledger: dict, now: float) -> list[tuple[str, dict]]:
    """当前真正有资格开口的模式（供提示词列举；其余模式不出现＝没有开口路径）。"""
    prune(ledger, now)
    out = []
    for pattern_id, pattern in ledger.get("patterns", {}).items():
        ok, _reason = can_speak(ledger, pattern_id, now)
        if ok:
            out.append((pattern_id, pattern))
    out.sort(key=lambda item: (-len(fresh_instances(item[1], now)), item[0]))
    return out


def surface_note(ledger: dict, now: float, **gate) -> str:
    """拼进本轮 STEP 文本的教练段；不允许开口的时刻返回空串（红线上没有路径）。"""
    allowed, reason = surface_allowed(**gate)
    if not allowed:
        return ""
    lines = ["【隐性教练】此刻是操作流断点/失败刚发生后的停手/等待时刻——"
             "教练话只允许在这种时刻出现，专注流中不开口。"]
    eligible = eligible_patterns(ledger, now)
    if not eligible:
        lines.append(
            "账本里没有攒够 7 天内 2 个实例的模式：本轮不做教练开口。"
            "若刚发生的事是某条反复摩擦的又一次实例，只能 quiet 记一笔："
            "topic=coach:<id>（稳定小写短名），state 写「刚才……」的具体事件锚点；"
            "无锚点的原则句（如「你要善于提供上下文」）不许记、不许说。")
    else:
        lines.append("已攒够实例、此刻允许开口的模式（只准从这里挑，一个模式只说一次）：")
        for pattern_id, pattern in eligible:
            anchors = fresh_instances(pattern, now)[-2:]
            lines.append(f"- coach:{pattern_id}｜最近锚点："
                         + " / ".join(ins["anchor"] for ins in anchors))
        lines.append(
            "开口要求：kind=companion 或 offer、topic=coach:<id>；第一句必须点名片中"
            "那件刚发生的事，并给出他当场能照抄/照做的替代物（给汽车，不讲原理；"
            "可直接附着在他正在做的动作上示范），二者缺一就 quiet。"
            "结构修复型 offer（写进 AGENTS.md、存成命令/模板）仍走同意门。")
    lines.append(
        "没有列在这里的模式（说过/被拒/已掌握/实例不够）一律不许提；"
        "观察到他已经自己改用某法：quiet + topic=coach^<id> 让它退休。")
    return "\n".join(lines)


# ── GUIDE.md 围栏块：解析 / 渲染 / 剥离 / 合并 ──────────────────────
def _fmt_time(ts) -> str:
    return str(int(ts)) if isinstance(ts, (int, float)) and ts else "0"


def render_block(ledger: dict, *, now: float | None = None) -> str:
    """账本 → 围栏块文本（确定性；parse_block 可无损还原状态）。"""
    now = float(now if now is not None else time.time())
    prune(ledger, now)
    groups = {OBSERVING: [], SPOKEN: [], RETIRED: [], COOLDOWN: []}
    for pattern_id, pattern in ledger.get("patterns", {}).items():
        groups.setdefault(pattern.get("state", OBSERVING), []).append((pattern_id, pattern))
    titles = {
        OBSERVING: "观察中：只攒实例不说话；7 天内 >= 2 个实例才有资格开口一次",
        SPOKEN: "已说：等结果（accepted 退休；rejected/超时 冷却清零）",
        RETIRED: "已退休＝已掌握：永不再提，是用户画像的一部分",
        COOLDOWN: "冷却：被拒/没接，实例清零，同一模式永不再说",
    }
    lines = [
        BLOCK_OPEN,
        "## 隐性教练账本（机器围栏块：由代码维护，只读勿手改；全量重写 GUIDE.md 时本块自动剥离/合并）",
        "四态 observing/spoken/retired/cooldown；实例 7 天过期、开口需 >=2 实例、每模式只说一次。",
        "topic 约定：开口 coach:<id>（companion/offer）；quiet+coach:<id> 记实例（state 写锚点）；"
        "观察到用户已自改用同法 quiet+coach^<id>。id 为稳定小写短名（<=18 字符）。",
    ]
    for state in (OBSERVING, SPOKEN, RETIRED, COOLDOWN):
        items = sorted(groups[state], key=lambda kv: -float(kv[1].get("updated_at", 0)))
        if not items:
            continue
        lines.append(f"### {state} — {titles[state]}")
        for pattern_id, pattern in items:
            note = str(pattern.get("note") or "").replace("\n", " ").replace("｜", "/")[:MAX_NOTE]
            head = (f"- [{pattern_id}] state={state} spoken_at={_fmt_time(pattern.get('spoken_at'))} "
                    f"updated={_fmt_time(pattern.get('updated_at'))} instances={len(pattern.get('instances', []))}"
                    + (f"｜{note}" if note else ""))
            lines.append(head)
            for ins in pattern.get("instances", []):
                anchor = str(ins.get("anchor", "")).replace("\n", " ")
                lines.append(f"  - t={_fmt_time(ins.get('t'))}｜{anchor}")
    if not ledger.get("patterns"):
        lines.append("（暂无模式：先在断点上安静观察，用 quiet + topic=coach:<id> 攒实例）")
    meta = {"seen_outcomes": ledger.get("seen_outcomes", [])[-MAX_SEEN_OUTCOMES:],
            "blocked": ledger.get("blocked", [])[-MAX_BLOCKED:]}
    lines.append(_META_PREFIX + json.dumps(meta, ensure_ascii=False, sort_keys=True) + " -->")
    lines.append(BLOCK_CLOSE)
    return "\n".join(lines)


def parse_block(text: str) -> dict | None:
    """围栏块文本 → 账本；没有围栏块返回 None。尽力解析，坏行跳过不抛异常。"""
    if not text or BLOCK_OPEN not in text:
        return None
    start = text.index(BLOCK_OPEN)
    end = text.find(BLOCK_CLOSE, start)
    if end < 0:
        return None
    body = text[start + len(BLOCK_OPEN):end]
    ledger = new_ledger()
    current: dict | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        match = _HEADER_RE.match(line)
        if match:
            state = match.group("state")
            pattern_id = match.group("id").strip()
            if state not in STATES or not valid_id(pattern_id):
                current = None
                continue
            spoken_at = int(match.group("spoken"))
            current = {"id": pattern_id, "state": state, "instances": [],
                       "spoken_at": spoken_at or None,
                       "updated_at": float(match.group("updated")),
                       "note": (match.group("note") or "").strip()}
            ledger["patterns"][pattern_id] = current
            continue
        match = _INSTANCE_RE.match(line)
        if match and current is not None:
            current["instances"].append({"t": float(match.group("t")),
                                         "anchor": match.group("anchor").strip()})
            continue
        if line.strip().startswith(_META_PREFIX):
            payload = line.strip()[len(_META_PREFIX):]
            if payload.endswith("-->"):
                payload = payload[:-3].strip()
            try:
                meta = json.loads(payload)
                if isinstance(meta.get("seen_outcomes"), list):
                    ledger["seen_outcomes"] = [str(x) for x in meta["seen_outcomes"]][-MAX_SEEN_OUTCOMES:]
                if isinstance(meta.get("blocked"), list):
                    ledger["blocked"] = [x for x in meta["blocked"] if isinstance(x, dict)][-MAX_BLOCKED:]
            except (ValueError, TypeError):
                pass
    return ledger


def strip_block(text: str) -> str:
    """从 GUIDE.md 全文删掉教练围栏块（模型全量重写时先剥离它自己可能仿造的块）。"""
    if not text:
        return ""
    cleaned = _BLOCK_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def merge_block(guide_text: str, ledger: dict, *, now: float | None = None) -> str:
    """把规范账本块合并回 GUIDE.md：先剥离旧块（含模型仿造的），再追加规范块。"""
    body = strip_block(guide_text or "")
    block = render_block(ledger, now=now)
    return f"{body}\n\n{block}\n" if body else f"{block}\n"
