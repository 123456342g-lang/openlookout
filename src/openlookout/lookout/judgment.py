"""Evidence-weighted decisions for the companion loop.

User feedback is one observation in the ledger. It can change confidence and
timing, but it cannot install a rule or permanently suppress a candidate.
"""
from __future__ import annotations

from collections import Counter


def _evidence_strength(item: dict) -> float:
    evidence = item.get("evidence") or {}
    score = float(evidence.get("score") or item.get("score") or 0)
    repetitions = float(evidence.get("repetitions") or evidence.get("observations") or 0)
    external = evidence.get("external") or {}
    verified = bool((external.get("verified") or {}).get("ok"))
    strength = min(0.65, score / 50) + min(0.2, repetitions / 10)
    if verified:
        strength += 0.15
    return min(1.0, strength)


def decide(item: dict, feedback: list[dict] | None = None) -> dict:
    """Return an independent decision without mutating the candidate."""
    rows = [row for row in (feedback or []) if row.get("id") == item.get("id")]
    counts = Counter(row.get("action") for row in rows)
    strength = _evidence_strength(item)
    positive = counts["useful"]
    negative = counts["not_relevant"]
    conflict = positive and negative
    confidence = strength + min(0.12, positive * 0.04) - min(0.18, negative * 0.06)
    confidence = max(0.0, min(1.0, confidence))
    if conflict:
        state = "ask"
        reason = "证据和反馈方向不一致，先问清楚你当前真正要解决的事。"
    elif confidence >= 0.62:
        state = "act"
        reason = "证据足够集中，可以先做一个可回退的辅助动作。"
    elif confidence >= 0.30:
        state = "watch"
        reason = "有迹象但还不够确定，继续观察结果，不打扰你。"
    else:
        state = "quiet"
        reason = "目前证据太弱，暂不打扰。"
    return {
        "state": state,
        "confidence": round(confidence, 2),
        "reason": reason,
        "feedback_counts": dict(counts),
        "evidence_strength": round(strength, 2),
    }
