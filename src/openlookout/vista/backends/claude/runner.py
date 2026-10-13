"""Run one visual-game trajectory through Claude Code and native MCP."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import os
import queue
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from vista.backends.claude.mcp_host import ClaudeGameMcpHost
from vista.backends.claude.provider import (
    ANTHROPIC_PROVIDER,
    PROVIDER_ENV_NAMES,
    ClaudeCodeProvider,
    provider_environment,
)
from vista.backends.claude.quota import (
    ClaudeRateLimitEvent,
    rate_limit_event_from_message,
)
from vista.core.dispatcher import GameToolDispatcher
from vista.core.player import RecoveryPrompts, ToolInterface
from vista.core.session import CompactRecovery, RetryRecovery, RuntimeRecovery
from vista.core.timeouts import (
    ENV_CONNECT_RETRIES as ARC_CONNECT_RETRIES,
    ENV_CONNECT_TIMEOUT_SECONDS as ARC_CONNECT_TIMEOUT_SECONDS,
    ENV_READ_TIMEOUT_SECONDS as ARC_READ_TIMEOUT_SECONDS,
)

PLAYER_IMAGE = "arc3-claude-player:0.1"
CONTAINER_CLAUDE_BIN = "/opt/claude/claude"
# ── 宿主机模式工具/权限收口（issue #13 PR1）──────────────────────────────────
# 宿主机模式没有 Docker 沙箱。生产默认（未设置或空串）**一个** Claude 原生内建
# 工具都不放开：``--tools ""`` 禁用全部内建工具，模型只能触达已注册、经风险门与
# 撤销台账约束的 mcp__game__* MCP 工具。原生 Edit/Write/MultiEdit/Bash 绝不允许
# 出现在无人值守生产命令行里。
#
# 唯一例外是显式本地开发：本机环境设置非空的
# OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS="Read,Glob,..." 才透传。无人值守环境放开
# 这些工具 = 模型可直接改本机任意文件/执行任意命令，禁止在生产（含常驻 brain 的
# 运行环境与普通 run_offer）设置。
ENV_HOST_BUILTIN_TOOLS = "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS"
HOST_BUILTIN_TOOLS = ""
# 原生工具里具备直接写盘/执行能力的集合；命令行红线测试按这个集合断言。
NATIVE_UNSAFE_BUILTIN_TOOLS = frozenset({"Bash", "Edit", "Write", "MultiEdit"})
# 宿主机模式与容器模式一致，固定 default：--allowedTools 白名单之外的工具在
# ``-p`` 无人值守下会被自动拒绝。永不使用无约束 bypassPermissions。
HOST_PERMISSION_MODE = "default"
# 无人值守一次性任务（run_offer→cli）的 MCP 工具只允许 desktop_* 前缀的已注册
# 工具；companion / basic_* / inspect 等在该路径一律不可见。
HOST_MCP_ALLOWLIST_PREFIX = "desktop_"
_BUILTIN_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_DESKTOP_TOOL_NAME_RE = re.compile(r"^desktop_[a-z0-9_]+$")
CONTAINER_MCP_BRIDGE = "/opt/arc3/claude_mcp_bridge.py"
CONTAINER_COMPACT_HOOK = "/opt/arc3/claude_compact_hook.py"
PINNED_CLAUDE_VERSION = "2.1.220"
DEFAULT_PINNED_CLAUDE_BIN = (
    Path.home() / ".local" / "share" / "claude" / "versions" / PINNED_CLAUDE_VERSION
)
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CLAUDE_EFFORT = "xhigh"
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_PERMISSION_MODE = "default"
MAX_MCP_OUTPUT_TOKENS = 100_000
CLAUDE_PROVIDER_IMAGE_LIMIT = 600
CLAUDE_PROVIDER_IMAGE_COMPACT_AT = CLAUDE_PROVIDER_IMAGE_LIMIT - 1
CLAUDE_AUTO_COMPACT_WINDOW = 1_000_000
CLAUDE_AUTO_COMPACT_PERCENT = 90
DEFAULT_DECISION_LEASE_TIMEOUT_SECONDS = 120 * 60
PLAY_SETTLEMENT_TIMEOUT_SECONDS = (
    ARC_READ_TIMEOUT_SECONDS
    + ARC_CONNECT_TIMEOUT_SECONDS * (ARC_CONNECT_RETRIES + 1)
    + 5
)
CREDENTIAL_ENV_NAMES = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ARC_API_KEY",
)
RUNTIME_PREFLIGHT_PROMPT = (
    "This is a runtime preflight, not a game. Do not call tools. Reply exactly READY."
)


@dataclass(frozen=True)
class ClaudeUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float | None
    num_turns: int | None


@dataclass(frozen=True)
class ClaudeResult:
    segment: int
    returncode: int
    process_returncode: int
    final_message: str
    session_id: str | None
    resolved_models: tuple[str, ...]
    stdout_path: Path
    stderr_path: Path
    input_path: Path
    command_path: Path
    bridge_log_path: Path
    compact_events_path: Path
    usage: ClaudeUsage | None
    api_error_status: int | None = None
    session_image_blocks: int = 0
    peak_session_image_blocks: int = 0
    reset_boundary: bool = False
    context_boundary: str | None = None
    init_envelope: dict[str, Any] | None = None
    compact_boundaries: tuple[dict[str, Any], ...] = ()
    decision_lease_failure: str | None = None
    unconfirmed_play_calls: int = 0
    rate_limit_events: tuple[ClaudeRateLimitEvent, ...] = ()


@dataclass
class DecisionLeaseWatchdog:
    timeout_seconds: float
    started_at: float
    completed_tool_calls: int = 0

    def expired(
        self,
        *,
        now: float,
        completed_tool_calls: int,
        tool_calls_in_flight: int,
        last_tool_completed_at: float | None,
    ) -> bool:
        if completed_tool_calls != self.completed_tool_calls:
            self.completed_tool_calls = completed_tool_calls
            self.started_at = last_tool_completed_at or now
        if tool_calls_in_flight:
            return False
        return now - self.started_at >= self.timeout_seconds


class ClaudePreflightController:
    """A non-game controller used to initialize the exact formal runtime."""

    compact_restore_marker = None
    compact_checkpoint_marker = None
    retry_boundary_pending = False
    reset_starts_fresh_session = False

    @staticmethod
    def initial_image_paths() -> tuple[Path, ...]:
        return ()

    @staticmethod
    def handle(request: object) -> dict[str, Any]:
        return {
            "ok": False,
            "metadata": {
                "error": "Game tools are unavailable during runtime preflight."
            },
        }


def default_claude_bin(*, fallback: Path | None = None) -> Path:
    # Prefer an explicitly configured host executable, then a native Claude
    # installation discoverable on PATH.  This is required on Windows where
    # Claude is commonly installed as claude.exe/claude.cmd rather than the
    # pinned Linux binary used by the Docker player.
    configured = (os.getenv("OPENLOOKOUT_CLAUDE_BIN") or
                  os.getenv("CLAUDE_CODE_BIN") or
                  os.getenv("ARC3_CLAUDE_BIN"))
    discovered = shutil.which("claude") or shutil.which("claude.cmd")
    candidate = (Path(configured).expanduser() if configured else
                 Path(discovered).expanduser() if discovered else
                 DEFAULT_PINNED_CLAUDE_BIN if fallback is None else fallback)
    if not candidate.is_file() or (os.name != "nt" and not os.access(candidate, os.X_OK)):
        raise FileNotFoundError(
            f"Claude Code executable was not found at {candidate}."
        )
    return candidate.resolve()


def credential_free_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    child = dict(os.environ if environ is None else environ)
    for name in tuple(child):
        if name in CREDENTIAL_ENV_NAMES or name.startswith("CLAUDE_CODE_OAUTH_TOKEN_"):
            child.pop(name)
    return child


def claude_version(binary: Path | None = None) -> str:
    executable = (binary or default_claude_bin()).resolve()
    if os.name == "nt":
        # The Claude binary is a Linux build that Windows cannot execute, so
        # probe it inside the player image it will run in.
        argv = [
            "docker", "run", "--rm", "--pull=never", "--network", "none",
            "-v", f"{executable}:{CONTAINER_CLAUDE_BIN}:ro",
            "--entrypoint", CONTAINER_CLAUDE_BIN, PLAYER_IMAGE, "--version",
        ]
    else:
        argv = [str(executable), "--version"]
    result = subprocess.run(
        argv,
        text=True,
        capture_output=True,
        check=True,
        env=credential_free_environment(),
    )
    output = result.stdout.strip()
    return output.split()[0] if output else ""


def validate_claude_runtime(
    binary: Path | None = None,
    *,
    oauth_token: str | None = None,
    provider: ClaudeCodeProvider = ANTHROPIC_PROVIDER,
    provider_credential: str | None = None,
) -> Path:
    executable = (binary or default_claude_bin()).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Claude Code binary not found at {executable}")
    version = claude_version(executable)
    if version != PINNED_CLAUDE_VERSION:
        raise RuntimeError(
            f"Claude Code {PINNED_CLAUDE_VERSION} is required; found {version or 'unknown'}."
        )
    if provider.native:
        token = (
            oauth_token
            if oauth_token is not None
            else os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
        )
        if not token:
            raise RuntimeError(
                "CLAUDE_CODE_OAUTH_TOKEN is not set; run `claude setup-token` and "
                "export the generated subscription token."
            )
        return executable
    credential = (
        provider_credential
        if provider_credential is not None
        else os.getenv(provider.credential_env)
    )
    if not credential:
        raise RuntimeError(f"{provider.credential_env} is not set.")
    return executable


def claude_process_environment(
    oauth_token: str,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment containing only the assigned Claude credential."""

    if not oauth_token:
        raise ValueError("Claude OAuth token must not be empty")
    child = credential_free_environment(environ)
    child["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    return child


def host_passthrough_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """宿主机供应商透传环境（host_mode + LOCAL_HOST_PROVIDER 专用）。

    VISTA 不再持有任何凭据：claude 子进程继承当前进程环境，并叠加本机
    ``~/.claude/settings.json`` 的 ``env`` 块（ANTHROPIC_BASE_URL /
    ANTHROPIC_AUTH_TOKEN / ANTHROPIC_DEFAULT_*_MODEL 别名档）。
    注意 CLAUDE_CONFIG_DIR 在宿主机模式下指向项目隔离目录，settings 文件
    本身不会被 claude 读取，所以 env 块必须在这里显式搬过去。
    """

    child = dict(os.environ if environ is None else environ)
    settings = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        block = data.get("env")
        if isinstance(block, dict):
            for name, value in block.items():
                if isinstance(name, str) and isinstance(value, str):
                    child[name] = value
    except (OSError, ValueError):
        # 读不到本机配置时保持继承环境不变：由调用方/用户自行保证可用。
        pass
    return child


def provider_process_environment(
    variables: dict[str, str],
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """A child environment selecting exactly one model provider.

    Every variable that could redirect Claude Code to another endpoint or
    credential is removed first, so a run cannot inherit a token or a base
    URL that some earlier run left in the environment.
    """
    child = credential_free_environment(environ)
    for name in tuple(child):
        if name in PROVIDER_ENV_NAMES or name.startswith("ANTHROPIC_DEFAULT_"):
            child.pop(name)
    child.update(variables)
    return child


def prepare_claude_config(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    return target.resolve()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def create_short_socket_dir(segment: int) -> Path:
    """Create a private host path that stays below the AF_UNIX path limit."""

    directory = Path(tempfile.mkdtemp(prefix=f"arc3-claude-{segment:03d}-"))
    directory.chmod(0o700)
    socket_path = directory / "controller.sock"
    if len(os.fsencode(socket_path)) >= 100:
        shutil.rmtree(directory, ignore_errors=True)
        raise RuntimeError("Unable to create a sufficiently short game socket path.")
    return directory


def resolve_host_builtin_tools(explicit: str | None) -> list[str]:
    """Resolve the host-mode native-tool allow list (issue #13 PR1).

    ``None`` means "take the explicit local-dev environment value"; an empty
    string (brain passes one deliberately) means "locked even when the
    environment is polluted".  Unset/empty resolves to no native tools at all.
    Every token must be a plain PascalCase tool name, so neither CLI flags nor
    ``mcp__*`` permission rules can be smuggled through the env value.
    """

    raw = os.environ.get(ENV_HOST_BUILTIN_TOOLS, "") if explicit is None else explicit
    names: list[str] = []
    for token in str(raw or "").split(","):
        name = token.strip()
        if not name:
            continue
        if not _BUILTIN_TOOL_NAME_RE.fullmatch(name) or name.startswith("mcp__"):
            raise ValueError(
                f"{ENV_HOST_BUILTIN_TOOLS} contains an invalid tool name {name!r}; "
                "use a comma-separated list of Claude Code built-in tool names only."
            )
        if name not in names:
            names.append(name)
    return names


def normalize_host_mcp_allowlist(
    allowlist: "Collection[str] | None",
    *,
    registered: "Collection[str] | None",
) -> "frozenset[str] | None":
    """Validate the unattended host MCP allow list.

    Only registered ``desktop_*`` tools are admissible: the prefix rule blocks
    ``companion``/``basic_shell``/``inspect`` style names and the membership
    rule fails closed on typos and drift.
    """

    if allowlist is None:
        return None
    names = {str(name).strip() for name in allowlist}
    if not names or any(not _DESKTOP_TOOL_NAME_RE.fullmatch(name) for name in names):
        raise ValueError(
            "host_mcp_allowlist must contain only non-empty registered "
            f"{HOST_MCP_ALLOWLIST_PREFIX}* tool names."
        )
    if registered is not None:
        unknown = names - set(registered)
        if unknown:
            raise ValueError(
                "host_mcp_allowlist names are not registered MCP tools: "
                + ", ".join(sorted(unknown))
            )
    return frozenset(names)


class ClaudeCodeRunner:
    def __init__(
        self,
        *,
        visible_dir: Path,
        claude_config_dir: Path,
        io_dir: Path,
        controller: Any,
        claude_bin: Path | None = None,
        ca_bundle: Path | None = None,
        model: str = DEFAULT_CLAUDE_MODEL,
        effort: str = DEFAULT_CLAUDE_EFFORT,
        expected_model_id: str | None = None,
        oauth_token: str | None = None,
        task_timeout: int = 3600,
        image: str = PLAYER_IMAGE,
        host_mode: bool = False,
        # ``None`` (default): native tools stay disabled unless the explicit
        # local-dev env var OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS is set.  Callers
        # that want the production lock regardless of the environment pass ""
        # explicitly (the resident brain does this).
        host_builtin_tools: str | None = None,
        # Unattended one-shot host runs (run_offer→cli) pass the registered
        # desktop_* tool names; the advertised MCP surface and --allowedTools
        # are then restricted to exactly that set.  ``None`` keeps the whole
        # registered MCP surface (the resident brain needs it).
        host_mcp_allowlist: Collection[str] | None = None,
        display_size: int = 512,
        auto_compact_window: int | None = CLAUDE_AUTO_COMPACT_WINDOW,
        auto_compact_percent: int | None = CLAUDE_AUTO_COMPACT_PERCENT,
        decision_lease_timeout: int = DEFAULT_DECISION_LEASE_TIMEOUT_SECONDS,
        rate_limit_observer: Callable[[ClaudeRateLimitEvent], None] | None = None,
        credential_yield_requested: Callable[[], bool] | None = None,
        tool_interface: ToolInterface | None = None,
        recovery_prompts: RecoveryPrompts | None = None,
        native_compaction: bool = False,
        provider: ClaudeCodeProvider | None = None,
        provider_credential: str | None = None,
        provider_base_url: str | None = None,
        max_output_tokens: int | None = None,
        mcp_tool_timeout_ms: int | None = None,
    ) -> None:
        self.tool_interface = tool_interface
        self.recovery_prompts = recovery_prompts
        self.native_compaction = native_compaction
        self.visible_dir = visible_dir.resolve()
        self.guide_path = self.visible_dir / "GUIDE.md"
        self.working_path = self.visible_dir / "WORKING.md"
        self.agents_path = self.visible_dir / "AGENTS.md"
        self.agents_instructions = self.agents_path.read_text(encoding="utf-8")
        self.claude_config_dir = prepare_claude_config(claude_config_dir)
        self.io_dir = io_dir.resolve()
        self.controller = controller
        self.dispatcher = (
            tool_interface.executor
            if tool_interface is not None
            else GameToolDispatcher(
                controller=controller,
                guide_path=self.guide_path,
                working_path=self.working_path,
                checkpoint_via_working=True,
                interrupt_on_invalid_action_limit=True,
            )
        )
        self.claude_bin = (claude_bin or default_claude_bin()).resolve()
        self.ca_bundle = (
            ca_bundle or Path("/etc/ssl/certs/ca-certificates.crt")
        ).resolve()
        if effort not in CLAUDE_EFFORT_LEVELS:
            raise ValueError(
                f"Unsupported Claude effort {effort!r}; expected one of "
                f"{', '.join(CLAUDE_EFFORT_LEVELS)}."
            )
        self.model = model
        self.effort = effort
        self.expected_model_id = expected_model_id
        provider = provider or ANTHROPIC_PROVIDER
        self.provider = provider
        self.provider_base_url = provider_base_url
        if provider.name == "local":
            # 宿主机供应商透传：端点/凭据/模型档全部来自本机 claude 配置
            # （~/.claude/settings.json 的 env 块，由 host_passthrough_environment
            # 注入），项目不持有任何 key，也不覆盖用户的供应商选择。
            self.oauth_token = None
            self.provider_credential = None
            self.provider_environment = {}
        elif provider.native:
            self.oauth_token = (
                oauth_token
                if oauth_token is not None
                else os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
            )
            if not self.oauth_token:
                raise RuntimeError(
                    "CLAUDE_CODE_OAUTH_TOKEN is not set; run `claude setup-token` and "
                    "export the generated subscription token."
                )
            self.provider_credential = self.oauth_token
        else:
            self.oauth_token = None
            self.provider_credential = (
                provider_credential
                if provider_credential is not None
                else os.getenv(provider.credential_env)
            )
            if not self.provider_credential:
                raise RuntimeError(f"{provider.credential_env} is not set.")
        # MiMo's Anthropic-compatible gateway rejects the concrete provider
        # model id when Claude Code resolves it through ANTHROPIC_MODEL.  It
        # expects Claude's stable alias and performs the backend mapping
        # itself.  Keep the configured id for reporting, but select sonnet
        # for the transport environment (the CLI argument is already mapped
        # below).
        if provider.name == "local":
            # 宿主机供应商透传：没有任何项目侧端点/凭据/模型档可设，
            # 全部由 host_passthrough_environment 从本机配置搬过来。
            pass
        else:
            transport_model = "sonnet" if provider.name == "mimo" else model
            self.provider_environment = provider_environment(
                provider,
                credential=self.provider_credential,
                model=transport_model,
                effort=effort,
                base_url=provider_base_url,
            )
        for name, value in (
            ("max_output_tokens", max_output_tokens),
            ("mcp_tool_timeout_ms", mcp_tool_timeout_ms),
        ):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        self.max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else provider.max_output_tokens
        )
        self.mcp_tool_timeout_ms = (
            mcp_tool_timeout_ms
            if mcp_tool_timeout_ms is not None
            else provider.mcp_tool_timeout_ms
        )
        self.task_timeout = task_timeout
        if decision_lease_timeout < 1:
            raise ValueError("The decision lease timeout must be positive.")
        self.decision_lease_timeout = decision_lease_timeout
        self.image = image
        # Host mode removes the Docker sandbox.  It stays usable for the
        # desktop product because the command line now defaults to native-tool
        # lockdown (--tools "", default permissions, desktop_* MCP allowlist),
        # but the explicit acknowledgement remains so callers cannot select
        # host mode by accident.
        if host_mode and os.environ.get("OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE") != "1":
            raise ValueError(
                "host_mode=True is disabled: use the Docker Claude backend and "
                "authenticated MCP tools; set OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE=1 "
                "only for an explicitly isolated run."
            )
        if host_mcp_allowlist is not None and not host_mode:
            raise ValueError("host_mcp_allowlist only applies to host_mode=True.")
        self.host_mode = bool(host_mode)
        self.host_builtin_tools = resolve_host_builtin_tools(host_builtin_tools)
        registered_mcp_tools = (
            {tool["name"] for tool in tool_interface.definitions}
            if tool_interface is not None
            else None
        )
        self.host_mcp_allowlist = normalize_host_mcp_allowlist(
            host_mcp_allowlist, registered=registered_mcp_tools
        )
        unlocked_native = set(self.host_builtin_tools) & NATIVE_UNSAFE_BUILTIN_TOOLS
        if unlocked_native:
            # The env value is the explicit local-dev escape hatch.  Make the
            # risk visible in the process log of every such run.
            print(
                "[claude-host] WARNING: explicit local-dev native tools enabled "
                f"({', '.join(sorted(unlocked_native))}); the process can edit "
                "files and run commands outside every VISTA gate. Never set "
                f"{ENV_HOST_BUILTIN_TOOLS} for unattended production runs.",
                flush=True,
            )
        self.display_size = display_size
        if (auto_compact_window is None) != (auto_compact_percent is None):
            raise ValueError("Both auto-compact settings must be provided together.")
        if auto_compact_window is not None and auto_compact_window < 1:
            raise ValueError("The auto-compact window must be positive.")
        if auto_compact_percent is not None and not 1 <= auto_compact_percent <= 100:
            raise ValueError("The auto-compact percentage must be between 1 and 100.")
        self.auto_compact_window = auto_compact_window
        self.auto_compact_percent = auto_compact_percent
        if native_compaction:
            self.auto_compact_window = None
            self.auto_compact_percent = None
        self.rate_limit_observer = rate_limit_observer
        self.credential_yield_requested = credential_yield_requested
        self._segment_index = 0
        self._session_image_blocks: dict[str, int] = {}
        self.io_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.guide_path,
            self.agents_path,
            self.visible_dir / "screenshots",
            self.ca_bundle,
            Path(__file__).with_name("mcp_bridge.py"),
            Path(__file__).with_name("compact_hook.py"),
        ):
            if not path.exists():
                raise FileNotFoundError(f"Incomplete Claude player runtime: {path}")

    def run_task(self, prompt: str) -> ClaudeResult:
        return self._run_segment(
            prompt=prompt,
            initial_images=self.controller.initial_image_paths(),
        )

    def replace_oauth_token(self, oauth_token: str) -> None:
        if not oauth_token:
            raise ValueError("Claude OAuth token must be non-empty")
        if not self.provider.native:
            raise ValueError("OAuth token relay requires the Anthropic provider")
        self.oauth_token = oauth_token
        self.provider_credential = oauth_token
        transport_model = "sonnet" if self.provider.name == "mimo" else self.model
        self.provider_environment = provider_environment(
            self.provider,
            credential=oauth_token,
            model=transport_model,
            effort=self.effort,
            base_url=self.provider_base_url,
        )

    def _process_environment(self) -> dict[str, str]:
        if self.provider.name == "local" and self.host_mode:
            # 宿主机供应商透传：保留本机 ANTHROPIC_* 配置（不清除），
            # 只叠加宿主机模式的隔离/杂项变量。
            env = host_passthrough_environment()
            return {**env, **self._host_environment()}
        if self.provider.native:
            env = claude_process_environment(self.oauth_token)
        else:
            env = provider_process_environment(self.provider_environment)
        if self.host_mode:
            # 容器里这些是靠 docker run -e 传的；宿主机模式只能进 Popen 的 env。
            env = {**env, **self._host_environment()}
        return env

    def _host_environment(self) -> dict[str, str]:
        """宿主机模式的环境变量（对应 _docker_command 里的那串 -e）。"""
        env: dict[str, str] = {
            "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_CODE_DISABLE_CRON": "1",
            "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_AUTO_CONNECT_IDE": "false",
            "CLAUDE_CONFIG_DIR": str(self.claude_config_dir),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "MAX_MCP_OUTPUT_TOKENS": str(MAX_MCP_OUTPUT_TOKENS),
            "SSL_CERT_FILE": str(self.ca_bundle),
        }
        if self.auto_compact_window is not None:
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(self.auto_compact_window)
            env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] = str(self.auto_compact_percent)
        return env

    def _container_name(self, session_id: str) -> str | None:
        if self.host_mode:
            # 宿主机模式没有容器可删，别让终止逻辑去 docker rm 一个不存在的东西。
            return None
        # Name containers for compatible providers so they can be removed
        # explicitly when the client process is terminated.
        if self.provider.native:
            return None
        return f"arc3-{session_id}"

    def run_retry_task(self, recovery: RetryRecovery) -> ClaudeResult:
        return self._run_segment(
            prompt=self._recovery_prompt("retry", recovery),
            initial_images=recovery.image_paths,
            before_input=lambda: self.controller.complete_retry_recovery(recovery),
        )

    def resume_retry_task(
        self,
        session_id: str,
        recovery: RetryRecovery,
    ) -> ClaudeResult:
        return self._run_segment(
            prompt=self._recovery_prompt("retry", recovery),
            initial_images=recovery.image_paths,
            resume_session_id=session_id,
        )

    def resume_nonterminal_task(
        self,
        session_id: str,
        prompt: str,
    ) -> ClaudeResult:
        return self._run_segment(
            prompt=prompt,
            initial_images=(),
            resume_session_id=session_id,
        )

    def run_fresh_runtime_recovery(
        self,
        recovery: RuntimeRecovery,
    ) -> ClaudeResult:
        return self._run_segment(
            prompt=self._recovery_prompt("fresh_runtime", recovery),
            initial_images=recovery.image_paths,
            before_input=lambda: self.controller.complete_runtime_recovery(
                recovery,
                delivery="fresh_runtime_thread",
            ),
        )

    def run_compact_recovery(
        self,
        recovery: CompactRecovery,
        *,
        prompt: str | None = None,
    ) -> ClaudeResult:
        recovery_prompt = self._recovery_prompt("compact", recovery)
        if prompt is not None:
            recovery_prompt = "\n\n".join((recovery_prompt, prompt))
        return self._run_segment(
            prompt=recovery_prompt,
            initial_images=recovery.image_paths,
            before_input=lambda: self.controller.complete_compact_recovery(
                recovery,
                delivery="fresh_thread",
            ),
        )

    def _recovery_prompt(self, kind: str, recovery: Any) -> str:
        if self.recovery_prompts is not None:
            return getattr(self.recovery_prompts, kind)(recovery)
        return self._default_recovery_prompt(kind, recovery)

    def _default_recovery_prompt(self, kind: str, recovery: Any) -> str:
        raise RuntimeError("Task recovery prompts must be supplied by the adapter")

    def _default_tool_definitions(self) -> list[dict[str, Any]]:
        raise RuntimeError("Task tools must be supplied by the adapter")

    def run_input(
        self, task_input: Any, *, session_id: str | None = None
    ) -> ClaudeResult:
        from vista.backends.content import ordered_content
        if self.host_mode:
            print(f"[claude-host] run_input phase={getattr(task_input, 'phase', None)}", flush=True)
        return self._run_segment(
            prompt=task_input.text,
            initial_images=(),
            resume_session_id=session_id,
            ordered_input=ordered_content(task_input, "claude"),
        )

    def _tool_definitions(self) -> list[dict[str, Any]]:
        if self.tool_interface is not None:
            return list(self.tool_interface.definitions)
        return self._default_tool_definitions()

    def _mcp_tool_definitions(self) -> list[dict[str, Any]]:
        return self._tool_definitions()

    def _host_tool_interface(self) -> ToolInterface | None:
        """The tool interface the host MCP bridge advertises in host mode.

        With ``host_mcp_allowlist`` (run_offer→cli unattended path) the bridge
        only lists the registered desktop_* tools: companion/basic_*/inspect
        are invisible to the child process, so they cannot be called even if
        the model ignores the --allowedTools boundary.
        """
        if (
            not self.host_mode
            or self.host_mcp_allowlist is None
            or self.tool_interface is None
        ):
            return self.tool_interface
        filtered = tuple(
            definition
            for definition in self.tool_interface.definitions
            if definition.get("name") in self.host_mcp_allowlist
        )
        if not filtered:
            raise RuntimeError(
                "host MCP allowlist matched no registered tool; refusing to "
                "start a native Claude process without any gated MCP tool."
            )
        return replace(self.tool_interface, definitions=filtered)

    def _host_visible_tool_definitions(self) -> list[dict[str, Any]]:
        interface = self._host_tool_interface()
        if interface is not None:
            return list(interface.definitions)
        definitions = [
            definition
            for definition in self._mcp_tool_definitions()
            if self.host_mcp_allowlist is None
            or definition.get("name") in self.host_mcp_allowlist
        ]
        if self.host_mcp_allowlist is not None and not definitions:
            raise RuntimeError(
                "host MCP allowlist matched no registered tool; refusing to "
                "build a native Claude command without any gated MCP tool."
            )
        return definitions

    def _next_segment(self) -> int:
        segment = self._segment_index
        self._segment_index += 1
        return segment

    def _run_segment(
        self,
        *,
        prompt: str,
        initial_images: Any,
        resume_session_id: str | None = None,
        before_input: Callable[[], None] | None = None,
        disable_slash_commands: bool = True,
        ordered_input: list[dict[str, Any]] | None = None,
    ) -> ClaudeResult:
        if self.host_mode:
            print("[claude-host] entering _run_segment", flush=True)
        if not self.host_mode:
            validate_claude_runtime(
                self.claude_bin,
                oauth_token=self.oauth_token,
                provider=self.provider,
                provider_credential=self.provider_credential,
            )
        initial_images = tuple(initial_images)
        segment = self._next_segment()
        stem = f"segment_{segment:03d}"
        requested_session_id = resume_session_id or str(uuid.uuid4())
        container_name = self._container_name(requested_session_id)
        initial_image_blocks = self._session_image_blocks.get(
            requested_session_id, 0
        ) + (
            sum(block.get("type") == "image" for block in ordered_input)
            if ordered_input is not None
            else len(initial_images)
        )
        if initial_image_blocks >= CLAUDE_PROVIDER_IMAGE_LIMIT:
            raise RuntimeError(
                "Claude session reached the provider image safety limit before input."
            )
        stdout_path = self.io_dir / f"{stem}.stdout.jsonl"
        stderr_path = self.io_dir / f"{stem}.stderr.txt"
        input_path = self.io_dir / f"{stem}.input.json"
        command_path = self.io_dir / f"{stem}.command.json"
        bridge_log_path = self.io_dir / f"{stem}.bridge.jsonl"
        compact_events_path = self.io_dir / f"{stem}.compact.jsonl"
        bridge_token = secrets.token_urlsafe(32)
        mcp_config_path = self.claude_config_dir / f"{stem}.mcp.json"
        settings_path = self.claude_config_dir / f"{stem}.settings.json"
        self._game_port = _free_loopback_port() if os.name == "nt" else None
        self._write_mcp_config(mcp_config_path, bridge_token)
        self._write_settings(settings_path, compact_events_path.name)
        socket_dir = create_short_socket_dir(segment)
        socket_path = socket_dir / "controller.sock"

        command = (self._host_command if self.host_mode else self._docker_command)(
            mcp_config_path=mcp_config_path,
            settings_path=settings_path,
            socket_dir=socket_dir,
            session_id=requested_session_id,
            resume=resume_session_id is not None,
            disable_slash_commands=disable_slash_commands,
        )
        command_path.write_text(json.dumps(command, indent=2), encoding="utf-8")
        input_message = stream_user_message(prompt, initial_images)
        if ordered_input is not None:
            input_message["message"]["content"] = ordered_input
        input_path.write_text(
            json.dumps(sanitize_stream_message(input_message), indent=2),
            encoding="utf-8",
        )

        host = ClaudeGameMcpHost(
            socket_path=socket_path,
            token=bridge_token,
            tcp_port=getattr(self, "_game_port", None),
            dispatcher=self.dispatcher,
            display_size=self.display_size,
            log_path=bridge_log_path,
            call_namespace=stem,
            initial_image_blocks=initial_image_blocks,
            image_block_limit=CLAUDE_PROVIDER_IMAGE_LIMIT,
            image_compact_at=CLAUDE_PROVIDER_IMAGE_COMPACT_AT,
            include_compact_checkpoint=False,
            reset_requires_retry_state=(self.controller.reset_starts_fresh_session),
            tool_interface=self._host_tool_interface(),
            native_compaction=self.native_compaction,
            tool_definitions=self._host_visible_tool_definitions(),
        )
        process: subprocess.Popen[str] | None = None
        stream_queue: queue.Queue[tuple[str, str] | object] = queue.Queue()
        closed = object()
        final_message = ""
        resolved_models: set[str] = set()
        result_message: dict[str, Any] | None = None
        init_envelope: dict[str, Any] | None = None
        failure: str | None = None
        reset_boundary = False
        context_boundary: str | None = None
        compact_boundaries: list[dict[str, Any]] = []
        pending_play_tool_ids: set[str] = set()
        api_error_status: int | None = None
        decision_lease_failure: str | None = None
        unconfirmed_play_calls = 0
        rate_limit_events: list[ClaudeRateLimitEvent] = []

        try:
            # Keep the host transport diagnosable: a stalled native Claude
            # process must never look like a healthy, silent session.
            if self.host_mode:
                print(f"[claude-host] launch segment={segment} bin={self.claude_bin}", flush=True)
            host.start()
            process = subprocess.Popen(
                command,
                cwd=self.visible_dir,
                env=self._process_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_thread = _start_stream_reader(
                process.stdout, "stdout", stream_queue, stdout_path, closed
            )
            stderr_thread = _start_stream_reader(
                process.stderr, "stderr", stream_queue, stderr_path, closed
            )
            if self.host_mode:
                print(f"[claude-host] process pid={process.pid}; waiting MCP", flush=True)
            if not host.connected.wait(timeout=30):
                if host.failure is not None:
                    raise RuntimeError(
                        f"Claude game MCP failed: {type(host.failure).__name__}: "
                        f"{host.failure}"
                    )
                raise TimeoutError("Claude game MCP did not connect before input.")
            if self.host_mode:
                print("[claude-host] MCP connected; waiting tools", flush=True)
            if not host.tools_ready.wait(timeout=30):
                if host.failure is not None:
                    raise RuntimeError(
                        f"Claude game MCP failed: {type(host.failure).__name__}: "
                        f"{host.failure}"
                    )
                raise TimeoutError("Claude game tools were not delivered before input.")
            if self.host_mode:
                print("[claude-host] tools ready; sending input", flush=True)
            process.stdin.write(json.dumps(input_message, separators=(",", ":")) + "\n")
            process.stdin.flush()
            closed_streams = 0
            init_deadline = time.monotonic() + 30
            while init_envelope is None:
                if host.failure is not None:
                    raise RuntimeError(
                        f"Claude game MCP failed: {type(host.failure).__name__}: "
                        f"{host.failure}"
                    )
                if time.monotonic() >= init_deadline:
                    raise TimeoutError(
                        "Claude Code emitted no initialization envelope."
                    )
                try:
                    item = stream_queue.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError(
                            "Claude Code exited before runtime initialization."
                        )
                    continue
                if item is closed:
                    closed_streams += 1
                    continue
                source, line = item
                if source != "stdout":
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "Claude Code emitted invalid stream JSON during initialization."
                    ) from exc
                if message.get("type") != "system" or message.get("subtype") != "init":
                    continue
                init_envelope = message
                model = message.get("model")
                if isinstance(model, str):
                    resolved_models.add(model)
            sanitized_init = sanitize_init_envelope(init_envelope)
            if self.host_mode:
                sanitized_init["_openlookout_host_mode"] = True
            validate_instruction_envelope(
                sanitized_init,
                display_size=self.display_size,
                allow_slash_commands=not disable_slash_commands,
                tool_definitions=(
                    self._host_visible_tool_definitions()
                    if self.host_mode
                    else self._tool_definitions()
                ),
            )
            # Host-native mode uses the configured provider's Claude alias
            # (e.g. ``sonnet``) and lets the gateway route it.  The init
            # envelope therefore cannot prove a concrete upstream model ID;
            # only enforce the preflight-resolved ID on the pinned container
            # path where the same runtime/provider resolution was verified.
            if self.expected_model_id is not None and not self.host_mode:
                actual_model = resolved_model_id_from_envelope(sanitized_init)
                if actual_model != self.expected_model_id:
                    raise RuntimeError(
                        "Claude resolved a different model than the runtime preflight."
                    )
            if before_input is not None:
                before_input()
            host.enable_calls()
            decision_lease = DecisionLeaseWatchdog(
                timeout_seconds=self.decision_lease_timeout,
                started_at=time.monotonic(),
            )
            process.stdin.close()
            deadline = time.monotonic() + self.task_timeout
            while True:
                # 已经在本轮边界上主动收尾（decision_complete 等）后，MCP 连接
                # 随进程终止而断开是预期行为：Windows 上 TerminateProcess 会把
                # 还挂着待读数据的桥接连接打成 RST（WinError 10054）。此时决定
                # 已记录并确认，再把这条 teardown 噪声算成「MCP host failed」
                # 会让一个正常边界的片段返回 1，进而触发整轮 runtime recovery。
                if (
                    host.failure is not None
                    and context_boundary is None
                    and not reset_boundary
                ):
                    failure = f"MCP host failed: {type(host.failure).__name__}: {host.failure}"
                    _terminate(process, container_name)
                if (
                    host.boundary_delivered.is_set()
                    and not reset_boundary
                    and context_boundary is None
                ):
                    if self.tool_interface is not None and host.boundary_reason in {
                        "decision_complete",
                        "task_complete",
                        "provider_image_limit",
                    }:
                        context_boundary = host.boundary_reason
                    elif host.boundary_reason == "compact_checkpoint_saved":
                        context_boundary = "compact_checkpoint_saved"
                    elif host.boundary_reason == "compact_checkpoint":
                        context_boundary = "provider_image_limit"
                    elif host.boundary_reason == "invalid_action_limit":
                        context_boundary = "invalid_action_limit"
                        decision_lease_failure = "invalid_action_limit"
                    else:
                        reset_boundary = True
                    time.sleep(0.1)
                    _terminate(process, container_name)
                if (
                    context_boundary is None
                    and not reset_boundary
                    and self.credential_yield_requested is not None
                    and self.credential_yield_requested()
                ):
                    _, in_flight_calls, _ = host.tool_activity()
                    if credential_handoff_is_safe(
                        process_running=process.poll() is None,
                        tool_calls_in_flight=in_flight_calls,
                        pending_play_tool_ids=pending_play_tool_ids,
                        unconfirmed_play_calls=host.unconfirmed_play_calls,
                    ):
                        context_boundary = "credential_rate_limit"
                        decision_lease_failure = "credential_rate_limit"
                        host.disable_calls()
                        _terminate(process, container_name)
                if time.monotonic() >= deadline:
                    failure = "Claude player timed out."
                    _terminate(process, container_name)
                now = time.monotonic()
                completed_calls, in_flight_calls, last_completed_at = (
                    host.tool_activity()
                )
                if process.poll() is None and decision_lease.expired(
                    now=now,
                    completed_tool_calls=completed_calls,
                    tool_calls_in_flight=in_flight_calls,
                    last_tool_completed_at=last_completed_at,
                ):
                    decision_lease_failure = "decision_timeout"
                    failure = "Claude decision lease expired without another tool call."
                    host.disable_calls()
                    _terminate(process, container_name)
                try:
                    item = stream_queue.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None and closed_streams >= 2:
                        break
                    continue
                if item is closed:
                    closed_streams += 1
                    if process.poll() is not None and closed_streams >= 2:
                        break
                    continue
                source, line = item
                if source != "stdout":
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    failure = "Claude Code emitted invalid stream JSON."
                    continue
                rate_limit_event = rate_limit_event_from_message(message)
                if rate_limit_event is not None:
                    rate_limit_events.append(rate_limit_event)
                    if self.rate_limit_observer is not None:
                        self.rate_limit_observer(rate_limit_event)
                status = api_error_status_from_message(message)
                if status is not None:
                    api_error_status = status
                message_type = message.get("type")
                if message_type == "system" and message.get("subtype") == "init":
                    init_envelope = message
                    model = message.get("model")
                    if isinstance(model, str):
                        resolved_models.add(model)
                elif (
                    message_type == "system"
                    and message.get("subtype") == "compact_boundary"
                ):
                    compact_boundaries.append(sanitize_compact_boundary(message))
                    host.acknowledge_compaction()
                    if not self.native_compaction:
                        host.disable_calls()
                        context_boundary = "native_compact"
                        _terminate(process, container_name)
                elif message_type == "assistant":
                    assistant = message.get("message")
                    if isinstance(assistant, dict):
                        record_pending_play_tool_uses(
                            assistant,
                            pending_play_tool_ids,
                            tool_names={
                                f"mcp__game__{name}" for name in host.action_tools
                            },
                        )
                        model = assistant.get("model")
                        if isinstance(model, str):
                            resolved_models.add(model)
                        for block in assistant.get("content", []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "text":
                                text = block.get("text")
                                if isinstance(text, str):
                                    final_message = text
                elif message_type == "user":
                    user_message = message.get("message")
                    if isinstance(user_message, dict):
                        acknowledge_completed_play_tools(
                            user_message,
                            pending_play_tool_ids,
                            host.acknowledge_action_result,
                        )
                elif message_type == "result":
                    result_message = message
                    reported_failure = decision_lease_failure_from_result(message)
                    if reported_failure is not None:
                        decision_lease_failure = reported_failure
                        failure = "Claude ended the decision lease with an error."
                    result_text = message.get("result")
                    if isinstance(result_text, str):
                        final_message = result_text
                    model_usage = message.get("modelUsage")
                    if isinstance(model_usage, dict):
                        resolved_models.update(
                            key for key in model_usage if isinstance(key, str)
                        )
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            if process is not None:
                _terminate(process, container_name)
        finally:
            if process is not None:
                try:
                    process_returncode = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process_returncode = process.wait()
            else:
                process_returncode = 125
            if host.unconfirmed_play_calls and host.failure is None:
                host.wait_for_play_settlement(PLAY_SETTLEMENT_TIMEOUT_SECONDS)
            unconfirmed_play_calls = host.unconfirmed_play_calls
            if (
                context_boundary is None
                and not reset_boundary
                and self.credential_yield_requested is not None
                and self.credential_yield_requested()
            ):
                _, in_flight_calls, _ = host.tool_activity()
                if credential_handoff_is_safe(
                    process_running=False,
                    tool_calls_in_flight=in_flight_calls,
                    pending_play_tool_ids=pending_play_tool_ids,
                    unconfirmed_play_calls=unconfirmed_play_calls,
                ):
                    context_boundary = "credential_rate_limit"
                    decision_lease_failure = "credential_rate_limit"
            if unconfirmed_play_calls:
                decision_lease_failure = "unconfirmed_play"
                failure = "A play call did not reach a confirmed controller result."
            host.stop()
            mcp_config_path.unlink(missing_ok=True)
            shutil.rmtree(socket_dir, ignore_errors=True)

        if context_boundary is None and host.boundary_delivered.is_set():
            # The boundary landed while the streams were already closing.
            context_boundary = host.boundary_reason
        if (
            self.tool_interface is not None
            and decision_lease_failure == "runtime_exit"
            and aborted_at_boundary(result_message, boundary=context_boundary)
        ):
            # The host ended this segment on purpose (a decision or the task
            # completed) and terminated the CLI, which reports the stream it
            # was cut off from as an execution error. That is the expected
            # shape of a boundary, not a failure.
            decision_lease_failure = None
            failure = None
            with stderr_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    f"Claude stream aborted at the {context_boundary} boundary.\n"
                )
        if failure:
            with stderr_path.open("a", encoding="utf-8") as stream:
                stream.write(failure + "\n")
        if self.tool_interface is not None and failure:
            returncode = 1
        elif reset_boundary or context_boundary is not None:
            returncode = 0
        elif failure:
            returncode = 1
        else:
            returncode = process_returncode
        if (
            returncode == 0
            and not reset_boundary
            and context_boundary is None
            and result_message is None
        ):
            returncode = 1
            with stderr_path.open("a", encoding="utf-8") as stream:
                stream.write("Claude Code exited without a result message.\n")
        if returncode != 0 and decision_lease_failure is None:
            decision_lease_failure = "runtime_exit"

        observed_session_id = None
        if init_envelope is not None and isinstance(
            init_envelope.get("session_id"), str
        ):
            observed_session_id = init_envelope["session_id"]
        elif init_envelope is not None:
            observed_session_id = requested_session_id
        session_image_blocks = host.image_blocks_delivered
        if observed_session_id is not None:
            self._session_image_blocks[observed_session_id] = session_image_blocks
        self._session_image_blocks[requested_session_id] = session_image_blocks
        return ClaudeResult(
            segment=segment,
            returncode=returncode,
            process_returncode=process_returncode,
            final_message=final_message,
            session_id=observed_session_id,
            resolved_models=tuple(sorted(resolved_models)),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            input_path=input_path,
            command_path=command_path,
            bridge_log_path=bridge_log_path,
            compact_events_path=compact_events_path,
            usage=usage_from_result(result_message),
            api_error_status=api_error_status,
            session_image_blocks=session_image_blocks,
            peak_session_image_blocks=host.peak_image_blocks,
            reset_boundary=reset_boundary,
            context_boundary=context_boundary,
            init_envelope=sanitize_init_envelope(init_envelope),
            compact_boundaries=tuple(compact_boundaries),
            decision_lease_failure=decision_lease_failure,
            unconfirmed_play_calls=unconfirmed_play_calls,
            rate_limit_events=tuple(rate_limit_events),
        )

    def _game_endpoint(self) -> str:
        port = getattr(self, "_game_port", None)
        if self.host_mode:
            # 宿主机模式下 MCP bridge 和 host 在同一台机器上，直接走回环。
            return f"127.0.0.1:{port}" if port else "/run/arc3-game/controller.sock"
        return f"host.docker.internal:{port}" if port else "/run/arc3-game/controller.sock"

    def _write_mcp_config(self, path: Path, token: str) -> None:
        if self.host_mode:
            # 宿主机模式：bridge 就在本机，用当前解释器直接跑，不需要 /usr/bin/env 也不
            # 能 unset 凭据（那不是容器）。socket 走回环，见 _game_endpoint()。
            import sys

            bridge = Path(__file__).with_name("mcp_bridge.py").resolve()
            path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "game": {
                                "type": "stdio",
                                "command": sys.executable,
                                "args": [str(bridge)],
                                "env": {
                                    "ARC3_GAME_SOCKET": self._game_endpoint(),
                                    "ARC3_GAME_TOKEN": token,
                                },
                            }
                        }
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            return
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "game": {
                            "type": "stdio",
                            "command": "/usr/bin/env",
                            "args": [
                                *(
                                    argument
                                    for name in CREDENTIAL_ENV_NAMES
                                    for argument in ("-u", name)
                                ),
                                "python3",
                                CONTAINER_MCP_BRIDGE,
                            ],
                            "env": {
                                "ARC3_GAME_SOCKET": self._game_endpoint(),
                                "ARC3_GAME_TOKEN": token,
                            },
                        }
                    }
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _write_settings(
        self,
        path: Path,
        compact_event_log_name: str,
    ) -> None:
        if self.native_compaction or self.host_mode:
            # 宿主机模式下容器里的 compact hook 命令（/usr/bin/env -u ... python3
            # /opt/arc3/claude_compact_hook.py + 容器路径环境变量）拼不出来，Windows
            # 上也没有那种 env 前缀语法。这里只打开 autoCompact，不注册 hook ——
            # 少掉的是跨容器 compaction 的事件账本，不是 agent 的能力。
            path.write_text(
                '{"autoCompactEnabled":true,"hooks":{}}\n', encoding="utf-8"
            )
            path.chmod(0o600)
            return
        unset_credentials = " ".join(f"-u {name}" for name in CREDENTIAL_ENV_NAMES)
        hook_environment = [
            f"ARC3_COMPACT_EVENT_LOG=/claude-io/{compact_event_log_name}"
        ]
        marker_environment = (
            (
                "ARC3_COMPACT_CHECKPOINT_REQUEST",
                getattr(self.controller, "compact_checkpoint_marker", None),
            ),
            (
                "ARC3_COMPACT_CHECKPOINT_READY",
                getattr(self.controller, "compact_checkpoint_ready", None),
            ),
        )
        for name, marker in marker_environment:
            if marker is not None:
                hook_environment.append(
                    f"{name}={self._container_io_path(Path(marker))}"
                )
        hook = {
            "type": "command",
            "command": (
                f"/usr/bin/env {unset_credentials} "
                f"{' '.join(hook_environment)} "
                f"python3 {CONTAINER_COMPACT_HOOK}"
            ),
            "timeout": 10,
        }
        path.write_text(
            json.dumps(
                {
                    "autoCompactEnabled": True,
                    "hooks": {
                        "PreCompact": [{"hooks": [hook]}],
                        "PostCompact": [{"hooks": [hook]}],
                        "Stop": [{"hooks": [hook]}],
                    },
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _container_io_path(self, path: Path) -> str:
        if self.host_mode:
            # 没有容器，路径就是本机路径。
            return str(path.resolve())
        try:
            relative = path.resolve().relative_to(self.io_dir)
        except ValueError as exc:
            raise ValueError(
                "Compact markers must live inside the Claude I/O dir."
            ) from exc
        return str(Path("/claude-io") / relative)

    def _docker_command(
        self,
        *,
        mcp_config_path: Path,
        settings_path: Path,
        socket_dir: Path,
        session_id: str,
        resume: bool,
        disable_slash_commands: bool = True,
    ) -> list[str]:
        # Windows hosts have no POSIX ids; the container runs as an unprivileged user.
        uid = str(os.getuid()) if os.name != "nt" else "1000"
        gid = str(os.getgid()) if os.name != "nt" else "1000"
        bridge = Path(__file__).with_name("mcp_bridge.py").resolve()
        compact_hook = Path(__file__).with_name("compact_hook.py").resolve()
        allowed_tools = ",".join(
            f"mcp__game__{tool['name']}" for tool in self._tool_definitions()
        )
        command = [
            "docker",
            "run",
            "-i",
            "--rm",
            "--pull=never",
            "--network",
            "bridge",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "16g",
            "--cpus",
            "4",
            "--user",
            f"{uid}:{gid}",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--tmpfs",
            "/home/claude:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/workspace:rw,nosuid,nodev,size=16m",
            *self._provider_arguments(session_id),
            "-e",
            "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1",
            "-e",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1",
            "-e",
            "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1",
            "-e",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1",
            "-e",
            "CLAUDE_CODE_DISABLE_CRON=1",
            "-e",
            "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1",
            "-e",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
            "-e",
            "CLAUDE_CODE_AUTO_CONNECT_IDE=false",
            *self._auto_compact_environment(),
            "-e",
            "CLAUDE_CONFIG_DIR=/claude-config",
            "-e",
            "HOME=/home/claude",
            "-e",
            "TERM=dumb",
            "-e",
            "NO_COLOR=1",
            "-e",
            f"MAX_MCP_OUTPUT_TOKENS={MAX_MCP_OUTPUT_TOKENS}",
            "-e",
            "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
            "-v",
            f"{self.claude_bin}:{CONTAINER_CLAUDE_BIN}:ro",
            "-v",
            f"{bridge}:{CONTAINER_MCP_BRIDGE}:ro",
            "-v",
            f"{compact_hook}:{CONTAINER_COMPACT_HOOK}:ro",
            "-v",
            f"{self.ca_bundle}:/etc/ssl/certs/ca-certificates.crt:ro",
            "-v",
            f"{self.claude_config_dir}:/claude-config:rw",
            "-v",
            f"{self.io_dir}:/claude-io:rw",
            "-v",
            f"{socket_dir}:/run/arc3-game:rw",
            "-w",
            "/workspace",
            self.image,
            CONTAINER_CLAUDE_BIN,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-hook-events",
            "--model",
            ("sonnet" if self.provider.name == "mimo" else self.model),
            "--effort",
            self.effort,
            "--system-prompt",
            self.agents_instructions,
            "--setting-sources",
            "",
            "--settings",
            f"/claude-config/{settings_path.name}",
            "--mcp-config",
            f"/claude-config/{mcp_config_path.name}",
            "--strict-mcp-config",
            "--tools",
            "",
            "--allowedTools",
            allowed_tools,
            "--permission-mode",
            CLAUDE_PERMISSION_MODE,
            "--prompt-suggestions",
            "false",
            "--no-chrome",
        ]
        if disable_slash_commands:
            command.append("--disable-slash-commands")
        if resume:
            command.extend(["--resume", session_id])
        else:
            command.extend(["--session-id", session_id])
        return command

    def _host_command(
        self,
        *,
        mcp_config_path: Path,
        settings_path: Path,
        socket_dir: Path,
        session_id: str,
        resume: bool,
        disable_slash_commands: bool = True,
    ) -> list[str]:
        """宿主机模式：直接跑本机 claude，但默认锁死在受控工具面内。

        与 _docker_command 的差别只有「没有 docker 那层」隔离；工具面必须保持
        与容器路径等价的收口（issue #13 PR1）：

        * ``--tools ""`` 禁用全部 Claude 原生内建工具；仅当显式本地开发 env
          OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS 非空时才透传对应名单；
        * ``--allowedTools`` 只列已注册 MCP 工具（run_offer→cli 路径进一步
          收敛为 desktop_* 白名单）+ 显式放开的内建工具；
        * ``--permission-mode default``：白名单之外的工具在无人值守 ``-p``
          下一律自动拒绝，任何配置都不产生 bypassPermissions。
        """
        builtins = list(self.host_builtin_tools)
        allowed_tools = ",".join(
            [
                f"mcp__game__{tool['name']}"
                for tool in self._host_visible_tool_definitions()
            ]
            + builtins
        )
        # local provider：模型档交给本机供应商的别名解析（--model opus 经
        # ~/.claude/settings.json 的 ANTHROPIC_DEFAULT_OPUS_MODEL 落到具体模型，
        # 本机当前 = deepseek-v4.1-flash）。不直接传具体模型 id —— Claude Code
        # 的模型目录不认识它，会把 context window 错算成 200k（真实 1M）并每轮
        # 报 unrecognized_model；走别名档则窗口/压缩按供应商真实值计算。
        if self.provider.name == "local":
            transport_model = "opus"
        elif self.provider.name == "mimo":
            transport_model = "sonnet"
        else:
            transport_model = self.model
        command = [
            str(self.claude_bin),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-hook-events",
            "--model",
            transport_model,
            "--effort",
            self.effort,
            "--system-prompt",
            self.agents_instructions,
            "--setting-sources",
            "",
            "--settings",
            str(settings_path),
            "--mcp-config",
            str(mcp_config_path),
            "--strict-mcp-config",
            "--tools",
            ",".join(builtins),
            "--allowedTools",
            allowed_tools,
            "--permission-mode",
            HOST_PERMISSION_MODE,
            "--prompt-suggestions",
            "false",
            "--no-chrome",
        ]
        if disable_slash_commands:
            command.append("--disable-slash-commands")
        if resume:
            command.extend(["--resume", session_id])
        else:
            command.extend(["--session-id", session_id])
        return command

    def _provider_arguments(self, session_id: str) -> list[str]:
        """Container arguments that select the model provider.

        The native provider passes `-e CLAUDE_CODE_OAUTH_TOKEN`.
        Another provider passes its own variable names (values come from the
        client environment), its output and MCP timeout limits, and a container
        name so the container can be removed with its client.
        """
        arguments = [
            argument for name in self.provider_environment for argument in ("-e", name)
        ]
        if self.max_output_tokens is not None:
            arguments += [
                "-e",
                f"CLAUDE_CODE_MAX_OUTPUT_TOKENS={self.max_output_tokens}",
            ]
        if self.mcp_tool_timeout_ms is not None:
            arguments += ["-e", f"MCP_TOOL_TIMEOUT={self.mcp_tool_timeout_ms}"]
        container = self._container_name(session_id)
        if container is not None:
            arguments += ["--name", container]
        return arguments

    def _auto_compact_environment(self) -> list[str]:
        window = self.auto_compact_window
        percent = self.auto_compact_percent
        if window is None:
            return []
        return [
            "-e",
            f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={window}",
            "-e",
            f"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE={percent}",
        ]


def stream_user_message(prompt: str, image_paths: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        path = Path(image_path)
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                        ".gif": "image/gif",
                    }.get(path.suffix.lower(), "image/png"),
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                },
            }
        )
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


