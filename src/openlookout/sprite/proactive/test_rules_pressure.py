"""Critical memory must suspend an idle background browser, say so, and undo.

The audit raised resource_pressure:mem at 3% free and then, for three rounds,
left a sleeping chrome.exe in state S with no bubble and no undo row. Three
gates dropped it: it was not a long-idle renderer, its relief was under 5% of
a multi-GB hole, and a Linux probe never filled idle_s. These tests walk the
live rules path (one_pass, the real publish, the undo journal).
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sprite.framework import Action, Engine, Problem, Registry, Scenario
from sprite.procctl import JournaledController
from sprite.proactive import help as helpmod
from sprite.proactive import rules
from sprite.sysstate import Proc, RealProbe, Snapshot


def _quiet_env(world, root: Path) -> None:
    empty = root / "empty"
    empty.mkdir(exist_ok=True)
    world.env.user_dirs = [empty]
    world.env.temp_dirs = [empty]
    world.env.browser_cache_dirs = []
    world.env.pkg_cache_dirs = []
    world.env.downloads = None
    world.env.homework_dirs = []


def _snap(procs, avail_mb: float) -> Snapshot:
    return Snapshot(1_000.0, 16_000.0, avail_mb, {"/": (100.0, 50.0)}, procs, "notepad")


def _run_rounds(tmp_path, monkeypatch, procs, avail_mb: float, rounds: int = 3):
    home = tmp_path / "home"
    _probe, world, engine = rules.build_rules(home, live=False)
    _quiet_env(world, tmp_path)
    world.ctrl = JournaledController(home, live=False, spawn_watchdog=False)
    snap = _snap(procs, avail_mb)
    world.snap = snap
    world.refresh = lambda: snap
    ticks = {"t": 1_000_000.0}
    engine.clock = lambda: ticks["t"]
    offer_path = tmp_path / "perceive" / "offer.json"
    monkeypatch.setattr(helpmod, "OFFER", offer_path)
    published = []
    per_round = []
    for _ in range(rounds):
        world.snap = snap
        found = rules.one_pass(engine, world, home=home, now=ticks["t"])
        published.extend(found)
        per_round.append(found)
        ticks["t"] += rules.POLL_S
        snap.t += rules.POLL_S
        for proc in procs:
            proc.idle_s += rules.POLL_S
    return world, engine, published, per_round, offer_path


def test_critical_memory_suspends_reports_and_undoes(tmp_path, monkeypatch):
    background = Proc(4242, "chrome", 180, idle_s=0, cmdline="chrome")
    foreground = Proc(4243, "chrome", 400, idle_s=0, cmdline="chrome", foreground_tree=True)
    audible = Proc(4244, "chrome", 400, idle_s=0, cmdline="chrome", audio=True)
    windowed = Proc(4245, "chrome", 400, idle_s=0, cmdline="chrome", has_window=True)
    world, engine, published, per_round, offer_path = _run_rounds(
        tmp_path, monkeypatch, [background, foreground, audible, windowed], 480.0)
    assert per_round[0] == [] and per_round[1] == []
    assert len(published) == 1
    offer = published[0]
    assert offer["kind"] == "companion"
    assert offer["text"]
    assert offer["action_id"]
    saved = json.loads(offer_path.read_text(encoding="utf-8"))
    assert saved["action_id"] == offer["action_id"]
    assert saved["kind"] == "companion"
    journal = (tmp_path / "home" / "rules_undo.jsonl").read_text(encoding="utf-8")
    assert offer["action_id"] in journal
    assert 4242 in world.ctrl.suspended
    assert 4243 not in world.ctrl.suspended
    assert 4244 not in world.ctrl.suspended
    assert 4245 not in world.ctrl.suspended
    assert engine.undo(offer["action_id"]) is True
    assert 4242 not in world.ctrl.suspended


def test_warn_level_does_not_suspend_a_young_browser(tmp_path, monkeypatch):
    background = Proc(4242, "chrome", 180, idle_s=0, cmdline="chrome")
    _world, _engine, published, _rounds, _offer = _run_rounds(
        tmp_path, monkeypatch, [background], 2_400.0)
    assert published == []
    assert 4242 not in _world.ctrl.suspended


def _calls_for(tmp_path, kind: str, need: float, reliefs: list[tuple[str, float]]) -> list[str]:
    calls = []

    def propose(_pb, _world):
        actions = []
        for name, relief in reliefs:
            def run(name=name):
                calls.append(name)
                return {}
            actions.append(Action(name, name, "safe", "full", relief=relief, run=run, undo=lambda _r: None))
        return actions

    registry = Registry()
    registry.register(Scenario(
        "t",
        lambda _w: [Problem(kind, 1.0, "x", need=need, key="k", recheck=lambda: need)],
        propose,
        auto_caps=dict(items=9, bytes=1 << 40),
    ))
    engine = Engine(registry, tmp_path, gate=dict(min_value_s=0))
    engine.batch_interval_s = 0
    engine.retry_interval_s = 0
    engine.step(object())
    return calls


def test_non_memory_floor_still_skips_tiny_gains(tmp_path):
    calls = _calls_for(tmp_path, "p", 100.0, [("small", 1), ("big", 60), ("mid", 30), ("tiny", 3)])
    assert calls and calls[0] == "big"
    assert "tiny" not in calls and "small" not in calls


def test_memory_floor_keeps_a_reversible_suspend_against_a_huge_hole(tmp_path):
    calls = _calls_for(tmp_path, "mem", 4000.0, [("marginal", 90), ("enough", 126)])
    assert calls == ["enough"]


def _proc_state(pid: int) -> str:
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    return text.rsplit(")", 1)[1].split()[0]


def _wait_state(pid: int, expected: set[str], timeout: float = 2.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = _proc_state(pid)
        except OSError:
            last = ""
        if last in expected:
            return last
        time.sleep(0.05)
    return last


@pytest.mark.skipif(os.name == "nt", reason="SIGSTOP is the Linux suspend backend")
def test_live_suspend_stops_the_process_and_undo_resumes_it(tmp_path, monkeypatch):
    chrome = tmp_path / "chrome"
    chrome.symlink_to(sys.executable)
    child = subprocess.Popen(
        [str(chrome), "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    home = tmp_path / "home"
    ctrl = JournaledController(home, live=True, spawn_watchdog=False, allow_only={child.pid})
    atexit.unregister(ctrl.resume_all)
    try:
        assert _wait_state(child.pid, {"S", "R"}) in {"S", "R"}
        background = Proc(child.pid, "chrome", 180, idle_s=0, cmdline="chrome")
        _probe, world, engine = rules.build_rules(home, live=False)
        _quiet_env(world, tmp_path)
        world.ctrl = ctrl
        snap = _snap([background], 480.0)
        world.snap = snap
        world.refresh = lambda: snap
        ticks = {"t": 1_000_000.0}
        engine.clock = lambda: ticks["t"]
        offer_path = tmp_path / "perceive" / "offer.json"
        monkeypatch.setattr(helpmod, "OFFER", offer_path)
        published = []
        for _ in range(3):
            world.snap = snap
            published.extend(rules.one_pass(engine, world, home=home, now=ticks["t"]))
            ticks["t"] += rules.POLL_S
            snap.t += rules.POLL_S
            background.idle_s += rules.POLL_S
        assert published and published[-1]["kind"] == "companion"
        assert published[-1]["action_id"]
        assert child.pid in ctrl.suspended
        assert _wait_state(child.pid, {"T", "t"}) in {"T", "t"}
        assert engine.undo(published[-1]["action_id"]) is True
        assert _wait_state(child.pid, {"S", "R"}) in {"S", "R"}
        journal = (home / "rules_undo.jsonl").read_text(encoding="utf-8")
        assert published[-1]["action_id"] in journal
        assert json.loads(offer_path.read_text(encoding="utf-8"))["action_id"] == published[-1]["action_id"]
    finally:
        atexit.unregister(ctrl.resume_all)
        try:
            ctrl.resume(child.pid)
        except Exception:
            pass
        child.kill()
        child.wait(timeout=5)


def test_linux_probe_accumulates_idle_and_ignores_subsecond_samples(monkeypatch):
    if os.name == "nt":
        pytest.skip("the Linux probe is the one that was leaving idle_s at 0")
    monkeypatch.delenv("SPRITE_FORCE_WINPROBE", raising=False)

    class Cpu:
        def __init__(self, seconds: float):
            self.user = seconds
            self.system = 0.0

    class FakeProcess:
        def __init__(self, seconds: float):
            self.info = {
                "pid": 77,
                "name": "chrome",
                "memory_info": type("Mem", (), {"rss": 180 * 2**20})(),
                "ppid": 1,
                "cmdline": ["chrome"],
                "cwd": "/",
                "cpu_times": Cpu(seconds),
            }

    current = {"cpu": 1.0}

    def process_iter(_attrs=None):
        yield FakeProcess(current["cpu"])

    import psutil
    monkeypatch.setattr(psutil, "process_iter", process_iter)
    monkeypatch.setattr(psutil, "pid_exists", lambda _pid: True)
    clock = {"t": 1000.0}
    probe = RealProbe(disks=["/"], clock=lambda: clock["t"])

    def chrome_idle():
        proc = next(item for item in probe.snapshot().procs if item.pid == 77)
        return proc.idle_s

    assert chrome_idle() == 0
    clock["t"] = 1000.4
    assert chrome_idle() == 0
    clock["t"] = 1015.4
    assert chrome_idle() == pytest.approx(15.4)
    current["cpu"] = 3.0
    clock["t"] = 1030.4
    assert chrome_idle() == 0
