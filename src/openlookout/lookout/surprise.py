"""V1 惊喜 / 潜在需求门控。

一张卡要同时满足：
1. 行为可量化（facts 里至少 2 个数值证据）
2. 潜在需求：用户自己说不出、也多半没察觉（有“行为与假设不一致”的信号）
3. 可构建且已验证的成品（verified/draft + artifacts）
4. 不是提醒、不是意料中的杂务、不是纯观察

惊喜分 = evidence_strength × latent_gap × (1 − expectedness)
低于阈值或触发硬拒绝 → 不出卡。
"""
from __future__ import annotations

from typing import Any

# ---- 硬拒绝：永远不是 V1 卡片 ----
REJECT_KINDS = {
    "site_rhythm",       # 节律提醒，定时机器人也能做
    "last_minute",       # 纯观察
    "duplicate_copies",  # 多半有意为之
}

# 世界雷达 / 创业机会 / 账本 —— 不是 V1 核心
REJECT_KINDS_PRODUCT = {
    "world_signal", "opportunity", "switch_tax", "agent_ledger",
}

# 默认视为“意料中的杂务”，除非另有潜在不一致信号
EXPECTED_CHORE_KINDS = {
    "recurring_files",   # “我每周交周报”用户自己知道
    "repeated_download", # “我下过好几次”通常知道
    "deadline",          # 笔记里写过的截止日
    "recurring_doc_focus",
    "window_thrash",
}

# 提醒类求解状态
REMINDER_STATUS = {"reminder_only", "omit", "failed", "skipped"}

MIN_SURPRISE = 0.35
MAX_CARDS = 3


def _numeric_facts(facts: dict) -> list[tuple[str, float]]:
    out = []
    for k, v in (facts or {}).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((k, float(v)))
    return out


def latent_signals(f: dict, result: dict | None = None) -> list[tuple[str, float]]:
    """返回 (信号名, 强度) 列表。空列表 = 没有潜在不一致，通常不出卡。"""
    k = f.get("kind", "")
    F = f.get("facts") or {}
    L = f.get("local") or {}
    sig: list[tuple[str, float]] = []

    if k == "manual_summary":
        cells = float(F.get("cells_differ") or 0)
        unexplained = float(F.get("rows_unexplained") or F.get("cells_unexplained") or 0)
        if cells > 0:
            # 用户以为手填汇总是对的；行为证据显示对不上
            sig.append(("summary_vs_detail_mismatch", min(3.0, 1.0 + cells / 20.0 + unexplained / 5.0)))

    if k == "version_sprawl" and F.get("final_is_not_newest"):
        sig.append(("named_final_is_stale", 1.6 + 0.1 * float(F.get("versions") or 0)))

    if k == "numbered_series":
        multi = float(F.get("episodes_with_multiple_files") or 0)
        styles = float(F.get("naming_styles") or 0)
        waste = max(0.0, float(F.get("deliverable_files") or 0) - float(F.get("episodes") or 0))
        if multi >= 2 and styles >= 2:
            # 用户以为“交作业”就完了；实际在为命名/多副本付流程税
            sig.append(("series_process_tax", min(3.0, 0.8 + multi * 0.25 + styles * 0.2 + waste * 0.1)))

    if k == "report_mismatch":
        sig.append(("hand_vs_source_mismatch", 1.8))

    if k == "numeric_drift":
        sig.append(("category_value_drift", 1.4))

    if k == "duplicate_charge":
        sig.append(("silent_double_charge", 2.0))

    if k == "price_change":
        sig.append(("silent_price_hike", 1.7))

    if k == "periodic_assembly":
        mins = float(F.get("avg_minutes") or 0)
        if mins >= 25 and float(F.get("occurrences") or 0) >= 2:
            # 周期性手工拼装：用户可能以为“本来就要花这么久”
            sig.append(("hidden_assembly_cost", min(2.5, mins / 30.0)))

    if k == "copy_paste_friction":
        pending = float(F.get("pending_docs") or 0)
        pastes = float(F.get("pastes") or 0)
        if pending > 0 and pastes >= 15:
            sig.append(("pending_form_backlog", min(2.2, 0.8 + pending * 0.3)))

    if k == "repeated_lookup":
        searches = float(F.get("searches") or 0)
        if searches >= 8:
            sig.append(("answer_not_captured", min(2.0, searches / 10.0)))

    # 重复下载：只有“磁盘上还堆着相同副本”才算潜在杂乱；全删光则无信号
    if k == "tool_stack_churn":
        agents = float(F.get("distinct_agents") or 0)
        days = float(F.get("active_days") or 0)
        if agents >= 2 and days >= 5:
            # 用户以为在“换更好的马”；漏掉的是可用新能力（worktree/默认模型换代）而不必再装代理
            sig.append(("agent_switch_without_new_capability", min(2.8, 0.7 + agents * 0.25 + days / 40.0)))

    if k == "openlookout_build":
        ev = float(F.get("ol_events") or 0)
        if ev >= 5:
            sig.append(("building_observer_product", min(2.5, 0.8 + ev / 80.0)))

    if k == "repeated_download" and not L.get("all_gone"):
        same = float(F.get("same_size_copies") or 0)
        if same >= 3 and float(F.get("times") or 0) >= 3:
            sig.append(("download_clutter", min(1.5, same / 4.0)))

    return sig