def sanitize_stream_message(message: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(message))
    content = sanitized.get("message", {}).get("content", [])
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        source = block.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("data"), str):
            continue
        data = source["data"]
        source["data"] = {
            "encoded_chars": len(data),
            "sha256": hashlib.sha256(data.encode("ascii")).hexdigest(),
        }
    return sanitized


def record_pending_play_tool_uses(
    assistant_message: dict[str, Any],
    pending: set[str],
    *,
    tool_names: set[str] | None = None,
) -> None:
    if tool_names is None:
        tool_names = {"mcp__game__play"}
    for block in assistant_message.get("content", []):
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") in tool_names
            and isinstance(block.get("id"), str)
        ):
            pending.add(block["id"])


def acknowledge_completed_play_tools(
    user_message: dict[str, Any],
    pending: set[str],
    acknowledge: Callable[[], None],
) -> None:
    returned_ids = {
        block["tool_use_id"]
        for block in user_message.get("content", [])
        if isinstance(block, dict)
        and block.get("type") == "tool_result"
        and isinstance(block.get("tool_use_id"), str)
    }
    completed = returned_ids & pending
    if not completed:
        return
    pending.difference_update(completed)
    acknowledge()


def credential_handoff_is_safe(
    *,
    process_running: bool,
    tool_calls_in_flight: int,
    pending_play_tool_ids: set[str],
    unconfirmed_play_calls: int,
) -> bool:
    if tool_calls_in_flight or unconfirmed_play_calls:
        return False
    return not process_running or not pending_play_tool_ids


