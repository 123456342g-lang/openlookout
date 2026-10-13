"""Local desktop companion persistence and recorder lifecycle."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Inbox:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / "inbox.json"
        self.entries = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def merge(self, summary: dict):
        for item in summary.get("branch_candidates", []) + summary.get("assist_candidates", []):
            entry = self.entries.setdefault(item["id"], {"action": "pending", "until": 0})
            previous = entry.get("item") or {}
            entry["item"] = item
            if previous.get("evidence") != item.get("evidence"):
                entry["action"] = "pending"
                entry["until"] = 0
        save_json(self.path, self.entries)

    def pending(self, now=None):
        current = time.time() if now is None else now
        return [entry["item"] for entry in self.entries.values()
                if entry.get("until", 0) <= current]

    def feedback(self, item_id: str, action: str, now=None):
        if action not in {"useful", "already_known", "not_relevant", "later"}:
            raise ValueError("未知反馈")
        current = time.time() if now is None else now
        entry = self.entries[item_id]
        cooldowns = {
            "later": 3600,
            "useful": 21600,
            "already_known": 14400,
            "not_relevant": 86400,
        }
        entry.update(action="reviewed", last_feedback=action,
                     until=current + cooldowns[action])
        save_json(self.path, self.entries)
        self.append("feedback.jsonl", {"ts": datetime.now(timezone.utc).isoformat(), "id": item_id, "action": action})

    def append(self, name: str, row: dict):
        self.home.mkdir(parents=True, exist_ok=True)
        with (self.home / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def remember(self, instruction: str, scope: str):
        if not instruction.strip() or not scope.strip():
            raise ValueError("请填写偏好及适用范围")
        self.append("corrections.jsonl", {"ts": datetime.now(timezone.utc).isoformat(),
                    "instruction": instruction.strip(), "scope": scope.strip(), "source": "pet-user-input"})

    def export_rules(self) -> Path:
        from .trajectory import load_corrections

        rules = load_corrections(self.home / "corrections.jsonl")
        lines = ["# 我的 Agent 规则草稿\n", "由你主动填写的偏好整理；尚未安装到任何 Agent。请核对适用范围。\n"]
        seen = set()
        for row in rules:
            key = (row["scope"], row["instruction"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"\n## {row['scope']}\n\n{row['instruction']}\n")
        if not rules:
            raise ValueError("先填写一条偏好，再导出规则")
        path = self.home / "agent_rules_draft.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def snapshot_events(source: Path, destination: Path, limit: int = 10000, max_bytes: int = 8 * 1024 * 1024) -> dict:
    rows = deque(maxlen=limit)
    skipped_prefix = False
    if source.exists():
        with source.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            if size > max_bytes:
                stream.seek(size - max_bytes)
                stream.readline()
                skipped_prefix = True
            for raw in stream:
                if not raw.endswith(b"\n"):
                    break
                if not raw.strip():
                    continue
                row = json.loads(raw.decode("utf-8"))
                if not row.get("ts") or not row.get("type"):
                    raise ValueError("事件缺少 ts 或 type")
                if len(rows) == limit:
                    skipped_prefix = True
                rows.append(row)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "events.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    save_json(destination / "meta.json", {
        "now": datetime.now().isoformat(timespec="seconds"), "user_home": "",
        "watched_dirs": [], "user_aliases": [],
        "source": {"dataset": "pet-live", "window_limited": skipped_prefix},
    })
    return {"events": len(rows), "window_limited": skipped_prefix}


class Recorder:
    def __init__(self, repo: Path, home: Path):
        self.repo, self.home = repo, home
        self.process = None
        self.stop_path = home / "recorder.stop"

    @property
    def active(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self.active:
            return
        if sys.platform != "win32":
            raise RuntimeError("当前观察器需要 Windows")
        self.home.mkdir(parents=True, exist_ok=True)
        self.stop_path.unlink(missing_ok=True)
        command = [sys.executable, str(self.repo / "record_win.py"), "--out",
                   str(self.home / "capture" / "events.jsonl"), "--ext-port", "0",
                   "--stop-file", str(self.stop_path), "--parent-pid", str(os.getpid()),
                   "--heartbeat", "30", "--ignore-title", "OpenLookout"]
        with (self.home / "recorder.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(command, cwd=self.repo, stdout=log, stderr=log,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop(self):
        if not self.active:
            return
        self.stop_path.touch()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)


class InstanceLock:
    def __init__(self, path: Path):
        import msvcrt

        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        self.stream.write(b"0")
        self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.stream.close()
            raise RuntimeError("桌面精灵已经运行；请点击桌面上的圆形精灵展开") from None

    def close(self):
        self.stream.close()
