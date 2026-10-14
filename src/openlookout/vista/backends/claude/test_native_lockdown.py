"""issue #13 PR1 红线测试：host-native Claude 越权收口。

全部在**命令构造层**断言（不起容器、不联网、不启动真实 claude 进程）：

1. 默认生产 host 命令行：``--tools ""``、allowedTools 只有已注册 MCP 工具，
   不含原生 Edit/Write/MultiEdit/Bash，权限模式 ``default``，整条命令行不含
   ``bypassPermissions`` 字符串；host settings 文件也不含权限旁路；
2. ``OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS`` 开关两条路径：未设置/空串=全禁；
   显式非空才透传（bypassPermissions 依旧不出现）；显式空串（常驻 brain 的
   传法）压过被污染的环境；非法 token 直接 ValueError；
3. run_offer→cli 端到端构造：MCP 工具面（advertised + allowedTools）等于
   已注册 desktop_* 白名单，companion/basic_shell/inspect 不可见；
   白名单参数走私（companion、basic_shell、非法名、未注册名）一律拒绝；
4. 常驻 brain 路径：不传白名单时完整 MCP 面保留，但原生工具默认仍全禁。
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import certifi
import pytest
from PIL import Image

from vista.backends.claude import runner as rmod
from vista.backends.claude.factory import create_backend
from vista.backends.claude.mcp_host import ClaudeGameMcpHost
from vista.backends.claude.provider import LOCAL_HOST_PROVIDER
from vista.backends.claude.runner import (
    CLAUDE_PERMISSION_MODE,
    NATIVE_UNSAFE_BUILTIN_TOOLS,
    ClaudeCodeRunner,
    host_passthrough_environment,
    normalize_host_mcp_allowlist,
    resolve_host_builtin_tools,
    validate_instruction_envelope,
)
from vista.core.dispatcher import ToolExecution
from vista.core.player import ToolInterface

UNSAFE_NATIVE = {"Bash", "Edit", "Write", "MultiEdit"}
CA_BUNDLE = Path(certifi.where())

# 同时覆盖桌面动作工具、回合控制与只读 basic_*，模拟真实 runtime 的注册面。
ALL_TOOL_NAMES = (
    "desktop_inventory",
    "desktop_tidy",
    "desktop_reclaim",
    "desktop_plan",
    "companion",
    "basic_shell",
    "basic_time",
    "inspect",
    "write_working",
)


def _flag_value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def assert_native_tools_absent(argv: list[str]) -> None:
    """红线：--tools/--allowedTools 不含任何原生写/命令工具。"""
    tools_value = _flag_value(argv, "--tools")
    allowed_value = _flag_value(argv, "--allowedTools")
    assert tools_value == ""
    allowed = allowed_value.split(",")
    assert allowed and all(tool.startswith("mcp__game__") for tool in allowed)
    assert NATIVE_UNSAFE_BUILTIN_TOOLS.isdisjoint(allowed)
    # 扩展到两个 flag 的全部逗号 token，防止换个位置夹带。
    tokens = set(tools_value.split(",")) | set(allowed_value.split(","))
    assert NATIVE_UNSAFE_BUILTIN_TOOLS.isdisjoint(tokens)


def assert_no_bypass(argv: list[str]) -> None:
    joined = "\0".join(argv)
    assert "bypassPermissions" not in joined
    assert _flag_value(argv, "--permission-mode") == CLAUDE_PERMISSION_MODE == "default"


@pytest.fixture
def make_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE", "1")
    monkeypatch.delenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", raising=False)

    def _make(*, explicit_builtins=None, allowlist=None, host_mode=True, defs=None):
        root = tmp_path / f"runner-{len(list(tmp_path.iterdir()))}"
        visible = root / "visible"
        (visible / "screenshots").mkdir(parents=True)
        (visible / "GUIDE.md").write_text("guide", encoding="utf-8")
        (visible / "AGENTS.md").write_text("agents instructions", encoding="utf-8")
        state = root / "state"
        state.mkdir(parents=True)
        io_dir = root / "io"
        io_dir.mkdir()
        names = ALL_TOOL_NAMES if defs is None else defs
        interface = ToolInterface(
            definitions=tuple({"name": name} for name in names),
            executor=object(),
            action_tools=frozenset(),
            visual_readers=frozenset(),
            predict_images=lambda name, arguments: 0,
            acknowledge=lambda call_id: None,
        )
        kwargs = dict(
            visible_dir=visible,
            claude_config_dir=state,
            io_dir=io_dir,
            controller=SimpleNamespace(reset_starts_fresh_session=False),
            tool_interface=interface,
            claude_bin=root / "claude",
            ca_bundle=CA_BUNDLE,
            model="opus",
            effort="low",
            provider=LOCAL_HOST_PROVIDER,
            host_mode=host_mode,
        )
        if explicit_builtins is not None:
            kwargs["host_builtin_tools"] = explicit_builtins
        if allowlist is not None:
            kwargs["host_mcp_allowlist"] = allowlist
        runner = ClaudeCodeRunner(**kwargs)
        return runner, root

    return _make


def _host_command(runner, root: Path) -> list[str]:
    return runner._host_command(
        mcp_config_path=root / "mcp.json",
        settings_path=root / "settings.json",
        socket_dir=root,
        session_id="session-1",
        resume=False,
    )


# ── 纯函数：env 开关语义 ────────────────────────────────────────────────────


def test_resolve_builtins_unset_and_empty_mean_locked(monkeypatch):
    monkeypatch.delenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", raising=False)
    assert resolve_host_builtin_tools(None) == []
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "")
    assert resolve_host_builtin_tools(None) == []
    assert resolve_host_builtin_tools("") == []


def test_resolve_builtins_explicit_env_passes_through(monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", " Bash, Read ,Read,Glob ")
    assert resolve_host_builtin_tools(None) == ["Bash", "Read", "Glob"]


def test_resolve_builtins_explicit_empty_beats_polluted_env(monkeypatch):
    # 常驻 brain 显式传 ""：即使父进程环境被污染也必须锁死。
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash,Edit")
    assert resolve_host_builtin_tools("") == []


@pytest.mark.parametrize(
    "value",
    ["Bash;rm", "--permission-mode", "mcp__game__desktop_tidy", "Edit Write"],
)
def test_resolve_builtins_rejects_non_tool_tokens(monkeypatch, value):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", value)
    with pytest.raises(ValueError):
        resolve_host_builtin_tools(None)


def test_constants_are_locked_down():
    assert rmod.HOST_PERMISSION_MODE == "default"
    assert rmod.HOST_BUILTIN_TOOLS == ""
    assert NATIVE_UNSAFE_BUILTIN_TOOLS == {"Bash", "Edit", "Write", "MultiEdit"}


# ── 红线 1：默认生产 host 命令行 ─────────────────────────────────────────────


def test_default_host_command_is_locked(make_runner):
    runner, root = make_runner()
    argv = _host_command(runner, root)

    assert_native_tools_absent(argv)
    assert_no_bypass(argv)
    # 默认（brain 风格，不传白名单）保留完整已注册 MCP 面，但那是经闸门的工具。
    allowed = set(_flag_value(argv, "--allowedTools").split(","))
    assert "mcp__game__companion" in allowed
    assert "mcp__game__desktop_tidy" in allowed
    assert "--strict-mcp-config" in argv
    assert _flag_value(argv, "--setting-sources") == ""


def test_host_settings_file_has_no_permission_bypass(make_runner):
    runner, root = make_runner()
    settings = root / "settings.json"
    runner._write_settings(settings, "compact.jsonl")
    text = settings.read_text(encoding="utf-8")
    assert "bypassPermissions" not in text
    assert "permissions" not in text.lower()


# ── 红线 2：env 开关两条路径 ─────────────────────────────────────────────────


def test_env_optin_enables_exactly_listed_native_tools(make_runner, monkeypatch):
    monkeypatch.setenv(
        "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Read,Bash,Edit,Write,MultiEdit"
    )
    runner, root = make_runner()
    argv = _host_command(runner, root)

    assert _flag_value(argv, "--tools") == "Read,Bash,Edit,Write,MultiEdit"
    allowed = set(_flag_value(argv, "--allowedTools").split(","))
    assert {"Read", "Bash", "Edit", "Write", "MultiEdit"} <= allowed
    # 显式本地开发也不复活 bypassPermissions：靠 --allowedTools 显式放行。
    assert_no_bypass(argv)


def test_env_optin_does_not_grant_unlisted_tools(make_runner, monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Read,Glob")
    runner, root = make_runner()
    argv = _host_command(runner, root)
    allowed = set(_flag_value(argv, "--allowedTools").split(","))
    assert {"Read", "Glob"} <= allowed
    assert UNSAFE_NATIVE.isdisjoint(allowed)


def test_explicit_empty_argument_locks_even_with_env(make_runner, monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash,Write")
    runner, root = make_runner(explicit_builtins="")
    argv = _host_command(runner, root)
    assert_native_tools_absent(argv)
    assert_no_bypass(argv)


def test_invalid_env_value_fails_construction(make_runner, monkeypatch):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash --danger")
    with pytest.raises(ValueError):
        make_runner()


# ── 红线 3：desktop_* MCP 白名单 ─────────────────────────────────────────────


def test_mcp_allowlist_restricts_command_and_advertised_surface(make_runner):
    runner, root = make_runner(allowlist=frozenset({"desktop_inventory", "desktop_tidy"}))
    argv = _host_command(runner, root)

    allowed = set(_flag_value(argv, "--allowedTools").split(","))
    assert allowed == {"mcp__game__desktop_inventory", "mcp__game__desktop_tidy"}
    advertised = {tool["name"] for tool in runner._host_tool_interface().definitions}
    assert advertised == {"desktop_inventory", "desktop_tidy"}
    assert_native_tools_absent(argv)
    assert_no_bypass(argv)


@pytest.mark.parametrize(
    "names",
    [
        ["companion"],
        ["basic_shell"],
        ["inspect"],
        ["desktop_"],
        ["desktop_tidy;reboot"],
        ["mcp__game__desktop_tidy"],
    ],
)
def test_mcp_allowlist_rejects_non_desktop_names(names):
    with pytest.raises(ValueError):
        normalize_host_mcp_allowlist(names, registered={"desktop_tidy", "desktop_inventory"})


def test_mcp_allowlist_rejects_unregistered_names(make_runner):
    with pytest.raises(ValueError):
        make_runner(allowlist=frozenset({"desktop_does_not_exist"}))


def test_mcp_allowlist_requires_host_mode(make_runner):
    with pytest.raises(ValueError):
        make_runner(
            host_mode=False,
            allowlist=frozenset({"desktop_tidy"}),
        )


# ── cli 端到端构造（run_offer→cli 真实工厂路径，不联网/不起进程）──────────────


def _cli_runtime_and_backend(tmp_path, monkeypatch, *, builtins=""):
    """复刻 run.py + cli.factory 的真实构造链。

    ``builtins`` 默认空串：这正是 cli.py 现在无条件传给 create_backend 的
    值（review P1-1 修复），即使进程 env 被污染也不读环境。
    """
    monkeypatch.setenv("OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE", "1")
    monkeypatch.delenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", raising=False)

    from vista.core.contracts import Visual
    from vista.core.runtime import TaskRuntime
    from vista.benchmarks.desktop.session import DesktopSession
    from vista.benchmarks.desktop.profiles import make_experiment, make_profile

    image_bytes = io.BytesIO()
    Image.new("RGB", (16, 9), color=(0, 0, 0)).save(image_bytes, format="JPEG")
    visual = Visual("screen", "screen-1", image_bytes.getvalue(), 16, 9, "image/jpeg")
    session = DesktopSession(
        "测试目标", {"read_only": False}, visual=visual
    )
    profile = make_profile()
    experiment = make_experiment(
        profile,
        backend="claude",
        model="opus",
        effort="low",
        revision="0.1",
        presentation={"objective": "测试目标", "context": {"read_only": False}},
    )
    root = tmp_path / "run"
    root.mkdir()
    runtime = TaskRuntime(session, experiment, artifact_dir=root / "artifacts")
    try:
        # 与 cli.py factory 闭包里同一推导式。
        desktop_tools = frozenset(
            spec.name for spec in runtime.specs if spec.name.startswith("desktop_")
        )
        assert desktop_tools, "runtime 必须注册 desktop_* 工具"
        backend = create_backend(
            runtime,
            directory=root / "transport",
            oauth_token=None,
            binary=root / "claude",
            image="arc3-claude-player:0.1",
            provider=LOCAL_HOST_PROVIDER,
            provider_credential=None,
            provider_base_url=None,
            max_output_tokens=2048,
            ca_bundle=CA_BUNDLE,
            host_mode=True,
            host_builtin_tools=builtins,
            host_mcp_allowlist=desktop_tools,
        )
    finally:
        runtime.close()
    return backend, desktop_tools, root


def test_cli_factory_builds_exact_desktop_whitelist(tmp_path, monkeypatch):
    backend, desktop_tools, root = _cli_runtime_and_backend(tmp_path, monkeypatch)
    runner = backend.runner
    argv = _host_command(runner, root / "transport" / "state")

    allowed = set(_flag_value(argv, "--allowedTools").split(","))
    expected = {f"mcp__game__{name}" for name in desktop_tools}
    assert allowed == expected
    assert all(tool.startswith("mcp__game__desktop_") for tool in allowed)
    advertised = {tool["name"] for tool in runner._host_tool_interface().definitions}
    assert advertised == desktop_tools

    # 越权面：回合控制/basic_*/harness 工具在 run_offer 子进程里不可见。
    for hidden in ("companion", "basic_shell", "basic_time", "inspect", "write_working"):
        assert f"mcp__game__{hidden}" not in allowed
        assert hidden not in advertised

    # 白名单必须含真正干活的 gated/台账工具。
    for required in (
        "desktop_plan",
        "desktop_tidy",
        "desktop_reclaim",
        "desktop_write_deliverable",
        "desktop_capture_evidence",
        "desktop_undo",
    ):
        assert required in desktop_tools

    assert _flag_value(argv, "--tools") == ""
    assert_no_bypass(argv)


def test_cli_factory_brain_style_empty_builtins_beat_env(tmp_path, monkeypatch):
    # 常驻 brain 显式 "" + 父进程环境污染：命令仍必须锁死。
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash,Edit,Write")
    backend, _desktop_tools, root = _cli_runtime_and_backend(
        tmp_path, monkeypatch, builtins=""
    )
    argv = _host_command(backend.runner, root / "transport" / "state")
    assert _flag_value(argv, "--tools") == ""
    assert_no_bypass(argv)


def test_cli_real_argument_blocks_env_smuggling(tmp_path, monkeypatch, capsys):
    """review P1-1 红线：cli 真实传参（无条件 ""）+ 污染 env。

    场景：本机曾为本地开发 setx OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS=Bash，
    run_offer 子进程继承该变量；cli 的工厂现在无条件传 ""，命令行、
    allowedTools、MCP 广告面都不得出现任何原生工具，也不打 WARNING。
    """
    monkeypatch.setenv(
        "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash,Edit,Write,MultiEdit"
    )
    # 注意：不传 builtins，走 helper 默认 ""——与 cli.py 现在的写法一致。
    backend, desktop_tools, root = _cli_runtime_and_backend(tmp_path, monkeypatch)
    runner = backend.runner
    argv = _host_command(runner, root / "transport" / "state")

    assert _flag_value(argv, "--tools") == ""
    assert_native_tools_absent(argv)
    assert_no_bypass(argv)
    advertised = {tool["name"] for tool in runner._host_tool_interface().definitions}
    assert advertised == desktop_tools
    assert "WARNING" not in capsys.readouterr().out


def test_cli_source_wires_the_allowlist():
    """防回潮：cli.py 必须把白名单与空串实参真的传给 create_backend。"""
    cli_path = Path(__file__).resolve().parents[2] / "benchmarks" / "desktop" / "cli.py"
    source = cli_path.read_text(encoding="utf-8")
    assert 'spec.name.startswith("desktop_")' in source
    assert "host_mcp_allowlist=desktop_tools" in source
    # review P1-1：必须无条件显式空串，不能依赖 runner 默认读 env。
    assert 'host_builtin_tools=""' in source
    assert "create_backend" in source


def test_cli_help_epilog_documents_that_native_env_is_ignored(capsys):
    """复审非阻塞 P2：无人值守入口 --help 必须如实写明该 env 在此入口被忽略。"""
    from vista.benchmarks.desktop.cli import main

    # --help 在 parse_args 阶段 SystemExit(0)，早于 provider 加载，不会联网。
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS" in help_text
    assert "也会被忽略" in help_text
    # 不得再保留旧的误导措辞（「可设置以透传原生工具」）。
    assert "仅本地开发可显式设置环境变量" not in help_text
    assert "禁止设置" not in help_text


# ── review P1-2：MCP 服务端成员校验（tools/call 不只靠客户端自律）──────────────


def _mcp_host(tmp_path, *, definitions, use_interface=True):
    executed: list[str] = []

    def _execute(name, arguments, call_id):
        executed.append(name)
        return ToolExecution(f"executed {name}", True)

    dispatcher = SimpleNamespace(execute=_execute, controller=None)
    kwargs = dict(
        socket_path=tmp_path / "controller.sock",
        token="secret-token",
        dispatcher=dispatcher,
        display_size=16,
        log_path=tmp_path / "mcp-host.log",
    )
    if use_interface:
        kwargs["tool_interface"] = ToolInterface(
            definitions=tuple(definitions),
            executor=object(),
            action_tools=frozenset(),
            visual_readers=frozenset(),
            predict_images=lambda name, arguments: 0,
            acknowledge=lambda call_id: None,
        )
    else:
        kwargs["tool_definitions"] = list(definitions)
    host = ClaudeGameMcpHost(**kwargs)
    host.calls_enabled.set()
    return host, executed


def _tool_def(name):
    return {
        "name": name,
        "description": f"test tool {name}",
        "inputSchema": {"type": "object"},
    }


def test_mcp_call_rejects_unadvertised_tool_without_dispatch(tmp_path):
    host, executed = _mcp_host(
        tmp_path, definitions=[_tool_def("desktop_tidy")]
    )
    # tools/list 的广告面确实只有 desktop_tidy。
    listed = host._handle({"token": "secret-token", "method": "tools/list"})
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["desktop_tidy"]

    for hidden in ("companion", "basic_shell", "inspect", "desktop_reclaim"):
        request = {
            "token": "secret-token",
            "method": "tools/call",
            "name": hidden,
            "request_id": f"id-{hidden}",
            "arguments": {},
        }
        with pytest.raises(PermissionError):
            host._handle(request)
    assert executed == []

    # 广告面内的工具正常分发执行。
    response = host._handle(
        {
            "token": "secret-token",
            "method": "tools/call",
            "name": "desktop_tidy",
            "request_id": "id-ok",
            "arguments": {},
        }
    )
    assert executed == ["desktop_tidy"]
    assert response["execution"]["success"] is True


def test_mcp_call_rejects_when_no_definitions_supplied(tmp_path):
    # 双 None：fail-closed，任何调用都过不了成员校验。
    host, executed = _mcp_host(
        tmp_path, definitions=[], use_interface=False
    )
    host.tool_definitions = None
    with pytest.raises(PermissionError):
        host._handle(
            {
                "token": "secret-token",
                "method": "tools/call",
                "name": "desktop_tidy",
                "request_id": "id-x",
                "arguments": {},
            }
        )
    assert executed == []


def test_mcp_call_membership_uses_explicit_definitions_fallback(tmp_path):
    # 旧形态：不传 tool_interface、只传 tool_definitions，成员校验同样生效。
    host, executed = _mcp_host(
        tmp_path,
        definitions=[_tool_def("desktop_inventory")],
        use_interface=False,
    )
    with pytest.raises(PermissionError):
        host._handle(
            {
                "token": "secret-token",
                "method": "tools/call",
                "name": "companion",
                "request_id": "id-c",
                "arguments": {},
            }
        )
    response = host._handle(
        {
            "token": "secret-token",
            "method": "tools/call",
            "name": "desktop_inventory",
            "request_id": "id-s",
            "arguments": {},
        }
    )
    assert executed == ["desktop_inventory"]
    assert response["execution"]["success"] is True


# ── review P2-1：settings env 块按白名单搬运 + 控制变量不进 claude 子进程 ──────


def test_host_passthrough_settings_env_is_whitelisted(tmp_path, monkeypatch):
    claude_home = tmp_path / "home"
    (claude_home / ".claude").mkdir(parents=True)
    (claude_home / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://provider.example/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "settings-token",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "provider-opus",
                    "ANTHROPIC_MODEL": "provider-model",
                    "API_TIMEOUT_MS": "1000",
                    "CLAUDE_CODE_DANGEROUSLY_SKIP_PERMISSIONS": "1",
                    "RANDOM_TOOL_VAR": "evil",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        rmod.Path, "home", classmethod(lambda cls: claude_home)
    )
    child = host_passthrough_environment(
        environ={
            "PATH": "/usr/bin",
            "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS": "Bash",
        }
    )
    # 白名单键（含 ANTHROPIC_DEFAULT_ 前缀）透传。
    assert child["ANTHROPIC_BASE_URL"] == "https://provider.example/anthropic"
    assert child["ANTHROPIC_AUTH_TOKEN"] == "settings-token"
    assert child["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "provider-opus"
    assert child["ANTHROPIC_MODEL"] == "provider-model"
    # settings 里的非供应商/权限类键一律不搬。
    assert "API_TIMEOUT_MS" not in child
    assert "CLAUDE_CODE_DANGEROUSLY_SKIP_PERMISSIONS" not in child
    assert "RANDOM_TOOL_VAR" not in child
    # 普通继承环境保留，但我们的原生工具控制变量不得进入 claude 二进制子进程。
    assert child["PATH"] == "/usr/bin"
    assert "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS" not in child


def test_host_passthrough_missing_settings_keeps_environ(tmp_path, monkeypatch):
    claude_home = tmp_path / "empty-home"
    claude_home.mkdir()
    monkeypatch.setattr(rmod.Path, "home", classmethod(lambda cls: claude_home))
    child = host_passthrough_environment(environ={"PATH": "/usr/bin"})
    assert child == {"PATH": "/usr/bin"}


# ── review P2-2：env 非法值/WARNING 只作用于 host 构造，不误杀 Docker 路径 ─────


def test_invalid_native_tools_env_does_not_break_docker_runner(make_runner, monkeypatch, capsys):
    monkeypatch.setenv("OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS", "Bash --danger")
    # 非 host（Docker）构造必须成功：容器命令行硬编码 --tools ""，
    # 这个本地开发变量与它无关。
    runner, _root = make_runner(host_mode=False)
    assert runner.host_mode is False
    assert runner.host_builtin_tools == []
    assert runner.host_mcp_allowlist is None
    assert "WARNING" not in capsys.readouterr().out


# ── review P2-3：host 信封工具面精确匹配（生产形态）/ builtins 豁免（开发形态）─


def _host_envelope(tools):
    return {
        "_openlookout_host_mode": True,
        "tools": tools,
        "mcp_servers": [{"name": "game", "status": "connected"}],
        "permissionMode": "default",
        "slash_commands": [],
    }


def test_host_envelope_production_form_must_match_exactly():
    definitions = [{"name": "desktop_tidy"}, {"name": "desktop_inventory"}]
    expected = ["mcp__game__desktop_tidy", "mcp__game__desktop_inventory"]

    validate_instruction_envelope(
        _host_envelope(expected),
        display_size=16,
        tool_definitions=definitions,
    )

    # 未来某版 claude 若让 --tools "" 失效、多广告出原生工具：直接失败。
    with pytest.raises(RuntimeError):
        validate_instruction_envelope(
            _host_envelope(expected + ["Bash"]),
            display_size=16,
            tool_definitions=definitions,
        )
    # 缺一个 MCP 工具（桥接面被缩减）也失败。
    with pytest.raises(RuntimeError):
        validate_instruction_envelope(
            _host_envelope(["mcp__game__desktop_tidy"]),
            display_size=16,
            tool_definitions=definitions,
        )
    # 夹带别的 MCP 服务器工具同样失败。
    with pytest.raises(RuntimeError):
        validate_instruction_envelope(
            _host_envelope(expected + ["mcp__other__x"]),
            display_size=16,
            tool_definitions=definitions,
        )


def test_host_envelope_dev_form_allows_only_explicit_builtins():
    definitions = [{"name": "desktop_tidy"}]
    expected = ["mcp__game__desktop_tidy"]

    # 显式本地开发形态：额外工具必须恰好是本次放开的 builtins 名单。
    validate_instruction_envelope(
        _host_envelope(expected + ["Read", "Bash"]),
        display_size=16,
        tool_definitions=definitions,
        host_allowed_builtin_tools=["Read", "Bash"],
    )
    # 名单外的原生工具（env 没给）不豁免。
    with pytest.raises(RuntimeError):
        validate_instruction_envelope(
            _host_envelope(expected + ["Read", "Glob"]),
            display_size=16,
            tool_definitions=definitions,
            host_allowed_builtin_tools=["Read"],
        )
