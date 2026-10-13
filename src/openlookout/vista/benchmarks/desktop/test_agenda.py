from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from vista.core.contracts import ToolReply, Visual
from .agenda import Agenda
from .decision_engine import DecisionEngine
from .session import DesktopSession
from . import actions, brain


TOOLS = {"read_trace", "inspect_output", "change_setting"}


def goal(goal_id="unknown-workflow", **overrides):
    values = {
        "goal_id": goal_id, "goal": "Determine why the repeated export changes the result",
        "lane": "investigate", "evidence": ["operation trace: three exports, two different outputs"],
        "expected": "Distinguish stale input from an export setting mismatch",
        "state": "ready", "estimates": {"confidence": 0.8, "impact": 0.8},
        "action": {"tool": "read_trace", "arguments": {"section": "exports"}},
    }
    values.update(overrides)
    return values


def test_unknown_workflow_can_explore_without_registering_a_goal():
    agenda = Agenda(DecisionEngine())
    assert agenda.claim("read_trace", {"section": "unknown"}, mutation=False) is None
    assert not agenda.goals


def test_evidence_can_redirect_an_arbitrary_goal_without_a_domain_branch():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal()], TOOLS)
    claim = agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    agenda.record(claim, "read_trace", "Both exports read the same input; their settings differ",
                  success=True, mutation=False)
    agenda.update([goal(
        goal="Check the setting mismatch rather than the input",
        evidence=["read_trace result: same input, different settings"],
        action={"tool": "inspect_output", "arguments": {"setting": "units"}},
    )], TOOLS)
    assert agenda.claim("inspect_output", {"setting": "units"}, mutation=False) == ("unknown-workflow", "action")


def test_score_does_not_prevent_a_newly_justified_action():
    agenda = Agenda(DecisionEngine())
    agenda.update([
        goal("old", estimates={"confidence": 1, "impact": 1, "urgency": 1}),
        goal("new", action={"tool": "inspect_output", "arguments": {}},
             estimates={"confidence": 0.1, "impact": 0.1}),
    ], TOOLS)
    assert agenda.selected().goal_id == "old"
    assert agenda.claim("inspect_output", {}, mutation=False) == ("new", "action")


def test_waiting_does_not_block_independent_exploration_or_erase_other_goals():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal("blocked", state="waiting", waiting_on="The remote export has not finished")], TOOLS)
    agenda.update([goal("available")], TOOLS)
    assert agenda.selected().goal_id == "available"
    assert agenda.goals["blocked"].state == "waiting"
    assert agenda.claim("inspect_output", {}, mutation=False) is None


def test_results_are_attributed_only_to_the_matching_goal():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal("first"), goal("second", action={"tool": "inspect_output", "arguments": {}})], TOOLS)
    claim = agenda.claim("inspect_output", {}, mutation=False)
    agenda.record(claim, "inspect_output", "new observation", success=True, mutation=False)
    assert not agenda.goals["first"].last_result
    assert agenda.goals["second"].last_result["text"] == "new observation"


def test_ambiguous_action_is_not_silently_attributed():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal("first"), goal("second")], TOOLS)
    with pytest.raises(ValueError, match="多个目标"):
        agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    assert all(item.state == "ready" for item in agenda.goals.values())


def test_mutation_requires_independent_verification_and_completion_assessment():
    agenda = Agenda(DecisionEngine())
    change = goal(action={"tool": "change_setting", "arguments": {"units": "mm"}},
                  verification={"tool": "inspect_output", "arguments": {}})
    agenda.update([change], TOOLS)
    claim = agenda.claim("change_setting", {"units": "mm"}, mutation=True)
    action_id = agenda.record(claim, "change_setting", "written", success=True, mutation=True)
    with pytest.raises(ValueError, match="单独核验"):
        agenda.update([dict(change, state="done", result_id=action_id, assessment="write succeeded")], TOOLS)
    claim = agenda.claim("inspect_output", {}, mutation=False)
    verification_id = agenda.record(claim, "inspect_output", "output now uses mm", success=True, mutation=False)
    with pytest.raises(ValueError, match="assessment"):
        agenda.update([dict(change, state="done", result_id=verification_id)], TOOLS)
    agenda.update([dict(change, state="done", result_id=verification_id,
                        assessment="The independently read output matches the required units")], TOOLS)
    assert agenda.goals["unknown-workflow"].state == "done"


