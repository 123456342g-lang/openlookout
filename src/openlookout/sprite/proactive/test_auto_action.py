from __future__ import annotations

import json
import subprocess

import sprite.proactive.live as livemod


def test_supervised_recorder_reuses_existing_collector_without_clipboard_text():
    argv = livemod.CHILDREN["recorder"]
    assert argv[0].endswith("record_win.py")
    assert "--keep-text" not in argv
    assert argv[argv.index("--out") + 1].endswith("operations.jsonl")
    assert argv[argv.index("--parent-pid") + 1] == str(livemod.os.getpid())


def test_run_offer_executes_and_reports_reversible_result(tmp_path, monkeypatch):
    monkeypatch.setattr(livemod, "DIR", tmp_path)
    offer = {"id": "offer-1", "text": "整理桌面", "kind": "offer"}
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, '{"final":"已整理，随时可以撤回。"}', "")

    monkeypatch.setattr(livemod.subprocess, "run", fake_run)
    messages = []
    livemod.run_offer(offer, messages.append)

    assert calls and "--objective" in calls[0][0]
    assert messages == [{"kind": "action", "text": "已整理，随时可以撤回。", "action_id": "offer-1"}]
    rows = [json.loads(line) for line in (tmp_path / "offers.jsonl").read_text("utf-8").splitlines()]
    assert rows[-1]["result"] == "auto_completed"


def test_offer_status_reads_latest_execution_state(tmp_path, monkeypatch):
    monkeypatch.setattr(livemod, "DIR", tmp_path)
    path = tmp_path / "offers.jsonl"
    path.write_text(
        json.dumps({"id": "offer-1", "result": "auto_started"})
        + "\n"
        + json.dumps({"id": "offer-1", "result": "auto_completed"})
        + "\n",
        encoding="utf-8",
    )
    assert livemod.offer_status("offer-1") == "auto_completed"
    assert livemod.offer_status("missing") is None
