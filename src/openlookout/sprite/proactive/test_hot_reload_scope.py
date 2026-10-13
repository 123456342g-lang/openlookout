"""brain 热更新的监测范围。

故障实录（2026-10-13 14:07–14:39）：改了
``vista/backends/claude/factory.py`` 让 ``create_backend`` 多接受一个参数，
结果 brain 每轮 ``TypeError`` -> 静默降级到 direct 端点 -> 每轮 HTTP 400。
精灵带着 400 跑了半小时，而 378 个测试全绿——因为 ``brain_stamp()`` 只盯着
``vista/benchmarks/desktop/``，后端目录根本不在视野里，改它永远不触发重启。

所以这里的测试不是测行为，是测**改动能不能被看见**。
"""
from __future__ import annotations

import ast
import inspect
import os

from sprite.proactive import live as live_mod


def _watched_files() -> set:
    """从 brain_stamp 的源码里取出它实际会看的文件集合。

    刻意不通过 mtime 行为间接推断：brain_stamp 返回所有候选文件 mtime 的
    max()，任何比目标文件更新的文件都会掩盖住目标文件的改动——那是 stamp
    的"有没有更新"语义，不是覆盖范围。要测覆盖范围就只能看它到底列了谁。
    """
    src = inspect.getsource(live_mod.brain_stamp)
    root = live_mod.ROOT
    desktop = root / "vista" / "benchmarks" / "desktop"
    backend = root / "vista" / "backends" / "claude"

    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith(".py"):
                names.add(node.value)

    candidates = set()
    for name in names:
        candidates.add(desktop / name)
        candidates.add(backend / name)
        candidates.add(live_mod.PKG / name)
    return candidates


def test_backend_factory_is_in_the_supervisor_watch_set():
    """改后端必须能触发 brain 重启，否则修复不会生效、也不会被察觉。"""
    factory = live_mod.ROOT / "vista" / "backends" / "claude" / "factory.py"
    assert factory.exists(), f"后端文件路径不对：{factory}"
    assert factory in _watched_files(), (
        "factory.py 不在 brain_stamp() 的监视范围里——改了后端也不会触发重启"
    )


def test_runner_is_in_the_supervisor_watch_set():
    """runner.py 决定 task_timeout / decision_lease，改它同样会静默影响 brain。"""
    runner = live_mod.ROOT / "vista" / "backends" / "claude" / "runner.py"
    assert runner.exists()
    assert runner in _watched_files(), "runner.py 不在 brain_stamp() 的监视范围里"


def test_desktop_brain_sources_are_still_watched():
    """补后端不能把原来的 desktop 目录挤掉——那是既有行为。"""
    watched = _watched_files()
    d = live_mod.ROOT / "vista" / "benchmarks" / "desktop"
    for name in ("brain.py", "session.py", "profiles.py"):
        assert (d / name) in watched, f"{name} 掉出了监视范围"


def test_stamp_is_stable_when_nothing_changes():
    """两次连续取值必须相同，否则 supervisor 会永远认为代码在变、无限重启。"""
    assert live_mod.brain_stamp() == live_mod.brain_stamp()


def test_stamp_moves_when_a_watched_file_is_touched():
    """正向验证 stamp 机制本身是活的（这里动的是 sprite/proactive/live.py）。"""
    target = live_mod.PKG / "live.py"
    original = target.stat().st_mtime
    before = live_mod.brain_stamp()
    try:
        os.utime(target, (original + 3600, original + 3600))
        after = live_mod.brain_stamp()
    finally:
        os.utime(target, (original, original))
    assert after > before, "touch 一个被监视的文件后 stamp 必须变化"