"""真实机器上的默认装配：用环境变量找到临时/缓存/下载/文档目录，注册内置场景。
Windows 上进程相关能力需要 psutil（可选：pip install psutil）；没有 psutil 时只做文件类清理，不碰进程。"""
from __future__ import annotations
import os, time
from pathlib import Path
from .framework import Registry
from .risk import Env
from .quarantine import Quarantine
from .sysstate import RealProbe, ProcController
from .scenarios import resource, extras


def provenance_win(p: Path):
    """读 NTFS 备用数据流 Zone.Identifier 里的 HostUrl（未在真实 Windows 验证）。"""
    try:
        for l in open(str(p) + ":Zone.Identifier", encoding="utf-8", errors="ignore"):
            if l.startswith("HostUrl="): return l.strip().split("=", 1)[1]
    except OSError: return None


def build(cfg: dict, home: Path):
    h = Path.home(); la = Path(os.environ.get("LOCALAPPDATA", h / ".cache"))
    env = Env(now=time.time(),
              temp_dirs=[Path(os.environ.get("TEMP", "/tmp"))],
              browser_cache_dirs=[la / "Google/Chrome/User Data/Default/Cache", la / "Microsoft/Edge/User Data/Default/Cache"],
              pkg_cache_dirs=[la / "pip/Cache", la / "npm-cache"],
              user_dirs=[h / "Documents", h / "Desktop", h / "Pictures", h / "Projects"],
              downloads=h / "Downloads", provenance=provenance_win if os.name == "nt" else (lambda p: None))
    world = resource.World(env=env, q=Quarantine(home), ctrl=ProcController() if os.name == "nt" else None)
    if os.name == "nt":
        # T6：真实 Windows 自启/通知控制器，与进程控制器组合（场景按 hasattr 取用）
        from .scenarios import win_ctrl as wc
        wc_ = wc.WindowsController(home)
        world.ctrl = wc.Composite(ProcController(), wc_)
        world.startup = wc_.list_startup()
    reg = Registry(); reg.register(resource.make())
    if cfg.get("desktop_tidy", True) and (h / "Desktop").is_dir(): reg.register(extras.desktop_pile(h / "Desktop"))
    from .scenarios import more
    reg.register(more.browser_tabs())                    # 数据源（snap.tabs）未接前自动静默
    reg.register(more.battery_prewarn())                 # 数据源（snap.battery）未接前自动静默
    reg.register(more.homework_env_prep())               # 扫描 user_dirs 里的编号作业目录
    projs = [Path(p) for p in cfg.get("projects", [])]
    if projs:   # 通用约定学习 + 重复造轮子证据提供者（联网查 GitHub，查不到就不动）
        from .scenarios import conventions as scv
        from .conventions import ConventionLearner
        from .capability import GitHubIndex, VerifierPolicy
        from .reinvention import ReinventionProvider
        reg.register(scv.make(ConventionLearner(), lambda w: projs, providers=[ReinventionProvider(GitHubIndex(os.environ.get("GITHUB_TOKEN")), VerifierPolicy(), lambda w: projs)]))
    return RealProbe(), world, reg
