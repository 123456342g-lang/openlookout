"""observe layer unit tests — run on Linux with fakes; no Windows APIs."""
from __future__ import annotations
import json
import time
from pathlib import Path
from observe.events import normalize_browser_payload, is_browser_error_code, extract_error_code
from observe.browser_ingest import ExtensionIngestState, ingest_extension_payload, drain_queue
from observe.eventlog import EventLog, dwell_signals, flicker_signals, browse_failures
from observe.capture_hook import NullCapture, TriggerRequest
from observe.vision_stub import NullVision, KeywordHeuristicVision


def test_normalize_url_nav_error():
    assert normalize_browser_payload({"kind": "url", "url": "https://example.com/a"})["type"] == "url"
    nav = normalize_browser_payload({"kind": "nav", "url": "https://example.com/b", "transition": "typed"})
    assert nav["type"] == "nav" and nav["transition"] == "typed"
    err = normalize_browser_payload({"kind": "browser_error", "url": "http://10.0.0.1/", "error": "net::ERR_EMPTY_RESPONSE"})
    assert err["type"] == "browser_error" and err["error"] == "ERR_EMPTY_RESPONSE"
    assert normalize_browser_payload({"kind": "url"}) is None  # no url


def test_error_code_helpers():
    assert is_browser_error_code("ERR_EMPTY_RESPONSE")
    assert extract_error_code("net::ERR_CONNECTION_REFUSED") == "ERR_CONNECTION_REFUSED"
    assert is_browser_error_code("This site can’t be reached")


def test_ingest_queues_typed_events():
    st = ExtensionIngestState()
    ingest_extension_payload(st, {"kind": "browser_error", "url": "http://x.test/", "error": "ERR_FAILED"})
    ingest_extension_payload(st, {"kind": "nav", "url": "http://x.test/ok", "title": "ok"})
    q = drain_queue(st)
    types = [e["type"] for e in q]
    assert "browser_error" in types and "nav" in types
    assert st.last_url == "http://x.test/ok"


def test_dwell_and_flicker(tmp_path):
    now = 1_800_000_000.0
    lines = []
    # long dwell on Word
    lines.append({"ts": now - 200, "type": "focus", "app": "word", "title": "报告.docx", "dur_s": 240})
    # flicker between excel and browser
    for i in range(10):
        app, title = (("excel", "Sheet"), ("google-chrome", "Docs"))[i % 2]
        lines.append({"ts": now - 90 + i * 5, "type": "focus", "app": app, "title": title, "dur_s": 2})
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    log = EventLog([p])
    ev = log.events(since=now - 1000)
    # stamp _t
    for e in ev:
        e["_t"] = e.get("_t") or now
    # re-read with proper ts parsing — use ISO
    lines2 = []
    from datetime import datetime, timezone
    def iso(t):
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    lines2.append({"ts": iso(now - 200), "type": "focus", "app": "word", "title": "报告.docx", "dur_s": 240})
    for i in range(10):
        app, title = (("excel", "Sheet"), ("google-chrome", "Docs"))[i % 2]
        lines2.append({"ts": iso(now - 90 + i * 5), "type": "focus", "app": app, "title": title, "dur_s": 2})
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in lines2) + "\n", encoding="utf-8")
    ev = EventLog([p]).events(types={"focus"})
    d = dwell_signals(ev, now=now, min_dwell_s=120)
    assert any(x["app"] == "word" and x["dwell_s"] >= 240 for x in d)
    f = flicker_signals(ev, now=now, window_s=180, min_switches=8, pair_min=4)
    assert f and f[0]["switches"] >= 4


def test_browse_failures_prefer_browser_error(tmp_path):
    now = time.time()
    from datetime import datetime, timezone
    def iso(t):
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
    lines = [
        {"ts": iso(now - 30), "type": "browser_error", "url": "http://192.0.2.10/x", "error": "ERR_EMPTY_RESPONSE"},
        {"ts": iso(now - 20), "type": "focus", "app": "google-chrome", "title": "192.0.2.10 - ERR_EMPTY_RESPONSE - Google Chrome", "dur_s": 5},
        {"ts": iso(now - 10), "type": "nav", "url": "http://example.com/"},  # success — not a failure
    ]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    ev = EventLog([p]).events()
    fails = browse_failures(ev, now=now, window_s=300)
    assert fails
    assert fails[0]["source"] == "browser_error"
    assert "ERR_EMPTY_RESPONSE" in fails[0]["codes"]
    assert fails[0]["host"] == "192.0.2.10"
    # no hardcoded user LAN from this test beyond what we put in the log
    assert not any("172.16.170.169" in json.dumps(f) for f in fails)


def test_capture_hook_not_a_loop():
    cap = NullCapture()
    assert cap.capture(TriggerRequest(reason="stalemate_dwell")) is None
    v = NullVision().judge_frame(b"")
    assert v.stuck is False
    h = KeywordHeuristicVision().judge_frame(b"", title="错误对话框")
    assert h.stuck is True
