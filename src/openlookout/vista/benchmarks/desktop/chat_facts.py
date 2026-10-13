"""Legacy daily fact experiment, no longer used by the live brain.

This is deliberately separate from the visual loop: the visual model decides
whether a topic matters, while this module quietly gathers a few public facts
that make a chosen opening feel like a real conversation.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .weather import daily as daily_weather


def _public_fact(now: float) -> str:
    tm = time.localtime(now)
    url = f"https://zh.wikipedia.org/api/rest_v1/feed/onthisday/births/{tm.tm_mon}/{tm.tm_mday}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "OpenLookout/1.0"})
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        rows = data.get("births") or []
        for row in rows:
            text = " ".join(str(row.get("text") or "").split())
            if text and len(text) <= 120:
                return text
    except Exception:
        pass
    return ""


def _recent_win(path: Path, now: float) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines[-80:]):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("result") != "auto_completed":
            continue
        if now - float(row.get("t_answer", row.get("t", 0)) or 0) > 3 * 86400:
            break
        report = str(row.get("report") or row.get("text") or "").strip()
        if report and len(report) <= 180:
            return report
    return ""


def collect(path: Path, weather_path: Path, offers_path: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    path = Path(path)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("day") == day and isinstance(cached, dict):
            facts = dict(cached)
        else:
            facts = {"day": day}
    except (OSError, ValueError, TypeError):
        facts = {"day": day}

    if not facts.get("weather"):
        facts["weather"] = daily_weather(weather_path, now)
    if not facts.get("public_fact"):
        facts["public_fact"] = _public_fact(now)
    facts["recent_win"] = _recent_win(Path(offers_path), now)
    local = datetime.fromtimestamp(now)
    facts["time"] = local.strftime("%H:%M")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return facts
