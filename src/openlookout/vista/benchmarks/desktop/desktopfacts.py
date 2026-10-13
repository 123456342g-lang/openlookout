"""桌面环境事实。

屏幕截图描述前台工作，桌面目录事实补足被窗口遮住的背景环境。这里只报告
真实的、可复核的文件数量，不替模型决定用户是否需要整理。
"""
from __future__ import annotations

import os
import time
from pathlib import Path


DEFAULT_MIN_FILES = 12
DEFAULT_REPEAT_S = 600.0
RECENT_S = 120.0
SKIP_SUFFIXES = {".lnk", ".url", ".ini"}
SKIP_NAMES = {"desktop.ini", "thumbs.db", "整理"}
SAFE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".tif", ".tiff",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".exe", ".msi", ".msix", ".appx", ".dmg", ".pkg",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv",
}


def desktop_root() -> Path:
    configured = os.environ.get("OPENLOOKOUT_DESKTOP") or os.environ.get("SPRITE_DESKTOP")
    return Path(configured).expanduser() if configured else Path.home() / "Desktop"


def _visible_files(root: Path) -> list[Path]:
    try:
        entries = root.iterdir()
    except OSError:
        return []
    result = []
    for path in entries:
        try:
            if not path.is_file() or path.is_symlink():
                continue
            if path.name.lower() in SKIP_NAMES or path.name.startswith("."):
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if path.suffix.lower() not in SAFE_SUFFIXES:
                continue
            if os.name == "nt":
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                if attrs != 0xFFFFFFFF and attrs & 0x6:  # hidden or system
                    continue
            result.append(path)
        except OSError:
            continue
    return result


class DesktopWatcher:
    """低噪声地报告桌面是否出现明显文件积压。"""

    def __init__(self, *, root: Path | None = None, min_files: int = DEFAULT_MIN_FILES,
                 repeat_s: float = DEFAULT_REPEAT_S, clock=time.time):
        self.root = Path(root) if root else desktop_root()
        self.min_files = int(min_files)
        self.repeat_s = float(repeat_s)
        self.clock = clock
        self.last_count: int | None = None
        self.last_emit: float | None = None

    def observe(self, now: float | None = None) -> "DesktopFacts":
        t = self.clock() if now is None else float(now)
        files = _visible_files(self.root)
        count = len(files)
        signature = tuple(sorted(p.name for p in files))
        changed = self.last_count != count or getattr(self, "last_signature", None) != signature
        should_emit = count >= self.min_files and (changed or self.last_emit is None or t - self.last_emit >= self.repeat_s)
        if should_emit:
            self.last_emit = t
        self.last_count = count
        self.last_signature = signature
        return DesktopFacts(self.root, count, files, should_emit, self.min_files)


class DesktopFacts:
    __slots__ = ("root", "count", "files", "should_emit", "min_files")

    def __init__(self, root: Path, count: int, files: list[Path], should_emit: bool, min_files: int):
        self.root = root
        self.count = count
        self.files = files
        self.should_emit = should_emit
        self.min_files = min_files

    def line(self) -> str:
        if not self.should_emit or self.count < self.min_files:
            return ""
        return f"【桌面】桌面上有 {self.count} 个散落文件（不含快捷方式和系统文件）；可用 desktop_tidy 按类型归类，移动前会记录撤回路径。"


def load(root: Path | None = None, **kwargs) -> DesktopWatcher:
    return DesktopWatcher(root=root, **kwargs)