def test_successful_probe_requires_a_semantic_assessment_but_no_extra_read():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal()], TOOLS)
    claim = agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    result_id = agenda.record(claim, "read_trace", "same input; settings differ", success=True, mutation=False)
    agenda.update([goal(state="done", result_id=result_id,
                        assessment="Same input rules out stale data; the mismatch identifies the next investigation")], TOOLS)
    assert agenda.goals["unknown-workflow"].state == "done"


def test_failed_or_other_goal_result_cannot_complete_a_goal():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal("first"), goal("second", action={"tool": "inspect_output", "arguments": {}})], TOOLS)
    claim = agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    result_id = agenda.record(claim, "read_trace", "unavailable", success=False, mutation=False)
    for goal_id in ("first", "second"):
        with pytest.raises(ValueError):
            agenda.update([goal(goal_id, state="done", result_id=result_id, assessment="finished")], TOOLS)


def test_restart_verifies_an_interrupted_mutation_without_replaying_it(tmp_path):
    agenda = Agenda(DecisionEngine(), tmp_path / "agenda.json")
    agenda.update([goal(action={"tool": "change_setting", "arguments": {}},
                        verification={"tool": "inspect_output", "arguments": {}})], TOOLS)
    agenda.claim("change_setting", {}, mutation=True)
    restored = Agenda.load(DecisionEngine(), agenda.path)
    assert restored.goals["unknown-workflow"].state == "verify"
    assert restored.action_for(restored.selected())["tool"] == "inspect_output"
    with pytest.raises(ValueError):
        restored.claim("change_setting", {}, mutation=True)


def test_no_progress_requires_a_changed_plan_and_failed_batch_update_is_atomic():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal()], TOOLS)
    claim = agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    agenda.record(claim, "read_trace", "no trace available", success=False, mutation=False)
    with pytest.raises(ValueError, match="已尝试"):
        agenda.update([goal("new"), goal()], TOOLS)
    assert "new" not in agenda.goals
    assert agenda.goals["unknown-workflow"].state == "review"


def test_dependency_cycles_are_rejected_and_waiting_dependencies_are_respected():
    agenda = Agenda(DecisionEngine())
    with pytest.raises(ValueError, match="循环"):
        agenda.update([goal("first", depends_on=["second"]), goal("second", depends_on=["first"])], TOOLS)
    assert not agenda.goals
    agenda.update([goal(depends_on=["missing-input"])], TOOLS)
    assert agenda.selected() is None
    assert agenda.claim("read_trace", {"section": "exports"}, mutation=False) is None


@pytest.fixture
def session():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, "JPEG")
    visual = Visual("screen", "synthetic", buffer.getvalue(), 20, 20, mime_type="image/jpeg")
    desktop = DesktopSession("synthetic exploration", {}, visual=visual)
    desktop.agenda = Agenda(DecisionEngine())
    return desktop


def test_tool_exception_preserves_uncertainty_and_schedules_verification(session):
    session.agenda.update([goal(action={"tool": "change_setting", "arguments": {}},
                               verification={"tool": "inspect_output", "arguments": {}})], TOOLS)

    def partial_failure(arguments):
        raise OSError("potentially sensitive detail")

    reply = session._handler("change_setting", partial_failure)({})
    assert not reply.success
    assert "potentially sensitive detail" not in reply.text
    assert "不宣称没有改动" in reply.text
    assert session.agenda.goals["unknown-workflow"].state == "verify"
    assert session.action_results[-1]["success"] is False


def test_rejected_evidence_review_does_not_leave_a_running_goal(session):
    session.agenda.update([goal(action={"tool": "desktop_review_evidence", "arguments": {"id": "unseen"}})],
                          {"desktop_review_evidence"})
    reply = session._handler("desktop_review_evidence", lambda arguments: ToolReply("must not execute"))({"id": "unseen"})
    assert not reply.success
    assert session.agenda.goals["unknown-workflow"].state == "review"
    assert session.agenda.goals["unknown-workflow"].last_result["success"] is False


def test_new_readonly_capability_can_explore_without_adding_a_tool_whitelist(session, monkeypatch):
    read_spec = replace(actions.SPECS["desktop_history"][1], name="read_trace")
    monkeypatch.setitem(actions.SPECS, "read_trace", (lambda arguments: ToolReply("new evidence"), read_spec))
    reply = session._handler("read_trace", actions.SPECS["read_trace"][0])({})
    assert reply.success
    assert session.actions == 0
    assert not session.agenda.goals


def test_recorded_probe_still_counts_as_actual_evidence_coverage():
    backend = brain.VisualDirectBackend.__new__(brain.VisualDirectBackend)
    backend.history = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "probe", "name": "desktop_history"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "probe", "content": [
            {"type": "text", "text": json.dumps({"ok": True, "records": ["new event"]})
             + "\n目标结果 result_id=probe-result；对照预期判断改善或反证"}]}]},
    ]
    assert '"history_pages_read": 1' in backend._investigation_fact()


