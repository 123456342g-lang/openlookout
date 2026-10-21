"""Pause, quit, missing config, and the rules child. No display and no model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sprite.config import sprite_home
from sprite.i18n import t
from sprite.proactive import control, first_run, live, rules
from sprite.proactive import mimo_proxy
from vista.benchmarks.desktop import brain


def test_menu_spec_and_actions_write_flags(tmp_path):
    assert [action for action, _label in control.menu_spec(False)] == ["pause", "undo", "quit"]
    assert control.menu_spec(False)[0][1] == t("menu_pause")
    assert control.menu_spec(True)[0] == ("resume", t("menu_resume"))
    assert control.apply_menu_action("pause", tmp_path) == "pause"
    assert control.paused(tmp_path)
    assert control.apply_menu_action("resume", tmp_path) == "resume"
    assert not control.paused(tmp_path)
    assert control.apply_menu_action("undo", tmp_path) == "undo"
    assert control.take_undo(tmp_path) == "last"
    assert control.take_undo(tmp_path) is None
    assert control.apply_menu_action("quit", tmp_path) == "quit"
    assert control.quit_requested(tmp_path)


def test_service_tick_does_not_start_children_after_quit(tmp_path):
    (tmp_path / "QUIT").write_text("1", encoding="utf-8")
    started = []
    result = live.service_tick(
        {}, {}, {}, {},
        start=lambda name: started.append(name),
        log=lambda _message: None,
        home=tmp_path,
    )
    assert result == "quit"
    assert started == []


def test_missing_provider_holds_brain_and_still_starts_the_window(monkeypatch):
    monkeypatch.setattr(live, "provider_problem", lambda: "need a provider file")
    monkeypatch.setattr(live, "publish", lambda _offer: None)
    with pytest.raises(live.BrainWaitingForConfig, match="need a provider file"):
        live.start("brain")

    def start(name):
        if name == "brain":
            raise live.BrainWaitingForConfig("need a provider file")
        return object()

    logs = []
    procs, _spawned, fails, dropped = live.spawn_children(
        ["brain", "gui"], start=start, log=logs.append, now=10.0)
    assert "gui" in procs
    assert "brain" not in procs
    assert fails["brain"] == 0
    assert dropped["brain"]["retry_at"] == 10.0 + live.RESPAWN_PROBE_S
    assert logs


def test_brain_run_exits_before_build_when_config_is_missing(monkeypatch):
    monkeypatch.setattr(brain, "provider_problem", lambda: "need a provider file")

    def boom(*_args, **_kwargs):
        raise AssertionError("build must not run without a provider")

    monkeypatch.setattr(brain, "build", boom)
    with pytest.raises(SystemExit) as caught:
        brain.run()
    assert caught.value.code == 2


def test_rules_child_is_supervised_and_publishes_without_a_model(tmp_path, monkeypatch):
    assert live.CHILDREN["rules"] == ["-m", "sprite.proactive.rules"]
    _probe, world, engine = rules.build_rules(tmp_path, live=False)
    assert "resource_pressure" in engine.reg.scenarios
    assert world.ctrl is not None

    class Action:
        id = "act-1"
        kind = "quarantine_cache"
        result = {"ids": []}
        blast_items = 2

    class Out:
        acted = [Action()]
        text_short = "收起了缓存"
        text_done = ""

    class FakeEngine:
        def step(self, _world):
            return [Out()]

    published = []
    monkeypatch.setattr(rules, "publish", published.append)
    offers = rules.one_pass(FakeEngine(), world, home=tmp_path, now=1.0)
    assert offers[0]["kind"] == "companion"
    assert offers[0]["action_id"] == "act-1"
    assert published[0]["kind"] == "companion"
    assert (tmp_path / "rules_undo.jsonl").is_file()


def test_undo_recorded_restores_a_quarantined_file(tmp_path):
    source = tmp_path / "cache.tmp"
    source.write_bytes(b"cache")
    _probe, world, _engine = rules.build_rules(tmp_path / "home", live=False)
    entry = world.q.put(source, "test")
    assert not source.exists()
    row = {"id": "q1", "kind": "quarantine_cache", "result": {"ids": [entry["id"]]}}
    journal = tmp_path / "home" / "rules_undo.jsonl"
    journal.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert rules.undo_recorded(tmp_path / "home", world, "q1")
    assert source.read_bytes() == b"cache"


def test_sprite_home_does_not_use_a_drive_letter_default(monkeypatch):
    monkeypatch.delenv("SPRITE_HOME", raising=False)
    path = sprite_home()
    assert path.is_absolute()
    assert "E:" not in path.parts
    text = Path(brain.__file__).read_text(encoding="utf-8")
    assert "E:\\OpenLookout\\sprite_home" not in text


def test_mimo_proxy_requires_an_explicit_upstream(monkeypatch):
    source = Path(mimo_proxy.__file__).read_text(encoding="utf-8")
    assert "xiaomimimo" not in source
    assert "mimo-v2.6-flash" not in source
    monkeypatch.delenv("MIMO_UPSTREAM", raising=False)
    monkeypatch.delenv("OPENLOOKOUT_UPSTREAM", raising=False)
    monkeypatch.delenv("MIMO_MODEL", raising=False)
    monkeypatch.delenv("OPENLOOKOUT_MODEL", raising=False)
    with pytest.raises(RuntimeError):
        mimo_proxy.upstream_url()
    with pytest.raises(RuntimeError):
        mimo_proxy.upstream_model("")


def test_setup_writes_provider_and_env(tmp_path):
    provider = tmp_path / "provider.json"
    env = tmp_path / ".env"
    first_run.setup_from_answers(
        {"protocol": "openai", "base_url": "http://localhost:11434/v1",
         "model": "your-ollama-model", "api_key": "ollama"},
        provider_path=provider,
        env_path=env,
    )
    saved = json.loads(provider.read_text(encoding="utf-8"))
    assert saved == {
        "protocol": "openai",
        "base_url": "http://localhost:11434/v1",
        "model": "your-ollama-model",
    }
    assert env.read_text(encoding="utf-8").split("=", 1)[1].strip() == "ollama"


def test_wizard_noninteractive_does_not_start(monkeypatch, capsys):
    monkeypatch.setattr(first_run, "provider_problem", lambda: "need a provider file")
    assert first_run.run_wizard() == 2
    assert "need a provider file" in capsys.readouterr().out


def test_wizard_rejects_a_bad_protocol(monkeypatch):
    monkeypatch.setattr(first_run, "provider_problem", lambda: "need a provider file")
    answers = iter(["ftp"])
    lines = []
    code = first_run.run_wizard(read=lambda _prompt: next(answers), write=lines.append)
    assert code == 2
    assert lines
