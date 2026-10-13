"""python -m vista.benchmarks.desktop.cli --objective "..." [--read-only] [--binary PATH]
Runs one desktop task on the VISTA harness with the host-native Claude Code as the
transport. The model comes from the host's own provider configuration
(~/.claude/settings.json env block, e.g. the opus alias -> deepseek-v4.1-flash)."""
from __future__ import annotations

import argparse, json, os, sys, time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]          # src/openlookout
PLAYER_IMAGE = "arc3-claude-player:0.1"
HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        epilog=(
            "安全默认（issue #13 PR1）：宿主机模式只放行已注册的 desktop_* MCP 工具"
            "（经风险门与撤销台账），Claude 原生 Edit/Write/MultiEdit/Bash 默认全禁，"
            "且不使用 bypassPermissions。仅本地开发可显式设置环境变量 "
            "OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS 透传原生工具；无人值守环境放开等于"
            "允许模型直接改文件/跑命令，生产（含普通 run_offer）禁止设置。"
        )
    )
    ap.add_argument("--objective", required=True)
    ap.add_argument("--binary", type=Path, default=None, help="host claude binary (default: PATH lookup, then the pinned Linux build)")
    ap.add_argument("--directory", type=Path, default=None, help="new run directory (default: a timestamped one)")
    ap.add_argument("--read-only", action="store_true", help="tell the agent not to change anything")
    a = ap.parse_args(argv)
    if a.binary is None:
        import shutil
        configured = os.environ.get("OPENLOOKOUT_CLAUDE_BIN") or shutil.which("claude")
        a.binary = Path(configured) if configured else HOME / "bin" / "claude-linux-2.1.220"
    if a.directory is None:
        a.directory = HOME / "desktop_runs" / time.strftime("%Y%m%d-%H%M%S")
    from sprite.proactive.provider import load_provider
    _p = load_provider()
    cfg = {"model": _p.model, "base_url": _p.base_url, "api_key": _p.api_key}

    import certifi
    from vista.backends.claude import create_backend
    from vista.backends.claude.provider import LOCAL_HOST_PROVIDER
    from vista.benchmarks.desktop.run import run_task

    # 宿主机模式：直接用本机 claude code，供应商与模型档来自本机配置
    # （~/.claude/settings.json 的 env 块），不经 Docker、不需要项目持 key。
    # OPENLOOKOUT_DIRECT_ONLY=1 可显式退回 VisualDirectBackend。
    host_model = str(os.environ.get("OPENLOOKOUT_MODEL") or "opus")

    def factory(runtime, directory):
        if os.environ.get("OPENLOOKOUT_DIRECT_ONLY") == "1":
            from vista.benchmarks.desktop.brain import VisualDirectBackend
            return VisualDirectBackend(cfg, runtime)
        # 无人值守收口（issue #13 PR1）：普通 run_offer 起的一次性任务只允许
        # 已注册的 desktop_* MCP 工具（DesktopSession 风险门 + 撤销台账），
        # companion/basic_*/inspect 在子进程里不可见；原生 Edit/Write/MultiEdit/
        # Bash 默认全禁（runner 默认 --tools "" + default 权限模式），只有显式
        # 本地开发 env OPENLOOKOUT_CLAUDE_BUILTIN_TOOLS 才透传。
        desktop_tools = frozenset(
            spec.name for spec in runtime.specs if spec.name.startswith("desktop_")
        )
        return create_backend(
            runtime, directory=directory, oauth_token=None, binary=a.binary, image=PLAYER_IMAGE,
            provider=LOCAL_HOST_PROVIDER, provider_credential=None, provider_base_url=None,
            max_output_tokens=2048, ca_bundle=Path(certifi.where()), host_mode=True,
            host_mcp_allowlist=desktop_tools,
        )

    objective = a.objective + ("（只读：不要挂起、结束或移动任何东西。）" if a.read_only else "")
    result = run_task(objective, {"read_only": a.read_only}, directory=a.directory, backend="claude",
                      model=host_model, effort="low", backend_factory=factory)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
