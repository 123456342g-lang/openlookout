"""Pause, quit, and undo signals for the resident sprite.

The files live under the sprite home directory so the window, the supervisor,
the brain, and the rules process can see the same decision without a socket.
Quit means the supervisor stops and does not start children again.
"""
from __future__ import annotations

from pathlib import Path

from ..config import sprite_home
from ..i18n import t


def home_of(home: Path | None = None) -> Path:
    return sprite_home() if home is None else Path(home)


def _flag(home: Path | None, name: str) -> Path:
    return home_of(home) / name


def paused(home: Path | None = None) -> bool:
    return _flag(home, "PAUSE").is_file()


def quit_requested(home: Path | None = None) -> bool:
    return _flag(home, "QUIT").is_file()


def request_pause(home: Path | None = None) -> None:
    path = _flag(home, "PAUSE")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1", encoding="utf-8")


def clear_pause(home: Path | None = None) -> None:
    _flag(home, "PAUSE").unlink(missing_ok=True)


def request_quit(home: Path | None = None) -> None:
    path = _flag(home, "QUIT")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1", encoding="utf-8")


def request_undo(home: Path | None = None, action_id: str = "last") -> None:
    path = _flag(home, "UNDO")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(action_id or "last", encoding="utf-8")


def take_undo(home: Path | None = None) -> str | None:
    path = _flag(home, "UNDO")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip() or "last"
    path.unlink(missing_ok=True)
    return text


def menu_spec(paused_now: bool) -> list[tuple[str, str]]:
    """Right-click and tray entries: pause or resume, undo, quit."""
    first = ("resume", t("menu_resume")) if paused_now else ("pause", t("menu_pause"))
    return [first, ("undo", t("menu_undo")), ("quit", t("menu_quit"))]


def apply_menu_action(action: str, home: Path | None = None) -> str:
    if action == "pause":
        request_pause(home)
        return "pause"
    if action == "resume":
        clear_pause(home)
        return "resume"
    if action == "undo":
        request_undo(home, "last")
        return "undo"
    if action == "quit":
        request_quit(home)
        return "quit"
    raise ValueError(f"unknown menu action {action!r}")
