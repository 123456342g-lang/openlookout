"""看准时机的算法：由行为事件驱动，而不是时钟。

替代 brain.py 里 ``heartbeat_due = now - last_turn >= HEARTBEAT_S`` 这种定时触发。

一个时刻 t 值不值得占用一次判断，取决于价值比较：

    V(开口) − V(沉默) = 关联度 × 时效 × 可撤回性 − 打扰代价

触发条件（都是「边」，不是「刻」）：

* ``action_boundary``  用户刚完成一个有内容的动作（file_save / clipboard / file_open）
                        —— 这是最自然的插话时机，因为动作已结束、结果可指认。
* ``transition``       前台应用切换，且这个切换足够意外（残差 s_t 高）。
* ``salience``         窗口内出现一个高残差时刻（s_t ≥ THETA_HI）。
* ``backlog``          自上次判断以来累积了足够多的事件（按事件数，不按时间）。

不做的事：不为了「到点了」开口；不在用户还在连续操作时插话；对同一情境重复触发要降权。

本模块可离线单独运行（重放 operations.jsonl，看它会挑中哪些时刻）：

    python -m sprite.proactive.timing --ops <operations.jsonl> [--report <out.md>]
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from sprite.config import sprite_home

# ── 参数（全部可复算，不含在线自裁量） ──────────────────────────────
WINDOW_S = 90.0          # 回看窗口
SETTLE_S = 6.0           # 距最后一个事件多久算「用户停下了」
BUSY_S = 10.0            # 判定「正在连续操作」的窗口
BUSY_N = 5               # 该窗口内事件数达到多少算忙
TAU_S = 39.0             # 时效衰减常数 = 实测打断代价中位（不再是拍的 45.0）
                         # 依据：一次开口的价值衰减应当与打断它的代价同尺度——
                         # 若用户为回到原任务要付 39s，那么超过 39s 才被说出口的信息已经亏了。
                         # 口径与来源见 COST_S_DEFAULT 的注释（tmp_timing2/cost_model.py）。
THETA_HI = 9.0           # 高残差阈值（salience 触发）——仅在参考样本不足时兜底
THETA_TRANS = 7.0        # 应用切换要够意外才触发——同上，兜底值
BACKLOG_N = 40           # 按事件数的兜底（不是按时间的兜底）
REPEAT_HARD_S = 180.0      # 同一 (app,type) 在此窗口内硬性不重复触发
REPEAT_COOLDOWN_S = 900.0  # 之后仍按重复降权，直到完全遗忘
SMOOTH = 0.5
BACKLOG_APPS = 3           # 积压触发还要求事件够杂，否则只是「又过了一阵」

RELATEDNESS = {
    "file_save": 1.00,
    "clipboard": 0.95,
    "file_open": 0.90,
    "focus": 0.60,
}
ACTION_TYPES = {"file_save", "clipboard", "file_open"}
# 阈值不再拍绝对数：改成这台机器自己的分位数。不同机器 s_t 分布不同，绝对数不可迁移
# （08b 的教训：换机器就得重调；分位数不用）。
THETA_HI_Q = 0.99        # 显著时刻：参考分布的第 99 分位
THETA_TRANS_Q = 0.97     # 意外切换：第 97 分位
THETA_FLOOR = 3.0        # 分位数的下界，避免分布退化时阈值贴地
THETA_REF_MIN = 200      # 参考样本少于此数就退回绝对阈值，并如实说明
V_SILENCE = 0.25         # 沉默本身的价值：不打扰（仅用于日志对照，不再是判据）
BUSY_PENALTY = 0.35
REPEAT_PENALTY = 0.40

# ---- 期望效用门槛（替换手调常数 V_SILENCE 作为判据）---------------------------
# 依据 Horvitz CHI 1999（DOI 10.1145/302979.303030）：
#   eu(A|E) = p(G|E)·u(A,G) + [1−p(G|E)]·u(A,¬G)；行动 iff eu > u(¬A)。
# 令 u(A,G)=BENEFIT_S（开口有用时替你省下的秒数）、u(A,¬G)=−COST_S（打断代价）、u(¬A)=0：
#   开口 iff p_useful · BENEFIT_S > COST_S   ← 门槛 p* = COST_S / BENEFIT_S 由此解出，不是常数。
# COST_S 不再是全局手调值：本机实测（E:\OpenLookout\tmp_timing2\cost_model.py，
# 3 个月历史 84,123 条事件、n=723 次真实切换、已滤掉 2–3 秒的记录器 tick 抖动）：
#   切走后再切回同一应用的延迟中位 39s、P75 163s、P90 749s。
# 该量随情境变化，所以优先用当前前台应用自己的中位代价；取不到才落到全局值。
COST_S_DEFAULT = 39.0
BENEFIT_S = 60.0         # 一次开口预期为用户省下的秒数（出厂保守值，可调；见 report 里的对照）
COST_MODEL_S = {         # 每个应用的实测打断代价（秒），样本≥30
    "tabbit": 177.0,
    "microsoft-edge": 167.0,
    "default": 27.0,
}


def measured_cost(app: str) -> float:
    return COST_MODEL_S.get((app or "").strip().lower(), COST_S_DEFAULT)


def stop_threshold(app: str, *, benefit_s: float | None = None) -> float:
    """p* = cost / benefit，裁剪到 [0, 0.95]。benefit 默认取 r_t 校准值（样本不足或只有沉默则出厂先验）。"""
    if benefit_s is None:
        benefit_s = benefit_now()[0]
    benefit = max(benefit_s, 1.0)
    return max(0.0, min(0.95, measured_cost(app) / benefit))


# ---- 用 r_t 校准 BENEFIT_S（而不是由我拍一个 60）------------------------------
# 现成的学习信号：E:\OpenLookout\sprite_home\perceive\outcomes.jsonl（三态落库）。
# 校准目标：让门槛 p* 等于**实际观测到的开口有效率**——p* = cost/benefit
# 反解出 benefit = cost / rate。这就是 PRISM（2602.01532）说的“校准过的介入价值门”。
# 样本不足时退回出厂先验，并如实说明“证据不足”，不假装学会了。
#
# 词表纪律（10-12 事故的修正）：沉默不是回答，观测不到有用不能让门槛变松。
#   _POSITIVE      accepted / responded —— 用户明确接住了这次开口，才算“这次开口有用”。
#   _NEGATIVE      rejected —— 只有用户明确说“不”才是反证。
#   _NO_EVIDENCE   ignored（真给过选项却没选）/ unanswered（没给选项、没人理）/
#                  acknowledged（点“好”只是看见）—— 三者都没回答“这次开口有没有用”，
#                  既不计正例也不计负例，只从样本量里剔除。
# 旧代码把 ignored 当负例：一句 companion 气泡只要 180s 没人打字就记成 ignored，
# 于是“越没人理”越像“观测有效率=0”，反而把门槛放到 1/5（见 learned_benefit_s 注释）。
OUTCOMES_PATH = Path(os.environ.get("OPENLOOKOUT_PERCEIVE") or (sprite_home() / "perceive")) / "outcomes.jsonl"
_POSITIVE = {"accepted", "responded"}
_NEGATIVE = {"rejected"}
_NO_EVIDENCE = {"ignored", "unanswered", "acknowledged"}
MIN_OUTCOMES = 20
BENEFIT_MIN_S = 30.0     # 收益下界＝保守端：收益估得越小，p* = cost/benefit 越紧
BENEFIT_MAX_S = 300.0    # 收益上界＝放开端


def _wilson_lower(hits: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = hits / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2 * total)
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - radius) / denom)


def learned_benefit_s(path: Path | None = None) -> tuple[float, str]:
    """返回 (benefit_s, 依据说明)。样本不足、或只有沉默（无证据）时返回出厂先验 BENEFIT_S。"""
    path = path or OUTCOMES_PATH
    positives = negatives = silent = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.startswith("{"):
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                outcome = str(row.get("outcome") or "")
                if outcome in _POSITIVE:
                    positives += 1
                elif outcome in _NEGATIVE:
                    negatives += 1
                elif outcome in _NO_EVIDENCE:
                    silent += 1
    except OSError:
        return BENEFIT_S, f"读不到 {path.name}，用出厂先验 {BENEFIT_S:.0f}s"
    total = positives + negatives
    silent_note = f"；另有 {silent} 条沉默/仅确认（无证据），不计入" if silent else ""
    if total < MIN_OUTCOMES:
        return BENEFIT_S, (f"可判定的结果行只有 {total} 条（<{MIN_OUTCOMES}{silent_note}），证据不足，"
                           f"仍用出厂先验 {BENEFIT_S:.0f}s——这不是学出来的")
    if positives == 0:
        # cost/rate 在 rate=0 处无定义。旧代码在这里返回 benefit=300s，即 p* = 39/300 = 0.13——
        # 比“证据不足”时的 39/60 = 0.65 松得多，等于“一次有用都没观测到反而更爱开口”，方向反了。
        # 这里取参数区间的保守端（收益下界 30s → p* 顶到 0.95）：明确的负证据只会让门槛更紧，不会更松。
        return BENEFIT_MIN_S, (f"{negatives}/{total} 条明确为负、正例 0 条{silent_note}，"
                               f"cost/rate 无定义；取保守端 benefit={BENEFIT_MIN_S:.0f}s（p* 顶到上限）——"
                               f"一次有用都没观测到，就别再开口")
    rate = _wilson_lower(positives, total)
    if rate <= 0.0:
        # 有正例但 Wilson 下界仍为 0（样本极小）：同样不外推 cost/0，取保守端。
        return BENEFIT_MIN_S, (f"{positives}/{total} 正面但 Wilson 下界为 0{silent_note}，"
                               f"不做无限外推；取保守端 benefit={BENEFIT_MIN_S:.0f}s")
    benefit = max(BENEFIT_MIN_S, min(BENEFIT_MAX_S, COST_S_DEFAULT / rate))
    return benefit, (f"由 r_t 校准：{positives}/{total} 正面{silent_note}，Wilson 下界 {rate:.3f} → "
                     f"benefit = {COST_S_DEFAULT:.0f}/{rate:.3f} = {benefit:.0f}s")


_BENEFIT_CACHE: dict = {"stamp": None, "value": BENEFIT_S, "why": "出厂先验（尚未读 r_t）"}


def benefit_now() -> tuple[float, str]:
    """按账本 mtime 缓存的校准收益：每有一条新结果就重算一次，不重复读盘。"""
    try:
        stamp = OUTCOMES_PATH.stat().st_mtime_ns
    except OSError:
        stamp = None
    if stamp != _BENEFIT_CACHE["stamp"]:
        value, why = learned_benefit_s()
        _BENEFIT_CACHE.update(stamp=stamp, value=value, why=why)
    return _BENEFIT_CACHE["value"], _BENEFIT_CACHE["why"]


def _to_ts(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def normalize(events: Iterable[dict]) -> list[dict]:
    """统一成 {ts: float, type, app, title}，丢弃无时间戳的行。

    clipboard / file_save 这类事件在 recorder 里通常不带 app，补成「当时的前台应用」，
    否则会把数据缺陷（app='?'）当成行为异常。
    """
    out: list[dict] = []
    for row in events:
        if not isinstance(row, dict):
            continue
        ts = _to_ts(row.get("ts"))
        if ts is None:
            continue
        out.append({
            "ts": ts,
            "type": str(row.get("type") or "?"),
            "app": str(row.get("app") or ""),
            "title": str(row.get("title") or ""),
        })
    out.sort(key=lambda r: r["ts"])
    carried = "?"
    for row in out:
        if row["app"] and row["app"] != "?":
            carried = row["app"]
        elif row["type"] != "focus":
            row["app"] = carried
        elif not row["app"]:
            row["app"] = "?"
    return out


def surprises(events: Sequence[dict], smooth: float = SMOOTH) -> list[float]:
    """一阶马尔可夫残差 s_t = -log2 P(app_t|app_{t-1}) - log2 P(type_t)。"""
    if not events:
        return []
    counts: dict[tuple[str, str], int] = {}
    app_prev: dict[str, int] = {}
    type_n: dict[str, int] = {}
    seq: list[tuple[str, str | None, str]] = []
    for ev in events:
        app, typ = ev["app"], ev["type"]
        prev = seq[-1][0] if seq else None
        seq.append((app, prev, typ))
        app_prev[app] = app_prev.get(app, 0) + 1
        type_n[typ] = type_n.get(typ, 0) + 1
        if prev is not None:
            counts[(prev, app)] = counts.get((prev, app), 0) + 1
    total_app = len(seq)
    total_type = sum(type_n.values()) or 1
    out: list[float] = []
    for i, (app, prev, typ) in enumerate(seq):
        n_from = app_prev.get(prev, 0) if prev is not None else total_app
        num = counts.get((prev, app), 0) if prev is not None else app_prev.get(app, 0)
        k_app = len({a for (p, a) in counts}) + 1
        p_app = (num + smooth) / ((n_from if prev is not None else total_app) + smooth * k_app)
        k_type = len(type_n) + 1
        p_type = (type_n.get(typ, 0) + smooth) / (total_type + smooth * k_type)
        out.append(-math.log2(max(p_app, 1e-9)) - math.log2(max(p_type, 1e-9)))
    return out


@dataclass
class Moment:
    fire: bool
    score: float
    kind: str
    why: str
    key: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fire": self.fire, "score": round(self.score, 3), "kind": self.kind,
            "why": self.why, "key": self.key,
            **{k: v for k, v in self.detail.items()},
        }


def _event_key(ev: dict) -> str:
    return f"{ev['app']}|{ev['type']}@{int(ev['ts'])}"


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return THETA_FLOOR
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return max(THETA_FLOOR, ordered[idx])


def theta_thresholds(events: Sequence[dict]) -> tuple[float, float, bool]:
    """用全部可见流水的 s_t 分布定阈值，而不是拍 9.0 / 7.0。

    返回 (theta_hi, theta_trans, 是否用了分位数)。样本不足时退回绝对阈值，
    并让调用方能如实说明「这台机器还没攒够参考分布」。
    """
    if len(events) < THETA_REF_MIN:
        return THETA_HI, THETA_TRANS, False
    ref = surprises(events)
    if len(ref) < THETA_REF_MIN:
        return THETA_HI, THETA_TRANS, False
    return _quantile(ref, THETA_HI_Q), _quantile(ref, THETA_TRANS_Q), True


def observe(
    events: Sequence[dict],
    now: float,
    *,
    last_fire_ts: float = 0.0,
    last_fire_key: str = "",
    last_fire_by_type: dict[str, float] | None = None,
    arrivals: dict[str, float] | None = None,
    window_s: float = WINDOW_S,
) -> Moment:
    """此刻是否值得开口。纯函数：同样的输入必得同样的输出。

    ``arrivals``：这条事件「第一次被我们看见」的时刻。记录器常把一个区间写在结束时、
    却用开始时刻做 ts（focus 的 dur_s 就是区间长度），所以按自称时间算时效会把一个
    刚刚才变得可行动的边界算成过期。可行动的时刻应以「我们发现它」为准。
    """
    window = [e for e in events if now - window_s <= e["ts"] <= now + 1]
    if not window:
        return Moment(False, 0.0, "silence", "窗口内没有任何行为事件", "", {"events_in_window": 0})

    ss = surprises(window)
    theta_hi, theta_trans, theta_from_quantile = theta_thresholds(events)
    latest = window[-1]
    since_last_event = max(0.0, now - latest["ts"])
    busy_n = sum(1 for e in window if e["ts"] >= now - BUSY_S)
    busy = busy_n >= BUSY_N
    settled = since_last_event >= SETTLE_S
    hi = max(range(len(window)), key=lambda i: ss[i])
    hi_s, hi_ev = ss[hi], window[hi]
    new_ev = [e for e in window if e["ts"] > last_fire_ts]

    detail = {
        "events_in_window": len(window),
        "events_since_fire": len(new_ev),
        "s_now": round(ss[-1], 2),
        "s_max": round(hi_s, 2),
        "s_max_at": hi_ev["ts"],
        "s_max_app": hi_ev["app"],
        "s_max_type": hi_ev["type"],
        "since_last_event_s": round(since_last_event, 1),
        "busy": busy,
        "busy_n": busy_n,
        "theta_hi": round(theta_hi, 2),
        "theta_trans": round(theta_trans, 2),
        "theta_from_quantile": theta_from_quantile,
        "settled": settled,
    }

    # 动作边界只等「上一个动作」结束；纯粹的前台窗口 tick 不该让一个已完成的动作失效
    action_ts = [e["ts"] for e in window if e["type"] in ACTION_TYPES]
    last_action_ts = max(action_ts) if action_ts else 0.0
    detail["since_last_action_s"] = round(max(0.0, now - last_action_ts), 1) if last_action_ts else None

    # ── 候选触发（按关联度排序，先取到就先算） ────────────────────
    candidate: dict | None = None
    kind = ""
    for ev in reversed(new_ev):
        if ev["type"] in ACTION_TYPES:
            candidate, kind = ev, "action_boundary"
            break
    if candidate is None:
        for i in range(len(window) - 1, 0, -1):
            if window[i]["app"] != window[i - 1]["app"] and ss[i] >= theta_trans:
                candidate, kind = window[i], "transition"
                break
    if candidate is None and hi_ev["ts"] > last_fire_ts and hi_s >= theta_hi:
        candidate, kind = hi_ev, "salience"
    if candidate is None and len(new_ev) >= BACKLOG_N and len({e["app"] for e in new_ev}) >= BACKLOG_APPS:
        candidate, kind = latest, "backlog"

    if candidate is None:
        detail["reason"] = "没有新的边（动作边界 / 意外切换 / 高残差 / 事件积压）"
        return Moment(False, 0.0, "silence", "没有值得占用的新时刻", "", detail)

    settle_ref = last_action_ts if kind == "action_boundary" else latest["ts"]
    if settle_ref and now - settle_ref < SETTLE_S:
        waited = now - settle_ref
        detail["reason"] = f"{kind} 刚发生 {waited:.1f}s，还没到可行动的边界"
        return Moment(False, 0.0, "hold", "等这一个动作结束再开口", "", detail)

    key = _event_key(candidate)
    if key == last_fire_key:
        detail["reason"] = "这个时刻已经用过了"
        return Moment(False, 0.0, "silence", "同一时刻不重复开口", key, detail)

    stamp = f"{candidate['app']}|{candidate['type']}"
    if last_fire_by_type and stamp in last_fire_by_type:
        gap = now - last_fire_by_type[stamp]
        if gap < REPEAT_HARD_S:
            detail["reason"] = f"{stamp} 在 {gap:.0f}s 前刚触发过（硬冷却 {REPEAT_HARD_S:.0f}s）"
            return Moment(False, 0.0, "hold", f"刚为同一情境开口过，不重复", key, detail)

    relatedness = RELATEDNESS.get(candidate["type"], 0.5)
    seen_at = (arrivals or {}).get(key, candidate["ts"])
    actionable_ts = max(candidate["ts"], seen_at)
    age = max(0.0, now - actionable_ts)
    recency = math.exp(-age / TAU_S)
    reversibility = 1.0  # 说话本身可撤回
    disturbance = BUSY_PENALTY if busy else 0.10
    repeat_pen = 0.0
    if last_fire_by_type and stamp in last_fire_by_type:
        if now - last_fire_by_type[stamp] < REPEAT_COOLDOWN_S:
            repeat_pen = REPEAT_PENALTY
    score = relatedness * recency * reversibility - disturbance - repeat_pen
    # p_useful：relatedness×recency 作为“这次开口真有用”的工程代理（两者都∈[0,1]）；
    # 门槛由实测打断代价与预期收益解出，而不是手调的 V_SILENCE。
    useful_p = max(0.0, relatedness * recency - disturbance - repeat_pen)
    # 门槛真正用的收益是校准值，顺手记下来：旧版本明细里报的是出厂先验 BENEFIT_S，
    # 而 p_star 却按校准收益算，两个数对不上，明细也就不可复算了。
    need_benefit, _need_why = benefit_now()
    need_p = stop_threshold(candidate["app"], benefit_s=need_benefit)
    detail.update({
        "trigger": kind,
        "trigger_app": candidate["app"],
        "trigger_type": candidate["type"],
        "trigger_title": candidate["title"][:60],
        "age_s": round(age, 1),
        "relatedness": relatedness,
        "recency": round(recency, 3),
        "disturbance": disturbance,
        "repeat_penalty": repeat_pen,
        "v_silence": V_SILENCE,
        "p_useful": round(useful_p, 3),
        "p_star": round(need_p, 3),
        "cost_s": measured_cost(candidate["app"]),
        "benefit_s": need_benefit,
    })
    if busy and kind != "action_boundary":
        return Moment(False, score, "hold", "用户还在连续操作，等动作结束", key, detail)
    if useful_p <= need_p:
        detail["reason"] = (f"p_useful={useful_p:.3f} ≤ p*={need_p:.3f}"
                            f"（打断代价 {measured_cost(candidate['app']):.0f}s / 预期收益 {need_benefit:.0f}s）")
        return Moment(False, score, "silence", "比不上沉默，安静", key, detail)
    why = {
        "action_boundary": f"用户刚做了一个{_zh(candidate['type'])}动作（{candidate['app']}）",
        "transition": f"从一个意外的地方切到 {candidate['app']}（s={ss[hi]:.1f}）",
        "salience": f"{candidate['app']} 出现异常时刻（s={hi_s:.1f}）",
        "backlog": f"累积了 {len(new_ev)} 个事件没看过",
    }.get(kind, kind)
    return Moment(True, score, kind, why, key, detail)


def _zh(typ: str) -> str:
    return {"file_save": "保存文件", "clipboard": "剪贴板", "file_open": "打开文件"}.get(typ, typ)


# ── 有状态封装：给 brain 主循环用 ──────────────────────────────────
@dataclass
class Tracker:
    """记住「上次为哪个时刻开口过」与「每条事件我们是什么时候第一次看见的」。"""

    last_fire_ts: float = 0.0
    last_fire_key: str = ""
    last_fire_by_type: dict[str, float] = field(default_factory=dict)
    seen: dict[str, float] = field(default_factory=dict)
    last: Moment | None = None

    def consider(self, events: Sequence[dict], now: float) -> Moment:
        keys = {_event_key(e) for e in events}
        fresh = {k: v for k, v in self.seen.items() if k in keys}
        for k in keys - fresh.keys():
            fresh[k] = now        # 这是我们第一次看见它，不是它自称发生的时刻
        self.seen = fresh
        self.last = observe(events, now, last_fire_ts=self.last_fire_ts,
                            last_fire_key=self.last_fire_key,
                            last_fire_by_type=self.last_fire_by_type,
                            arrivals=self.seen)
        return self.last

    def commit(self, now: float) -> None:
        m = self.last
        if m is None or not m.fire:
            return
        self.last_fire_ts = now
        self.last_fire_key = m.key
        app, typ = m.detail.get("trigger_app"), m.detail.get("trigger_type")
        if app and typ:
            self.last_fire_by_type[f"{app}|{typ}"] = now


# ── 离线重放：看它会挑中哪些时刻 ────────────────────────────────────
def replay(events: Sequence[dict], step_s: float = 2.0) -> list[dict]:
    """按 2s 采样时钟重放（与 brain 主循环同频），返回被挑中的时刻。

    关键：不能只在「事件发生的那一瞬」求值，否则 since_last_event 永远是 0、
    「等动作结束」这条规则永远不会生效。真实循环是在事件之后的安静时刻才开口。
    """
    picked: list[dict] = []
    last_fire_ts, last_fire_key = 0.0, ""
    last_by_type: dict[str, float] = {}
    if not events:
        return picked
    t = events[0]["ts"]
    end = events[-1]["ts"]
    while t <= end:
        m = observe(events, t, last_fire_ts=last_fire_ts,
                    last_fire_key=last_fire_key, last_fire_by_type=last_by_type)
        if m.fire:
            picked.append({**m.to_dict(), "at": t})
            last_fire_ts, last_fire_key = t, m.key
            stamp = f"{m.detail.get('trigger_app')}|{m.detail.get('trigger_type')}"
            last_by_type[stamp] = t
        t += step_s
    return picked


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    ops = Path(argv[argv.index("--ops") + 1]) if "--ops" in argv else sprite_home() / "perceive" / "operations.jsonl"
    report = Path(argv[argv.index("--report") + 1]) if "--report" in argv else None
    events = normalize(_read_jsonl(ops))
    if not events:
        print(f"没有可用事件：{ops}")
        return 1
    span = events[-1]["ts"] - events[0]["ts"]
    picked = replay(events)
    lines = [
        f"# 看准时机的算法：离线重放",
        "",
        f"- 数据：`{ops}`",
        f"- 事件：{len(events)} 条，跨度 {span / 60:.1f} 分钟",
        f"- 参数：窗口 {WINDOW_S:.0f}s，停手 {SETTLE_S:.0f}s，忙碌 {BUSY_S:.0f}s/{BUSY_N} 事件，"
        f"τ={TAU_S:.0f}s，θ_hi={THETA_HI}，θ_trans={THETA_TRANS}，积压 {BACKLOG_N}，"
        f"重复冷却 {REPEAT_COOLDOWN_S:.0f}s，V(沉默)={V_SILENCE}",
        f"- **挑中 {len(picked)} 个时刻**（若按 30s 心跳会判断 {span / 30:.0f} 次）",
        "",
        "| # | 时刻 | app | type | 触发 | V | 为什么 |",
        "|---|------|-----|------|------|---|--------|",
    ]
    for i, p in enumerate(picked, 1):
        t = datetime.fromtimestamp(p["at"]).strftime("%m-%d %H:%M:%S")
        lines.append(f"| {i} | {t} | {p.get('trigger_app')} | {p.get('trigger_type')} | "
                     f"{p['kind']} | {p['score']:.3f} | {p['why']} |")
    kinds: dict[str, int] = {}
    for p in picked:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    lines += ["", f"触发类型分布：{kinds}", ""]
    text = "\n".join(lines)
    print(text)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"\n报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
