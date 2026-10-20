"""The second stale block of the same action is terminal."""
from vista.benchmarks.desktop.stale_guard import (
    FIRST_BLOCK,
    STALE_COOLDOWN_S,
    TERMINAL_BLOCK,
    action_key,
    note_stale_block,
    note_stale_success,
)


def test_second_block_tells_the_model_to_drop_the_plan():
    key = action_key("desktop_trim", {"pid": 4})
    state, first = note_stale_block({}, key, now=100.0)
    assert first == FIRST_BLOCK
    assert "新的 CURRENT" in first
    again, second = note_stale_block(state, key, now=130.0)
    assert second == TERMINAL_BLOCK
    assert "dropped" in second
    assert again[key]["count"] == 2
    assert state[key]["count"] == 1  # previous ledger untouched


def test_success_or_cooldown_clears_the_count():
    key = action_key("desktop_trim", {"pid": 4})
    state, _ = note_stale_block({}, key, now=100.0)
    cleared = note_stale_success(state, key)
    assert key not in cleared
    _, first_again = note_stale_block(state, key, now=100.0 + STALE_COOLDOWN_S + 1)
    assert first_again == FIRST_BLOCK


def test_a_different_action_does_not_inherit_the_count():
    trim = action_key("desktop_trim", {"pid": 4})
    other = action_key("desktop_trim", {"pid": 9})
    state, _ = note_stale_block({}, trim, now=100.0)
    _, text = note_stale_block(state, other, now=110.0)
    assert text == FIRST_BLOCK
