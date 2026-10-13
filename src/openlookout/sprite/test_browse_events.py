"""browser_error in events.jsonl must surface via network.parse_browse_signals."""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path
from sprite.scenarios import network as N


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def test_parse_browser_error_event(tmp_path):
    now = time.time()
    p = tmp_path / "events.jsonl"
    rows = [
        {"ts": iso(now - 10), "type": "browser_error", "url": "http://198.51.100.7/api", "error": "ERR_EMPTY_RESPONSE"},
        {"ts": iso(now - 5), "type": "nav", "url": "http://example.com/"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    sigs = N.parse_browse_signals([p], now_ts=now, window_s=300)
    assert sigs
    assert sigs[0].get("err") is True
    assert sigs[0].get("host") == "198.51.100.7"
    assert sigs[0].get("source") == "browser_error"
    assert "172.16.170.169" not in json.dumps(sigs)
