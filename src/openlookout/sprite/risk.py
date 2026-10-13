"""风险模型：给“可以清理的候选”分级。原则：不确定就当高风险；任何一条硬护栏命中都直接降为 high（永不自动动、也不提议删除）。
级别：safe（可再生/可重新下载/可挂起，自动做）、medium（有可验证副本等，批量问一次）、high（用户文档、未保存、唯一物，不碰）。"""
from __future__ import annotations
import os, re, time
from dataclasses import dataclass, field
from pathlib import Path

UNKNOWN_REASON = "既不是可再生缓存也没有可验证副本，当作唯一物"
USER_DOC_EXT = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".py", ".ipynb", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs",
                ".psd", ".ai", ".sketch", ".fig", ".csv", ".json", ".db", ".sqlite", ".sqlite3", ".key", ".pem", ".pfx", ".kdbx", ".md", ".txt", ".tex",
                ".bib", ".odt", ".rtf", ".dwg", ".mp4", ".mov", ".wav", ".jpg", ".jpeg", ".png", ".heic", ".zip", ".7z", ".rar", ".sql", ".env", ".ini", ".yaml", ".yml", ".toml"}
PRECIOUS = re.compile(r"(final|backup|备份|论文|thesis|毕业|重要|important|合同|发票|invoice|passport|身份|密码|password|wallet|私钥|recovery)", re.I)
INSTALLER_EXT = {".exe", ".msi", ".iso", ".dmg", ".pkg", ".deb", ".appimage"}
LOCK_NAMES = re.compile(r"(^~\$|\.lock$|\.swp$|\.crdownload$|\.part$|^\.~lock)")
EDITORS = {"winword", "excel", "powerpnt", "code", "notepad++", "notepad", "typora", "obsidian", "pycharm64", "idea64", "sublime_text", "wps", "et", "wpp", "photoshop", "illustrator"}
BROWSERS = {"chrome", "msedge", "firefox", "brave", "tabbit"}
HELPERS = {"msedgewebview2", "crashpad_handler", "chrome_crashpad_handler", "updater", "gpu-process-helper"}
PROTECTED = {"explorer", "system", "dwm", "csrss", "winlogon", "services", "svchost", "lsass", "msmpeng", "python", "pythonw", "cmd", "powershell", "wt", "conhost",
             "openlookout", "sprite", "ssh", "sshd", "docker", "dockerd", "postgres", "mysqld", "mongod", "redis-server"}


@dataclass
class Risk:
    level: str                 # safe | medium | high
    reason: str
    regenerable: bool = False
    action: str = ""           # quarantine | suspend | none
    copy: str | None = None


def _high(r): return Risk("high", r, False, "none")


@dataclass
class Env:
    now: float = field(default_factory=time.time)
    temp_dirs: list = field(default_factory=list)          # 系统/用户临时目录
    browser_cache_dirs: list = field(default_factory=list)
    pkg_cache_dirs: list = field(default_factory=list)     # pip/npm/nuget 缓存
    user_dirs: list = field(default_factory=list)          # 文档/桌面/图片/项目
    downloads: Path | None = None
    open_paths: set = field(default_factory=set)           # 正被占用/打开的文件
    provenance: callable = lambda p: None                  # 下载来源 URL（Zone.Identifier）
    find_copy: callable = lambda p: None                   # 字节级验证过的另一份副本路径
    running: list = field(default_factory=list)            # 运行中进程（用于判断“正在使用”）
    big_mb: int = 500                                       # “大文件”门槛（演示用沙箱会调小；真实使用保持 500）

    def under(self, p: Path, roots):
        p = Path(p)
        return any(Path(r) == p or Path(r) in p.parents for r in roots)


