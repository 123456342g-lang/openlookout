"""系统事实的测试。核心要求：报出来的每个数字都必须是真的，不是编的。

真值回归的做法很硬——测试里自己用 psutil/shutil 读一遍，再和模块报的对比，
对不上就失败。这样「它是不是在瞎报」由机器判定，不靠人看。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from vista.benchmarks.desktop.systemfacts import (
    DEFAULTS, SystemWatcher, disk_facts, heavy_procs, load, mem_facts, save, state_path,
)


def _w(**kw) -> SystemWatcher:
    return SystemWatcher(clock=kw.pop("clock", lambda: 1000.0), **kw)


def _fake(disk=None, mem=None, procs=None):
    """注入固定读数，用来测判定逻辑（趋势、告急阈值），不依赖真实机器状态。"""
    d = disk if disk is not None else {"ok": True, "free_gb": 80.0, "free_pct": 60.0, "used_gb": 53.0, "total_gb": 133.0}
    m = mem if mem is not None else {"ok": True, "avail_gb": 12.0, "avail_pct": 45.0, "used_gb": 15.0, "total_gb": 27.0}
    p = procs if procs is not None else []
    return dict(disk=lambda *a: dict(d), mem=lambda *a: dict(m), procs=lambda *a, **k: list(p))


# ---------------------------------------------------------------- 真值回归：数字必须是真的
def test_disk_reading_matches_shutil():
    """报的 C 盘读数必须和 shutil 自己读的一致——不允许四舍五入到离谱。"""
    f = disk_facts("C:/")
    truth = shutil.disk_usage("C:/")
    assert f["ok"] and f["total_gb"] > 0
    assert abs(f["free_gb"] - truth.free / 2**30) < 0.05
    assert abs(f["free_pct"] - truth.free / truth.total * 100) < 0.05


def test_mem_reading_matches_psutil():
    import psutil
    f = mem_facts()
    truth = psutil.virtual_memory()
    assert f["ok"]
    assert abs(f["avail_gb"] - truth.available / 2**30) < 0.05
    assert abs(f["avail_pct"] - truth.available / truth.total * 100) < 0.05


def test_heavy_procs_carry_pid_and_are_sorted():
    """挂起/结束必须精确到 pid，模型没有 pid 就提不出能执行的建议。"""
    rows = heavy_procs(top_n=3, heavy_mb=1)
    assert isinstance(rows, list)
    for r in rows:
        assert {"pid", "name", "rss_mb"} <= set(r)
    assert [r["rss_mb"] for r in rows] == sorted((r["rss_mb"] for r in rows), reverse=True)


def test_bad_disk_path_reports_failure_not_a_guess():
    """读不到就说读不到，绝不返回旧值或猜值。"""
    f = disk_facts("Z:/definitely-not-a-drive")
    assert f["ok"] is False and "error" in f


# ---------------------------------------------------------------- 判定：告急 / 不告急
def test_calm_machine_says_nothing():
    """一切正常时一个字都不说——宁可安静，误打扰比漏提醒代价高。"""
    w = SystemWatcher(disk=_fake()["disk"], mem=_fake()["mem"], procs=_fake()["procs"], clock=lambda: 0.0)
    assert w.observe().line() == ""


def test_critical_disk_is_reported_with_real_numbers():
    """C 盘告急必须报出来，并且带上可用 desktop_processes 核对的数字。"""
    w = SystemWatcher(disk=_fake(disk={"ok": True, "free_gb": 0.6, "free_pct": 0.4,
                                       "used_gb": 148.4, "total_gb": 149.0})["disk"],
                      mem=_fake()["mem"], procs=_fake()["procs"], clock=lambda: 0.0)
    f = w.observe()
    assert f.disk_critical
    line = f.line()
    assert "C盘" in line and "0.6" in line, line          # 就是真读到的那个数
    assert len(line) <= 140, line


def test_critical_memory_is_reported():
    w = SystemWatcher(disk=_fake()["disk"],
                      mem=_fake(mem={"ok": True, "avail_gb": 1.07, "avail_pct": 6.8,
                                     "used_gb": 14.9, "total_gb": 16.0})["mem"],
                      procs=_fake()["procs"], clock=lambda: 0.0)
    f = w.observe()
    assert f.mem_critical and "内存" in f.line() and "1.07" in f.line()


def test_healthy_disk_does_not_trigger():
    w = SystemWatcher(disk=_fake(disk={"ok": True, "free_gb": 80.0, "free_pct": 60.0,
                                       "used_gb": 53.0, "total_gb": 133.0})["disk"],
                      mem=_fake()["mem"], procs=_fake()["procs"], clock=lambda: 0.0)
    assert not w.observe().disk_critical


def test_no_memory_reading_does_not_panic():
    """psutil 缺失时不能崩，也不能瞎报。"""
    w = SystemWatcher(disk=_fake()["disk"], mem=lambda *a: dict(ok=False, error="没有 psutil"),
                      procs=lambda *a, **k: [], clock=lambda: 0.0)
    f = w.observe()
    assert f.mem_critical is False
    assert "内存" not in f.line()


# ---------------------------------------------------------------- 趋势
def test_worsening_disk_is_reported_even_before_threshold():
    """还没到告急线，但正在快速恶化——这才是最该提的时刻。"""
    import psutil
    clock = {"t": 0.0}
    vals = iter([80.0, 40.0])
    w = SystemWatcher(cfg={"trend_every_s": 1.0}, clock=lambda: clock["t"],
                      disk=lambda *a: {"ok": True, "free_gb": next(vals), "free_pct": 30.0,
                                       "used_gb": 70.0, "total_gb": 120.0},
                      mem=_fake()["mem"], procs=_fake()["procs"])
    clock["t"] = 0.0
    w.observe()
    clock["t"] = 3600.0
    f = w.observe()
    assert f.trend["known"] and f.trend["disk_delta_gb"] < 0
    assert "变少" in f.line()


def test_improving_disk_is_not_reported():
    """在好转就不该报——不能让用户以为有坏消息。"""
    clock = {"t": 0.0}
    vals = iter([40.0, 80.0])
    w = SystemWatcher(cfg={"trend_every_s": 1.0}, clock=lambda: clock["t"],
                      disk=lambda *a: {"ok": True, "free_gb": next(vals), "free_pct": 50.0,
                                       "used_gb": 40.0, "total_gb": 120.0},
                      mem=_fake()["mem"], procs=_fake()["procs"])
    clock["t"] = 0.0
    w.observe()
    clock["t"] = 3600.0
    assert w.observe().line() == ""


def test_single_sample_has_no_trend():
    """只有一笔读数就敢谈趋势是瞎报——必须没有趋势。"""
    w = SystemWatcher(clock=lambda: 0.0, **_fake())
    assert w.observe().trend["known"] is False


# ---------------------------------------------------------------- 持久化
def test_persistence_round_trip():
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        w = SystemWatcher(clock=lambda: 0.0, **_fake())
        w.observe()
        save(w, home)
        assert state_path(home).exists()
        again = load(home)
        assert again.samples and again.samples[0]["disk_free"] == 80.0
        json.loads(state_path(home).read_text("utf-8"))     # 必须是合法 JSON


def test_load_without_file_is_fresh():
    with tempfile.TemporaryDirectory() as d:
        w = load(Path(d))
        assert w.samples == []


# ---------------------------------------------------------------- 现状：这台机器现在什么样
def test_this_machine_reports_its_real_state():
    """直接在这台机器上跑一次：要么安静，要么报真数，不许报错。"""
    f = SystemWatcher().observe()
    assert isinstance(f.line(), str)
    assert f.short()