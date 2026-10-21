"""Words the user is allowed to see.

Internal judgment (activity, risk tiers, ledgers, tool names, prompt text)
stays on disk. Bubbles and the click-to-chat dialog only get a spoken line.
"""
from __future__ import annotations

import re

from ..i18n import LiveText, t

QUIET_DIALOG = LiveText("quiet_dialog")

_LEAK = re.compile(
    r"("
    r"desktop_[a-z0-9_]+"
    r"|basic_shell"
    r"|outcomes\.jsonl"
    r"|GUIDE\.md"
    r"|WORKING\.md"
    r"|permissions\.json"
    r"|coach:[A-Za-z0-9_-]+"
    r"|issue\s*#?\s*\d+"
    r"|\bPR\s*#?\s*\d+"
    r"|\b(?:low|medium|high)\s*风险"
    r"|风险批次"
    r"|风险的事"
    r"|心跳轮"
    r"|next_step"
    r"|\bCURRENT\b"
    r"|risk:(?:low|medium|high)"
    r"|现场已变化"
    r"|trim-[a-z0-9-]+"
    r")",
    re.IGNORECASE,
)

_SAFE_RECLAIM = ("临时文件", "临时目录", "缓存", "回收站")


def leaks_internal(text: str | None) -> bool:
    """True when this sentence would tell the user about our own machinery."""
    return bool(_LEAK.search(str(text or "")))


def dialog_status(current: dict | None) -> str:
    """Header for the click-to-chat dialog.

    Only a spoken line is eligible. Quiet turns, and any turn whose spoken
    line still contains internal words, become one fixed neutral sentence.
    ``activity``, ``state``, and ``next_step`` are never rendered.
    """
    if not isinstance(current, dict):
        return str(QUIET_DIALOG)
    speech = current.get("speech") if isinstance(current.get("speech"), dict) else {}
    kind = str(speech.get("kind") or current.get("kind") or "").strip()
    say = str(speech.get("say") or "").strip() or str(current.get("say") or "").strip()
    if kind == "quiet" or not say or leaks_internal(say):
        return str(QUIET_DIALOG)
    return say


def user_label(topic: str | None) -> str:
    """Short label safe to put in '我开始处理…'."""
    label = str(topic or "").strip()
    if not label or leaks_internal(label) or label.startswith("risk:"):
        return t("this_thing")
    return label


def offer_is_safe_reclaim(offer: dict | None) -> bool:
    """Temp, cache, or recycle-bin cleanup the user already nodded to.

    Batches with an explicit item list stay on that list. Anything else that
    is not this narrow cleanup still goes through the normal task runner.
    """
    if not isinstance(offer, dict) or offer.get("items"):
        return False
    text = f"{offer.get('text') or ''} {offer.get('topic') or ''}"
    return any(word in text for word in _SAFE_RECLAIM)
