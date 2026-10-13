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
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ── 口径：本模块自持的词表（不从 timing 导入，避免与并行改动耦合）────────────
# 新增/未知标签不会被丢：落在 unknown 类里，单独列出。
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

    # 4) 按天
    days = _day_summary(outcomes)
    report["days"] = days
    report["trend"] = trend_verdict(days)

    # 5) 提议侧（offers.jsonl）：kind × result + join 覆盖率
    offer_rows = data["offers.jsonl"]
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
            lines.append(f"  - 口径对齐：timing 读的就是本报告这份 outcomes.jsonl。")
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
