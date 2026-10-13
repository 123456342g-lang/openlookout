from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import actions


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "DELIVERABLES", tmp_path / "deliverables")
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    return tmp_path


def test_deliverable_journal_precedes_write_and_original_files_are_untouched(isolated, monkeypatch):
    original_open = Path.open

    def check_open(path, mode="r", *args, **kwargs):
        if mode == "xb":
            rows = [json.loads(row) for row in actions.JOURNAL.read_text(encoding="utf-8").splitlines()]
            assert rows[-1]["path"] == str(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", check_open)
    reply = actions.desktop_write_deliverable({"name": "checked.csv", "content": "item,total\n支架,450\n",
                                               "sources": ["quote.csv row 1"]})
    assert reply.success
    result = json.loads(reply.text)
    assert Path(result["path"]).read_text(encoding="utf-8") == "item,total\n支架,450\n"
    assert actions.undo({}).success
    assert not Path(result["path"]).exists()


def test_existing_or_user_modified_deliverable_is_never_overwritten_or_removed(isolated):
    args = {"name": "report.md", "content": "verified result", "sources": ["actual source"]}
    reply = actions.desktop_write_deliverable(args)
    path = Path(json.loads(reply.text)["path"])
    assert not actions.desktop_write_deliverable(dict(args, content="replacement")).success
    path.write_text("user edited this", encoding="utf-8")
    assert not actions.undo({}).success
    assert path.read_text(encoding="utf-8") == "user edited this"


@pytest.mark.parametrize("name", ["../outside.md", "sub/file.md", "C:/outside.md", "script.py", "run.exe"])
def test_deliverable_cannot_escape_or_create_executable_content(isolated, name):
    reply = actions.desktop_write_deliverable({"name": name, "content": "text", "sources": ["actual source"]})
    assert not reply.success
    assert not actions.JOURNAL.exists()


def test_browser_connector_parses_top_level_json_not_nested_objects(monkeypatch):
    class Result:
        stdout = 'TABBIT_PLAYWRIGHT_INSTANCE=example\n{"status":"succeeded","result":{"value":{"title":"page"}}}\n'

    monkeypatch.setattr(actions, "_tabbit_cli", lambda: "tabbit-cli")
    monkeypatch.setattr(actions.subprocess, "run", lambda *args, **kwargs: Result())
    assert actions._tabbit_json(["create"])["status"] == "succeeded"


def test_browser_inventory_removes_query_tokens_and_releases_task(monkeypatch):
    calls = []

    def cli(arguments, **kwargs):
        calls.append(arguments)
        return {"tabs": [{"tabId": 12, "title": "page", "url": "https://example.com/callback?token=private#code=hidden"}],
                "truncated": False} if arguments[0] == "create" else {"finished": True}

    monkeypatch.setattr(actions, "_tabbit_json", cli)
    reply = actions.desktop_browser_inventory({})
    assert "private" not in reply.text and "hidden" not in reply.text
    assert json.loads(reply.text)["tabs"][0]["url"] == "https://example.com/callback"
    assert calls[-1][0] == "finish"


def test_pending_browser_observation_waits_for_original_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "_BROWSER_PENDING", {})

    def cli(arguments, **kwargs):
        calls.append(arguments)
        return {"status": "running"} if arguments[0] == "nodejs" else {"status": "succeeded", "result": {"value": "page"}}

    monkeypatch.setattr(actions, "_tabbit_json", cli)
    assert not actions.desktop_browser_observe({"tab_id": 12}).success
    assert actions.desktop_browser_observe({"tab_id": 12}).success
    assert [call[0] for call in calls] == ["nodejs", "receipt", "finish"]
