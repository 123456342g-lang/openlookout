from __future__ import annotations

import json

from . import permissions
from .agenda import Agenda
from .decision_engine import DecisionEngine


TOOLS = {"read_trace", "inspect_output"}


def make_goal(goal_id: str, *, state="ready", tool="read_trace"):
    return {
        "goal_id": goal_id,
        "goal": f"Check {goal_id}",
        "lane": "investigate",
        "evidence": [f"observed:{goal_id}"],
        "expected": f"Evidence for {goal_id}",
        "state": state,
        "estimates": {"confidence": 0.8, "impact": 0.5},
        "action": {"tool": tool, "arguments": {"id": goal_id}},
        "waiting_on": "External result is unavailable" if state == "waiting" else "",
    }


def test_quiet_preserves_executable_work_and_exposes_work_separately(tmp_path, monkeypatch):
    from . import session as session_mod
    from .session import DesktopSession
    from vista.core.contracts import Visual
    from PIL import Image
    import io

    monkeypatch.setattr(session_mod, "CURRENT", tmp_path / "current.json")
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "JPEG")
    session = DesktopSession("test", {}, visual=Visual("screen", "test", buf.getvalue(), 20, 20, mime_type="image/jpeg"))
    session.agenda = Agenda(DecisionEngine())
    session.agenda.update([make_goal("first")], TOOLS)

    assert session._companion({"kind": "quiet"}).success
    assert session.agenda.goals["first"].state == "ready"
    current = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    assert current["speech"]["kind"] == "quiet"
    assert current["work"]["status"] == "ready"
    assert current["work"]["tool"] == "read_trace"
    assert "arguments" not in current["next_step"]
    assert "observed:first" not in json.dumps(current["work"])
    session._companion({"kind": "quiet", "next_step": {
        "status": "waiting", "goal": "Wait for reply", "action": "Wait", "evidence": "Conversation pending"}})
    assert session.agenda.goals["first"].state == "ready"
    from .brain import ContinuationTracker
    tracker = ContinuationTracker()
    assert tracker.pending(session.decisions[-1], session.evidence_revision, session.agenda)


def test_empty_and_external_waiting_agendas_do_not_autonomously_wake():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    tracker = ContinuationTracker()
    assert tracker.pending({"kind": "quiet"}, 0, agenda) is None
    assert not agenda.due()
    agenda.update([make_goal("blocked", state="waiting")], TOOLS)
    assert tracker.pending({"kind": "quiet"}, 0, agenda) is None
    assert not agenda.due()


def test_waiting_goal_does_not_wake_or_starve_independent_ready_goal():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    agenda.update([
        make_goal("blocked", state="waiting"),
        make_goal("available", tool="inspect_output"),
    ], TOOLS)
    tracker = ContinuationTracker()
    first = tracker.pending({}, 0, agenda)
    assert first and "available" in first
    tracker.consume(first, 0)
    assert tracker.pending({}, 0, agenda) is None


def test_restart_running_goal_only_offers_verification(tmp_path):
    path = tmp_path / "agenda.json"
    agenda = Agenda(DecisionEngine(), path)
    change = make_goal("change", tool="read_trace")
    change["action"] = {"tool": "read_trace", "arguments": {"id": "change"}}
    change["verification"] = {"tool": "inspect_output", "arguments": {"id": "change"}}
    agenda.update([change], TOOLS)
    agenda.claim("read_trace", {"id": "change"}, mutation=True)

    restored = Agenda.load(DecisionEngine(), path)
    assert restored.goals["change"].state == "verify"
    assert restored.continuation_step()["tool"] == "inspect_output"
    assert restored.action_for(restored.goals["change"])["tool"] == "inspect_output"


def test_consumed_first_goal_does_not_starve_other_work_or_repeat_without_progress():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    agenda.update([make_goal("first"), make_goal("second")], TOOLS)
    tracker = ContinuationTracker()
    first = tracker.pending({"kind": "quiet"}, 0, agenda)
    tracker.consume(first, 0)
    second = tracker.pending({"kind": "quiet"}, 0, agenda)
    assert second and second != first
    tracker.consume(second, 0)
    assert tracker.pending({"kind": "quiet"}, 0, agenda) is None


