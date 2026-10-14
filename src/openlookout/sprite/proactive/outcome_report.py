"""开口质量的离线度量（只读）。

为什么要有这个文件
------------------
这个项目最缺的是「改进可测」。当前唯一的真实学习信号是
``sprite_home/perceive/outcomes.jsonl``（一行一次开口的最终结果），
但它把三类完全不同的东西塞进了同一个字段：

    正面证据   accepted / responded   —— 用户选了第一个选项 / 用户直接打字回话
    负面证据   rejected               —— 用户明确选了别的
    无证据     ignored / unanswered   —— 气泡超时消失，用户全程没反应

**沉默不是拒绝。** 把 ``ignored`` 算进分母得到的「接受率」一定是假的：
已知实测里就有开口其实帮上了忙、却因为旧口径气泡写死 180s 超时被记成
``ignored``（例如「清了 Temp：C 盘 1.96G→3.04G」）。所以本报告：

1. 按 kind 分列（companion / 带选项的 offer / 其他），给出每个 kind 的样本量；
2. 把三类标签分开计数；任何「接受率/有效率」都写清分母，并显式标注
   「无回应不等于拒绝」；同时把「把沉默算进分母」那个误导数字单独点出来；
3. 未知/新出现的 outcome 字符串全部计数并单列，绝不静默丢弃
   （T1 正在引入新值 ``unanswered``，本模块自带词表，不依赖 timing.py 的版本）；
4. 按天分布，样本不足就直说「样本不足，不画趋势」；
5. 只读地调用 ``sprite.proactive.timing`` 的 ``benefit_now()`` /
   ``stop_threshold(app)``，把 ``why`` 原文照录，并说明是否处于「证据不足」状态
   （timing 拿不到就降级为「校准状态未知」，不崩）；
6. 一句话结论：这套数据能不能支撑「开口质量在变好」——不能就直说不能。

纪律
----
* 只读：本模块**只**打开 ``perceive/`` 下的文件读，绝不写入、绝不 mkdir。
* 输出：默认打到 stdout；``--report <path>`` 只写到你指定的那一个路径
  （拒绝写进 ``perceive/``，防止误伤实时账本）。
* 不引入任何第三方依赖（标准库）。

用法::

    python -m sprite.proactive.outcome_report [--json] [--report <path>]
                                             [--perceive <dir>] [--app <name>]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ── 口径：本模块自持的词表（不从 timing 导入，避免与并行改动耦合）────────────
# 新增/未知标签不会被丢：落在 unknown 类里，单独列出。
#
# 词表分叉（issue #15 现状证据 2，本 PR（②）只在报告侧标注，不改另两处）：
# 同一组状态词目前在三个文件各维护一份——
#   * live.py 的 ``SETTLED_OFFER_STATES``（offer 结果态与 outcome 混在一个 frozenset）；
#   * timing.py 的 ``_POSITIVE/_NEGATIVE/_NO_EVIDENCE``（acknowledged 归 no-evidence）；
#   * 本文件的 POSITIVE/NEGATIVE/SILENCE/AMBIGUOUS（acknowledged 归 ambiguous）。
# 行号会漂移，认符号名；①账本字段落地后是否合并词表，按 issue #15 后续方案处理。
POSITIVE = ("accepted", "responded")          # 正面证据
NEGATIVE = ("rejected",)                      # 负面证据（用户明确选了别的）
SILENCE = ("ignored", "unanswered", "expired", "timeout")   # 无证据（沉默类）
AMBIGUOUS = ("acknowledged", "undo_requested", "undone")    # 已知但口径模糊，单列、
                                                            # 不进任何分子/分母
CLASSES = ("positive", "negative", "silence", "ambiguous", "unknown")

CLASS_ZH = {
    "positive": "正面证据",
    "negative": "负面证据",
    "silence": "无证据（沉默）",
    "ambiguous": "模糊（单列，不入分母）",
    "unknown": "未知标签",
}

# 证据够不够，先验取自 timing.MIN_OUTCOMES（=20），但这里用的是更严的分母：
# 只数正面+负面，不把沉默算进来。
MIN_EVIDENCE = 20
MIN_PER_DAY = 5        # 单日结果少于此数 → 不画趋势
MIN_DAYS = 2           # 少于两天 → 不画趋势
# 「疑似气泡超时」判据（PR #16 复审 P1-3 修正）。
# 沉默行是 GUI on_expire 在气泡到点被收走时落账的，旧判据 SILENCE_HINT_S=170
# 绑的是「companion 气泡上限 180s」；PR #16 后 companion 按句长给 30~90s、
# 带选项 offer 为 OFFER_ASK_S×2=120s，旧阈值对新数据再也不会命中，报告还会
# 打印已不成立的「180s 来不及回应」。新判据按**每一行自己的 kind/文本**推导
# 它本该活多久（bubble_budget_s）：latency 达到本行预算 = 到点被收走的沉默。
# on_expire 经 Tk 调度/重启重放落账可能略晚于预定寿命，给这点容差。
EXPIRY_TOLERANCE_S = 5.0
# live 不可用时的同值兜底（与 live.BUBBLE_READ_S/PER_CHAR/MAX_S、OFFER_ASK_S×2
# 同步——改 live 时长时记得改这里；正常路径直接取 live 常量，不靠这组值）。
_FALLBACK_COMPANION_BUDGET = (30.0, 0.1, 90.0)
_FALLBACK_OFFER_BUDGET_S = 120.0
LATE_USER_WINDOW_S = 900.0  # 结果落库后这么久内用户打字 → 疑似漏记的「responded」

# ── ② 离线四指标（issue #15）：阈值集中在此，全部只读、只描述，不做任何拦截 ──────
MIN_METRIC_SAMPLE = 20       # 四指标统一的样本下限（与 MIN_EVIDENCE 对齐）：不足就明说「不能判断」
CLUSTER_GAP_S = 120.0        # 相邻开口间隔 ≤ 此值 → 算同一个突发簇（#10「≤120s 成簇」口径）
LATENCY_VALID_MAX_S = 86400.0   # latency 合理性上限 24h；超出按污染行剔除并计数
                             # （实测 o-rej 行 latency_s=1.79e9，是测试污染，不是回应延迟）
GAP_BIN_EDGES_S = (0.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0)  # 间隔长尾直方图边界
# ① 才会落账本的字段（issue #15 ①：offer_t/anchor/turn_trigger/reply_to）。
# 本轮这些字段在生产 outcomes 里不存在：报告只能显式报「缺失/不可算」，绝不伪造默认值凑指标。
FIELD_OFFER_T = "offer_t"           # 原开口时刻（①）
FIELD_ANCHOR = "anchor"             # {app,type,title} 锚点（①）
FIELD_TURN_TRIGGER = "turn_trigger" # timing|heartbeat|screen|feedback|reply|maintenance（①）
FIELD_REPLY_TO = "reply_to"         # 非空 = 对话簇，主动度量要排除（①）

def bubble_budget_s(row: Mapping[str, Any]) -> float:
    """这条开口按 PR #16 新口径本该有的气泡寿命（秒），判据只依赖行自身的
    kind/text：

    * kind=offer：带选项气泡 OFFER_ASK_S×2（实挂 120s）；
    * 其余（companion/缺失/历史行）：``live.bubble_seconds(text)``，30~90s。

    阈值直接从 live 推导，避免两处常量再次漂移；live 导入失败（例如并行开发中
    文件有语法错误）时用与 live 同值的兜底常量。
    """
    kind = str(row.get("kind") or "").strip().lower()
    text = row.get("text")
    try:
        from . import live
    except Exception:
        live = None
    if live is not None:
        try:
            if kind == "offer":
                return float(live.OFFER_ASK_S) * 2.0
            return float(live.bubble_seconds(text if text is not None else ""))
        except Exception:
            pass
    read_s, per_char_s, max_s = _FALLBACK_COMPANION_BUDGET
    if kind == "offer":
        return _FALLBACK_OFFER_BUDGET_S
    return max(read_s, min(max_s, read_s + len(str(text or "")) * per_char_s))


FILE_NAMES = ("outcomes.jsonl", "offers.jsonl", "feedback.jsonl", "conversation.jsonl")


# ── 路径 ────────────────────────────────────────────────────────────────────
def default_perceive_dir() -> Path:
    """解析 perceive 目录。与 perceive.py / timing.py 的既有解析保持一致，只读。

    优先 ``OPENLOOKOUT_PERCEIVE``（timing.py 用的），其次 ``SPRITE_HOME``/perceive
    （perceive.py 用的），否则落到本机默认路径。**不 mkdir**。
    """
    env = os.environ.get("OPENLOOKOUT_PERCEIVE")
    if env:
        return Path(env)
    home = os.environ.get("SPRITE_HOME")
    if home:
        return Path(home) / "perceive"
    return Path(r"E:\OpenLookout\sprite_home") / "perceive"


# ── 读取（只读、优雅降级）────────────────────────────────────────────────────
def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """读一个 JSONL 文件。返回 ``(行, 坏行数)``。

    * 文件缺失 / 不可读 → ``([], 0)``，不抛异常（缺失是正常状态：账本还没建）。
    * 空行跳过；非 ``{`` 开头或 JSON 解析失败的行计入坏行，不静默吞掉。
    * 只读：以 ``encoding="utf-8"`` 打开，绝不 append。
    """
    rows: list[dict] = []
    bad = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if not line.startswith("{"):
                    bad += 1
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    bad += 1
    except OSError:
        return [], 0
    return rows, bad


def _to_ts(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
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


# ── 分类 ────────────────────────────────────────────────────────────────────
def classify(label: Any) -> str:
    """把一个 outcome 字符串归入 ``positive|negative|silence|ambiguous|unknown``。

    未知字符串一律 ``unknown``（绝不当成 silence 或 negative）；空值也是 unknown。
    """
    text = str(label if label is not None else "").strip().lower()
    if text in POSITIVE:
        return "positive"
    if text in NEGATIVE:
        return "negative"
    if text in SILENCE:
        return "silence"
    if text in AMBIGUOUS:
        return "ambiguous"
    return "unknown"


def bucket_of(row: Mapping[str, Any], offers: Mapping[str, Mapping[str, Any]]) -> str:
    """按 kind 归档：``companion`` / ``offer_with_options``（带选项的 offer）/ ``other``。

    「带选项」的判据：该 id 在 offers.jsonl 里的原始 offer 定义了非空 ``options``
    （``record_offer_result`` 会把整个 offer 落盘，所以 options 跟着走）；取不到就退回
    结果行自己带的 ``options``。判不出来一律 ``other``，不做猜测。
    """
    kind = str(row.get("kind") or "").strip().lower()
    if kind == "companion":
        return "companion"
    if kind == "offer":
        options = None
        linked = offers.get(str(row.get("id") or ""))
        if isinstance(linked, Mapping):
            options = linked.get("options")
        if options is None:
            options = row.get("options")
        return "offer_with_options" if options else "other"
    return "other"


def _index_offers(offers: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """id → 该 id 的最后一行（与 live.offer_status 的「最后状态为准」一致）。"""
    out: dict[str, Mapping[str, Any]] = {}
    for row in offers:
        key = str(row.get("id") or "")
        if key:
            out[key] = row
    return out


def _class_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = {cls: 0 for cls in CLASSES}
    for row in rows:
        counts[classify(row.get("outcome"))] += 1
    return counts


def _meaningful(counts: Mapping[str, int]) -> int:
    """有明确证据的开口数 = 正面 + 负面（**不含沉默**，也不含模糊/未知）。"""
    return int(counts.get("positive", 0)) + int(counts.get("negative", 0))


# ── ② 四指标：确定性纯函数（合成账本夹具可直接测，不读盘、不依赖时钟）────────────
def _finite_number(value: Any) -> float | None:
    """把 int/float 转成有限 float；bool、字符串、NaN/Inf 一律 None（不猜测、不解析）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _nonempty(value: Any) -> bool:
    """锚点/reply_to 「非空」判据：None/空串/空容器不算，0/False 也不算锚点。"""
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return bool(value)


def _percentile(sorted_vals: Sequence[float], q: float) -> float | None:
    """确定性最近秩百分位（nearest-rank, rank=ceil(q*n)）；入参需已升序。"""
    if not sorted_vals:
        return None
    rank = math.ceil(q * len(sorted_vals))
    return float(sorted_vals[max(0, min(rank - 1, len(sorted_vals) - 1))])


FIELD_KEYS = (FIELD_OFFER_T, FIELD_ANCHOR, FIELD_TURN_TRIGGER, FIELD_REPLY_TO)


def _field_status_one(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """① 四个新字段在一本账本里的存在情况（只读盘点，不补默认值）。"""
    total = len(rows)
    out: dict[str, dict] = {}
    for key in FIELD_KEYS:
        with_key = sum(1 for r in rows if key in r)
        nonempty = sum(1 for r in rows if _nonempty(r.get(key)))
        out[key] = {"rows_total": total, "rows_with_key": with_key,
                    "rows_nonempty": nonempty}
    return out


def ledger_field_status(outcomes: Sequence[Mapping[str, Any]],
                        offer_rows: Sequence[Mapping[str, Any]] = ()) -> dict:
    """① 四个新字段的存在盘点，**按数据源分列**（P2-1）。

    ``reply_to`` 今天就由 session 发布时写进 offer dict 并随 offers.jsonl 落盘，
    而 outcomes 侧要等①；所以不能只盘 outcomes 就断言「字段整体缺失」。
    """
    return {"outcomes": _field_status_one(outcomes),
            "offers": _field_status_one(offer_rows)}


def _row_is_reply_cluster(row: Mapping[str, Any]) -> bool:
    """outcome 行自己带的①对话簇标记：reply_to 非空，或 turn_trigger == "reply"。"""
    if _nonempty(row.get(FIELD_REPLY_TO)):
        return True
    return str(row.get(FIELD_TURN_TRIGGER) or "").strip().lower() == "reply"


def opening_moments(outcomes: Sequence[Mapping[str, Any]],
                    offers: Mapping[str, Mapping[str, Any]]) -> dict:
    """为每条 outcome 还原一个「主动开口时刻」，并逐行标注来源，**绝不伪造**。

    可信时刻来源（取第一个可用的；前三个都精确，第四个不存在——拿不到就按污染剔除）：
      1. ``offer_t``——① 落地后的原开口时刻（当前生产账本没有，预留自动启用）；
      2. offers.jsonl 按现有 id join 到的 offer ``t``（提议侧记录的开口时刻）；
      3. ``t - latency_s`` 重构——record_outcome 写盘时 latency_s 就是
         ``结果时刻 - offer['t']``（live.py record_outcome），所以这是换算不是猜测，
         沉默行同样成立；要求 0 ≤ latency_s ≤ LATENCY_VALID_MAX_S；
      4. 前三个都拿不到（join 缺失且 latency 缺失/非法，实测如 o-rej 的 1.79e9s）
         → **不静默读秒**：单列为疑似污染，从主动开口序列剔除并计数点名。
    连结果时刻 t 都没有的行另计 ``no_timestamp_rows``。

    对话簇排除（两个数据源，①的 outcome 侧优先，P2-1）：
      * outcome 行自带 reply_to 非空 / turn_trigger=="reply"（①字段）；
      * 否则 join 到的 offer 行带非空 reply_to——该字段①未落地前**今天就在
        offers.jsonl 里**（session 发布时摘进 offer dict），实测生产 6 行。
    两侧都没有标记时才如实说明「无法识别对话簇」，不再与 offers join 覆盖率自相矛盾。
    """
    moments: list[dict] = []
    sources: Counter = Counter()
    excluded_reply_outcomes = 0
    excluded_reply_offers = 0
    polluted: list[dict] = []
    no_ts = 0
    reply_outcomes_present = any(FIELD_REPLY_TO in r or FIELD_TURN_TRIGGER in r
                                 for r in outcomes)
    reply_offers_present = any(
        isinstance(r, Mapping) and (_nonempty(r.get(FIELD_REPLY_TO))
                                    or FIELD_REPLY_TO in r
                                    or FIELD_TURN_TRIGGER in r)
        for r in offers.values())
    for row in outcomes:
        linked = offers.get(str(row.get("id") or ""))
        if _row_is_reply_cluster(row):
            excluded_reply_outcomes += 1
            continue
        if isinstance(linked, Mapping) and (
                _nonempty(linked.get(FIELD_REPLY_TO))
                or str(linked.get(FIELD_TURN_TRIGGER) or "").strip().lower() == "reply"):
            # offer 侧的回话簇标记（①前唯一在盘的来源）；①的 outcome 侧已在上面优先判过
            excluded_reply_offers += 1
            continue
        ts: float | None = None
        source: str | None = None
        offer_t = _finite_number(row.get(FIELD_OFFER_T))
        if offer_t is not None:
            ts, source = offer_t, "offer_t"
        if ts is None and isinstance(linked, Mapping):
            joined_t = _finite_number(linked.get("t"))
            if joined_t is not None:
                ts, source = joined_t, "offers_join"
        t = _finite_number(row.get("t"))
        latency = _finite_number(row.get("latency_s"))
        latency_valid = latency is not None and 0.0 <= latency <= LATENCY_VALID_MAX_S
        if ts is None:
            if t is not None and latency_valid:
                ts, source = t - latency, "reconstructed_t_minus_latency"
            elif t is not None:
                # join 缺失（且无 offer_t）+ latency 缺失/非法 → 只剩带超时偏移的
                # 结果时刻可读；读它就是静默读秒（o-rej 即此路径），剔除并点名。
                reason_bits = []
                if offer_t is None and not isinstance(linked, Mapping):
                    reason_bits.append("offers_join 缺失")
                if latency is None:
                    reason_bits.append("latency_s 缺失")
                else:
                    reason_bits.append(
                        f"latency_s 非法（{latency:.1f}s 超出 0~"
                        f"{int(LATENCY_VALID_MAX_S)}s）")
                polluted.append({
                    "id": str(row.get("id") or ""),
                    "outcome": str(row.get("outcome") or ""),
                    "latency_s": latency,
                    "reason": "；".join(reason_bits) or "开口时刻不可信",
                })
                continue
            else:
                no_ts += 1
                continue
        moments.append({"id": str(row.get("id") or ""), "ts": ts, "source": source})
        sources[source] += 1
    moments.sort(key=lambda m: (m["ts"], m["id"]))
    return {"moments": moments, "timestamp_sources": dict(sorted(sources.items())),
            "excluded_reply_rows": excluded_reply_outcomes + excluded_reply_offers,
            "excluded_reply_rows_outcomes": excluded_reply_outcomes,
            "excluded_reply_rows_offers": excluded_reply_offers,
            "reply_outcomes_present": reply_outcomes_present,
            "reply_offers_present": reply_offers_present,
            "polluted_rows": polluted[:10],
            "polluted_n": len(polluted),
            "no_timestamp_rows": no_ts}


def _gap_histogram(gaps: Sequence[float]) -> list[dict]:
    """间隔长尾分布：0s 单列，其余按 GAP_BIN_EDGES_S 左开右闭，末桶 +∞。"""
    counts = [0] * (len(GAP_BIN_EDGES_S) + 1)
    for gap in gaps:
        if gap <= 0:
            counts[0] += 1
            continue
        placed = False
        for i in range(len(GAP_BIN_EDGES_S) - 1):
            if GAP_BIN_EDGES_S[i] < gap <= GAP_BIN_EDGES_S[i + 1]:
                counts[i + 1] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    labels = ["0s"]
    labels += [f"({GAP_BIN_EDGES_S[i]:.0f}, {GAP_BIN_EDGES_S[i + 1]:.0f}]s"
               for i in range(len(GAP_BIN_EDGES_S) - 1)]
    labels.append(f">{GAP_BIN_EDGES_S[-1]:.0f}s")
    return [{"bin_s": label, "n": n} for label, n in zip(labels, counts)]


def burstiness(moments_info: Mapping[str, Any]) -> dict:
    """指标 1：主动开口间隔突发度——中位/p90、CV=σ/μ、≤120s 成簇与长尾分布。

    CV **只监控、不拦截**（issue #15 非目标：不设配额/阈值闸）；
    样本 < MIN_METRIC_SAMPLE 时数字照给（描述性），但结论必须是「不能判断」。

    本函数**内部先按时间排序**（P2-4）：gap 序列、成簇 run、来源对标注全部基于
    同一份排序结果，不依赖调用方喂入顺序。
    """
    moments = sorted(moments_info.get("moments") or (),
                     key=lambda m: (float(m["ts"]), str(m.get("id") or "")))
    ts = [float(m["ts"]) for m in moments]
    srcs = [str(m.get("source") or "?") for m in moments]
    # 排序后相邻对严格一一对应：不再丢负 gap（相等时刻产生 0s gap，仍计入成簇）
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    gap_pairs = [f"{a}→{b}" for a, b in zip(srcs, srcs[1:])]
    pair_counter = Counter(gap_pairs)
    mixed_n = sum(n for pair, n in pair_counter.items()
                  if pair.split("→")[0] != pair.split("→")[1])
    n_openings = len(ts)
    out: dict[str, Any] = {
        "n_openings": n_openings,
        "n_gaps": len(gaps),
        "timestamp_sources": moments_info.get("timestamp_sources", {}),
        "cluster_gap_s": CLUSTER_GAP_S,
        "excluded_reply_rows": moments_info.get("excluded_reply_rows", 0),
        "excluded_reply_rows_outcomes": moments_info.get("excluded_reply_rows_outcomes", 0),
        "excluded_reply_rows_offers": moments_info.get("excluded_reply_rows_offers", 0),
        "reply_outcomes_present": moments_info.get("reply_outcomes_present", False),
        "reply_offers_present": moments_info.get("reply_offers_present", False),
        "polluted_n": moments_info.get("polluted_n", 0),
        "polluted_rows": moments_info.get("polluted_rows", []),
        "no_timestamp_rows": moments_info.get("no_timestamp_rows", 0),
        "gap_mixed_source_n": mixed_n,
        "gap_source_pairs": dict(sorted(pair_counter.items())),
        "gap_median_s": None, "gap_p90_s": None, "gap_mean_s": None,
        "gap_std_s": None, "gap_cv": None, "gap_min_s": None, "gap_max_s": None,
        "gap_histogram": [],
        "cluster_n": 0, "turns_in_clusters": 0, "singleton_n": n_openings,
        "cluster_size_histogram": {}, "largest_cluster_turns": 0,
        "cv_policy": "CV=σ/μ（总体标准差）只监控、不拦截，本报告不设任何阈值闸。",
    }
    if gaps:
        ordered = sorted(gaps)
        mean_gap = statistics.fmean(gaps)
        std_gap = statistics.pstdev(gaps)
        out.update({
            "gap_median_s": float(statistics.median(ordered)),
            "gap_p90_s": _percentile(ordered, 0.90),
            "gap_mean_s": float(mean_gap),
            "gap_std_s": float(std_gap),
            "gap_cv": float(std_gap / mean_gap) if mean_gap > 0 else None,
            "gap_min_s": float(ordered[0]),
            "gap_max_s": float(ordered[-1]),
            "gap_histogram": _gap_histogram(gaps),
        })
    # 成簇：时间序上，相邻开口间隔 ≤ CLUSTER_GAP_S 归入同一簇（与上面 gaps 同源）
    sizes: list[int] = []
    if ts:
        run = 1
        for gap in gaps:
            if gap <= CLUSTER_GAP_S:
                run += 1
            else:
                sizes.append(run)
                run = 1
        sizes.append(run)
    burst_sizes = [s for s in sizes if s >= 2]
    out["cluster_n"] = len(burst_sizes)
    out["turns_in_clusters"] = sum(burst_sizes)
    out["singleton_n"] = sum(1 for s in sizes if s == 1)
    out["cluster_size_histogram"] = {str(k): v for k, v in
                                     sorted(Counter(burst_sizes).items())}
    out["largest_cluster_turns"] = max(burst_sizes, default=0)

    if n_openings < 2:
        out["verdict"] = ("不能判断：可信开口时刻的行不足 2 条，连一个间隔都算不出来"
                          "（不是 CV=0，也不是节奏平稳）。")
    elif n_openings < MIN_METRIC_SAMPLE:
        out["verdict"] = (f"样本不足，不能判断突发度是否异常：只有 {n_openings} 个可信开口"
                          f"（<{MIN_METRIC_SAMPLE}）；以下间隔/簇数字仅作描述，"
                          f"CV 只监控、不拦截。")
    else:
        out["verdict"] = (f"描述性结果（n={n_openings}，未做显著性检验）：间隔中位数 "
                          f"{out['gap_median_s']:.1f}s、p90 {out['gap_p90_s']:.1f}s、"
                          f"CV={out['gap_cv']:.3f}；{out['cluster_n']} 个 ≤"
                          f"{int(CLUSTER_GAP_S)}s 突发簇。CV 只监控、不拦截，"
                          f"本报告不据此给好坏结论。")
    notes = ["开口时刻来源计数（逐行标注，不伪造；三个来源均精确，无超时偏移）："
             + (json.dumps(out["timestamp_sources"], ensure_ascii=False) or "{}")]
    if out["polluted_n"]:
        ids = "、".join(str(p.get("id") or "") for p in out["polluted_rows"][:5])
        notes.append(f"疑似污染 {out['polluted_n']} 行已从开口序列剔除（不静默读秒；"
                     f"如 join 缺失 + latency 非法）：{ids}")
    # 对话簇排除：两个数据源如实分开说（P2-1），不能再笼统声称「字段缺失无法排除」
    if out["excluded_reply_rows"]:
        notes.append(
            f"已排除对话簇开口 {out['excluded_reply_rows']} 行"
            f"（outcomes 侧①字段 {out['excluded_reply_rows_outcomes']} 行；"
            f"offers.jsonl join 侧 reply_to {out['excluded_reply_rows_offers']} 行"
            f"——该字段①落地前已随 offer 落盘）。")
    if not out["reply_outcomes_present"] and not out["reply_offers_present"]:
        notes.append("outcomes 与 offers 两侧都没有 reply_to/turn_trigger 标记："
                     "无法识别对话簇，间隔序列可能混入「用户回话引出的再开口」。")
    elif not out["reply_outcomes_present"]:
        notes.append("outcomes 侧 reply_to/turn_trigger 仍缺失（①未落地）："
                     "当前排除只覆盖 offers join 命中的开口，join 不上的行无法判别。")
    if out["gap_mixed_source_n"]:
        notes.append(
            f"{out['gap_mixed_source_n']} 个 gap 的两个端点来自不同时刻来源，"
            f"来源对分布 {json.dumps(out['gap_source_pairs'], ensure_ascii=False)}；"
            f"消费方据此识别混合边界（三来源均精确，仅作溯源标注）。")
    if out["no_timestamp_rows"]:
        notes.append(f"{out['no_timestamp_rows']} 行连结果时刻都缺失，未计入序列。")
    out["notes"] = notes
    return out


def anchor_stats(outcomes: Sequence[Mapping[str, Any]],
                 field_status: Mapping[str, Mapping[str, Any]]) -> dict:
    """指标 2：无锚点占比（按 kind 分列）。① 的 anchor 字段缺失时显式「不可算」。

    P2-5：**分母只数 anchor 字段存在的行**。字段缺失（①灰度期的历史行）与
    「字段存在但确认为空」在结构上严格分开，JSON 消费方不能把缺失误读成无锚点开火。
    每个 kind 给 ``coverage = with_field/n``，占比 = anchorless_confirmed/with_field。
    """
    total = len(outcomes)
    status = dict(field_status.get(FIELD_ANCHOR) or {})
    with_key = int(status.get("rows_with_key") or 0)
    by_kind: dict[str, dict] = {}
    for row in outcomes:
        kind = str(row.get("kind") or "(缺失)") or "(缺失)"
        entry = by_kind.setdefault(kind, {
            "n": 0, "with_field": 0, "anchored": 0,
            "anchorless_confirmed": 0, "missing_field": 0})
        entry["n"] += 1
        if FIELD_ANCHOR in row:
            entry["with_field"] += 1
            if _nonempty(row.get(FIELD_ANCHOR)):
                entry["anchored"] += 1
            else:
                entry["anchorless_confirmed"] += 1
        else:
            entry["missing_field"] += 1
    for entry in by_kind.values():
        entry["coverage"] = entry["with_field"] / entry["n"] if entry["n"] else None
        # 分母只算字段存在的行；字段缺失不进分子也不进分母
        entry["anchorless_rate"] = (
            entry["anchorless_confirmed"] / entry["with_field"]
            if entry["with_field"] else None)
    out: dict[str, Any] = {
        "total": total,
        "rows_with_anchor_key": with_key,
        "coverage": with_key / total if total else None,
        "field_status": status,
        "by_kind": dict(sorted(by_kind.items())),
        "red_line": "≈0（issue #10：主动开口应几乎全部带锚点）",
        "denominator_note": "anchorless_rate 的分母 = 该 kind 内 anchor 字段存在的行；"
                            "字段缺失行进 coverage/missing_field，不进占比。",
    }
    if total == 0:
        out["computable"] = False
        out["anchorless_rate_overall"] = None
        out["verdict"] = "不能判断：outcomes.jsonl 没有任何行，无锚点占比无从算起。"
        return out
    if with_key == 0:
        # 铁律：①未落地时绝不给默认值凑出一个「100% 无锚点」
        out["computable"] = False
        out["anchorless_rate_overall"] = None
        out["verdict"] = ("锚点字段缺失（①未落地）：0/" + str(total)
                          + " 行含 anchor 字段，无锚点占比不可算——"
                            "不伪造默认值，也不把「字段缺失」当成「无锚点开火」。")
        return out
    confirmed = sum(e["anchorless_confirmed"] for e in by_kind.values())
    out["computable"] = True
    out["anchorless_rate_overall"] = confirmed / with_key
    if with_key < total:
        out["verdict"] = (f"部分可算：仅 {with_key}/{total} 行带 anchor 字段"
                          f"（覆盖率 {with_key / total:.3f}）；占比分母只数这 {with_key} 行，"
                          f"其余 {total - with_key} 行字段缺失、单列不进分母，"
                          f"勿把历史行当成无锚点开火。")
    else:
        out["verdict"] = f"可算：{total}/{total} 行带 anchor 字段（覆盖率 1.000），" \
                         f"整体无锚点占比 {out['anchorless_rate_overall']:.3f}（红线≈0）。"
    return out


def response_rates(classes: Mapping[str, int]) -> dict:
    """指标 3：回应率双口径并列（分母不同，绝不混成一个数）。

    * 观测回应率（三类标签）= (正面+负面) / (正面+负面+沉默)：沉默**进**分母，
      回答的是「用户有没有给出任何可观测反应」；
    * 有证据正面率 = 正面 / (正面+负面)：沉默**不进**分母，沿用
      ``_meaningful``（既有口径），回答的是「明确回应里正面占多少」。
    """
    pos = int(classes.get("positive", 0))
    neg = int(classes.get("negative", 0))
    sil = int(classes.get("silence", 0))
    amb = int(classes.get("ambiguous", 0))
    unk = int(classes.get("unknown", 0))
    obs_den = pos + neg + sil
    ev_den = pos + neg
    observed = {
        "name": "观测回应率（三类标签）",
        "numerator": pos + neg, "denominator": obs_den,
        "rate": (pos + neg) / obs_den if obs_den else None,
        "denominator_note": "正面+负面+沉默；沉默（无回应）进分母",
    }
    evidence = {
        "name": "有证据正面率",
        "numerator": pos, "denominator": ev_den,
        "rate": pos / ev_den if ev_den else None,
        "denominator_note": "正面+负面；沉默不进分母（沿用既有 _meaningful 口径）",
    }
    out = {"observed_response_rate": observed,
           "evidence_positive_rate": evidence,
           "excluded_from_both": {"ambiguous": amb, "unknown": unk}}
    if obs_den < MIN_METRIC_SAMPLE or ev_den < MIN_METRIC_SAMPLE:
        out["verdict"] = (f"样本不足，不能判断回应率高低：观测口径分母 {obs_den}、"
                          f"有证据口径分母 {ev_den}（任一 <{MIN_METRIC_SAMPLE}）；"
                          f"两个比率仅作描述，且分母不同，禁止互相替代。")
    else:
        out["verdict"] = ("双口径并列（分母不同、回答的问题不同）："
                          f"观测回应率 {observed['rate']:.3f}（沉默进分母），"
                          f"有证据正面率 {evidence['rate']:.3f}（沉默不进分母）。")
    return out


def receptivity_latency(outcomes: Sequence[Mapping[str, Any]]) -> dict:
    """指标 4：receptivity 延迟中位/p75/p90（只统计用户**有明确回应**的行）。

    沉默行的 latency_s 是气泡存活时长（≈180s 超时），不是回应延迟，必须排除；
    超过 LATENCY_VALID_MAX_S 的值按污染行剔除并计数（实测 o-rej=1.79e9s）。
    """
    vals: list[float] = []
    per_class = Counter()
    silence_n = ambiguous_n = unknown_n = invalid_n = 0
    invalid_examples: list[dict] = []
    for row in outcomes:
        cls = classify(row.get("outcome"))
        latency = _finite_number(row.get("latency_s"))
        if cls in ("positive", "negative"):
            if latency is not None and 0.0 <= latency <= LATENCY_VALID_MAX_S:
                vals.append(latency)
                per_class[cls] += 1
            else:
                invalid_n += 1
                if len(invalid_examples) < 5:
                    invalid_examples.append(
                        {"id": str(row.get("id") or ""), "outcome": cls,
                         "latency_s": latency})
        elif cls == "silence":
            silence_n += 1
        elif cls == "ambiguous":
            ambiguous_n += 1
        else:
            unknown_n += 1
    ordered = sorted(vals)
    n = len(vals)
    out: dict[str, Any] = {
        "n": n,
        "by_class": dict(sorted(per_class.items())),
        "median_s": _percentile(ordered, 0.50),
        "p75_s": _percentile(ordered, 0.75),
        "p90_s": _percentile(ordered, 0.90),
        "min_s": float(ordered[0]) if ordered else None,
        "max_s": float(ordered[-1]) if ordered else None,
        "excluded_silence_rows": silence_n,
        "excluded_ambiguous_rows": ambiguous_n,
        "excluded_unknown_rows": unknown_n,
        "excluded_invalid_latency_rows": invalid_n,
        "invalid_examples": invalid_examples,
        "population_note": "总体 = 正面+负面行且 0≤latency_s≤24h；"
                           "沉默行的 latency 是气泡超时时长而非回应延迟，已排除。",
    }
    if n == 0:
        out["verdict"] = "不能判断：没有任何带合法 latency_s 的明确回应行。"
    elif n < MIN_METRIC_SAMPLE:
        out["verdict"] = (f"样本不足，不能判断回应延迟是快是慢：明确回应行只有 {n} 条"
                          f"（<{MIN_METRIC_SAMPLE}）；分位数仅作描述。")
    else:
        out["verdict"] = (f"描述性结果（n={n}，未做显著性检验）：回应延迟中位 "
                          f"{out['median_s']:.1f}s / p75 {out['p75_s']:.1f}s / "
                          f"p90 {out['p90_s']:.1f}s。")
    return out


# ── 校准状态（弱依赖 timing.py；拿不到就降级）────────────────────────────────
def calibration(app: str = "default", timing_module: Any | None = None) -> dict:
    """只读地取 timing 的校准状态。**不把 import timing 写成硬依赖。**

    * 导入失败 / 任一调用抛异常 → 对应字段写错误原因，并标记「校准状态未知」；
    * 成功 → 照录 ``benefit_now()`` 的 ``why`` 原文与 ``stop_threshold(app)``，
      并附带 timing.py 的 mtime（队友正在并行改它，得能区分版本）；
    * 额外只读地取 timing 自己的 ``_POSITIVE/_NEGATIVE/MIN_OUTCOMES``，用于暴露
      **口径差异**（例如 timing 把 ignored 当负面证据，正是报告要点名的误导分母）。
    """
    out: dict[str, Any] = {"app": app, "available": False, "status": "校准状态未知"}
    mod = timing_module
    if mod is None:
        try:
            from . import timing as mod  # type: ignore  # 延迟导入：只在真正需要时
        except Exception as exc:  # ImportError / SyntaxError（队友正在写）等
            out["reason"] = (f"无法导入 sprite.proactive.timing"
                             f"（{type(exc).__name__}: {exc}）——降级为「校准状态未知」")
            return out
    out["available"] = True
    out["status"] = "校准状态已读取"
    out["module"] = getattr(mod, "__name__", "timing")

    module_file = getattr(mod, "__file__", None)
    if module_file:
        try:
            stat = Path(module_file).stat()
            out["timing_path"] = str(module_file)
            out["timing_mtime"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except OSError:
            pass

    why = None
    try:
        benefit, why = mod.benefit_now()
        out["benefit_s"] = float(benefit)
        out["benefit_why"] = str(why)
    except Exception as exc:
        out["benefit_why"] = None
        out["benefit_error"] = f"{type(exc).__name__}: {exc}"
    try:
        out["p_star"] = float(mod.stop_threshold(app))
    except Exception as exc:
        out["p_star"] = None
        out["p_star_error"] = f"{type(exc).__name__}: {exc}"

    timing_outcomes = getattr(mod, "OUTCOMES_PATH", None)
    out["timing_outcomes_path"] = str(timing_outcomes) if timing_outcomes else None
    # 只读地暴露校准模块自己的词表/阈值（缺失则 None，绝不因此报错）
    out["timing_vocabulary"] = {
        "positive": sorted(getattr(mod, "_POSITIVE", []) or []),
        "negative": sorted(getattr(mod, "_NEGATIVE", []) or []),
        "min_outcomes": getattr(mod, "MIN_OUTCOMES", None),
    }
    # 结构性判据（不靠措辞）：why 里的证据不足标记 + 本模块自算的有证据开口数
    markers = ("证据不足", "出厂先验", "没有足够")
    out["why_says_insufficient"] = bool(why) and any(m in str(why) for m in markers)
    if out["why_says_insufficient"]:
        # status 必须与 available 自洽：上面标过「已读取」，这里补上 timing 自报的证据不足
        out["status"] = "校准状态已读取（timing 自报证据不足）"
    return out


# ── 汇总 ────────────────────────────────────────────────────────────────────
def _bucket_summary(rows: Sequence[Mapping[str, Any]],
                    offers: Mapping[str, Mapping[str, Any]]) -> dict[str, dict]:
    buckets: dict[str, dict] = {}
    for row in rows:
        name = bucket_of(row, offers)
        bucket = buckets.setdefault(name, {
            "n": 0,
            "classes": {cls: 0 for cls in CLASSES},
            "labels": Counter(),
            "raw_kinds": Counter(),
        })
        label = str(row.get("outcome") if row.get("outcome") is not None else "").strip().lower()
        bucket["n"] += 1
        bucket["classes"][classify(row.get("outcome"))] += 1
        bucket["labels"][label or "(空)"] += 1
        bucket["raw_kinds"][str(row.get("kind") or "(缺失)")] += 1
    # Counter → dict，保证 JSON 可序列化、键顺序稳定
    for bucket in buckets.values():
        bucket["labels"] = dict(sorted(bucket["labels"].items()))
        bucket["raw_kinds"] = dict(sorted(bucket["raw_kinds"].items()))
        bucket["evidence_n"] = _meaningful(bucket["classes"])
    ordered = {}
    for name in ("companion", "offer_with_options", "other"):
        if name in buckets:
            ordered[name] = buckets[name]
    for name in sorted(buckets):
        if name not in ordered:
            ordered[name] = buckets[name]
    return ordered


def _day_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    days: dict[str, dict] = {}
    for row in rows:
        ts = _to_ts(row.get("t"))
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts is not None else "未知"
        entry = days.setdefault(day, {"n": 0, "classes": {cls: 0 for cls in CLASSES}})
        entry["n"] += 1
        entry["classes"][classify(row.get("outcome"))] += 1
    for entry in days.values():
        entry["evidence_n"] = _meaningful(entry["classes"])
        entry["positive_rate_evidence_only"] = (
            entry["classes"]["positive"] / entry["evidence_n"] if entry["evidence_n"] else None
        )
    return dict(sorted(days.items()))


def trend_verdict(days: Mapping[str, Mapping[str, Any]]) -> dict:
    """按天趋势判定。样本不足就直说「样本不足」，不画趋势结论。"""
    dated = {d: v for d, v in days.items() if d != "未知"}
    n_days = len(dated)
    if n_days < MIN_DAYS:
        return {"verdict": "样本不足",
                "reason": f"只有 {n_days} 天有结果（画趋势至少需要 {MIN_DAYS} 天）——不画趋势"}
    thin = [d for d, v in dated.items() if v["n"] < MIN_PER_DAY]
    if thin:
        return {"verdict": "样本不足",
                "reason": f"{len(thin)} 天单日结果 <{MIN_PER_DAY} 条"
                          f"（{', '.join(thin[:5])}{'…' if len(thin) > 5 else ''}）——不画趋势"}
    no_evidence = [d for d, v in dated.items() if v["evidence_n"] == 0]
    if no_evidence:
        return {"verdict": "样本不足",
                "reason": f"{len(no_evidence)} 天没有任何有证据的开口（全是沉默/模糊/未知）"
                          f"（{', '.join(no_evidence[:5])}{'…' if len(no_evidence) > 5 else ''}）"
                          f"——不画趋势"}
    ordered = [dated[d] for d in sorted(dated)]
    half = max(1, len(ordered) // 2)
    first, last = ordered[:half], ordered[half:]
    first_rate = (sum(v["classes"]["positive"] for v in first)
                  / max(1, sum(v["evidence_n"] for v in first)))
    last_rate = (sum(v["classes"]["positive"] for v in last)
                 / max(1, sum(v["evidence_n"] for v in last)))
    if last_rate > first_rate:
        verdict = "前半段→后半段 正面率上升（描述性，未做显著性检验）"
    elif last_rate < first_rate:
        verdict = "前半段→后半段 正面率下降（描述性，未做显著性检验）"
    else:
        verdict = "前半段→后半段 正面率持平（描述性，未做显著性检验）"
    return {"verdict": verdict,
            "reason": f"前 {len(first)} 天 {first_rate:.3f} → 后 {len(last)} 天 {last_rate:.3f}",
            "first_rate": first_rate, "last_rate": last_rate}


def overall_conclusion(summary: Mapping[str, Any]) -> str:
    """一句话结论：这套数据能不能支撑「开口质量在变好」。不能就直说不能。"""
    total = int(summary.get("total") or 0)
    ev = summary["evidence"]
    if total == 0:
        return "不能：结果账本里没有任何行，无从判断。"
    if ev["evidence_n"] == 0:
        return (f"不能：{total} 条结果全部是「无证据」（沉默 {ev['silence']} 条、"
                f"模糊 {ev['ambiguous']} 条、未知 {ev['unknown']} 条），"
                f"没有任何正面或负面证据——无回应不等于拒绝，这套数据不能支撑"
                f"「开口质量在变好」。")
    if ev["evidence_n"] < MIN_EVIDENCE:
        return (f"不能：有明确证据的开口只有 {ev['evidence_n']} 条"
                f"（<{MIN_EVIDENCE}），其中正面 {ev['positive']} / 负面 {ev['negative']}；"
                f"样本太小，任何「变好/变差」都超出数据能支撑的范围。")
    trend = summary["trend"]
    if str(trend["verdict"]).startswith("样本不足"):
        return (f"不能：证据量 {ev['evidence_n']} 条虽然够，但按天分布不足以画趋势"
                f"（{trend['reason']}）。")
    return (f"可以支撑一个描述性观察：正面 {ev['positive']} / 负面 {ev['negative']}，"
            f"{trend['verdict']}。注意这仍不是因果结论。")


def summarize(perceive_dir: Path, *, app: str = "default",
              timing_module: Any | None = None) -> dict:
    """汇总四本账本 + 校准状态 + 结论。返回值 JSON 可序列化。"""
    perceive_dir = Path(perceive_dir)
    files: dict[str, dict] = {}
    data: dict[str, list[dict]] = {}
    for name in FILE_NAMES:
        path = perceive_dir / name
        rows, bad = read_jsonl(path)
        data[name] = rows
        files[name] = {"path": str(path), "exists": path.exists(),
                       "rows": len(rows), "malformed": bad}

    outcomes = data["outcomes.jsonl"]
    offers_map = _index_offers(data["offers.jsonl"])
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "perceive_dir": str(perceive_dir),
        "files": files,
        "vocabulary": {"positive": list(POSITIVE), "negative": list(NEGATIVE),
                       "silence": list(SILENCE), "ambiguous": list(AMBIGUOUS)},
        "total": len(outcomes),
    }

    # 1) 按 kind 分列
    buckets = _bucket_summary(outcomes, offers_map)
    report["buckets"] = buckets
    report["bucket_order"] = list(buckets)

    # 2) 三类标签 + 分母
    classes = _class_counts(outcomes)
    labels = Counter(str(r.get("outcome") if r.get("outcome") is not None else "").strip().lower()
                     or "(空)" for r in outcomes)
    evidence_n = _meaningful(classes)
    report["classes"] = classes
    report["labels"] = dict(sorted(labels.items()))
    report["unknown_labels"] = {k: v for k, v in sorted(labels.items())
                                if classify(k) == "unknown"}
    report["ambiguous_labels"] = {k: v for k, v in sorted(labels.items())
                                  if classify(k) == "ambiguous"}
    report["evidence"] = {
        "positive": classes["positive"],
        "negative": classes["negative"],
        "silence": classes["silence"],
        "ambiguous": classes["ambiguous"],
        "unknown": classes["unknown"],
        "evidence_n": evidence_n,
        # 有证据口径：分母 = 有明确正/负证据的开口数（正面+负面），沉默不进分母
        "positive_rate_evidence_only": (classes["positive"] / evidence_n) if evidence_n else None,
        "denominator_evidence_only": evidence_n,
        # 误导口径：把沉默算进分母。单独列出，只为点名这个错误，不作为结论。
        "positive_rate_including_silence": (classes["positive"] / len(outcomes)) if outcomes else None,
        "denominator_including_silence": len(outcomes),
    }

    # 3) 未知/新标签（已计数，绝不静默丢弃）
    report["unknown_note"] = ("未知标签全部已计数并单列；它们不并入任何分子/分母。"
                              "新增的 outcome 字符串（如 T1 的 unanswered）若不在本模块词表里，"
                              "会出现在这里。")

    # 2b) issue #15 ②：离线四指标（全部确定性纯函数；缺 ① 字段时显式降级，不伪造）
    offer_rows = data["offers.jsonl"]
    field_status = ledger_field_status(outcomes, offer_rows)
    report["ledger_fields"] = field_status
    report["burstiness"] = burstiness(opening_moments(outcomes, offers_map))
    report["anchors"] = anchor_stats(outcomes, field_status["outcomes"])
    report["response_rates"] = response_rates(classes)
    report["receptivity_latency"] = receptivity_latency(outcomes)

    # 4) 按天
    days = _day_summary(outcomes)
    report["days"] = days
    report["trend"] = trend_verdict(days)

    # 5) 提议侧（offers.jsonl）：kind × result + join 覆盖率
    offer_kinds: dict[str, dict] = {}
    for row in offer_rows:
        kind = str(row.get("kind") or "(缺失)")
        result = str(row.get("result") or "(缺失)")
        entry = offer_kinds.setdefault(kind, {"n": 0, "results": Counter(),
                                              "with_options": 0})
        entry["n"] += 1
        entry["results"][result] += 1
        if row.get("options"):
            entry["with_options"] += 1
    for entry in offer_kinds.values():
        entry["results"] = dict(sorted(entry["results"].items()))
    joined = sum(1 for r in outcomes if str(r.get("id") or "") in offers_map)
    outcome_ids = {str(r.get("id") or "") for r in outcomes if r.get("id")}
    report["offers"] = {
        "rows": len(offer_rows),
        "kind_result": offer_kinds,
        "distinct_ids": len(offers_map),
        "joined_outcomes": joined,
        "offers_without_outcome": len(set(offers_map) - outcome_ids),
        "note": "offers.jsonl 的 result 是「提议侧」状态（shown/auto_started/…），"
                "不是用户回应；没有对应 outcomes 行的提议 = 还没被观测到结果。",
    }

    # 6) 对话账本：交叉核对「记成沉默、其实用户回了话」
    conversation = data["conversation.jsonl"]
    user_rows = [r for r in conversation if str(r.get("role") or "") == "user"]
    late_replies: list[dict] = []
    for row in outcomes:
        t = _to_ts(row.get("t"))
        if t is None:
            continue
        for reply in user_rows:
            rt = _to_ts(reply.get("t"))
            if rt is None or not (t < rt <= t + LATE_USER_WINDOW_S):
                continue
            late_replies.append({
                "outcome_id": str(row.get("id") or ""),
                "outcome": str(row.get("outcome") or ""),
                "outcome_class": classify(row.get("outcome")),
                "outcome_t": t,
                "user_reply_t": rt,
                "user_text": str(reply.get("text") or "")[:160],
            })
    late_replies.sort(key=lambda r: r["user_reply_t"])
    report["conversation"] = {
        "rows": len(conversation),
        "user": len(user_rows),
        "assistant": sum(1 for r in conversation if str(r.get("role") or "") == "assistant"),
        "late_user_replies": late_replies,
        "note": "结果落库后 %d 秒内用户打字，但结果记成沉默 → 疑似漏记的 responded"
                % int(LATE_USER_WINDOW_S),
    }

    # 7) 反馈账本（辅助信号：没有 offer 级 join key，不并入开口分母）
    feedback = data["feedback.jsonl"]
    report["feedback"] = {
        "rows": len(feedback),
        "kinds": dict(sorted(Counter(str(r.get("kind") or "(缺失)") for r in feedback).items())),
        "note": "feedback.jsonl 是用户反馈文本，没有 offer 级 join key，"
                "不能并入开口级分母；此处只作为旁证。",
    }

    # 8) 沉默样本明细：把每一条无证据开口连文本一起列出来，
    #    并标出 latency 是否达到这一行**按它自己 kind/文本算出的气泡寿命**
    #    （companion 30~90s、offer 120s）：到点被收走的沉默 ≠ 用户拒绝。
    details = []
    for row in outcomes:
        if classify(row.get("outcome")) != "silence":
            continue
        ts = _to_ts(row.get("t"))
        latency = row.get("latency_s")
        try:
            latency_f = float(latency) if latency is not None else None
        except (TypeError, ValueError):
            latency_f = None
        budget = bubble_budget_s(row)
        details.append({
            "id": str(row.get("id") or ""),
            "t": ts,
            "day": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "未知",
            "kind": str(row.get("kind") or ""),
            "outcome": str(row.get("outcome") or ""),
            "latency_s": latency_f,
            "bubble_budget_s": budget,
            "suspected_timeout": bool(latency_f is not None
                                      and latency_f + EXPIRY_TOLERANCE_S >= budget),
            "text": str(row.get("text") or "")[:200],
        })
    details.sort(key=lambda r: (r["t"] is None, r["t"]))
    report["silence_details"] = details

    # 9) 校准状态
    calib = calibration(app, timing_module)
    calib["evidence_n_this_report"] = evidence_n
    calib["insufficient"] = bool(calib.get("why_says_insufficient")
                                 or evidence_n < MIN_EVIDENCE)
    reasons = []
    if calib.get("why_says_insufficient"):
        reasons.append("timing 的 why 明说证据不足")
    if evidence_n < MIN_EVIDENCE:
        reasons.append(f"有明确证据的开口只有 {evidence_n} 条（<{MIN_EVIDENCE}）")
    if not calib.get("available"):
        reasons.append(calib.get("reason") or "timing 不可用")
    calib["insufficient_reason"] = "；".join(reasons) or "证据量达到判据"
    out_path = files["outcomes.jsonl"]["path"]
    calib["aligned_with_report"] = (calib.get("timing_outcomes_path") == out_path
                                    if calib.get("timing_outcomes_path") else None)
    report["calibration"] = calib

    # 10) 结论 + 提醒
    report["conclusion"] = overall_conclusion(report)
    report["caveats"] = [
        "无回应不等于拒绝：ignored/unanswered 是「没观测到回应」，不是「用户不要」。",
        "把沉默算进分母得到的「接受率」是误导数字，本报告把它单独列出只为点名。",
        "outcomes.jsonl 一行 = 一次开口；同一 offer 会被 live.py 按 id 去重。",
        "结果账本的行来自气泡超时/用户选择/用户打字三条路径；"
        "任何一条路径漏记都会让分布偏。",
    ]
    return report


# ── 渲染 ────────────────────────────────────────────────────────────────────
def _rate(value: Any) -> str:
    if value is None:
        return "—（分母为 0）"
    return f"{float(value):.3f}"


def _fmt_s(value: Any) -> str:
    """秒数格式化：None → 占位；整数秒不带小数。"""
    if value is None:
        return "—"
    v = float(value)
    return f"{v:.0f}s" if abs(v - round(v)) < 1e-9 else f"{v:.1f}s"


def _cell(text: Any, limit: int = 60) -> str:
    out = str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()
    if len(out) > limit:
        out = out[:limit] + "…"
    return out or "（空）"


def render_markdown(report: Mapping[str, Any]) -> str:
    """把汇总渲染成人读的 Markdown。"""
    ev = report["evidence"]
    lines: list[str] = []
    lines.append("# 开口质量度量（离线、只读）")
    lines.append("")
    lines.append(f"- 数据目录：`{report['perceive_dir']}`")
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append("- 口径（本模块自持，不从 timing 导入）：")
    lines.append(f"  - **正面证据** positive = {', '.join(report['vocabulary']['positive'])}")
    lines.append(f"  - **负面证据** negative = {', '.join(report['vocabulary']['negative'])}")
    lines.append(f"  - **无证据（沉默）** = {', '.join(report['vocabulary']['silence'])}"
                 " —— **无回应不等于拒绝**")
    lines.append(f"  - 模糊（单列、不入分母）= {', '.join(report['vocabulary']['ambiguous'])}"
                 "（acknowledged 只表示看见，不等于愿意）")
    lines.append("  - 未知 = 其余任何字符串，全部计数并单列，绝不静默丢弃")
    lines.append("")
    lines.append("## 0. 读了什么")
    lines.append("")
    lines.append("| 文件 | 存在 | 行数 | 坏行 |")
    lines.append("|---|---|---|---|")
    for name in FILE_NAMES:
        info = report["files"][name]
        lines.append(f"| `{name}` | {'是' if info['exists'] else '否（缺失，已优雅跳过）'} "
                     f"| {info['rows']} | {info['malformed']} |")
    lines.append("")

    # 1. 按 kind
    lines.append("## 1. 按 kind 分列（结果账本 outcomes.jsonl）")
    lines.append("")
    if not report["buckets"]:
        lines.append("没有结果行。")
    else:
        lines.append("| kind | 样本量 | 正面 | 负面 | 无证据 | 模糊 | 未知 | 有证据(=正+负) "
                     "| 正面率（有证据分母） |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, bucket in report["buckets"].items():
            cls = bucket["classes"]
            lines.append(f"| {name} | {bucket['n']} | {cls['positive']} | {cls['negative']} "
                         f"| {cls['silence']} | {cls['ambiguous']} | {cls['unknown']} "
                         f"| {bucket['evidence_n']} "
                         f"| {_rate(cls['positive'] / bucket['evidence_n'] if bucket['evidence_n'] else None)} |")
        lines.append("")
        lines.append("原始标签逐 kind 计数：")
        for name, bucket in report["buckets"].items():
            lines.append(f"- `{name}`（样本 {bucket['n']}）：{bucket['labels']}；"
                         f"raw kind：{bucket['raw_kinds']}")
        lines.append("")
        lines.append("> 「带选项的 offer」= kind=offer 且原始 offer 有非空 `options`；"
                     "其余 offer 与缺失/未知 kind 归入「其他」。")
    lines.append("")

    # 2. 三类标签
    lines.append("## 2. 三类标签与分母（把沉默当拒绝是错的）")
    lines.append("")
    lines.append(f"- 结果行总数 = {report['total']}")
    lines.append(f"- 正面证据 = {ev['positive']}；负面证据 = {ev['negative']}；"
                 f"**无证据（沉默）= {ev['silence']}**；模糊 = {ev['ambiguous']}；"
                 f"未知 = {ev['unknown']}")
    lines.append(f"- **接受率（有证据口径）** = 正面 / (正面+负面) = {ev['positive']} / "
                 f"{ev['denominator_evidence_only']} = **{_rate(ev['positive_rate_evidence_only'])}**"
                 f"；分母 = 有明确正/负证据的开口数，沉默不进分母。")
    lines.append(f"- ⚠️ 误导口径（**不要用**）= 正面 / 全部结果 = {ev['positive']} / "
                 f"{ev['denominator_including_silence']} = "
                 f"**{_rate(ev['positive_rate_including_silence'])}**"
                 f"——这个分母把 {ev['silence']} 条沉默算成了「没被接受」；"
                 f"**无回应不等于拒绝**，所以这个数字是误导的，本报告只为点名它而列出。")
    lines.append(f"- 全部标签计数：{report['labels']}")
    if ev["ambiguous"]:
        lines.append(f"- 模糊标签（不入分母）：{report['ambiguous_labels']}"
                     "（acknowledged = 用户只是看见/点了「好」，不等于愿意）")
    lines.append("")

    # 2b. issue #15 ②：离线四指标
    lines.append("## 2b. 离线四指标（issue #15 ②，只读；样本不足一律明说「不能判断」）")
    lines.append("")
    fields = report["ledger_fields"]
    lines.append("① 账本字段盘点（offer_t/anchor/turn_trigger/reply_to，按数据源分列）：")
    for source, label in (("outcomes", "outcomes.jsonl（①落地侧）"),
                          ("offers", "offers.jsonl（reply_to 今天已随 offer 落盘）")):
        lines.append(f"- {label}：")
        for key, info in fields[source].items():
            lines.append(f"  - `{key}`：{info['rows_with_key']}/{info['rows_total']} 行带键，"
                         f"其中非空 {info['rows_nonempty']}")
    lines.append("")

    burst = report["burstiness"]
    lines.append("### 2b-1. 间隔突发度（主动开口 gap）")
    lines.append("")
    lines.append(f"- 可信开口数 = {burst['n_openings']}，间隔数 = {burst['n_gaps']}；"
                 f"成簇口径 = 相邻间隔 ≤ {burst['cluster_gap_s']:.0f}s；"
                 f"已排除对话簇 {burst['excluded_reply_rows']} 行、疑似污染 "
                 f"{burst['polluted_n']} 行")
    if burst["n_gaps"]:
        lines.append(f"- gap 中位数 = **{_fmt_s(burst['gap_median_s'])}**，"
                     f"p90 = **{_fmt_s(burst['gap_p90_s'])}**，"
                     f"均值 = {_fmt_s(burst['gap_mean_s'])}，"
                     f"σ = {_fmt_s(burst['gap_std_s'])}，"
                     f"**CV=σ/μ = {_rate(burst['gap_cv'])}**"
                     f"（最小 {_fmt_s(burst['gap_min_s'])} / 最大 {_fmt_s(burst['gap_max_s'])}）")
        hist = "；".join(f"{b['bin_s']}×{b['n']}" for b in burst["gap_histogram"])
        lines.append(f"- 间隔长尾分布：{hist}")
        lines.append(f"- 跨时刻来源的 gap = {burst['gap_mixed_source_n']} 个"
                     f"（来源对分布 {burst['gap_source_pairs']}，用于识别混合边界）")
    else:
        lines.append("- 间隔不足 1 个，分位数/CV/长尾均无法计算。")
    lines.append(f"- ≤{burst['cluster_gap_s']:.0f}s 突发簇 = **{burst['cluster_n']} 簇**，"
                 f"簇内轮次合计 {burst['turns_in_clusters']}，最大簇 {burst['largest_cluster_turns']} 轮，"
                 f"孤立开口 {burst['singleton_n']} 个；簇大小分布（簇轮次→簇数）= "
                 f"{burst['cluster_size_histogram'] or '{}'}")
    lines.append(f"- {burst['cv_policy']}")
    lines.append(f"- **判定：{burst['verdict']}**")
    for note in burst["notes"]:
        lines.append(f"  - {note}")
    lines.append("")

    anchors = report["anchors"]
    lines.append("### 2b-2. 无锚点占比（按 kind 分列，红线≈0）")
    lines.append("")
    lines.append(f"- **判定：{anchors['verdict']}**")
    if anchors.get("computable"):
        lines.append(f"- 整体无锚点占比 = **{_rate(anchors.get('anchorless_rate_overall'))}**"
                     f"（分母只数 anchor 字段存在的 {anchors['rows_with_anchor_key']} 行；"
                     f"全量 {anchors['total']} 行，覆盖率 "
                     f"{_rate(anchors.get('coverage'))}；字段缺失不进占比）")
        lines.append("")
        lines.append("| kind | 样本量 | 字段覆盖率 | 有锚点 | 确认无锚点 | 字段缺失 | 无锚点占比 |")
        lines.append("|---|---|---|---|---|---|---|")
        for kind, entry in anchors["by_kind"].items():
            lines.append(f"| {_cell(kind)} | {entry['n']} | {_rate(entry['coverage'])} "
                         f"| {entry['anchored']} | {entry['anchorless_confirmed']} "
                         f"| {entry['missing_field']} | {_rate(entry['anchorless_rate'])} |")
        lines.append("")
        lines.append(f"> {anchors['denominator_note']}")
    lines.append("")

    rates = report["response_rates"]
    obs = rates["observed_response_rate"]
    epr = rates["evidence_positive_rate"]
    lines.append("### 2b-3. 回应率（双口径并列，分母不同，禁止互相替代）")
    lines.append("")
    lines.append(f"- **{obs['name']}** = (正面+负面)/(正面+负面+沉默) = "
                 f"{obs['numerator']}/{obs['denominator']} = **{_rate(obs['rate'])}**"
                 f"——{obs['denominator_note']}")
    lines.append(f"- **{epr['name']}** = 正面/(正面+负面) = "
                 f"{epr['numerator']}/{epr['denominator']} = **{_rate(epr['rate'])}**"
                 f"——{epr['denominator_note']}")
    excluded = rates["excluded_from_both"]
    lines.append(f"- 两个口径都不含模糊 {excluded['ambiguous']} 行、未知 {excluded['unknown']} 行。")
    lines.append(f"- **判定：{rates['verdict']}**")
    lines.append("")

    delay = report["receptivity_latency"]
    lines.append("### 2b-4. receptivity 延迟（明确回应行；沉默/污染行已排除）")
    lines.append("")
    lines.append(f"- 样本 n = {delay['n']}（正面 {delay['by_class'].get('positive', 0)} / "
                 f"负面 {delay['by_class'].get('negative', 0)}）；"
                 f"中位 = **{_fmt_s(delay['median_s'])}**，"
                 f"p75 = **{_fmt_s(delay['p75_s'])}**，"
                 f"p90 = **{_fmt_s(delay['p90_s'])}**"
                 f"（区间 {_fmt_s(delay['min_s'])} ~ {_fmt_s(delay['max_s'])}）")
    lines.append(f"- 排除：沉默 {delay['excluded_silence_rows']} 行（latency 是气泡超时时长，"
                 f"不是回应延迟）、模糊 {delay['excluded_ambiguous_rows']}、"
                 f"未知 {delay['excluded_unknown_rows']}、"
                 f"非法/超 24h 污染值 {delay['excluded_invalid_latency_rows']} 行。")
    lines.append(f"- {delay['population_note']}")
    lines.append(f"- **判定：{delay['verdict']}**")
    lines.append("")

    # 3. 未知标签
    lines.append("## 3. 未知/新出现的标签")
    lines.append("")
    if report["unknown_labels"]:
        for label, count in report["unknown_labels"].items():
            lines.append(f"- `{label}` × {count}")
    else:
        lines.append("无。（新值一旦出现会出现在这里，并计入上面的「未知」列；"
                     "T1 的 `unanswered` 已在本模块词表的沉默类里。）")
    lines.append(f"- {report['unknown_note']}")
    lines.append("")

    # 4. 按天
    lines.append("## 4. 按天分布与趋势")
    lines.append("")
    lines.append("| 日期 | 结果数 | 正面 | 负面 | 无证据 | 模糊 | 未知 | 有证据 | "
                 "正面率（有证据分母） |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for day, entry in report["days"].items():
        cls = entry["classes"]
        lines.append(f"| {day} | {entry['n']} | {cls['positive']} | {cls['negative']} "
                     f"| {cls['silence']} | {cls['ambiguous']} | {cls['unknown']} "
                     f"| {entry['evidence_n']} | {_rate(entry['positive_rate_evidence_only'])} |")
    if not report["days"]:
        lines.append("| （无） | 0 | 0 | 0 | 0 | 0 | 0 | 0 | —（分母为 0） |")
    lines.append("")
    trend = report["trend"]
    lines.append(f"- **趋势判定：{trend['verdict']}** —— {trend['reason']}")
    lines.append("")

    # 5. 校准
    lines.append("## 5. 当前校准状态（sprite.proactive.timing，只读）")
    lines.append("")
    calib = report["calibration"]
    if not calib.get("available"):
        lines.append(f"- **校准状态未知**：{calib.get('reason')}")
    else:
        lines.append(f"- timing 模块：`{calib.get('timing_path', calib.get('module'))}`")
        if calib.get("timing_mtime"):
            lines.append(f"- timing.py mtime：`{calib['timing_mtime']}`"
                         "（队友可能在并行改它，据此区分版本）")
        lines.append(f"- `benefit_now()` → benefit_s = **{calib.get('benefit_s')}**")
        if calib.get("benefit_why") is not None:
            lines.append("- `benefit_now()` 的 why 原文（照录）：")
            lines.append("")
            lines.append(f"  > {str(calib['benefit_why'])}")
            lines.append("")
        else:
            lines.append(f"- `benefit_now()` 调用失败：{calib.get('benefit_error')}")
        lines.append(f"- `stop_threshold('{calib.get('app')}')` → p* = **{calib.get('p_star')}**")
        if calib.get("p_star_error"):
            lines.append(f"  - 失败：{calib['p_star_error']}")
        lines.append(f"- **是否处于「证据不足」状态：{'是' if calib.get('insufficient') else '否'}**"
                     f" —— 判据：{calib.get('insufficient_reason')}")
        tv = calib.get("timing_vocabulary") or {}
        lines.append(f"- 口径差异（只读取出，用于发现分母被污染）：timing 自己用 "
                     f"positive={tv.get('positive')}、negative={tv.get('negative')}、"
                     f"MIN_OUTCOMES={tv.get('min_outcomes')}。"
                     f"本报告 negative 只有 {list(NEGATIVE)}。")
        if "ignored" in (tv.get("negative") or []):
            lines.append("  - ⚠️ 注意：timing 把 `ignored`（沉默）也算作负面证据，"
                         "所以它的「有效率」分母包含沉默——这正是本报告要点名的误导口径。")
        aligned = calib.get("aligned_with_report")
        if aligned is False:
            lines.append(f"  - ⚠️ 口径不对齐：timing 读的是 `{calib.get('timing_outcomes_path')}`，"
                         f"本报告读的是 `{report['files']['outcomes.jsonl']['path']}`"
                         f"——上面的 why 不对应这份数据。")
        elif aligned is True:
            lines.append("  - 口径对齐：timing 读的就是本报告这份 outcomes.jsonl。")
    lines.append("")

    # 6. 提议侧 + 交叉核对
    offers = report["offers"]
    lines.append("## 6. 旁证：提议侧与对话交叉核对")
    lines.append("")
    lines.append(f"- offers.jsonl 共 {offers['rows']} 行 / {offers['distinct_ids']} 个不同 id；"
                 f"其中有结果行（outcomes）的 {offers['joined_outcomes']} 个，"
                 f"还没被观测到结果的 {offers['offers_without_outcome']} 个。")
    lines.append(f"- {offers['note']}")
    for kind, entry in (offers["kind_result"] or {}).items():
        lines.append(f"  - kind=`{kind}`：{entry['n']} 行；result 分布 {entry['results']}；"
                     f"带非空 options 的 {entry['with_options']} 行")
    conv = report["conversation"]
    lines.append(f"- conversation.jsonl 共 {conv['rows']} 行（user {conv['user']} / "
                 f"assistant {conv['assistant']}）。")
    lines.append(f"- 交叉核对（{conv['note']}）："
                 f"{'发现 ' + str(len(conv['late_user_replies'])) + ' 条' if conv['late_user_replies'] else '0 条'}")
    for item in conv["late_user_replies"]:
        lines.append(f"  - outcome `{item['outcome']}`（{item['outcome_class']}）之后 "
                     f"用户回了话：{_cell(item['user_text'])}")
    fb = report["feedback"]
    lines.append(f"- feedback.jsonl 共 {fb['rows']} 行，kind 分布 {fb['kinds']}。{fb['note']}")
    lines.append("")

    # 7. 沉默明细
    lines.append("## 7. 无证据（沉默）样本明细 —— 看清它们是「没回应」而不是「被拒绝」")
    lines.append("")
    if not report["silence_details"]:
        lines.append("没有沉默样本。")
    else:
        lines.append("| # | 时间 | kind | latency_s | 该行气泡寿命 | 疑似气泡超时 | 文本 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, item in enumerate(report["silence_details"], 1):
            lat = "—" if item["latency_s"] is None else f"{item['latency_s']:.1f}"
            budget = f"{item['bubble_budget_s']:.0f}"
            lines.append(f"| {i} | {item['day']} | {item['kind']} | {lat} | {budget} "
                         f"| {'是' if item['suspected_timeout'] else '否'} "
                         f"| {_cell(item['text'], 90)} |")
        lines.append("")
        lines.append("> 「疑似气泡超时」= latency 达到这一行按 PR #16 新口径本该有的"
                     "气泡寿命（companion 按句长 30~90s、带选项 offer 120s，"
                     f"落账容差 {EXPIRY_TOLERANCE_S:.0f}s）：沉默是气泡到点被收走造成的，"
                     "不是用户拒绝。PR #16 之前的历史行 companion 气泡写死 180s，"
                     "按本判据同样会被标为超时——因为它们本来就是。"
                     "这类行里**已经**包含真实帮上忙的汇报——"
                     "「核完 DEVELOPMENT-PLAN 事实2…」与"
                     "「清了 Temp 里超过24小时的文件：C盘从 1.96G 回到 3.04G」"
                     "都是用户没回、事情却办成了的 ignored 行。"
                     "这就是「无回应不等于拒绝」的活证据："
                     "把这类行算成「没被接受」，分母就被污染了。")
    lines.append("")

    # 8. 结论
    lines.append("## 8. 一句话结论")
    lines.append("")
    lines.append(f"**{report['conclusion']}**")
    lines.append("")
    lines.append("提醒：")
    for caveat in report["caveats"]:
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────
def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sprite.proactive.outcome_report",
        description="开口质量的离线度量（只读；绝不写 perceive/）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--report", help="把报告写到这个路径（只写这一个路径）")
    parser.add_argument("--perceive", help="perceive 数据目录（默认自动解析）")
    parser.add_argument("--app", default="default",
                        help="stop_threshold(app) 用的前台应用名（默认 default）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    perceive_dir = Path(args.perceive) if args.perceive else default_perceive_dir()
    report = summarize(perceive_dir, app=args.app)

    if args.json:
        payload = {k: v for k, v in report.items() if k != "bucket_order"}
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = render_markdown(report)

    print(text)

    if args.report:
        target = Path(args.report)
        # 只读纪律：拒绝把报告写进 perceive/（那里是实时账本）
        if _inside(target, perceive_dir):
            print(f"\n拒绝写入 perceive/：{target}", file=sys.stderr)
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"\n报告：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
