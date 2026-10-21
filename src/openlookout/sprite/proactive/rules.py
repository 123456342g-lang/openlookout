"""Deterministic resource rules on the live path.

This is the tested sprite engine (memory pressure, suspend, reclaim). It does
not call a model. The supervisor starts it beside brain/gui/recorder. Safe
reversible actions run under the engine's own gates; the window then shows one
line and an undo button.

Pause skips a pass. Quit ends the process. Undo replays the engine while it is
still running, and otherwise restores quarantine ids or resumes a suspended pid
from the rules journal.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import defaults
from ..config import sprite_home
from ..framework import Engine
from ..i18n import t, ui_language
from ..procctl import JournaledController
from .control import paused, quit_requested, take_undo
from .help import publish

POLL_S = 15.0
JOURNAL = "rules_undo.jsonl"


def build_rules(home: Path, *, live: bool = True):
    root = Path(home)
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"desktop_tidy": False, "projects": []}
    probe, world, registry = defaults.build(cfg, root)
    if world.ctrl is None:
        world.ctrl = JournaledController(root, live=live, spawn_watchdog=False)
    if getattr(world, "refresh", None) is None:
        world.refresh = probe.snapshot
    return probe, world, Engine(registry, root)


def remember(home: Path, action) -> None:
    row = {
        "id": getattr(action, "id", ""),
        "kind": getattr(action, "kind", ""),
        "result": getattr(action, "result", None) or {},
    }
    path = Path(home) / JOURNAL
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rows(home: Path) -> list[dict]:
    path = Path(home) / JOURNAL
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def undo_recorded(home: Path, world, action_id: str) -> bool:
    rows = _rows(home)
    if action_id == "last":
        chosen = rows[-1] if rows else None
    else:
        chosen = next((row for row in reversed(rows) if row.get("id") == action_id), None)
    if not chosen:
        return False
    kind = str(chosen.get("kind") or "")
    result = chosen.get("result") or {}
    if kind.startswith("quarantine") and getattr(world, "q", None) is not None:
        for item in result.get("ids") or []:
            try:
                world.q.restore(item)
            except (KeyError, FileNotFoundError, OSError):
                continue
        return True
    if kind.startswith("suspend") and getattr(world, "ctrl", None) is not None:
        pid = result.get("pid")
        if pid is None:
            return False
        world.ctrl.resume(pid)
        return True
    return False


def report_text(out) -> str:
    acted = list(getattr(out, "acted", []) or [])
    if not acted:
        return ""
    files = sum(
        int(getattr(action, "blast_items", 0) or 0)
        for action in acted
        if str(getattr(action, "kind", "")).startswith("quarantine")
    )
    procs = sum(1 for action in acted if str(getattr(action, "kind", "")).startswith("suspend"))
    if ui_language() == "zh":
        text = str(getattr(out, "text_short", "") or getattr(out, "text_done", "") or "").strip()
        if text:
            return text
    if files and procs:
        return t("rules_both", files=files, procs=procs)
    if files:
        return t("rules_files", files=files)
    if procs:
        return t("rules_procs", procs=procs)
    return t("rules_done")


def publish_outcome(out, *, now: float | None = None) -> dict | None:
    text = report_text(out)
    if not text:
        return None
    acted = list(getattr(out, "acted", []) or [])
    action_id = str(getattr(acted[-1], "id", "") or "")
    offer = {
        "id": f"rules-{time.time_ns()}",
        "t": time.time() if now is None else now,
        "text": text,
        "topic": "rules",
        "kind": "companion",
        "action_id": action_id,
    }
    publish(offer)
    return offer


def one_pass(engine, world, *, home: Path, now: float | None = None) -> list[dict]:
    published = []
    for out in engine.step(world):
        for action in list(getattr(out, "acted", []) or []):
            remember(home, action)
        offer = publish_outcome(out, now=now)
        if offer is not None:
            published.append(offer)
    return published


def apply_pending_undo(engine, world, home: Path) -> bool:
    token = take_undo(home)
    if not token:
        return False
    target = token
    if token == "last":
        rows = _rows(home)
        target = str(rows[-1]["id"]) if rows else ""
    if target and engine.undo(target):
        return True
    return undo_recorded(home, world, token)


def main() -> int:
    home = sprite_home()
    probe, world, engine = build_rules(home, live=True)
    while not quit_requested(home):
        if paused(home):
            time.sleep(POLL_S)
            continue
        if apply_pending_undo(engine, world, home):
            time.sleep(POLL_S)
            continue
        try:
            world.snap = probe.snapshot()
            if world.env is not None:
                world.env.now = time.time()
            one_pass(engine, world, home=home)
        except Exception as exc:
            print(f"[rules] {type(exc).__name__}", flush=True)
        time.sleep(POLL_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