def classify_file(path, env: Env) -> Risk:
    p = Path(path)
    try:
        if p.is_symlink(): return _high("符号链接/联接点，可能指向别处")
        st = p.stat()
    except OSError: return _high("读不到状态")
    if not p.is_file(): return _high("不是普通文件")
    age_h = (env.now - st.st_mtime) / 3600
    name = p.name
    if str(p) in env.open_paths or LOCK_NAMES.search(name): return _high("文件正被占用或是锁/临时标记文件")
    if age_h < 2: return _high("两小时内改过，可能正在使用")
    if PRECIOUS.search(str(p)): return _high("路径里有“最终/备份/论文/重要”等字样")
    ext = p.suffix.lower()
    in_temp = env.under(p, env.temp_dirs); in_bc = env.under(p, env.browser_cache_dirs); in_pkg = env.under(p, env.pkg_cache_dirs)
    in_user = env.under(p, env.user_dirs)
    # __pycache__ 里的 .pyc 永远可再生
    if ext == ".pyc" and p.parent.name == "__pycache__": return Risk("safe", "Python 字节码缓存，可再生", True, "quarantine")
    if in_user and not (in_temp or in_bc or in_pkg): 
        pass                                     # 用户目录里的东西，除了安装包规则，一律不当缓存
    elif in_bc:
        if ext in USER_DOC_EXT: return _high("在浏览器缓存目录里却是文档类文件，可能是用户放的")
        return Risk("safe", "浏览器缓存，可再生", True, "quarantine")
    elif in_pkg:
        return Risk("safe", "包管理器缓存，可重新下载", True, "quarantine")
    elif in_temp:
        if ext in USER_DOC_EXT: return _high("临时目录里的文档类文件，可能是未保存/导出的工作")
        if age_h < 24: return _high("临时文件不到一天，可能还在用")
        return Risk("safe", "超过一天的临时文件", True, "quarantine")
    # 旧安装包：必须有可验证来源
    if env.downloads and env.under(p, [env.downloads]) and ext in INSTALLER_EXT and age_h > 24 * 30:
        url = env.provenance(p)
        if url and url.startswith("https://"): return Risk("safe", f"旧安装包，可从 {url[:40]} 重新下载", True, "quarantine")
        return Risk("medium", "旧安装包但查不到下载来源", False, "quarantine")
    # 大而旧的文件，有字节级验证过的另一份副本
    if st.st_size >= env.big_mb * 2**20 and age_h > 24 * 90:
        c = env.find_copy(p)
        if c and Path(c) != p and not env.under(Path(c), env.temp_dirs + env.browser_cache_dirs): return Risk("medium", f"大而旧，另有一份核对过的副本：{c}", False, "quarantine", str(c))
    return _high(UNKNOWN_REASON)


def classify_dir(path, env: Env) -> Risk:
    p = Path(path)
    if p.name == "node_modules":
        proj = p.parent
        if not (proj / "package.json").exists(): return _high("没有 package.json，来路不明")
        if not any((proj / f).exists() for f in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")): return _high("没有锁文件，无法保证重装得出同样结果")
        if any(str(proj) in (r.cwd or "") or str(proj) in (r.cmdline or "") for r in env.running): return _high("有进程正在使用这个项目")
        newest = max((q.stat().st_mtime for q in proj.iterdir() if q.is_file()), default=0)
        if (env.now - newest) < 14 * 86400: return _high("项目最近两周还在改")
        return Risk("medium", "可由锁文件重装，但需要联网重装", False, "quarantine")
    return _high("未知目录")


PROC_IDLE_SCALE = 1.0      # 空闲时长门槛的缩放。真实使用=1（15/30 分钟）；现场演示会调小，让刚启动的精灵不必先观察 15 分钟（演示专用，见 demo_live）


def classify_proc(pr, our_pid=None) -> Risk:
    n = pr.name.lower()
    if n in PROTECTED or pr.pid == our_pid: return _high("系统/受保护进程")
    if n in EDITORS or any(m in (pr.title or "") for m in ("*", "●", "未保存", "unsaved", "Untitled", "无标题")) and pr.has_window:
        return _high("编辑器或窗口标题显示可能有未保存内容")
    if pr.foreground_tree: return _high("属于当前前台窗口")
    if pr.audio: return _high("正在播放/通话")
    audio_unknown = pr.audio is None
    if pr.children and n not in BROWSERS: return _high("有子进程，可能在跑任务")
    if n in BROWSERS and "--type=renderer" in (pr.cmdline or ""):
        if pr.has_window or pr.idle_s < (1800 if audio_unknown else 900) * PROC_IDLE_SCALE or pr.rss_mb < 150: return _high("不是长时间空闲的大渲染进程" + ("（音频状态未知，要求空闲更久）" if audio_unknown else ""))
        return Risk("safe", f"浏览器后台标签进程，空闲 {pr.idle_s/60:.0f} 分钟，挂起即可，切回浏览器时自动恢复", True, "suspend")
    if n in HELPERS and not pr.parent_alive and not pr.has_window and pr.idle_s >= 1800 * PROC_IDLE_SCALE and pr.rss_mb >= 50:
        return Risk("safe", f"父进程已退出的残留辅助进程，空闲 {pr.idle_s/60:.0f} 分钟，挂起", True, "suspend")
    return _high("不是已知的可安全处理类型")
