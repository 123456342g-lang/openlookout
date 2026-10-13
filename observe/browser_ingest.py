"""Browser-extension ingest: platform-agnostic conversion of POSTs → typed events.

The Windows recorder (`record_win.py`) and Linux recorder share this logic so
nav / url / browser_error land in events.jsonl the same way.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Callable
from .events import normalize_browser_payload


@dataclass
class ExtensionIngestState:
    """Shared state for the local extension HTTP receiver."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    url_by_title: dict = field(default_factory=dict)
    last_url: str | None = None
    queue: list = field(default_factory=list)  # pending typed events (dicts without forced ts)


def ingest_extension_payload(st: ExtensionIngestState, payload: dict, emit: Callable | None = None) -> dict | None:
    """Normalize payload, update url map, optionally emit immediately.

    emit(event_dict) — if provided, called under st.lock with a ready event
    (caller may inject ts). Returns the normalized event or None.
    """
    ev = normalize_browser_payload(payload or {})
    if not ev:
        return None
    with st.lock:
        if ev.get("type") in ("url", "nav") and ev.get("url"):
            title = ev.get("title") or ""
            if title:
                st.url_by_title[title] = ev["url"]
            st.last_url = ev["url"]
        if ev.get("type") == "browser_error" and ev.get("url"):
            # Keep last failing URL discoverable for focus-title join
            st.last_url = ev["url"]
        if emit:
            emit(dict(ev))
        else:
            st.queue.append(dict(ev))
    return ev


def drain_queue(st: ExtensionIngestState) -> list:
    with st.lock:
        q, st.queue = st.queue, []
    return q