def expectedness(f: dict, signals: list[tuple[str, float]]) -> float:
    """0 = 完全意外，1 = 完全意料之中。"""
    k = f.get("kind", "")
    if k in REJECT_KINDS or k in REJECT_KINDS_PRODUCT:
        return 1.0
    if not signals:
        return 0.95
    if k in EXPECTED_CHORE_KINDS and not signals:
        return 0.95
    # 有潜在不一致信号 → 降低 expectedness
    base = {
        "manual_summary": 0.15,
        "version_sprawl": 0.25,
        "report_mismatch": 0.2,
        "numeric_drift": 0.3,
        "duplicate_charge": 0.2,
        "price_change": 0.25,
        "numbered_series": 0.35,
        "periodic_assembly": 0.4,
        "copy_paste_friction": 0.45,
        "repeated_lookup": 0.5,
        "repeated_download": 0.7,
        "recurring_files": 0.85,
    }.get(k, 0.6)
    # 信号越强，越不像“早知道”
    strength = sum(s for _, s in signals)
    return max(0.05, base - 0.08 * strength)


def evidence_strength(f: dict) -> float:
    nums = _numeric_facts(f.get("facts") or {})
    if len(nums) < 2:
        return 0.0
    # 有多个数值、且不全是 0/1 旗标
    nontrivial = [v for _, v in nums if abs(v) >= 2]
    return min(2.0, 0.4 * len(nums) + 0.15 * len(nontrivial))


def score_finding(f: dict, result: dict | None) -> dict[str, Any]:
    """给单条 finding + 求解结果打分。返回 gate 记录。"""
    k = f.get("kind", "")
    status = (result or {}).get("status", "omit")
    arts = (result or {}).get("artifacts") or []
    verify = (result or {}).get("verify_deid") or {}

    reasons: list[str] = []
    if k in REJECT_KINDS or k in REJECT_KINDS_PRODUCT:
        reasons.append(f"硬拒绝：类型 {k} 属于提醒/观察/非 V1 产品路径")
    if status in REMINDER_STATUS:
        reasons.append(f"硬拒绝：求解状态={status}（提醒或无法交付）")
    if status == "draft" and not arts:
        reasons.append("硬拒绝：draft 但没有成品文件")
    if status == "verified" and not arts:
        reasons.append("硬拒绝：verified 但没有成品文件")
    if verify.get("mode") == "observation_only":
        reasons.append("硬拒绝：observation_only")

    signals = latent_signals(f, result)
    if not signals:
        reasons.append("无潜在不一致信号（用户多半已知或只是例行）")

    ev = evidence_strength(f)
    if ev <= 0:
        reasons.append("行为证据不足（facts 数值 < 2）")

    exp = expectedness(f, signals)
    gap = sum(s for _, s in signals) if signals else 0.0
    surprise = round(ev * gap * (1.0 - exp), 3) if not reasons else 0.0

    # 必须可量化指标：从 facts 抽主指标
    metric = _primary_metric(f, signals)

    passed = (not reasons) and surprise >= MIN_SURPRISE and metric is not None
    if not passed and surprise < MIN_SURPRISE and not reasons:
        reasons.append(f"惊喜分 {surprise} < 阈值 {MIN_SURPRISE}")

    return {
        "id": f.get("id"),
        "kind": k,
        "passed": passed,
        "surprise": surprise if passed or surprise else 0.0,
        "evidence_strength": round(ev, 3),
        "latent_gap": round(gap, 3),
        "expectedness": round(exp, 3),
        "signals": [{"name": n, "strength": round(s, 3)} for n, s in signals],
        "metric": metric,
        "status": status,
        "n_artifacts": len(arts),
        "reject_reasons": reasons,
    }


