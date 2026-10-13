from __future__ import annotations

from pathlib import Path

import pytest

from .decision_engine import Candidate, DecisionEngine


def candidate(candidate_id: str, **overrides) -> Candidate:
    values = {
        "candidate_id": candidate_id,
        "lane": "help",
        "goal_id": "goal",
        "evidence": 1.0,
        "confidence": 1.0,
        "impact": 0.5,
        "urgency": 0.2,
        "blocker_relief": 0.2,
        "information_gain": 0.0,
        "success_probability": 0.8,
        "action_cost": 0.1,
        "interruption_cost": 0.1,
        "risk": 0.0,
        "reversibility": 1.0,
        "downstream_value": 0.0,
        "novelty": 0.0,
    }
    values.update(overrides)
    return Candidate(**values)


def test_blocking_disk_problem_beats_cosmetic_memory_maintenance():
    engine = DecisionEngine()
    disk = candidate(
        "disk-blocker",
        goal_id="finish-download",
        impact=1.0,
        urgency=1.0,
        blocker_relief=1.0,
        success_probability=0.9,
    )
    memory = candidate(
        "memory-tidy",
        lane="maintenance",
        goal_id="none",
        impact=0.1,
        urgency=0.05,
        blocker_relief=0.0,
        success_probability=0.9,
    )

    decision = engine.choose([memory, disk])

    assert decision.selected is disk
    assert decision.status == "act"


def test_high_memory_without_user_impact_is_waited_on():
    engine = DecisionEngine()
    memory = candidate(
        "memory-tidy",
        lane="maintenance",
        impact=0.05,
        urgency=0.0,
        blocker_relief=0.0,
        information_gain=0.0,
        interruption_cost=0.7,
    )

    decision = engine.choose([memory])

    assert decision.status == "wait"
    assert decision.selected is None


def test_low_cost_information_probe_can_beat_low_value_chat():
    engine = DecisionEngine()
    probe = candidate(
        "inspect-next-step",
        lane="investigate",
        information_gain=1.0,
        downstream_value=1.0,
        novelty=1.0,
        action_cost=0.05,
        interruption_cost=0.05,
    )
    chat = candidate(
        "small-talk",
        lane="conversation",
        impact=0.1,
        success_probability=0.8,
        interruption_cost=0.5,
    )

    decision = engine.choose([chat, probe])

    assert decision.selected is probe
    assert decision.status == "investigate"


def test_irreversible_risky_action_is_suppressed_even_with_high_impact():
    engine = DecisionEngine()
    risky = candidate(
        "delete-files",
        impact=1.0,
        urgency=1.0,
        blocker_relief=1.0,
        risk=1.0,
        reversibility=0.0,
    )

    decision = engine.choose([risky])

    assert decision.status == "wait"
    assert decision.selected is None


def test_weak_evidence_does_not_trigger_action():
    engine = DecisionEngine()
    uncertain = candidate(
        "guess",
        evidence=0.1,
        confidence=0.1,
        impact=1.0,
        urgency=1.0,
        blocker_relief=1.0,
    )

    decision = engine.choose([uncertain])

    assert decision.status == "wait"
    assert decision.selected is None


def test_explicit_outcomes_update_prior_and_duplicates_are_ignored():
    engine = DecisionEngine()

    assert engine.record_outcome("task", "success", event_id="e1")
    assert not engine.record_outcome("task", "success", event_id="e1")
    assert engine.record_outcome("task", "failure", event_id="e2")

    stats = engine.stats["task"]
    assert stats.attempts == 2
    assert stats.successes == 1
    assert stats.failures == 1
    assert stats.dismissals == 0


def test_success_and_failure_change_future_ranking():
    engine = DecisionEngine()
    first = candidate("first", impact=0.6, success_probability=0.5)
    second = candidate("second", impact=0.6, success_probability=0.5)

    assert engine.choose([first, second]).selected is first
    engine.record_outcome("first", "failure", event_id="failure-1")
    assert engine.choose([first, second]).selected is second
    engine.record_outcome("first", "success", event_id="success-1")
    assert engine.stats["first"].attempts == 2


def test_save_and_load_preserve_learning_state(tmp_path: Path):
    path = tmp_path / "decision-state.json"
    engine = DecisionEngine(path)
    engine.record_outcome("task", "success", event_id="e1")
    engine.total_decisions = 4
    engine.save()

    restored = DecisionEngine.load(path)

    assert restored.total_decisions == 4
    assert restored.stats["task"].successes == 1
    assert restored.seen_outcomes == {"e1"}


def test_invalid_outcome_is_rejected():
    with pytest.raises(ValueError):
        DecisionEngine().record_outcome("task", "unknown", event_id="e1")


def test_novelty_without_a_decision_to_improve_does_not_reward_research():
    engine = DecisionEngine()
    probe = candidate("irrelevant-research", lane="investigate", impact=0, urgency=0,
                      blocker_relief=0, information_gain=1, downstream_value=0, novelty=1)
    decision = engine.choose([probe])
    assert decision.selected is None
    assert decision.score.information_value == 0
    assert decision.score.uncertainty_bonus == 0
