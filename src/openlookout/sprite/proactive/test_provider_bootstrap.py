"""bootstrap_dotenv：.env 本地开关注入环境的规则（setdefault、不覆盖真实环境变量）。"""
from __future__ import annotations

from sprite.proactive import provider


def _write_env(path, text):
    path.write_text(text, encoding="utf-8")


def test_bootstrap_loads_simple_assignment(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "PROJECT_ROOT", tmp_path)
    _write_env(tmp_path / ".env", 'OPENLOOKOUT_BACKEND=direct\nSOME_TOKEN="quoted-value-123"\n')
    env: dict = {}
    applied = provider.bootstrap_dotenv(env)
    assert env["OPENLOOKOUT_BACKEND"] == "direct"
    assert env["SOME_TOKEN"] == "quoted-value-123"
    assert applied == env


def test_bootstrap_skips_comments_blank_and_malformed(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "PROJECT_ROOT", tmp_path)
    _write_env(tmp_path / ".env", "# a comment\n\n  # indented comment\nNO_EQUALS_LINE\nA=1\n")
    env: dict = {}
    applied = provider.bootstrap_dotenv(env)
    assert applied == {"A": "1"}


def test_bootstrap_never_overrides_existing_env(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "PROJECT_ROOT", tmp_path)
    _write_env(tmp_path / ".env", "A=from-file\nB=from-file\n")
    env = {"A": "from-env"}
    applied = provider.bootstrap_dotenv(env)
    assert env["A"] == "from-env"          # 真实环境变量优先
    assert env["B"] == "from-file"
    assert applied == {"B": "from-file"}


def test_bootstrap_without_dotenv_file_is_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "PROJECT_ROOT", tmp_path)
    assert provider.bootstrap_dotenv({}) == {}
