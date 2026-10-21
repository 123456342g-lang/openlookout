"""brain 的事实接线：确认三件事
1. brain 能import（reading 被换成 watching/systemfacts 之后没留坏引用）
2. 事实行是拼进 STEP 文本的，不是各自为政
3. 系统压力这条线真的会附给模型——这是视觉看不见的唯一来源
"""
from __future__ import annotations

import inspect

import pytest

from vista.benchmarks.desktop import brain
from vista.benchmarks.desktop import systemfacts, watching


def test_brain_imports_cleanly():
    """reading 已换成 watching + systemfacts，brain 里不该再有活着的 reading 引用。"""
    src = inspect.getsource(brain)
    assert "watching_fact" in src and "system_fact" in src
    # 老名字只允许出现在注释/文档里，不能是活的调用或 import
    assert "from . import reading" not in src
    assert "reading_fact(" not in src
    assert "reading.load" not in src and "reading.save" not in src


def test_watching_fact_is_empty_when_nothing_to_say():
    """没事发生的时候必须是空串——不能让模型每轮都收到废话。"""
    w = watching.Watcher(clock=lambda: 0.0)
    out = brain.watching_fact(w, None, idle_s=0.0)
    assert isinstance(out, str) and out == ""


def test_system_fact_says_nothing_when_calm():
    """系统正常时一个字都不说（硬规则3：宁可安静）。"""
    calm = systemfacts.SystemWatcher(
        disk=lambda *a: dict(ok=True, free_gb=100.0, free_pct=70.0, used_gb=30.0, total_gb=130.0),
        mem=lambda *a: dict(ok=True, avail_gb=12.0, avail_pct=45.0, used_gb=15.0, total_gb=27.0),
        procs=lambda *a, **k: [], clock=lambda: 0.0)
    assert brain.system_fact(calm) == ""


def test_system_fact_speaks_when_critical():
    """C 盘告急必须进到模型那一侧——视觉看不见的只有这条线。"""
    tight = systemfacts.SystemWatcher(
        disk=lambda *a: dict(ok=True, free_gb=0.6, free_pct=0.4, used_gb=148.4, total_gb=149.0),
        mem=lambda *a: dict(ok=True, avail_gb=12.0, avail_pct=45.0, used_gb=15.0, total_gb=27.0),
        procs=lambda *a, **k: [], clock=lambda: 0.0)
    out = brain.system_fact(tight)
    assert "C盘" in out and "0.6" in out, out


def test_this_machine_now():
    """在这台机器上真跑一次，两条线都不许抛异常。"""
    assert isinstance(brain.system_fact(systemfacts.load(brain.COMPANION)), str)
    assert isinstance(brain.watching_fact(watching.load(brain.COMPANION), None), str)


def test_preparation_has_no_fixed_topic_or_daily_service(tmp_path, monkeypatch):
    first = brain.idle_scan_fact(heartbeat=True, idle_s=10.0, now=100.0)
    second = brain.idle_scan_fact(heartbeat=True, idle_s=10.0, now=200.0)
    assert first == second
    assert "自己选择最值得继续的一步" in first
    assert "不要一次性扫完整历史" in first
    assert list(tmp_path.iterdir()) == []


def test_idle_scan_does_not_treat_reading_as_absence(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "COMPANION", tmp_path)
    out = brain.idle_scan_fact(heartbeat=True, idle_s=watching.DEFAULTS["away_s"] + 1, now=100.0)
    assert "可能在阅读或等待" in out
    assert "不把无操作直接当成人已离开" in out


