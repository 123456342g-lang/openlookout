from __future__ import annotations

import json

from vista.benchmarks.desktop import weather
from vista.core.contracts import ToolReply


def _reply(**overrides):
    payload = {
        "ok": True,
        "location": "上海, Shanghai, China",
        "current": {"temperature_2m": 22, "apparent_temperature": 21},
        "today": {"temperature_2m_min": 16, "temperature_2m_max": 25,
                   "precipitation_probability_max": 20},
    }
    payload.update(overrides)
    return ToolReply(json.dumps(payload, ensure_ascii=False))


def test_fetch_uses_explicit_location(monkeypatch):
    monkeypatch.setattr(weather, "infer_location", lambda: ("上海", False))
    monkeypatch.setattr(weather, "basic_weather", lambda args: _reply())
    text = weather.fetch()
    assert "今天上海天气" in text
    assert "22°C" in text
    assert "降水概率 20%" in text


def test_fetch_is_silent_when_provider_fails(monkeypatch):
    monkeypatch.setattr(weather, "basic_weather", lambda args: ToolReply("{}", success=False))
    assert weather.fetch("上海") == ""


def test_infer_location_never_uses_network_or_timezone(monkeypatch):
    monkeypatch.delenv("OPENLOOKOUT_WEATHER_LOCATION", raising=False)
    monkeypatch.delenv("SPRITE_WEATHER_LOCATION", raising=False)
    monkeypatch.setattr(weather, "_ip_location", lambda: (_ for _ in ()).throw(AssertionError())) if hasattr(weather, "_ip_location") else None
    assert weather.infer_location() == ("", False)


def test_fetch_uses_windows_coordinates_without_guessing_city(monkeypatch):
    monkeypatch.setattr(weather, "infer_location", lambda: ("", False))
    monkeypatch.setattr(weather, "_windows_coordinates", lambda: (31.23, 121.47))
    monkeypatch.setattr(weather, "basic_weather", lambda args: _reply(
        location="31.23,121.47", timezone="Asia/Shanghai"))
    text = weather.fetch()
    assert "今天当前位置附近天气" in text


def test_daily_cache_avoids_second_network_call(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(weather, "fetch", lambda: calls.append(1) or "今天当前位置附近天气：现在约 22°C。")
    path = tmp_path / "weather.json"
    first = weather.daily(path, now=1_700_000_000)
    second = weather.daily(path, now=1_700_000_100)
    assert first == second
    assert len(calls) == 1
