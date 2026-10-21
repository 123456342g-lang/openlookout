"""内存告急时的手段：desktop_trim 必须够轻、够安全。

为什么它是内存告急的第一手段：
- 进程还活着、还在跑，只是不再占着闲置的页；
- 那些页程序自己要用时会**自动换回**（换页，不丢数据）；
- 所以**没有需要撤回的改动**——这比挂起（进程冻结、用户看见卡住）和结束（丢现场）都轻。

要钉住的：
1. 真的把可用内存抬上去了（用真进程量，别用假数）
2. 被拒的进程一个都不许碰（前台/系统/安全/自己）
3. 失败时如实说「没有改动任何东西」，不许谎报成功
"""
from __future__ import annotations

import subprocess
import sys
import time

import psutil
import pytest

from vista.benchmarks.desktop import actions


def _victim() -> subprocess.Popen:
    """一个吃内存的短命进程，用完即杀。"""
    return subprocess.Popen([sys.executable, "-c",
                             "x = bytearray(300 * 1024 * 1024)\nimport time\ntime.sleep(60)"])


# ---------------------------------------------------------------- 真效果
@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows kernel32")
def test_trim_frees_memory_for_real(monkeypatch):
    """真跑：起一个吃内存的进程，trim 之后可用内存应该上升。

    只把「前台判定」拿掉来构造干净的实验条件——真跑时前台保护照样生效，
    那是另一个测试专门钉的。
    """
    monkeypatch.setattr(actions, "_refusal", lambda pid: None)
    v = _victim()
    try:
        time.sleep(2.0)
        p = psutil.Process(v.pid)
        assert p.memory_info().rss > 200 * 2 ** 20, "先确认它确实吃了内存"
        before = psutil.virtual_memory().available
        r = actions.trim({"pid": v.pid})
        after = psutil.virtual_memory().available
        assert r.success, r.text
        # 进程还活着 = 没被杀掉，这是 trim 与 suspend/end 的本质区别
        assert v.poll() is None, "trim 不许结束进程"
        assert after >= before, f"可用内存不该变少：{before} -> {after}"
    finally:
        v.kill(); v.wait(timeout=10)


def test_trim_needs_no_undo():
    """trim 不产生需要撤回的改动——所以不该往journal 里写东西。"""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        j = Path(d) / "undo.jsonl"
        old = actions.JOURNAL
        actions.JOURNAL = j
        try:
            v = _victim()
            try:
                time.sleep(1.5)
                actions.trim({"pid": v.pid})
            finally:
                v.kill(); v.wait(timeout=10)
        finally:
            actions.JOURNAL = old
        assert not j.exists(), "trim 没有需要撤回的改动，不该写 journal"


# ---------------------------------------------------------------- 拒绝：不该碰的一律不碰
def test_trim_refuses_self():
    r = actions.trim({"pid": psutil.Process().pid})
    assert r.success is False and "本程序" in r.text


def test_trim_refuses_foreground(monkeypatch):
    """前台窗口的进程不能碰——那是用户正在用的。"""
    import os
    monkeypatch.setattr(actions, "foreground_family", lambda: {psutil.Process().pid})
    r = actions.trim({"pid": psutil.Process().pid})
    assert r.success is False and "前台" in r.text


def test_trim_refuses_protected_names(monkeypatch):
    """系统/安全进程不碰。"""
    from sprite.procctl import DENY_NAMES
    if not DENY_NAMES:
        pytest.skip("保护名单为空")
    monkeypatch.setattr(actions, "_refusal", lambda pid: f"{next(iter(DENY_NAMES))} 在保护名单")
    r = actions.trim({"pid": 12345})
    assert r.success is False and "保护名单" in r.text


def test_trim_refuses_dead_pid():
    r = actions.trim({"pid": 999999})
    assert r.success is False
    assert "没有改动" in r.text or "不存在" in r.text, "失败要说清没改动任何东西"


# ---------------------------------------------------------------- 失败不许谎报
@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows kernel32")
def test_failure_never_claims_success(monkeypatch):
    """OpenProcess 失败时必须如实说没改动，不能返回成功。"""
    import ctypes
    monkeypatch.setattr(actions, "_refusal", lambda pid: None)
    monkeypatch.setattr(ctypes.windll.kernel32, "OpenProcess", lambda *a: 0)
    r = actions.trim({"pid": psutil.Process().pid})
    assert r.success is False
    assert "没有改动" in r.text


def test_trim_is_registered_for_the_model():
    """工具必须真的给模型，否则等于没有。"""
    from vista.benchmarks.desktop.profiles import TOOLS
    assert "desktop_trim" in actions.SPECS
    assert "desktop_trim" in TOOLS


def test_trim_described_as_the_lightest_option():
    """提示要写清「先试这个」——否则模型会直接去挂起。"""
    spec = actions.SPECS["desktop_trim"][1]
    assert "最轻" in spec.description or "先试这个" in spec.description
    assert "不需要撤销" in spec.description