def test_terminal_goal_does_not_resume_stale_speech_step():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    agenda.update([make_goal("finished", state="dropped")], TOOLS)
    decision = {"next_step": dict(make_goal("finished")["action"], status="ready", action="Read again")}
    assert ContinuationTracker().pending(decision, 0, agenda) is None


def test_terminal_verification_cannot_resume_with_equivalent_default_read_arguments():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    change = make_goal("finished", state="dropped")
    change["verification"] = {"tool": "desktop_read_local", "arguments": {"path": "C:/isolated/result.csv"}}
    agenda.update([change], TOOLS | {"desktop_read_local"})
    decision = {"next_step": {"status": "ready", "action": "Read again", "tool": "desktop_read_local",
                             "arguments": {"path": "C:/isolated/result.csv", "offset": 0, "limit": 5000}}}
    assert ContinuationTracker().pending(decision, 0, agenda) is None


def test_result_receipt_keeps_actual_request_and_expected_through_independent_verification(tmp_path):
    agenda = Agenda(DecisionEngine(), tmp_path / "agenda.json")
    change = make_goal("change")
    change["verification"] = {"tool": "inspect_output", "arguments": {"id": "change"}}
    agenda.update([change], TOOLS)
    claim = agenda.claim("read_trace", {"id": "change"}, mutation=True)
    action_id = agenda.record(claim, "read_trace", "changed", success=True, mutation=True)
    claim = agenda.claim("inspect_output", {"id": "change"}, mutation=False)
    verify_id = agenda.record(claim, "inspect_output", "independent output matches", success=True, mutation=False)
    agenda.update([{"goal_id": "change", "state": "done", "result_id": verify_id,
                    "assessment": "Independent output matches the expected result"}], TOOLS)
    restored = Agenda.load(DecisionEngine(), agenda.path)
    stored = restored.goals["change"]
    assert stored.action_result["id"] == action_id
    assert stored.action_result["request"]["arguments"] == {"id": "change"}
    assert stored.last_result["request"]["arguments"] == {"id": "change"}
    assert stored.last_result["expected"] == change["expected"]
    assert stored.assessment == "Independent output matches the expected result"


def test_repeat_claim_of_unconfirmed_running_tool_is_rejected():
    import pytest

    agenda = Agenda(DecisionEngine())
    agenda.update([make_goal("first")], TOOLS)
    agenda.claim("read_trace", {"id": "first"}, mutation=False)
    with pytest.raises(ValueError, match="执行中"):
        agenda.claim("read_trace", {"id": "first"}, mutation=False)


def test_delivery_of_old_snapshot_does_not_consume_new_result():
    agenda = Agenda(DecisionEngine())
    agenda.update([make_goal("first")], TOOLS)
    offered_revision = agenda.revision
    claim = agenda.claim("read_trace", {"id": "first"}, mutation=False)
    agenda.record(claim, "read_trace", "new facts", success=True, mutation=False)
    agenda.mark_delivered(offered_revision)
    assert agenda.due()
    agenda.mark_delivered()
    assert not agenda.due()


def test_unrelated_evidence_does_not_repeat_consumed_agenda_step():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    agenda.update([make_goal("first")], TOOLS)
    tracker = ContinuationTracker()
    key = tracker.pending({}, 0, agenda)
    tracker.consume(key, 0)
    assert tracker.pending({}, 5, agenda) is None


