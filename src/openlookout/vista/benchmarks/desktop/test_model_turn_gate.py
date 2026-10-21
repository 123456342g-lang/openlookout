"""Idle must not call the model.

A missing thumbnail used to count as a screen change, and startup always ran
an INITIAL turn. Together those were about eight HTTP calls in the first half
minute on a machine where nothing had happened.
"""
from __future__ import annotations

import inspect

from vista.benchmarks.desktop import brain


def test_missing_thumbnail_is_not_a_screen_change():
    assert brain.changed(None, [0, 1, 2]) is False
    assert brain.changed([0, 1, 2], None) is False
    assert brain.changed([], [0, 1, 2]) is False
    same = [10] * 48
    assert brain.changed(same, list(same)) is False
    assert brain.changed([0] * 48, [255] * 48) is True


def test_model_turn_due_is_false_until_a_real_trigger():
    assert brain.model_turn_due() is False
    assert brain.model_turn_due(screen_due=True) is True
    assert brain.model_turn_due(reply_due=True) is True
    assert brain.model_turn_due(feedback="用户刚刚对你说了话") is True
    assert brain.model_turn_due(maintenance_due=True) is True
    assert brain.model_turn_due(goal_due=True) is True


def test_run_does_not_wake_on_heartbeat_or_history():
    src = inspect.getsource(brain.run)
    start = src.index("if not model_turn_due(")
    gate = src[start:src.index("):", start)]
    assert "heartbeat_due" not in gate
    assert "history_due" not in gate
    assert "screen_due=screen_due" in gate
    assert "reply_due=reply_due" in gate
    assert "DirectReply(boundary=None)" in src