def test_maintenance_signal_wakes_on_pressure_and_clears_on_recovery():
    resources = {"available": 12.0}
    watcher = systemfacts.SystemWatcher(
        disk=lambda: dict(ok=True, free_gb=100.0, free_pct=70.0),
        mem=lambda: dict(ok=True, avail_gb=resources["available"], avail_pct=resources["available"] * 4),
        procs=lambda *args: [])
    signal = brain.MaintenanceSignal(watcher)
    assert signal.observe(0) == ""
    assert not signal.pending
    resources["available"] = 0.5
    assert signal.observe(31)
    assert signal.pending
    signal.consume()
    assert signal.observe(62)
    assert not signal.pending
    resources["available"] = 12.0
    assert signal.observe(93) == ""
    assert not signal.pending
    resources["available"] = 0.4
    assert signal.observe(124)
    assert signal.pending


def test_maintenance_refresh_uses_current_facts_before_decision():
    resources = {"free": 0.6}
    watcher = systemfacts.SystemWatcher(
        disk=lambda: dict(ok=True, free_gb=resources["free"], free_pct=resources["free"]),
        mem=lambda: dict(ok=True, avail_gb=12.0, avail_pct=45.0), procs=lambda *args: [])
    signal = brain.MaintenanceSignal(watcher)
    assert "0.6" in signal.observe(0)
    resources["free"] = 11.0
    assert signal.observe(2, refresh=True) == ""
    assert not signal.pending


def test_maintenance_signal_wakes_when_critical_pressure_changes():
    resources = {"free": 0.77}
    watcher = systemfacts.SystemWatcher(
        disk=lambda: dict(ok=True, free_gb=resources["free"], free_pct=resources["free"]),
        mem=lambda: dict(ok=True, avail_gb=12.0, avail_pct=45.0),
        procs=lambda *args: [],
    )
    signal = brain.MaintenanceSignal(watcher)
    assert signal.observe(0)
    signal.consume()
    assert not signal.pending
    resources["free"] = 0.60
    assert signal.observe(31)
    assert signal.pending