def test_new_action_result_reenables_same_independent_verification():
    from .brain import ContinuationTracker

    agenda = Agenda(DecisionEngine())
    change = make_goal("change")
    change["verification"] = {"tool": "inspect_output", "arguments": {"id": "change"}}
    agenda.update([change], TOOLS)
    tracker = ContinuationTracker()
    first = agenda.claim("read_trace", {"id": "change"}, mutation=True)
    agenda.record(first, "read_trace", "first version", success=True, mutation=True)
    first_key = tracker.pending({}, 0, agenda)
    tracker.consume(first_key, 0)
    verify = agenda.claim("inspect_output", {"id": "change"}, mutation=False)
    agenda.record(verify, "inspect_output", "does not yet satisfy expectation", success=True, mutation=False)
    agenda.update([{"goal_id": "change", "state": "ready", "action": {
        "tool": "read_trace", "arguments": {"id": "change", "version": 2}}}], TOOLS)
    second = agenda.claim("read_trace", {"id": "change", "version": 2}, mutation=True)
    agenda.record(second, "read_trace", "second version", success=True, mutation=True)
    assert tracker.pending({}, 0, agenda) not in {None, first_key}


def test_restart_receipt_keeps_the_interrupted_request(tmp_path):
    agenda = Agenda(DecisionEngine(), tmp_path / "agenda.json")
    change = make_goal("change")
    change["verification"] = {"tool": "inspect_output", "arguments": {"id": "change"}}
    agenda.update([change], TOOLS)
    agenda.claim("read_trace", {"id": "change"}, mutation=True)
    restored = Agenda.load(DecisionEngine(), agenda.path)
    assert restored.goals["change"].last_result["request"]["arguments"] == {"id": "change"}
    assert restored.goals["change"].last_result["interrupted"]


