"""Read events.jsonl and derive observation signals (no screenshots).

Signals:
  dwell_signals   — same app+title held long with long dur_s (stuck / idle in one window)
  flicker_signals — rapid focus A↔B ping-pong (confused clicking / can't find control)
  browse_failures — nav/url/browser_error + weak focus-title ERR_* (never invents hosts)
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from .events import is_browser_error_code, extract_error_code

BROWSER_APP_RE = re.compile(
    r"chrome|msedge|edge|firefox|brave|opera|vivaldi|chromium|tabbit", re.I
)


def _parse_ts(raw) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def iter_events(path: Path, max_bytes: int = 2_000_000) -> Iterable[dict]:
    try:
        data = path.read_bytes()
    except OSError:
        return
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    text = data.decode("utf-8", "replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


@dataclass
class EventLog:
    paths: list[Path] = field(default_factory=list)

    @classmethod
    def from_home(cls, home: Path) -> "EventLog":
        home = Path(home)
        cands = [
            home / "events.jsonl",
            home.parent / "data" / "events.jsonl",
            home.parent / "data" / "pet" / "capture" / "events.jsonl",
            home / "capture" / "events.jsonl",
        ]
        try:
            cands.append(home.resolve().parent / "data" / "events.jsonl")
        except Exception:
            pass
        paths, seen = [], set()
        for c in cands:
            try:
                r = c.resolve()
            except Exception:
                r = c
            if r in seen:
                continue
            seen.add(r)
            if c.is_file():
                paths.append(c)
        return cls(paths)

    def events(self, types: set[str] | None = None, since: float | None = None) -> list[dict]:
        out = []
        for p in self.paths:
            for e in iter_events(p):
                if types and e.get("type") not in types:
                    continue
                t = _parse_ts(e.get("ts"))
                if since is not None and t is not None and t < since:
                    continue
                e = dict(e)
                e["_t"] = t
                out.append(e)
        out.sort(key=lambda e: e.get("_t") or 0)
        return out


def dwell_signals(
    events: list[dict],
    *,
    now: float,
    min_dwell_s: float = 120.0,
    window_s: float = 900.0,
) -> list[dict]:
    """Same foreground window held ≥ min_dwell_s inside window_s.

    Uses focus.dur_s when present; otherwise infers from consecutive focus gaps.
    """
    focus = [e for e in events if e.get("type") == "focus" and (e.get("_t") or 0) >= now - window_s]
    agg: dict[tuple, dict] = {}
    for e in focus:
        app = str(e.get("app") or "")
        title = str(e.get("title") or "")
        key = (app, title)
        dur = float(e.get("dur_s") or 0)
        slot = agg.setdefault(key, dict(app=app, title=title, dwell_s=0.0, hits=0, last_ts=e.get("_t") or 0))
        slot["dwell_s"] += max(dur, 0)
        slot["hits"] += 1
        slot["last_ts"] = max(slot["last_ts"], e.get("_t") or 0)
    out = [v for v in agg.values() if v["dwell_s"] >= min_dwell_s]
    out.sort(key=lambda x: -x["dwell_s"])
    return out[:20]


def flicker_signals(
    events: list[dict],
    *,
    now: float,
    window_s: float = 180.0,
    min_switches: int = 8,
    pair_min: int = 4,
) -> list[dict]:
    """Rapid focus ping-pong between two (or few) windows — user stuck hunting a control."""
    focus = [e for e in events if e.get("type") == "focus" and (e.get("_t") or 0) >= now - window_s]
    if len(focus) < min_switches:
        return []
    keys = [(str(e.get("app") or ""), str(e.get("title") or "")[:80]) for e in focus]
    pair_counts: dict[tuple, int] = defaultdict(int)
    for a, b in zip(keys, keys[1:]):
        if a == b:
            continue
        pair = tuple(sorted([a, b]))
        pair_counts[pair] += 1
    out = []
    for (a, b), n in pair_counts.items():
        if n >= pair_min:
            out.append(dict(
                a_app=a[0], a_title=a[1], b_app=b[0], b_title=b[1],
                switches=n, window_s=window_s,
            ))
    out.sort(key=lambda x: -x["switches"])
    return out[:10]


def browse_failures(
    events: list[dict],
    *,
    now: float,
    window_s: float = 900.0,
) -> list[dict]:
    """Real browse-failure signals from nav/url/browser_error; optional weak focus ERR_*.

    Does NOT invent hosts. Hosts only from event url/title. Prefer browser_error.
    """
    since = now - window_s
    agg: dict[str, dict] = {}

    def _host_from_url(url: str) -> str:
        if not url:
            return ""
        m = re.match(r"(?i)^(?:https?://)?([^/\s?#:]+)(?::\d+)?", url.strip())
        return (m.group(1).lower() if m else "").rstrip(".")

    for e in events:
        t = e.get("_t")
        if t is not None and t < since:
            continue
        typ = e.get("type")
        if typ == "browser_error":
            host = _host_from_url(str(e.get("url") or ""))
            code = str(e.get("error") or extract_error_code(str(e.get("message") or "")) or "ERR_FAILED")
            key = host or f"err:{code}"
            slot = agg.setdefault(key, dict(host=host, count=0, err=True, codes=[], urls=[], source="browser_error", last_ts=t or 0))
            slot["count"] += 1
            slot["err"] = True
            slot["last_ts"] = max(slot["last_ts"], t or 0)
            if code and code not in slot["codes"] and len(slot["codes"]) < 5:
                slot["codes"].append(code)
            u = e.get("url")
            if u and u not in slot["urls"] and len(slot["urls"]) < 3:
                slot["urls"].append(str(u)[:300])
        elif typ in ("nav", "url"):
            # Successful nav alone is not a failure; only keep if later paired — skip here.
            # (discoverers that need last URL use EventLog directly.)
            continue
        elif typ == "focus":
            app = str(e.get("app") or "")
            if not BROWSER_APP_RE.search(app):
                continue
            title = str(e.get("title") or "")
            if not is_browser_error_code(title):
                continue
            # Weak: title-only ERR — mark but source=focus_title (insufficient alone for "understood")
            code = extract_error_code(title) or "ERR_FAILED"
            url = e.get("url") or ""
            host = _host_from_url(str(url))
            key = host or f"focus:{code}:{hash(title) & 0xFFFF}"
            slot = agg.setdefault(key, dict(host=host, count=0, err=True, codes=[], urls=[], source="focus_title", last_ts=t or 0, titles=[]))
            slot["count"] += 1
            slot["last_ts"] = max(slot["last_ts"], t or 0)
            if code not in slot["codes"]:
                slot["codes"].append(code)
            if title and title not in slot["titles"] and len(slot["titles"]) < 3:
                slot["titles"].append(title[:120])
            if url and url not in slot["urls"]:
                slot["urls"].append(str(url)[:300])

    # Prefer real browser_error; keep focus_title only if no stronger signal for same host
    strong_hosts = {v["host"] for v in agg.values() if v.get("source") == "browser_error" and v.get("host")}
    out = []
    for v in agg.values():
        if v.get("source") == "focus_title" and v.get("host") and v["host"] in strong_hosts:
            continue
        out.append(v)
    out.sort(key=lambda x: (0 if x.get("source") == "browser_error" else 1, -x["count"], -x["last_ts"]))
    return out[:20]