def sanitize_init_envelope(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    allowed = {
        "type",
        "subtype",
        "session_id",
        "tools",
        "mcp_servers",
        "model",
        "permissionMode",
        "slash_commands",
        "claude_code_version",
        "output_style",
        "skills",
        "plugins",
        "capabilities",
    }
    return {key: value[key] for key in allowed if key in value}


def validate_instruction_envelope(
    envelope: dict[str, Any] | None,
    *,
    display_size: int,
    allow_slash_commands: bool = False,
    tool_definitions: list[dict[str, Any]] | None = None,
) -> None:
    if not isinstance(envelope, dict):
        raise RuntimeError("Claude Code emitted no initialization envelope.")
    if tool_definitions is None:
        raise RuntimeError("Task tools must be supplied by the adapter")
    expected_tools = {f"mcp__game__{tool['name']}" for tool in tool_definitions}
    actual_tools = envelope.get("tools")
    host_mode = bool(envelope.get("_openlookout_host_mode"))
    if (
        not isinstance(actual_tools, list)
        or (not expected_tools.issubset(set(actual_tools)) if host_mode else
            len(actual_tools) != len(expected_tools) or set(actual_tools) != expected_tools)
    ):
        raise RuntimeError("Claude runtime did not expose the expected tool surface.")
    for key in ("skills", "plugins"):
        if not host_mode and envelope.get(key) != []:
            raise RuntimeError(f"Claude runtime exposed unexpected {key}.")
    if not allow_slash_commands and envelope.get("slash_commands") != []:
        raise RuntimeError("Claude runtime exposed unexpected slash_commands.")
    # host 模式同样强制 default（issue #13 PR1）：init 信封必须如实报告，
    # 任何旁路（外部 settings/别名）重新打开 bypassPermissions 都会在这里炸掉。
    if envelope.get("permissionMode") != CLAUDE_PERMISSION_MODE:
        raise RuntimeError("Claude runtime used an unexpected permission mode.")
    if not host_mode and envelope.get("claude_code_version") != PINNED_CLAUDE_VERSION:
        raise RuntimeError("Claude runtime used an unexpected Claude Code version.")
    servers = envelope.get("mcp_servers")
    if not isinstance(servers, list) or not any(
        isinstance(value, dict) and value.get("name") == "game" for value in servers
    ) or (not host_mode and len(servers) != 1):
        raise RuntimeError("Claude runtime did not expose the expected MCP server.")
    server = next(value for value in servers if isinstance(value, dict) and value.get("name") == "game")
    if not isinstance(server, dict) or server.get("name") != "game":
        raise RuntimeError("Claude runtime connected an unexpected MCP server.")
    status = server.get("status")
    if isinstance(status, str) and status.lower() != "connected":
        raise RuntimeError("Claude game MCP server is not connected.")


def resolved_model_id_from_envelope(envelope: dict[str, Any] | None) -> str:
    model = envelope.get("model") if isinstance(envelope, dict) else None
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("Claude Code did not report its resolved model ID.")
    normalized = model.strip()
    aliases = {"opus", "sonnet", "haiku"}
    if normalized.lower() in aliases:
        raise RuntimeError(
            "Claude Code reported a mutable model alias instead of a resolved model ID."
        )
    return normalized


def resolved_model_id(result: ClaudeResult) -> str:
    return resolved_model_id_from_envelope(result.init_envelope)


def sanitize_compact_boundary(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"type", "subtype", "session_id", "compact_metadata"}
    return {key: value[key] for key in allowed if key in value}


def usage_from_result(result: dict[str, Any] | None) -> ClaudeUsage | None:
    if not isinstance(result, dict):
        return None
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None
    return ClaudeUsage(
        input_tokens=_integer(usage.get("input_tokens")),
        output_tokens=_integer(usage.get("output_tokens")),
        cache_creation_input_tokens=_integer(usage.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_integer(usage.get("cache_read_input_tokens")),
        cost_usd=(
            float(result["total_cost_usd"])
            if isinstance(result.get("total_cost_usd"), (int, float))
            else None
        ),
        num_turns=(
            result["num_turns"] if type(result.get("num_turns")) is int else None
        ),
    )


def api_error_status_from_message(message: object) -> int | None:
    if not isinstance(message, dict):
        return None
    for key in ("api_error_status", "apiErrorStatus"):
        status = message.get(key)
        if type(status) is int:
            return status
    return None


def aborted_at_boundary(message: object, *, boundary: str | None) -> bool:
    """A segment the host cut off at a benchmark boundary, as the CLI reports it.

    The ARC3 path keeps its own accounting of this message; only the
    general task path consults this.
    """
    return (
        isinstance(message, dict)
        and boundary
        in {
            "decision_complete",
            "task_complete",
            "provider_image_limit",
            "compact_checkpoint_saved",
        }
        and message.get("terminal_reason") == "aborted_streaming"
        and message.get("subtype") == "error_during_execution"
    )


def decision_lease_failure_from_result(message: object) -> str | None:
    if not isinstance(message, dict) or message.get("type") != "result":
        return None
    result = message.get("result")
    if isinstance(result, str):
        normalized = result.lower()
        if "output token" in normalized and "maximum" in normalized:
            return "output_token_limit"
    if (
        message.get("is_error") is True
        or message.get("terminal_reason") == "api_error"
        or message.get("subtype") == "error_during_execution"
    ):
        return "runtime_exit"
    return None


def _integer(value: object) -> int:
    return value if type(value) is int else 0


def _start_stream_reader(
    stream: Any,
    source: str,
    output: queue.Queue[tuple[str, str] | object],
    path: Path,
    closed: object,
) -> threading.Thread:
    def read() -> None:
        with path.open("w", encoding="utf-8") as log:
            for line in stream:
                log.write(line)
                log.flush()
                output.put((source, line))
        output.put(closed)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return thread


def _terminate(process: subprocess.Popen[str], container: str | None = None) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    remove_container(container)


def remove_container(name: str | None) -> None:
    """`docker run` is only a client; killing it leaves the container running."""
    if not name:
        return
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
