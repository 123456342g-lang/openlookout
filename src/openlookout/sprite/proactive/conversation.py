"""Persistent conversation history for the sprite dialog.

The brain and the GUI have separate logs for observations, feedback, and
offers.  This module gives the user one readable timeline without making the
VISTA runtime depend on the GUI.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from ..i18n import t
from .perceive import DIR

LOG = DIR / "conversation.jsonl"


def append(role: str, text: str, *, kind: str = "message", source: str = "gui",
           event_id: str | None = None, t: float | None = None,
           reply_to: str | None = None) -> dict:
    value = str(text or "").strip()
    if not value:
        return {}
    if event_id:
        for old in _read(LOG):
            if old.get("id") == str(event_id) and old.get("source") == source:
                return old
    row = {
        "t": float(t if t is not None else time.time()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "text": value,
        "kind": kind,
        "source": source,
    }
    if event_id:
        row["id"] = str(event_id)
    if reply_to:
        row["reply_to"] = str(reply_to)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def history(limit: int = 80) -> list[dict]:
    """Return a time-ordered timeline, including logs written before this module."""
    rows = _read(LOG)
    # Once the GUI has started writing the unified log, its entries are the
    # source of truth. Only import legacy records that predate that log so a
    # completion is not shown twice (once from conversation.jsonl and once
    # from offers.jsonl).
    cutoff = min((float(r.get("t", 0) or 0) for r in rows), default=float("inf"))
    seen = {(r.get("source"), r.get("id"), r.get("kind"), r.get("t"), r.get("text")) for r in rows}

    feedback = DIR / "feedback.jsonl"
    for r in _read(feedback):
        item = {"t": r.get("t", 0), "role": "user", "text": r.get("text", ""),
                "kind": "feedback", "source": "feedback", "id": f"feedback:{r.get('t')}",
                "time": r.get("time") or _time_text(r.get("t", 0))}
        key = (item["source"], item["id"], item["kind"], item["t"], item["text"])
        if item["text"] and float(item["t"] or 0) < cutoff and key not in seen:
            rows.append(item); seen.add(key)

    offers = DIR / "offers.jsonl"
    for r in _read(offers):
        result = r.get("result")
        offer_id = str(r.get("id") or r.get("t") or "offer")
        text = str(r.get("text") or "").strip()
        if not text:
            continue
        if result == "shown":
            label = text
        elif result == "started":
            # 同意门之后：这是用户点了「好的」之后才出现的状态。
            label = t("started_hist", text=text)
        elif result == "expired":
            # 没等到答复就到期作废 —— 没动手，如实说没动手。
            label = t("expired_hist", text=text)
        elif result == "auto_started":
            label = t("started_hist", text=text)
        elif result == "auto_completed":
            label = str(r.get("report") or r.get("completion") or t("completed_hist", text=text))
        elif result == "auto_no_answer":
            # 进程正常退出、但这一段运行没有提交最终结论（旧词 auto_failed 的真实含义）。
            try:
                changes = int(r.get("mutations") or 0)
            except (TypeError, ValueError):
                changes = 0
            if r.get("report"):
                label = str(r["report"])
            elif changes:
                label = t("no_answer_mutations", n=changes)
            else:
                label = t("no_answer_clean")
        elif result == "auto_errored":
            label = str(r.get("report") or t("errored_hist"))
        elif result == "auto_failed":
            # 历史行：旧代码把「没提交结论」记成了 auto_failed，且没记 report/mutations。
            # 不把历史行重新解释成新语义，只给一句对当时两种情形都成立的文案。
            label = str(r.get("report") or t("stopped_hist"))
        elif result == "undone":
            label = t("undone_hist")
        else:
            continue
        item = {"t": r.get("t_answer", r.get("t", 0)), "role": "assistant", "text": label,
                "kind": r.get("kind", "offer"), "source": "offers",
                "id": f"offer:{offer_id}:{result}",
                "time": _time_text(r.get("t_answer", r.get("t", 0)))}
        key = (item["source"], item["id"], item["kind"], item["t"], item["text"])
        if float(item["t"] or 0) < cutoff and key not in seen:
            rows.append(item); seen.add(key)

    rows.sort(key=lambda r: float(r.get("t", 0) or 0))
    return rows[-max(1, int(limit)):]


def message_id(row: dict) -> str:
    return str(row.get("id") or f"message:{row.get('t')}")


def pending_message(rows: list[dict]) -> dict | None:
    latest_user = next((row for row in reversed(rows) if row.get("role") == "user"), None)
    if latest_user is None:
        return None
    identity = message_id(latest_user)
    for row in rows:
        if row.get("role") != "assistant" or row.get("kind") == "reply":
            continue
        if row.get("reply_to") == identity:
            return None
        if (not row.get("reply_to") and not latest_user.get("id")
                and float(row.get("t", 0)) > float(latest_user.get("t", 0))):
            return None
    return latest_user


def _time_text(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""

