"""系统事实：视觉看不见、但决定这台电脑还能不能干活的那部分。

为什么必须有这个模块（AGENTS.md 的核心原则：视觉上下文由 VISTA 管，别再造一份）：
  VISTA 看得见「屏幕上开着什么」，看不见「C 盘只剩 0.4%」「内存已用 93%」。
  屏幕上就是开着个文件夹——画面里没有任何一个像素能说明磁盘快满了。
  所以「资源压力」这条线只能自己取事实，再附到模型的 STEP 里，跟watching 同一套规矩：
  **只给事实，不给结论**；不该说话的时候返回空串（宁可安静，误打扰比漏提醒代价高）。

它同时是「主动帮忙」这条闭环的事实源：只有知道 C 盘快满了，
才能在合适的时候说「要不要我清一下」——而不是等用户来问。

测得准不准全靠 tests 里的真值回归：psutil/shutil 的读数没有注入入口，
所以每个数字都在测试里核对「和你自己 psutil 读出来的一致」，不许拿假数糊弄。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None                # 没有 psutil 只做文件类事实，绝不猜进程

# 判定门槛。改这里等于改「什么情况算告急」。
DEFAULTS = dict(
    disk_free_pct=5.0,       # C 盘剩余低于这个百分比 = 告急
    disk_free_gb=10.0,       # 或者绝对值低于这个 GB（盘小的时候百分比会误导）
    mem_avail_gb=1.5,        # 可用内存低于这个 GB = 告急
    mem_avail_pct=10.0,      # 或者可用百分比低于这个
    top_n=5,                 # 报几个占资源的
    heavy_mb=512,            # 单进程超过这个 MB 才值得点名
    trend_every_s=600.0,     # 每 10 分钟记一次读数，用来算「是不是在恶化」
    keep_s=7 * 24 * 3600.0,  # 读数保留期
)


def _gb(n: float) -> float:
    return round(float(n) / 2 ** 30, 2)


def _mins(s) -> str:
    if s is None:
        return ""
    s = max(0.0, float(s))
    return f"{int(s // 60)} 分钟" if s >= 90 else f"{int(s)} 秒"


def disk_facts(path: str = "C:/") -> dict:
    """磁盘真实读数。拿不到就返回 ok=False，绝不用旧值或猜值。"""
    try:
        u = shutil.disk_usage(path)
        return dict(ok=True, path=path, free_gb=_gb(u.free), used_gb=_gb(u.used),
                    total_gb=_gb(u.total), free_pct=round(u.free / u.total * 100, 2))
    except OSError as e:
        return dict(ok=False, path=path, error=f"{type(e).__name__}")


def mem_facts() -> dict:
    """内存真实读数。"""
    if psutil is None:
        return dict(ok=False, error="没有 psutil")
    try:
        m = psutil.virtual_memory()
        return dict(ok=True, avail_gb=_gb(m.available), used_gb=_gb(m.used),
                    total_gb=_gb(m.total), avail_pct=round(m.available / m.total * 100, 2))
    except Exception as e:                        # psutil 在某些系统上会抛非 psutil.Error
        return dict(ok=False, error=f"{type(e).__name__}")


def heavy_procs(top_n: int = 5, heavy_mb: int = 512) -> list[dict]:
    """占资源最多的进程。只看内存——这是唯一能安全挂起的维度。

    返回的每一项都带 pid，因为挂起/结束必须精确到进程，模型需要 pid 才能提具体建议。
    """
    if psutil is None:
        return []
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            rss = p.info["memory_info"].rss // 2 ** 20
            if rss >= heavy_mb:
                rows.append(dict(pid=p.pid, name=(p.info["name"] or "")[:40], rss_mb=rss))
        except psutil.Error:
            continue
    rows.sort(key=lambda r: -r["rss_mb"])
    return rows[:top_n]


class SystemWatcher:
    """一轮一次 observe()，维护资源事实与趋势。clock/注入源便于无头测试。"""

    def __init__(self, cfg: dict | None = None, clock=time.time, *, disk=disk_facts, mem=mem_facts, procs=heavy_procs):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.clock = clock
        self._disk, self._mem, self._procs = disk, mem, procs
        self.samples: list[dict] = []          # [{t, disk_free, mem_avail}]按时间升序
        self.last_t: float | None = None

    # ------------------------------------------------------------------ 主入口
    def observe(self, now: float | None = None) -> "SystemFacts":
        t = now if now is not None else self.clock()
        d, m = self._disk(), self._mem()
        p = self._procs(self.cfg["top_n"], self.cfg["heavy_mb"])
        # 趋势按固定间隔记，不每轮都记——读数抖一下不代表在恶化
        if self.last_t is None or t - self.last_t >= self.cfg["trend_every_s"]:
            self.samples.append(dict(t=t, disk_free=d.get("free_gb"), mem_avail=m.get("avail_gb")))
            self.last_t = t
            cut = t - self.cfg["keep_s"]
            self.samples = [s for s in self.samples if s["t"] >= cut]
        return SystemFacts(d, m, p, self._trend(), self.cfg)

    def _trend(self) -> dict:
        """和最早的一笔比：是在恶化还是在好转。样本不足就什么都不说。"""
        if len(self.samples) < 2:
            return dict(known=False)
        a, b = self.samples[0], self.samples[-1]
        out = dict(known=True, span_s=b["t"] - a["t"])
        if a.get("disk_free") is not None and b.get("disk_free") is not None:
            out["disk_delta_gb"] = round(b["disk_free"] - a["disk_free"], 2)
        if a.get("mem_avail") is not None and b.get("mem_avail") is not None:
            out["mem_delta_gb"] = round(b["mem_avail"] - a["mem_avail"], 2)
        return out

    # ------------------------------------------------------------------ 持久化
    def to_dict(self) -> dict:
        return dict(samples=self.samples, last_t=self.last_t, cfg=self.cfg)

    @classmethod
    def from_dict(cls, d: dict) -> "SystemWatcher":
        w = cls(cfg=d.get("cfg"))
        w.samples = list(d.get("samples") or [])
        w.last_t = d.get("last_t")
        return w


class SystemFacts:
    """一轮的资源事实。字段名就是给模型看的事实名。"""

    __slots__ = ("disk", "mem", "procs", "trend", "cfg", "disk_critical", "mem_critical")

    def __init__(self, disk: dict, mem: dict, procs: list, trend: dict, cfg: dict):
        self.disk, self.mem, self.procs, self.trend, self.cfg = disk, mem, procs, trend, cfg
        self.disk_critical = bool(
            disk.get("ok") and (disk.get("free_pct", 100) <= cfg["disk_free_pct"]
                                or disk.get("free_gb", 1e9) <= cfg["disk_free_gb"]))
        self.mem_critical = bool(
            mem.get("ok") and (mem.get("avail_gb", 1e9) <= cfg["mem_avail_gb"]
                               or mem.get("avail_pct", 100) <= cfg["mem_avail_pct"]))

    def line(self) -> str:
        """附在 STEP 后面的一句事实。

        规矩和硬规则3 一致——宁可安静：
        - 一切正常：返回空串，一个字都不说；
        - 只在「已经告急」或「正在明显恶化」时才说话。
        """
        c = self.cfg
        urgent = self.disk_critical or self.mem_critical
        worsening = (self.trend.get("known") and
                     ((self.trend.get("disk_delta_gb") or 0) <= -c["disk_free_gb"] / 2
                      or (self.trend.get("mem_delta_gb") or 0) <= -c["mem_avail_gb"] / 2))
        if not (urgent or worsening):
            return ""
        parts = []
        if self.disk_critical:
            parts.append(f"C盘只剩 {self.disk.get('free_gb')}GB（{self.disk.get('free_pct')}%）")
        elif self.disk.get("ok") and worsening and self.trend.get("disk_delta_gb") is not None:
            parts.append(f"C盘在持续变少，{_mins(self.trend['span_s'])}里少了{abs(self.trend['disk_delta_gb'])}GB")
        if self.mem_critical:
            parts.append(f"可用内存只剩 {self.mem.get('avail_gb')}GB（已用 {round(100 - self.mem.get('avail_pct', 0), 1)}%）")
        elif self.mem.get("ok") and worsening and self.trend.get("mem_delta_gb") is not None:
            parts.append(f"可用内存{_mins(self.trend['span_s'])}里少了{abs(self.trend['mem_delta_gb'])}GB")
        if self.procs and (self.mem_critical or self.disk_critical):
            top = "、".join(f"{q['name']}({q['rss_mb']}MB, pid={q['pid']})" for q in self.procs[:3])
            parts.append(f"占资源最多的是：{top}")
        return "【系统】" + "；".join(parts) + "。"

    def short(self) -> str:
        """一行给界面看的现状（不是给模型的判断）。"""
        d = f"剩{self.disk.get('free_gb')}GB" if self.disk.get("ok") else "读不到"
        m = f"剩{self.mem.get('avail_gb')}GB" if self.mem.get("ok") else "读不到"
        return f"C盘{d}，内存{m}"


def state_path(home: Path) -> Path:
    return Path(home) / "companion" / "system.json"


def save(w: SystemWatcher, home: Path) -> None:
    p = state_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(w.to_dict(), ensure_ascii=False), "utf-8")
    tmp.replace(p)


def load(home: Path, cfg: dict | None = None) -> SystemWatcher:
    try:
        return SystemWatcher.from_dict(json.loads(state_path(home).read_text("utf-8")))
    except Exception:
        return SystemWatcher(cfg)