def test_build_defaults_to_direct_and_keeps_the_provider_model(monkeypatch, tmp_path):
    """An empty backend is direct HTTP. It does not call Claude or rewrite the model."""
    from vista.core import runtime as runtime_module

    created = {}

    class RuntimeStub:
        def __init__(self, session, experiment, artifact_dir):
            created["experiment"] = experiment
            self.context = type("Context", (), {})()

    monkeypatch.setattr(runtime_module, "TaskRuntime", RuntimeStub)
    monkeypatch.delenv("OPENLOOKOUT_BACKEND", raising=False)
    monkeypatch.delenv("OPENLOOKOUT_MODEL", raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("create_backend must not run when the backend is unset")

    import vista.backends.claude as claude_pkg
    monkeypatch.setattr(claude_pkg, "create_backend", boom)
    cfg = {"model": "configured-old-model", "base_url": "https://provider.invalid/anthropic",
           "api_key": "synthetic-not-a-secret", "protocol": "anthropic"}
    session, runtime, backend, mode = brain.build(cfg, tmp_path)
    assert mode == "direct-configured"
    assert backend.mode == "direct-configured"
    assert isinstance(backend, brain.VisualDirectBackend)
    assert backend.cfg["model"] == "configured-old-model"
    assert backend.cfg["base_url"] == cfg["base_url"]
    assert backend.cfg["api_key"] == cfg["api_key"]
    assert created["experiment"].model == "configured-old-model"


def test_claude_opt_in_raises_instead_of_falling_back(monkeypatch, tmp_path):
    from vista.core import runtime as runtime_module

    class RuntimeStub:
        def __init__(self, session, experiment, artifact_dir):
            self.context = type("Context", (), {})()

    monkeypatch.setattr(runtime_module, "TaskRuntime", RuntimeStub)
    monkeypatch.setenv("OPENLOOKOUT_BACKEND", "claude")
    monkeypatch.delenv("OPENLOOKOUT_NO_DOCKER_MCP", raising=False)
    monkeypatch.delenv("OPENLOOKOUT_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(brain.shutil, "which", lambda *_args, **_kwargs: None)

    def missing(**_kwargs):
        raise FileNotFoundError("synthetic missing claude")

    import vista.backends.claude.runner as runner
    monkeypatch.setattr(runner, "default_claude_bin", missing)
    cfg = {"model": "configured-old-model", "base_url": "https://provider.invalid/anthropic",
           "api_key": "synthetic-not-a-secret"}
    with pytest.raises(FileNotFoundError, match="synthetic missing claude"):
        brain.build(cfg, tmp_path)


def test_configured_claude_provider_receives_explicit_model():
    from vista.backends.claude.provider import MIMO_PROVIDER, provider_environment

    env = provider_environment(MIMO_PROVIDER, credential="synthetic",
                                model="configured-model-id", effort="low",
                                base_url="https://provider.invalid/anthropic")
    assert env["ANTHROPIC_MODEL"] == "configured-model-id"
    assert env["ANTHROPIC_BASE_URL"] == "https://provider.invalid/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "synthetic"


def test_backend_kind_defaults_to_direct(monkeypatch):
    monkeypatch.delenv("OPENLOOKOUT_BACKEND", raising=False)
    assert brain.backend_kind() == "direct"
    assert brain.backend_kind({"OPENLOOKOUT_BACKEND": ""}) == "direct"
    assert brain.backend_kind({"OPENLOOKOUT_BACKEND": "host"}) == "claude"
    assert brain.backend_kind({"OPENLOOKOUT_BACKEND": "claude"}) == "claude"
    assert brain.backend_kind({"OPENLOOKOUT_BACKEND": "typo"}) == "direct"


def test_backend_kind_accepts_direct_aliases():
    for value in ("direct", "1", " true ", "yes"):
        kind = brain.backend_kind({"OPENLOOKOUT_BACKEND": value})
        assert kind in brain.BACKEND_DIRECT_VALUES, value
    assert "mimo" not in brain.BACKEND_DIRECT_VALUES
    # An unknown name is not a new backend. It stays on direct.
    assert brain.backend_kind({"OPENLOOKOUT_BACKEND": "mimo"}) == "direct"


def test_build_direct_backend_keeps_provider_model_and_skips_claude(monkeypatch, tmp_path):
    """issue #29：OPENLOOKOUT_BACKEND=direct 时直连 provider 端点，保留配置模型，
    既不起本机 claude，也不走 preflight/容器降级。"""
    from vista.core import runtime as runtime_module

    class RuntimeStub:
        def __init__(self, session, experiment, artifact_dir):
            self.context = type("Context", (), {})()

    monkeypatch.setattr(runtime_module, "TaskRuntime", RuntimeStub)
    monkeypatch.setenv("OPENLOOKOUT_BACKEND", "direct")
    monkeypatch.delenv("OPENLOOKOUT_MODEL", raising=False)
    cfg = {"model": "configured-model", "base_url": "https://provider.example/anthropic",
           "api_key": "synthetic-not-a-secret"}
    session, runtime, backend, mode = brain.build(cfg, tmp_path)
    assert mode == "direct-configured"
    assert backend.mode == "direct-configured"
    assert isinstance(backend, brain.VisualDirectBackend)
    assert backend.cfg["model"] == "configured-model"
    assert backend.cfg["base_url"] == cfg["base_url"]
    assert backend.cfg["api_key"] == cfg["api_key"]


def test_build_direct_backend_openlookout_model_overrides(monkeypatch, tmp_path):
    from vista.core import runtime as runtime_module

    class RuntimeStub:
        def __init__(self, session, experiment, artifact_dir):
            self.context = type("Context", (), {})()

    monkeypatch.setattr(runtime_module, "TaskRuntime", RuntimeStub)
    monkeypatch.setenv("OPENLOOKOUT_BACKEND", "direct")
    monkeypatch.setenv("OPENLOOKOUT_MODEL", "explicit-model")
    cfg = {"model": "configured-model", "base_url": "https://provider.example/anthropic",
           "api_key": "synthetic-not-a-secret"}
    _, _, backend, mode = brain.build(cfg, tmp_path)
    assert mode == "direct-configured"
    assert backend.cfg["model"] == "explicit-model"
