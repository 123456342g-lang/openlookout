"""Small, cached weather service used by the proactive conversation lane.

The model can still call ``basic_weather`` when it needs a different place.
This module only supplies a low-cost daily fact for the companion's ordinary
morning/idle conversation, and stays silent when the public service is down.
"""
from __future__ import annotations

import json
import os
import asyncio
import time
from pathlib import Path

from .actions import basic_weather


def infer_location() -> tuple[str, bool]:
    """Return only a location explicitly configured by the user."""
    for key in ("OPENLOOKOUT_WEATHER_LOCATION", "SPRITE_WEATHER_LOCATION"):
        value = os.environ.get(key, "").strip()
        if value:
            return value[:80], True
    return "", False


def location_source() -> str:
    """Describe the source used for automatic location without exposing coordinates."""
    place, _ = infer_location()
    if place:
        return "explicit"
    if os.name != "nt":
        return "unavailable"
    try:
        from winrt.windows.devices.geolocation import Geolocator
        return "windows" if Geolocator else "unavailable"
    except ImportError:
        try:
            from winsdk.windows.devices.geolocation import Geolocator
            return "windows" if Geolocator else "unavailable"
        except ImportError:
            return "unavailable"


def _windows_coordinates() -> tuple[float, float] | None:
    """Read coarse coordinates only when Windows location permission allows it.

    The optional ``winrt``/``winsdk`` packages are deliberately not required
    for installation. If Windows denies access, return no location instead of
    guessing from a network exit or timezone.
    """
    if os.name != "nt":
        return None
    try:
        try:
            from winrt.windows.devices.geolocation import Geolocator
        except ImportError:
            from winsdk.windows.devices.geolocation import Geolocator

        async def read():
            position = await Geolocator().get_geoposition_async()
            point = position.coordinate.point.position
            return float(point.latitude), float(point.longitude)

        return asyncio.run(asyncio.wait_for(read(), timeout=3.0))
    except Exception:
        return None


def _summary(payload: dict, inferred: bool) -> str:
    current = payload.get("current") or {}
    today = payload.get("today") or {}
    location = str(payload.get("location") or "").strip()
    coordinate_label = _looks_like_coordinates(location)
    if "," in location and not coordinate_label:
        location = location.split(",", 1)[0].strip()
    if not location or coordinate_label:
        location = "当前位置附近"
    temp = current.get("temperature_2m")
    apparent = current.get("apparent_temperature")
    high, low = today.get("temperature_2m_max"), today.get("temperature_2m_min")
    rain = today.get("precipitation_probability_max")
    bits = []
    if temp is not None:
        bits.append(f"现在约 {temp}°C")
    if apparent is not None and apparent != temp:
        bits.append(f"体感 {apparent}°C")
    if high is not None or low is not None:
        bits.append(f"今天 {low or '?'}~{high or '?'}°C")
    if rain is not None:
        bits.append(f"降水概率 {rain}%")
    if not bits:
        return ""
    return f"今天{location or '当前位置附近'}天气：" + "，".join(bits) + "。"


def _looks_like_coordinates(value: str) -> bool:
    try:
        lat, lon = (float(x.strip()) for x in value.split(",", 1))
        return -90 <= lat <= 90 and -180 <= lon <= 180
    except (TypeError, ValueError):
        return False


def fetch(location: str | None = None) -> str:
    place, inferred = (location.strip(), False) if location else infer_location()
    try:
        if place:
            reply = basic_weather({"location": place})
        else:
            coords = _windows_coordinates()
            if not coords:
                return ""
            reply = basic_weather({"latitude": coords[0], "longitude": coords[1]})
            inferred = True
        if not reply.success:
            return ""
        payload = json.loads(reply.text)
        return _summary(payload, inferred)
    except Exception:
        return ""


def daily(path: Path, now: float | None = None) -> str:
    """Fetch once per local day and cache only the short human-facing fact."""
    now = time.time() if now is None else float(now)
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    path = Path(path)
    cached = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        cached = None
    if isinstance(cached, dict) and cached.get("schema") == 2 and cached.get("day") == day and isinstance(cached.get("text"), str):
        checked = float(cached.get("location_checked", 0) or 0)
        if now - checked < 1800:
            return cached["text"]

    current_place, _ = infer_location()
    if isinstance(cached, dict) and cached.get("schema") == 2 and (cached.get("day") == day
                                     and cached.get("location", "") == current_place
                                     and isinstance(cached.get("text"), str)):
        cached["location_checked"] = now
        try:
            path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return cached["text"]
    text = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps({"schema": 2, "day": day, "text": text, "location": current_place,
                                   "location_checked": now}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return text
