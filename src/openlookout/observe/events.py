"""Typed observation events for events.jsonl.

Primary channel is the operation log (focus / file_* / clipboard / nav / url / browser_error).
Screenshots are never an event type here — see capture_hook for triggered backup eyes.

Event types added for browse failures (beyond legacy focus/file/clipboard):
  nav            — navigation committed (url + optional transition)
  url            — active tab URL report (legacy extension kind, also emitted as typed event)
  browser_error  — navigation / load failure with chrome-style code (ERR_*) or HTTP empty

No user-specific hosts are hardcoded. Hosts come only from live events.
"""
from __future__ import annotations
import re
from typing import Any

EVENT_TYPES = frozenset({
    "focus", "file_open", "file_save", "clipboard", "form_edit",
    "nav", "url", "browser_error",
})

# Chrome / Chromium / Edge net error codes (and common localized phrases as secondary).
BROWSER_ERR_CODE_RE = re.compile(
    r"(?i)\b("
    r"ERR_[A-Z0-9_]+|"
    r"NS_ERROR_[A-Z0-9_]+|"
    r"net::ERR_[A-Z0-9_]+"
    r")\b"
)
BROWSER_ERR_PHRASE_RE = re.compile(
    r"(?i)Empty Response|This site can.?t be reached|无法访问|无法正常运作|"
    r"未发送任何|连接已重置|拒绝连接|Timed out|ERR_EMPTY|ERR_CONNECTION|"
    r"ERR_TUNNEL|ERR_PROXY|ERR_NAME|ERR_ADDRESS|ERR_TIMED_OUT|ERR_FAILED"
)


def is_browser_error_code(text: str) -> bool:
    if not text:
        return False
    return bool(BROWSER_ERR_CODE_RE.search(text) or BROWSER_ERR_PHRASE_RE.search(text))


def extract_error_code(text: str) -> str:
    """Return canonical ERR_* / NS_ERROR_* if present, else empty."""
    if not text:
        return ""
    m = BROWSER_ERR_CODE_RE.search(text)
    if not m:
        return ""
    code = m.group(1)
    if code.lower().startswith("net::"):
        code = code[5:]
    return code.upper() if code.upper().startswith("ERR_") else code


def normalize_browser_payload(payload: dict) -> dict | None:
    """Map extension POST body → one events.jsonl dict (without ts).

    Accepted kinds from the extension:
      url / nav / browser_error / form_edit
    Returns None if payload is unusable.
    """
    if not isinstance(payload, dict):
        return None
    kind = (payload.get("kind") or payload.get("type") or "").strip().lower()
    if kind in ("navigation", "navigate", "committed"):
        kind = "nav"
    if kind in ("error", "webnav_error", "load_error"):
        kind = "browser_error"
    if kind not in ("url", "nav", "browser_error", "form_edit"):
        return None

    out: dict[str, Any] = {"type": kind if kind != "form_edit" else "form_edit"}
    url = payload.get("url") or payload.get("href")
    if url:
        out["url"] = str(url)[:2000]
    title = payload.get("title")
    if title:
        out["title"] = str(title)[:300]
    app = payload.get("app")
    if app:
        out["app"] = str(app)[:80]
    tab_id = payload.get("tab_id") or payload.get("tabId")
    if tab_id is not None:
        try:
            out["tab_id"] = int(tab_id)
        except (TypeError, ValueError):
            pass

    if kind == "nav":
        for k in ("transition", "frame_id", "parent_frame_id"):
            if payload.get(k) is not None:
                out[k] = payload[k]
        return out if out.get("url") else None

    if kind == "url":
        return out if out.get("url") else None

    if kind == "browser_error":
        code = payload.get("error") or payload.get("code") or payload.get("error_code") or ""
        code = str(code).strip()
        if code.lower().startswith("net::"):
            code = code[5:]
        if not code and title:
            code = extract_error_code(str(title))
        if not code and url and is_browser_error_code(str(url)):
            code = extract_error_code(str(url))
        # Accept phrase-only failures (e.g. empty response page) when URL present
        phrase = payload.get("message") or payload.get("phrase") or title or ""
        if not code and is_browser_error_code(str(phrase)):
            code = extract_error_code(str(phrase)) or "ERR_FAILED"
        if not code and not out.get("url"):
            return None
        out["error"] = code or "ERR_FAILED"
        if phrase:
            out["message"] = str(phrase)[:300]
        return out

    # form_edit
    out["field_label"] = str(payload.get("field_label") or "")[:60]
    out["via"] = payload.get("via")
    return out if out.get("url") or out.get("field_label") else None
