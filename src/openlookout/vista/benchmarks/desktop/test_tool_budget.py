"""The forensic budget is a hard gate, not prompt advice.

Measured on 2026-10-13: one turn spent 23 evidence-gathering calls (40
``desktop_read_local`` across 8 turns) before the sprite said anything, and the
7-minute turns users noticed came from exactly that.  ``profiles.py`` already
told the model to budget its investigation; it kept reading anyway, so these
tests pin the behaviour at the dispatch layer where both transports pass.

Every assertion here runs a real ``TaskRuntime.execute`` and reads the returned
reply.  A test that only grepped the source would pass against a gate that never
fires, which is the failure this file exists to prevent.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from sprite.proactive import conversation, help as helpmod
from vista.benchmarks.desktop import actions, session as sessionmod
from vista.benchmarks.desktop.profiles import make_experiment, make_profile
from vista.core.contracts import ToolExecution, Visual
from vista.core.profiles import Phase
from vista.core.runtime import (
    DEFAULT_INVESTIGATION_BUDGET,
    TaskRuntime,
    investigation_budget,
)

FORENSIC = ("desktop_read_local", "basic_search", "desktop_history",
            "desktop_browser_observe")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "offers.log")
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "current.json")
    monkeypatch.setattr(conversation, "history", lambda limit=80: [])
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(buffer, "JPEG")
    visual = Visual("screen", "screen", buffer.getvalue(), 320, 200,
                    mime_type="image/jpeg")
    session = sessionmod.DesktopSession("取证预算", {}, visual=visual)
    experiment = make_experiment(make_profile(), backend="claude", model="test",
                                 effort="low", revision="budget-test",
                                 presentation={})
    built = TaskRuntime(session, experiment,
                        artifact_dir=tmp_path / "artifacts")
    built.begin_turn(built.prepare_input(Phase.INITIAL))
    return built


@pytest.fixture
def notes(tmp_path):
    path = tmp_path / "HANDOFF.md"
    path.write_text("第一段取证笔记。\n第二段取证笔记。\n", encoding="utf-8")
    return path


def read(runtime, path, index):
    return runtime.execute("desktop_read_local", {"path": str(path)},
                           f"call-{index}")


def test_forensic_budget_stops_the_run_of_reads(runtime, notes):
    """Eight reads in one turn: the first six run, the rest are refused."""
    replies = [read(runtime, notes, i) for i in range(8)]

    for index, reply in enumerate(replies[:DEFAULT_INVESTIGATION_BUDGET]):
        assert "取证预算已用完" not in reply.text, (
            f"call {index + 1} should still have been served")
        assert "取证笔记" in reply.text, (
            f"call {index + 1} should have returned real file content")

    for reply in replies[DEFAULT_INVESTIGATION_BUDGET:]:
        assert "取证预算已用完" in reply.text
        # Guidance, not a crash: the model must be able to read this and speak.
        assert reply.success is True


def test_refusal_names_the_next_step_rather_than_an_error(runtime, notes):
    """The message has to tell the model how to stop, or it keeps digging."""
    for index in range(DEFAULT_INVESTIGATION_BUDGET):
        read(runtime, notes, index)
    reply = read(runtime, notes, 99)

    assert "companion" in reply.text
    assert "quiet" in reply.text
    # A technical error would read as a fault to retry past.
    for marker in ("Traceback", "error", "Exception", "failed"):
        assert marker not in reply.text


def test_speaking_still_works_once_the_budget_is_gone(runtime, notes):
    """The point of the budget is to reach a turn that ends, not a dead turn."""
    for index in range(DEFAULT_INVESTIGATION_BUDGET):
        read(runtime, notes, index)
    read(runtime, notes, 50)

    said = runtime.execute(
        "companion",
        {"kind": "companion", "intent": "conversation",
         "say": "这几份文件我看到这里，先说结论。", "topic": "取证"},
        "say-1",
    )
    assert said.success is True
    assert "Traceback" not in said.text


def test_looking_at_the_machine_is_not_budgeted(runtime):
    """``desktop_processes`` is "what is happening now", not rummaging."""
    for index in range(DEFAULT_INVESTIGATION_BUDGET * 3):
        reply = runtime.execute("desktop_processes", {}, f"proc-{index}")
        assert "取证预算已用完" not in reply.text


def test_budget_is_per_turn_and_never_accumulates(runtime, notes):
    """Two turns of six reads each are both fully served."""
    for turn in range(2):
        runtime.begin_turn(runtime.prepare_input(Phase.STEP))
        for index in range(DEFAULT_INVESTIGATION_BUDGET):
            reply = read(runtime, notes, f"{turn}-{index}")
            assert "取证预算已用完" not in reply.text, (
                f"turn {turn} call {index} should have been served")
        assert "取证预算已用完" in read(runtime, notes, f"{turn}-over").text


def test_budget_is_shared_across_forensic_tools(runtime, notes, tmp_path):
    """The cap is one investigation budget, not one per tool name."""
    for index in range(3):
        runtime.execute("desktop_read_local", {"path": str(notes)}, f"r-{index}")
    for index in range(3):
        reply = runtime.execute("basic_search",
                                {"query": "取证", "root": str(tmp_path),
                                 "mode": "text"}, f"s-{index}")
        assert "取证预算已用完" not in reply.text

    assert "取证预算已用完" in runtime.execute(
        "desktop_read_local", {"path": str(notes)}, "r-over").text


def test_host_native_channel_hits_the_same_gate(tmp_path, monkeypatch, notes):
    """The host-native path must not be a way around the budget.

    Real chain: mcp host -> GameToolDispatcher -> delegate -> TaskRuntime.
    """
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "offers.log")
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "current.json")
    monkeypatch.setattr(conversation, "history", lambda limit=80: [])
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(buffer, "JPEG")
    visual = Visual("screen", "screen", buffer.getvalue(), 320, 200,
                    mime_type="image/jpeg")
    session = sessionmod.DesktopSession("取证预算", {}, visual=visual)
    experiment = make_experiment(make_profile(), backend="claude", model="test",
                                 effort="low", revision="budget-host",
                                 presentation={})
    built = TaskRuntime(session, experiment,
                        artifact_dir=tmp_path / "artifacts")
    from vista.backends.binding import tool_interface

    interface = tool_interface(built, "claude")
    built.begin_turn(built.prepare_input(Phase.INITIAL))

    replies = [
        interface.executor.execute("desktop_read_local", {"path": str(notes)},
                                   f"host-{index}")
        for index in range(DEFAULT_INVESTIGATION_BUDGET + 2)
    ]
    assert "取证预算已用完" not in replies[0].text, "the first read must be served"
    for reply in replies[:DEFAULT_INVESTIGATION_BUDGET]:
        assert "取证笔记" in reply.text, (
            "the host-native channel must still return real content")
    for reply in replies[DEFAULT_INVESTIGATION_BUDGET:]:
        assert "取证预算已用完" in reply.text


def test_only_the_four_forensic_tools_are_gated():
    """Marking the wrong set would either leak the gate or gag the sprite."""
    gated = {name for name, (_, spec) in actions.SPECS.items()
             if spec.investigation}
    assert gated == set(FORENSIC)
    # companion is registered outside SPECS, so check the spec directly.
    assert not actions.COMPANION_SPEC.investigation
    for name in ("desktop_processes", "desktop_write_deliverable"):
        assert not actions.SPECS[name][1].investigation


def test_budget_is_configurable_and_rejects_nonsense(monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_TOOL_BUDGET", "2")
    assert investigation_budget() == 2
    monkeypatch.setenv("OPENLOOKOUT_TOOL_BUDGET", "not-a-number")
    assert investigation_budget() == DEFAULT_INVESTIGATION_BUDGET
    monkeypatch.setenv("OPENLOOKOUT_TOOL_BUDGET", "0")
    assert investigation_budget() == DEFAULT_INVESTIGATION_BUDGET
    monkeypatch.delenv("OPENLOOKOUT_TOOL_BUDGET")
    assert investigation_budget() == DEFAULT_INVESTIGATION_BUDGET


def test_configured_budget_is_the_one_enforced(runtime, notes, monkeypatch):
    """An override has to reach the gate, not just the resolver."""
    monkeypatch.setenv("OPENLOOKOUT_TOOL_BUDGET", "2")
    runtime.begin_turn(runtime.prepare_input(Phase.STEP))
    assert "取证预算已用完" not in read(runtime, notes, 0).text
    assert "取证预算已用完" not in read(runtime, notes, 1).text
    assert "取证预算已用完" in read(runtime, notes, 2).text


def test_a_refused_call_never_reaches_the_filesystem(runtime, notes):
    """A budget that still read the file would be a budget in name only."""
    from dataclasses import replace as dc_replace

    served = []
    binding = runtime._bindings["desktop_read_local"]
    original = binding.handler

    def counting(arguments):
        served.append(arguments)
        return original(arguments)

    runtime._bindings["desktop_read_local"] = dc_replace(binding,
                                                         handler=counting)
    try:
        for index in range(DEFAULT_INVESTIGATION_BUDGET + 3):
            read(runtime, notes, index)
    finally:
        runtime._bindings["desktop_read_local"] = binding

    assert len(served) == DEFAULT_INVESTIGATION_BUDGET, (
        f"expected exactly {DEFAULT_INVESTIGATION_BUDGET} real reads, "
        f"got {len(served)}")


def test_exhaustion_is_recorded_for_forensics(runtime, notes):
    """Operators need to see the gate firing, not infer it from silence."""
    import json

    for index in range(DEFAULT_INVESTIGATION_BUDGET + 1):
        read(runtime, notes, index)
    events = runtime.artifacts.root / "events.jsonl"
    rows = [json.loads(line) for line in
            events.read_text(encoding="utf-8").splitlines()]
    spent = [row for row in rows
             if row.get("event") == "investigation_budget_spent"]
    assert len(spent) == 1
    assert spent[0]["tool"] == "desktop_read_local"
    assert spent[0]["budget"] == DEFAULT_INVESTIGATION_BUDGET