def _primary_metric(f: dict, signals: list[tuple[str, float]]) -> dict | None:
    """每张卡必须带一个可量化主指标。"""
    F = f.get("facts") or {}
    k = f.get("kind", "")
    mapping = {
        "manual_summary": ("cells_differ", "手填汇总与明细不一致的格数", "格"),
        "version_sprawl": ("versions", "同文档并存版本数", "个"),
        "numbered_series": ("deliverable_files", "系列任务留下的报告文件数", "个"),
        "report_mismatch": ("occurrences", "数字对不上的次数", "次"),
        "numeric_drift": ("occurrences", "数值漂移观测点", "处"),
        "duplicate_charge": ("occurrences", "疑似重复扣费笔数", "笔"),
        "price_change": ("occurrences", "涨价观测", "次"),
        "periodic_assembly": ("avg_minutes", "每次手工拼装平均耗时", "分钟"),
        "copy_paste_friction": ("pastes", "跨应用粘贴次数", "次"),
        "repeated_lookup": ("searches", "同类反复搜索次数", "次"),
        "repeated_download": ("times", "同一文件下载次数", "次"),
        "tool_stack_churn": ("distinct_agents", "交替使用的 AI 编程代理数", "个"),
        "openlookout_build": ("ol_events", "OpenLookout 相关痕迹数", "条"),
    }
    if k == "manual_summary" and F.get("rows_unexplained"):
        return {"name": "rows_unexplained", "label": "规则解释不了、仍需核对的人次", "value": F["rows_unexplained"], "unit": "人次"}
    if k == "version_sprawl" and F.get("final_is_not_newest"):
        return {"name": "final_is_not_newest", "label": "名叫最终/final 却不是最新的版本数", "value": F.get("named_final") or 1, "unit": "个"}
    if k == "numbered_series":
        waste = max(0, int(F.get("deliverable_files") or 0) - int(F.get("episodes") or 0))
        return {"name": "extra_deliverables", "label": "超出期数的多余报告文件", "value": waste, "unit": "个",
                "extra": {"episodes_with_multiple_files": F.get("episodes_with_multiple_files"), "naming_styles": F.get("naming_styles")}}
    if k not in mapping:
        nums = _numeric_facts(F)
        if len(nums) < 2:
            return None
        name, val = max(nums, key=lambda x: abs(x[1]))
        return {"name": name, "label": name, "value": val, "unit": ""}
    key, label, unit = mapping[k]
    if key not in F:
        nums = _numeric_facts(F)
        if not nums:
            return None
        name, val = nums[0]
        return {"name": name, "label": label, "value": val, "unit": unit}
    return {"name": key, "label": label, "value": F[key], "unit": unit}


def gate(findings: list[dict], results: dict[str, dict], max_cards: int = MAX_CARDS,
         feedback_fn=None) -> dict[str, Any]:
    """对全部候选打分。ranking = surprise × feedback_mult × trend_boost。
    feedback_fn(f) -> (mult, hits)。趋势加成：结果里带 verified trends 则 ×1.4。
    """
    audits = []
    for f in findings:
        rid = f.get("id")
        res = results.get(rid) or {}
        a = score_finding(f, res)
        fb_mult, fb_hits = (1.0, [])
        if feedback_fn:
            fb_mult, fb_hits = feedback_fn(f)
        trends = res.get("trends") or []
        trend_boost = 1.4 if trends else 1.0
        # 有趋势但未通过基础门控：仍拒绝（不做新闻卡）
        ranking = round(a["surprise"] * fb_mult * trend_boost, 3) if a["passed"] else 0.0
        # 反馈 demote 极低时视为不通过展示
        if a["passed"] and fb_mult < 0.15:
            a["passed"] = False
            a["reject_reasons"] = list(a["reject_reasons"]) + [
                f"用户反馈降权（×{fb_mult}）：" + (fb_hits[0].get("reason") if fb_hits else "demote")
            ]
            ranking = 0.0
        a["feedback_mult"] = round(fb_mult, 3)
        a["feedback_hits"] = fb_hits
        a["trend_boost"] = trend_boost
        a["n_trends"] = len(trends)
        a["ranking"] = ranking
        audits.append(a)
    passed = [a for a in audits if a["passed"]]
    # 有趋势的优先，再比 ranking
    passed.sort(key=lambda a: (-(1 if a["n_trends"] else 0), -a["ranking"], -a["surprise"]))
    selected = passed[:max_cards]
    overflow = passed[max_cards:]
    return {
        "min_surprise": MIN_SURPRISE,
        "max_cards": max_cards,
        "audits": audits,
        "selected_ids": [a["id"] for a in selected],
        "overflow_ids": [a["id"] for a in overflow],
        "rejected_ids": [a["id"] for a in audits if not a["passed"]],
    }


SCORING_DOC = """
# 惊喜门控计分（V1）

## 硬拒绝（直接出局）
- 类型：site_rhythm / last_minute / duplicate_copies（提醒或纯观察）
- 类型：world_signal / opportunity / switch_tax / agent_ledger（非 V1 产品路径）
- 求解状态：reminder_only / omit / failed / observation_only
- 无成品文件

## 必须同时成立
1. **行为可量化**：facts 中至少 2 个数值字段 → evidence_strength > 0
2. **潜在不一致信号** latent_signals 非空，例如：
   - manual_summary：手填汇总与明细格数不一致
   - version_sprawl：名叫最终/final 的不是最新
   - numbered_series：多期多文件 + 多种命名写法（流程税）
   - report_mismatch / numeric_drift / duplicate_charge / price_change
   - periodic_assembly：平均 ≥25 分钟的周期性手工拼装
3. **惊喜分** = evidence_strength × latent_gap × (1 − expectedness) ≥ 0.35
4. **主指标** metric 可写出（用于卡片上的数字）

## 意料中的杂务（高 expectedness）
recurring_files / repeated_download（无堆积）/ deadline 等：即使用户有节律，也不算“没察觉的需求”。

## 每日上限
通过门控后按惊喜分排序，最多 3 张。
"""
