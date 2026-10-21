"""配置与数据目录。所有数据只存本地。"""
from __future__ import annotations
import json, os
from pathlib import Path

DEFAULTS = {
    "watch": {                       # 目录 -> 启用的规则
        "~/Downloads": ["dedupe"],
        "~/Documents": ["scaffold", "versioning"],
    },
    "poll_s": 5.0,                   # 扫描间隔
    "settle_s": 60.0,                # 文件/目录这么久没变才动手（避免动正在编辑的文件）
    "max_depth": 2,
    "quiet_hours": ["23:00", "08:00"],   # 静默时段不动手；设为 null 关闭
    "daily_cap": 5,                  # 每天最多自动动手次数
    "max_ops_per_action": 30,
    "bubble_seconds": 12,
    "recorder": False,               # true 时顺带启动 recorder_win/record_win.py
    "enabled": True,
    "daily_tokens": 20000,           # 云端模型每日 token 硬上限；超了降级为本地措辞/保守判断
    "daily_usd": 0.05,
    "voice_llm": False,              # true：用 MiMo 润色（只发脱敏事实，密钥读 ~/.config/ai-butler/mimo.env）
}


def sprite_home() -> Path:
    """Runtime data for the resident sprite. Does not create the directory.

    SPRITE_HOME wins. Otherwise a per-user path. A drive-letter default such as
    E:\\OpenLookout is a relative path on Linux and would create a junk directory
    in the working tree, so it is not used.
    """
    env = os.environ.get("SPRITE_HOME")
    if env and str(env).strip():
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home()
        return root / "OpenLookout" / "sprite_home"
    return Path.home() / ".openlookout" / "sprite_home"


def data_dir() -> Path:
    env = os.environ.get("SPRITE_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OpenLookoutSprite"
    else:
        p = Path.home() / ".openlookout_sprite"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load(home: Path | None = None) -> dict:
    home = home or data_dir()
    cfg = json.loads(json.dumps(DEFAULTS))
    f = home / "config.json"
    if f.exists():
        cfg.update(json.loads(f.read_text(encoding="utf-8")))
    else:
        f.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg
