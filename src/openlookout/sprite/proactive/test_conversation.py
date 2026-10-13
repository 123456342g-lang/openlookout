from __future__ import annotations

import json

from sprite.proactive import conversation


def test_history_imports_legacy_feedback_and_offer(tmp_path, monkeypatch):
    d = tmp_path / "perceive"
    d.mkdir()
    monkeypatch.setattr(conversation, "DIR", d)
    monkeypatch.setattr(conversation, "LOG", d / "conversation.jsonl")
    (d / "feedback.jsonl").write_text(json.dumps({"t": 1, "text": "别清理内存"}) + "\n", encoding="utf-8")
    (d / "offers.jsonl").write_text(json.dumps({"id": "o1", "t": 2, "text": "整理桌面", "kind": "offer", "result": "shown"}) + "\n", encoding="utf-8")

    rows = conversation.history()
    assert [(r["role"], r["text"]) for r in rows] == [("user", "别清理内存"), ("assistant", "整理桌面")]


def test_unified_log_prevents_duplicate_legacy_completion(tmp_path, monkeypatch):
    d = tmp_path / "perceive"
    d.mkdir()
    monkeypatch.setattr(conversation, "DIR", d)
    monkeypatch.setattr(conversation, "LOG", d / "conversation.jsonl")
    conversation.append("assistant", "已整理桌面", kind="action", event_id="o1:completed", t=10)
    (d / "offers.jsonl").write_text(json.dumps({"id": "o1", "t": 11, "text": "整理桌面", "kind": "offer", "result": "auto_completed", "report": "已整理桌面"}) + "\n", encoding="utf-8")

    rows = conversation.history()
    assert [r["text"] for r in rows] == ["已整理桌面"]


def test_append_deduplicates_replayed_offer_after_gui_restart(tmp_path, monkeypatch):
    d = tmp_path / "perceive"
    d.mkdir()
    monkeypatch.setattr(conversation, "DIR", d)
    monkeypatch.setattr(conversation, "LOG", d / "conversation.jsonl")
    conversation.append("assistant", "我看到了", event_id="offer-1")
    conversation.append("assistant", "我看到了", event_id="offer-1")
    assert len((d / "conversation.jsonl").read_text(encoding="utf-8").splitlines()) == 1

