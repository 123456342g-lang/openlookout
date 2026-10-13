"""Focused tests for the proactive desktop tidy action.

The fixture points ``SPRITE_DESKTOP`` at a temporary directory so these tests
never inspect or modify the real user's desktop.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from vista.benchmarks.desktop import actions


@pytest.fixture()
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Desktop"
    root.mkdir()
    monkeypatch.setenv("SPRITE_DESKTOP", str(root))
    monkeypatch.setattr(actions, "JOURNAL", tmp_path / "undo.jsonl")
    monkeypatch.setattr(actions, "HOME", tmp_path / "sprite_home")
    return root


def _old_file(path: Path, content: bytes = b"fixture") -> Path:
    path.write_bytes(content)
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(path, (old, old))
    return path


def _seed_pile(root: Path) -> list[Path]:
    files = [
        _old_file(root / "photo.png", b"photo"),
        _old_file(root / "bundle.zip", b"bundle"),
        _old_file(root / "installer.msi", b"installer"),
        _old_file(root / "recording.mp3", b"audio"),
    ]
    return files


def test_tidy_ignores_a_small_desktop(desktop: Path):
    files = [_old_file(desktop / "one.txt"), _old_file(desktop / "two.png")]

    reply = actions.tidy({"min_files": 3})

    assert reply.success
    assert all(path.exists() for path in files)
    assert not list((desktop / "整理").rglob("*") if (desktop / "整理").exists() else [])


def test_tidy_moves_an_obvious_pile_without_deleting(desktop: Path):
    files = _seed_pile(desktop)
    original = {path.name: path.read_bytes() for path in files}

    reply = actions.tidy({"min_files": 3})

    assert reply.success
    assert all(not path.exists() for path in files)
    organized = [
        path for path in (desktop / "整理").rglob("*")
        if path.is_file() and path.name in original
    ]
    assert len(organized) == len(files)
    assert {path.name: path.read_bytes() for path in organized} == original


def test_tidy_never_overwrites_an_existing_destination(desktop: Path):
    files = _seed_pile(desktop)
    destination = desktop / "整理" / "图片" / "photo.png"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"keep this file")

    reply = actions.tidy({"min_files": 3})

    assert reply.success
    assert files[0].exists(), "a colliding source remains in place"
    assert files[0].read_bytes() == b"photo"
    assert destination.read_bytes() == b"keep this file"
    organized = [
        path for path in (desktop / "整理").rglob("*")
        if path.is_file() and path.name in {item.name for item in files}
    ]
    assert len(organized) == len(files)


def test_tidy_leaves_work_files_in_place(desktop: Path):
    notes = _old_file(desktop / "notes.txt", b"keep")
    source = _old_file(desktop / "photo.png", b"move")
    for index in range(4):
        _old_file(desktop / f"archive-{index}.zip")

    reply = actions.tidy({"min_files": 5})

    assert reply.success
    assert notes.exists() and notes.read_bytes() == b"keep"
    assert not source.exists()


def test_tidy_undo_restores_every_moved_file(desktop: Path):
    files = _seed_pile(desktop)
    original = {path.name: path.read_bytes() for path in files}

    reply = actions.tidy({"min_files": 3})
    assert reply.success
    assert actions.JOURNAL.exists()
    assert all(not path.exists() for path in files)

    undone = actions.undo({})

    assert undone.success
    assert all(path.exists() for path in files)
    assert {path.name: path.read_bytes() for path in files} == original

