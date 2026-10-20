"""Release guards: rate-limit give-up, text replies, prompt typos, speech leaks."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from sprite.proactive import help as helpmod
from vista.benchmarks.desktop import brain, session as sessionmod
from vista.benchmarks.desktop.profiles import SYSTEM
from vista.core.contracts import Visual


def test_429_stops_after_three_tries(monkeypatch):
    import urllib.error

    sleeps = []
    calls = []

    def fail(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(brain.ModelRateLimited):
        brain.model_response(object(), sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == list(brain.RATE_LIMIT_BACKOFF_S)


def test_rate_limit_notice_is_plain_language(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "PERCEIVE", tmp_path)
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    backend = type("Backend", (), {})()
    brain.arm_rate_limit(backend, now=10.0)
    row = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    say = row["speech"]["say"]
    assert say == brain.RATE_LIMIT_SAY
    assert "429" not in say
    assert backend.rate_limited_until == 10.0 + brain.RATE_LIMIT_COOLDOWN_S
    brain.arm_rate_limit(backend, now=20.0)
    assert backend.rate_limit_said is True
    assert backend.rate_limited_until == 20.0 + brain.RATE_LIMIT_COOLDOWN_S


def test_plain_text_reply_does_not_force_a_screenshot():
    base = dict(screen_due=False, window_due=False, timing_due=False, fb="",
                return_due=False, reply_due=True, now=1000.0, last_visual_turn=1000.0)
    assert brain.turn_wants_visual(**base, reply_text="帮我清理一下 C 盘") is False
    assert brain.turn_wants_visual(**base, reply_text="这个窗口怎么关不掉") is True
    assert brain.turn_wants_visual(**base) is True


def test_conversation_prompt_typos_are_gone(monkeypatch):
    monkeypatch.setattr("sprite.proactive.conversation.history", lambda limit=24: [])
    text = brain.conversation_fact(idle_s=3, now=1_700_000_000)
    for broken in ("接睢", "开丢", "下丢", "填这?", "GUIDE.md?"):
        assert broken not in text
    assert "旧事不当当前事实。" in text
    assert "自然开一个话题" in text


def test_profile_opens_as_an_assistive_partner():
    opening = SYSTEM.lstrip()
    assert opening.startswith("你是辅助型伙伴")
    assert "现场已变化" in SYSTEM
    assert "回收站" in opening.split("你是陪在用户身边", 1)[0]


def test_leaked_companion_line_is_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "offers.jsonl")
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "current.json")
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "JPEG")
    visual = Visual("screen", "leak-test", buffer.getvalue(), 32, 32, mime_type="image/jpeg")
    session = sessionmod.DesktopSession("陪伴", {}, visual=visual)
    reply = session._companion({
        "kind": "companion",
        "say": "Trae 想拿 PR #15 当证据，outcomes.jsonl 有 60 行",
        "topic": "协作",
        "confidence": 0.9,
    })
    assert "没有发给用户" in reply.text
    assert session.reports == []
    assert not (tmp_path / "offer.json").exists()
    current = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    blob = json.dumps(current, ensure_ascii=False)
    assert "PR #15" not in blob
    assert "outcomes.jsonl" not in blob
