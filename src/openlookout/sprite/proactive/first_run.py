"""First-run check and a small setup wizard.

Missing provider.json or API key prints one localized sentence and exits 2.
It does not start Claude Code. On a terminal, the wizard can write
provider.json and .env. A non-interactive run only prints the sentence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..i18n import t
from .provider import DEFAULT_FILE, PROJECT_ROOT, load_provider

ENV_FILE = PROJECT_ROOT / ".env"


def python_problem() -> str | None:
    if sys.version_info < (3, 11):
        return t("need_python")
    return None


def provider_problem() -> str | None:
    version = python_problem()
    if version:
        return version
    try:
        load_provider()
    except FileNotFoundError:
        return t("need_provider")
    except RuntimeError:
        return t("need_key")
    except (ValueError, KeyError, json.JSONDecodeError):
        return t("bad_provider")
    return None


def write_provider(path: Path, *, protocol: str, base_url: str, model: str) -> None:
    if protocol not in {"anthropic", "openai"}:
        raise ValueError(protocol)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"protocol": protocol, "base_url": base_url.rstrip("/"), "model": model}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_env_key(path: Path, api_key: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = []
    found = False
    for line in lines:
        if line.strip().startswith("SPRITE_API_KEY="):
            kept.append("SPRITE_API_KEY=" + api_key)
            found = True
        else:
            kept.append(line)
    if not found:
        kept.append("SPRITE_API_KEY=" + api_key)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def setup_from_answers(answers: dict, *, provider_path: Path | None = None, env_path: Path | None = None) -> None:
    protocol = str(answers.get("protocol") or "").strip().lower()
    if protocol not in {"anthropic", "openai"}:
        raise ValueError(t("wizard_bad_protocol"))
    base_url = str(answers.get("base_url") or "").strip()
    model = str(answers.get("model") or "").strip()
    api_key = str(answers.get("api_key") or "").strip()
    if not base_url or not model or not api_key:
        raise ValueError(t("bad_provider"))
    write_provider(provider_path or DEFAULT_FILE, protocol=protocol, base_url=base_url, model=model)
    write_env_key(env_path or ENV_FILE, api_key)


def _ask(prompt: str, read) -> str:
    return str(read(prompt + ": ")).strip()


def run_wizard(*, read=input, write=print, provider_path: Path | None = None, env_path: Path | None = None) -> int:
    version = python_problem()
    if version:
        write(version)
        return 2
    problem = provider_problem()
    if problem is None:
        write(t("config_ok"))
        return 0
    interactive = read is not input or sys.stdin.isatty()
    if read is input and not sys.stdin.isatty():
        write(problem)
        return 2
    if not interactive:
        write(problem)
        return 2
    write(problem)
    protocol = _ask(t("wizard_protocol"), read).lower()
    if protocol not in {"anthropic", "openai"}:
        write(t("wizard_bad_protocol"))
        return 2
    try:
        setup_from_answers(
            {
                "protocol": protocol,
                "base_url": _ask(t("wizard_base"), read),
                "model": _ask(t("wizard_model"), read),
                "api_key": _ask(t("wizard_key"), read),
            },
            provider_path=provider_path,
            env_path=env_path,
        )
    except ValueError as exc:
        write(str(exc))
        return 2
    write(t("config_ok"))
    return 0


def main(argv=None) -> int:
    del argv
    return run_wizard()


if __name__ == "__main__":
    raise SystemExit(main())
