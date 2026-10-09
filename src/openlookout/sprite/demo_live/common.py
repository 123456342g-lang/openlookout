"""演示公共：路径、阈值、沙箱环境。全部只指向沙箱；真实目录只有在 config 里明确列出才会加入（默认不加）。"""
from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path

EAT_FLOOR_GB = 1.5            # eat_memory 永远给系统留的可用内存下限（硬编码，参数也不能低于它）
DEMO_IDLE_SCALE = 0.07        # 演示把“空闲 15/30 分钟”缩成约 1/2 分钟（真实使用不缩放）
BIG_MB = 20                   # 演示沙箱里的“大文件”门槛（真实 500MB）
MARK = ".sprite_demo_sandbox"


def sandbox_root() -> Path:
    e = os.environ.get("SPRITE_SANDBOX")
    if e: return Path(e)
    return Path(r"E:\OpenLookout\sprite_sandbox\demo") if os.name == "nt" else Path(tempfile.gettempdir()) / "sprite_sandbox" / "demo"


def home_dir() -> Path:
    e = os.environ.get("SPRITE_HOME")
    p = Path(e) if e else (Path(r"E:\OpenLookout\sprite_home") if os.name == "nt" else Path(tempfile.gettempdir()) / "sprite_home")
    p.mkdir(parents=True, exist_ok=True); return p


def demo_cfg_path(home: Path) -> Path: return Path(home) / "demo_live.json"


def load_demo_cfg(home: Path) -> dict:
    f = demo_cfg_path(home)
    d = dict(mem_warn=0.20, mem_warn_gb=None, extra_cache_dirs=[], max_suspend=6, max_suspend_mb=4096)
    if f.exists(): d.update(json.loads(f.read_text("utf-8")))
    else: f.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    return d


def warn_gb(total_mb: float, dc: dict) -> float:
    """sprite 判定“内存告急”的可用内存阈值（GB）。小内存机器抬高到 ≥2.3GB，保证 eat_memory 在留足 1.5GB 的前提下也能触发。"""
    if dc.get("mem_warn_gb"): return float(dc["mem_warn_gb"])
    return max(dc.get("mem_warn", 0.20) * total_mb / 1024, EAT_FLOOR_GB + 0.8)


def eat_target_avail_gb(total_mb: float, dc: dict) -> float:
    w = warn_gb(total_mb, dc); return max(EAT_FLOOR_GB, min(0.85 * w, w - 0.4))


def mem_now():
    from ..sysstate import RealProbe
    return RealProbe()._mem()          # (total_mb, avail_mb)
