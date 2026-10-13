from __future__ import annotations

from datetime import datetime

from vista.benchmarks.desktop.chat_planner import ChatPlanner


def test_chat_planner_is_quiet_when_user_is_away_or_work_is_active(tmp_path):
    p = ChatPlanner(tmp_path / "chat.json")
    assert p.choose(idle_s=301, has_active_work=False, now=1000) is None
    assert p.choose(idle_s=30, has_active_work=True, now=2000) is None


def test_chat_planner_has_budget_and_cooldown(tmp_path):
    p = ChatPlanner(tmp_path / "chat.json")
    c = p.choose(idle_s=90, has_active_work=False, now=1_000_000)
    assert c is not None
    p.mark_shown(c.topic, 1_000_000)
    assert p.choose(idle_s=90, has_active_work=False, now=1_000_100) is None
    c2 = p.choose(idle_s=90, has_active_work=False, now=1_001_000)
    assert c2 is not None
    p.mark_shown(c2.topic, 1_001_000)
    assert p.choose(idle_s=90, has_active_work=False, now=1_002_000) is None


def test_chat_planner_learns_dismissal_and_renders_friend_message(tmp_path):
    p = ChatPlanner(tmp_path / "chat.json")
    p.sync([{"id": "x", "topic": "check_in", "kind": "companion", "result": "dismissed", "t": 1}])
    c = p.choose(idle_s=90, has_active_work=False, now=2_000_000)
    assert c is not None
    assert p.render(c)
    assert "用户在" not in p.render(c)