def test_observed_clue_runs_silently_to_independently_verified_deliverable(tmp_path, monkeypatch):
    import csv
    import io
    import re

    from PIL import Image
    from sprite.proactive import conversation
    from vista.core.contracts import ToolReply, Visual
    from vista.core.profiles import Phase
    from vista.core.runtime import TaskRuntime
    from . import actions, brain, session as session_mod
    from .profiles import make_experiment, make_profile
    from .session import DesktopSession

    source = tmp_path / "recent.csv"
    source.write_text("item,quantity,price,total\nframe,2,5,9\n", encoding="utf-8")
    output = tmp_path / "deliverables" / "checked.csv"
    monkeypatch.setattr(actions, "DELIVERABLES", output.parent)
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    monkeypatch.setattr(session_mod, "CURRENT", tmp_path / "current.json")
    monkeypatch.setattr(brain, "PERCEIVE", tmp_path)
    monkeypatch.setattr(brain, "residual_fact", lambda: "")
    monkeypatch.setattr(brain, "long_term_fact", lambda: "")
    monkeypatch.setattr(conversation, "history", lambda limit=80: [])
    history_spec = actions.SPECS["desktop_history"][1]
    monkeypatch.setitem(actions.SPECS, "desktop_history", (
        lambda args: ToolReply(json.dumps({"records": [{"path": str(source), "type": "repeated_export"}]})),
        history_spec))
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, "JPEG")
    visual = Visual("screen", "unchanged", image.getvalue(), 20, 20, mime_type="image/jpeg")
    desktop = DesktopSession("Observe the user's context and decide whether help is useful", {}, visual=visual)
    desktop.agenda = Agenda(DecisionEngine(), tmp_path / "agenda.json")
    # 这条用例考的是**续办生命周期**（目标登记 → 执行 → 独立读回 → done），
    # 不是权限闸门。而 desktop_write_deliverable 是中风险，默认档要攒批等点头，
    # 那会把执行推迟到批准之后，续办链路根本走不到。
    # 所以这里显式把中风险设成 auto：闸门本身由 test_risk_tier*.py 单独钉住，
    # 这里要的是一个不被打断的干净执行环境。测试名里的 silently 指
    # 「不打扰用户」，而不是「绕过闸门」。
    desktop.gate = permissions.Gate(policy=permissions.Policy(
        low=permissions.Mode.AUTO, medium=permissions.Mode.AUTO, high=permissions.Mode.ASK))
    experiment = make_experiment(make_profile(), backend="claude", model="isolated", effort="low",
                                 revision="test", presentation={})
    runtime = TaskRuntime(desktop, experiment, artifact_dir=tmp_path / "artifacts")
    backend = brain.VisualDirectBackend({"model": "isolated", "base_url": "https://isolated.invalid", "api_key": "fixture"}, runtime)
    backend.attach(desktop)
    tracker = brain.ContinuationTracker()
    requests = []
    prepared = {}

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def last_receipt(body):
        for message in reversed(body["messages"]):
            for block in reversed(message["content"]):
                if block.get("type") == "tool_result":
                    return "\n".join(part.get("text", "") for part in block.get("content", []))
        raise AssertionError("A real tool receipt must reach the next model request")

    def respond(request, timeout):
        body = json.loads(request.data)
        stage = len(requests)
        requests.append(body)
        if stage == 0:
            name, arguments = "desktop_history", {}
        elif stage == 1:
            record = json.loads(last_receipt(body))["records"][0]
            planned = make_goal("export-check")
            planned.update(evidence=["history: repeated export"],
                           action={"tool": "desktop_read_local", "arguments": {"path": record["path"]}})
            name, arguments = "desktop_plan", {"changes": [planned]}
        elif stage in {2, 5, 7}:
            name, arguments = "companion", {"kind": "quiet"}
        elif stage in {3, 6, 8}:
            step = tracker.step
            name, arguments = step["tool"], step["arguments"]
        elif stage == 4:
            receipt = json.loads(last_receipt(body).split("\n目标结果")[0])
            row = next(csv.DictReader(io.StringIO(receipt["text"])))
            correct = int(row["quantity"]) * int(row["price"])
            assert correct != int(row["total"])
            prepared["content"] = f"item,reported,correct\n{row['item']},{row['total']},{correct}\n"
            change = {"goal_id": "export-check", "state": "ready", "evidence": ["source rows independently read"],
                      "expected": "Checked table preserves the source row and corrected multiplication",
                      "action": {"tool": "desktop_write_deliverable", "arguments": {
                          "name": output.name, "sources": [str(source)], "content": prepared["content"]}},
                      "verification": {"tool": "desktop_read_local", "arguments": {"path": str(output)}}}
            name, arguments = "desktop_plan", {"changes": [change]}
        elif stage == 9:
            text = last_receipt(body)
            receipt = json.loads(text.split("\n目标结果")[0])
            assert receipt["text"] == prepared["content"]
            result_id = re.search(r"result_id=([a-f0-9]+)", text).group(1)
            name, arguments = "desktop_plan", {"changes": [{"goal_id": "export-check", "state": "done",
                "result_id": result_id, "assessment": "Independent read preserves the source row and matches multiplication"}]}
        elif stage == 10:
            name, arguments = "companion", {"kind": "quiet", "next_step": {
                "status": "done", "goal": "Checked export", "action": "Verified table", "evidence": "Independent file read"}}
        else:
            raise AssertionError("No unbounded model rounds are allowed")
        return Response({"content": [{"type": "tool_use", "id": f"stage-{stage}", "name": name, "input": arguments}],
                         "stop_reason": "tool_use"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    try:
        first = backend.run(runtime.prepare_input(Phase.INITIAL, public_text="Observe the visible context"))
        assert first.boundary == "decision_complete"
        assert desktop.decisions[-1]["kind"] == "quiet"
        for _ in range(3):
            key = tracker.pending(desktop.decisions[-1], desktop.evidence_revision, desktop.agenda)
            assert key
            tracker.consume(key, desktop.evidence_revision)
            result = backend.run(runtime.prepare_input(Phase.STEP, public_text="【续办】" + json.dumps(tracker.step),
                                                       observation=desktop.observe(visual)))
            assert result.boundary == "decision_complete"
        assert output.read_text(encoding="utf-8") == "item,reported,correct\nframe,9,10\n"
        assert len(desktop.action_results) == 1
        assert desktop.agenda.goals["export-check"].state == "done"
        assert all(row["kind"] == "quiet" for row in desktop.decisions)
        assert tracker.pending(desktop.decisions[-1], desktop.evidence_revision, desktop.agenda) is None
        assert not desktop.agenda.due()
        current = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
        assert current["work"]["status"] == "idle"
        assert "arguments" not in current.get("next_step", {})
    finally:
        runtime.close()
