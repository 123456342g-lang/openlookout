from __future__ import annotations

import json

from vista.benchmarks.desktop import chat_facts


def test_collect_caches_public_fact_and_recent_win(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_facts, "_public_fact", lambda now: "某位作家今天出生")
    monkeypatch.setattr(chat_facts, "daily_weather", lambda path, now: "今天东京天气：晴。")
    offers = tmp_path / "offers.jsonl"
    offers.write_text(json.dumps({"result": "auto_completed", "t_answer": 1_000,
                                  "report": "项目测试通过了"}, ensure_ascii=False) + "\n", encoding="utf-8")
    facts = chat_facts.collect(tmp_path / "facts.json", tmp_path / "weather.json", offers, now=10_000)
    assert facts["weather"]
    assert facts["public_fact"] == "某位作家今天出生"
    assert facts["recent_win"] == "项目测试通过了"


def test_planner_can_choose_non_weather_conversation(tmp_path):
    from vista.benchmarks.desktop.chat_planner import ChatPlanner

    planner = ChatPlanner(tmp_path / "chat.json")
    candidates = planner.candidates(
        idle_s=90, has_active_work=False, now=1_000_000,
        facts={"public_fact": "某位作家今天出生", "recent_win": "项目测试通过了"},
    )
    topics = {candidate.topic for candidate in candidates}
    assert {"curiosity", "small_win"} <= topics
    rendered = [planner.render(candidate, 1_000_000) for candidate in candidates]
    assert any("作家" in text or "测试通过" in text for text in rendered)
