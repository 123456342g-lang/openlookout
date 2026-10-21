"""The installer picks one Python >= 3.11 and does not run a step twice."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_install_scripts_accept_any_python_311_and_do_not_double_run():
    bat = (ROOT / "install.bat").read_bytes()
    ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    text = bat.decode("utf-8")
    assert b"\r\n" in bat
    assert "py -3.11" not in text and "py -3.11" not in ps1
    assert "set \"PY=py -3\"" in text
    assert "set \"PY=python\"" in text
    assert "%PY% -m pip install" in text
    assert "||" not in text
    assert text.count("%PY% -m sprite.proactive.live") == 1
    assert "Test-PythonAtLeast311 py -3" in ps1
    assert "Test-PythonAtLeast311 python" in ps1
    assert ps1.count("sprite.proactive.live") == 1
    assert "exit $wizard" in ps1