def test_execution_changes_wake_reasoning_even_when_heuristic_value_is_negative():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal(estimates={"confidence": 0, "impact": 0, "action_cost": 1})], TOOLS)
    assert agenda.selected() is None
    assert agenda.due()
    agenda.mark_delivered()
    assert not agenda.due()


def test_evidence_annotation_can_verify_a_saved_capture(session):
    reply = session._plan({"changes": [goal(
        action={"tool": "desktop_capture_evidence", "arguments": {}},
        verification={"tool": "desktop_review_evidence", "arguments": {"id": "capture"}},
    )]})
    assert reply.success


def test_mutating_tool_cannot_be_used_as_verification(session):
    reply = session._plan({"changes": [goal(
        action={"tool": "desktop_trim", "arguments": {"pid": 123}},
        verification={"tool": "desktop_trim", "arguments": {"pid": 123}},
    )]})
    assert not reply.success
    assert not session.agenda.goals


def test_existing_goal_completion_only_needs_a_delta():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal()], TOOLS)
    claim = agenda.claim("read_trace", {"section": "exports"}, mutation=False)
    result_id = agenda.record(claim, "read_trace", "different settings", success=True, mutation=False)
    agenda.update([{"goal_id": "unknown-workflow", "state": "done", "result_id": result_id,
                    "assessment": "Same input and distinct settings distinguish the two explanations"}], TOOLS)
    assert agenda.goals["unknown-workflow"].state == "done"


def test_deliverable_plan_does_not_repeat_the_long_body_but_preserves_target_and_sources():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal(action={"tool": "desktop_write_deliverable", "arguments": {"name": "checked.csv", "sources": ["quote.csv"]}},
                        verification={"tool": "inspect_output", "arguments": {}})], TOOLS | {"desktop_write_deliverable"})
    with pytest.raises(ValueError):
        agenda.claim("desktop_write_deliverable", {"name": "different.csv", "content": "result", "sources": ["quote.csv"]}, mutation=True)
    assert agenda.claim("desktop_write_deliverable", {"name": "checked.csv", "content": "actual calculated result",
                                                       "sources": ["quote.csv"]}, mutation=True)


def test_verification_read_accepts_an_unspecified_window_but_preserves_the_resource():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal(action={"tool": "change_setting", "arguments": {}},
                        verification={"tool": "desktop_read_local", "arguments": {"path": "C:/output/check.csv"}})],
                  TOOLS | {"desktop_read_local"})
    claim = agenda.claim("change_setting", {}, mutation=True)
    agenda.record(claim, "change_setting", "saved", success=True, mutation=True)
    assert agenda.claim("desktop_read_local", {"path": "C:/output/other.csv", "limit": 3000}, mutation=False) is None
    assert agenda.claim("desktop_read_local", {"path": "C:/output/check.csv", "offset": 100}, mutation=False) is None
    claim = agenda.claim("desktop_read_local", {"path": "c:\\output\\check.csv", "limit": 3000}, mutation=False)
    assert claim == ("unknown-workflow", "verify")
    result_id = agenda.record(claim, "desktop_read_local", "correct content", success=True, mutation=False)
    agenda.update([{"goal_id": "unknown-workflow", "state": "done", "result_id": result_id,
                    "assessment": "The independently read file has the expected content"}], TOOLS | {"desktop_read_local"})
    assert agenda.goals["unknown-workflow"].state == "done"


def test_mutation_mismatch_returns_registered_target_instead_of_requesting_a_new_plan():
    agenda = Agenda(DecisionEngine())
    agenda.update([goal(action={"tool": "change_setting", "arguments": {"units": "mm"}},
                        verification={"tool": "inspect_output", "arguments": {}})], TOOLS)
    with pytest.raises(ValueError, match="实际目标参数不匹配") as error:
        agenda.claim("change_setting", {"units": "cm"}, mutation=True)
    assert '"units": "mm"' in str(error.value)
    assert agenda.goals["unknown-workflow"].state == "ready"


def test_ready_continuation_needs_callable_tool_arguments(session):
    reply = session._companion({"kind": "quiet", "next_step": {
        "status": "ready", "goal": "verify the output", "action": "read the output", "evidence": "output saved",
        "tool": "desktop_read_local", "arguments": {}}})
    assert not reply.success
    assert "path" in reply.text
    assert not session.decisions
