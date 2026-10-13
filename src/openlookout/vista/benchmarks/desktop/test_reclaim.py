"""C 盘满的时候：主动清理（desktop_reclaim）的能力测试。

钉住三条硬规矩：
1. 只动 risk 判 safe 的（可再生/可还原）；medium / high / 认不出来的一律不动；
2. 动手前逐个重新核对，状态变了就跳过（宁可少清，不可错清）；
3. 全部进可还原隔离区，restore_quarantine 能原样放回（从不覆盖已存在的文件）；
4. 没有安全项时，电脑一个字节都没被改动，且如实说“没找到”。

测试用临时目录造一个假 env，不碰真实机器。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from vista.benchmarks.desktop import actions
from vista.benchmarks.desktop.actions import reclaim, restore_quarantine
from sprite.risk import Env
from sprite.quarantine import Quarantine


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """一个可控制的假环境：缓存目录 + 用户目录，隔离区在 tmp/home 下。"""
    home = tmp_path / "home"; home.mkdir()
    temp = tmp_path / "Temp"; temp.mkdir()
    cache = tmp_path / "Cache"; cache.mkdir()
    pkg = tmp_path / "PipCache"; pkg.mkdir()
    docs = tmp_path / "Documents"; docs.mkdir()
    dl = tmp_path / "Downloads"; dl.mkdir()
    sandbox = tmp_path / "sandbox"; sandbox.mkdir()
    env = Env(now=time.time(), temp_dirs=[temp], browser_cache_dirs=[cache], pkg_cache_dirs=[pkg],
              user_dirs=[docs], downloads=dl, provenance=lambda p: None, big_mb=10)
    monkeypatch.setattr(actions, "HOME", home)
    monkeypatch.setattr(actions, "JOURNAL", sandbox / "undo.jsonl")
    return dict(home=home, env=env, temp=temp, cache=cache, pkg=pkg, docs=docs, dl=dl)


def _mk(p: Path, data: bytes = b"x" * 1024) -> Path:
    """造一个“三天前”的文件：risk 规定两小时内改过的一律当正在使用（保守）。"""
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    t = time.time() - 3 * 86400
    import os as _os; _os.utime(p, (t, t))
    return p


def test_reclaims_regenerable_cache(world):
    _mk(world["cache"] / "f_0001", b"c" * 2048)
    out = reclaim({}, env=world["env"], disk=lambda: 100.0)
    assert "已把 1 个可再生文件收进隔离区" in out.text
    assert not (world["cache"] / "f_0001").exists()                       # 原文件已收走
    assert Quarantine(world["home"]).held()                               # 隔离区里确实收着


def test_never_touches_user_documents_or_unknowns(world):
    doc = _mk(world["docs"] / "报告.docx", b"d" * 4096)
    _mk(world["dl"] / "奇怪的东西.bin", b"u" * 4096)
    out = reclaim({}, env=world["env"], disk=lambda: 100.0)
    assert doc.exists() and doc.read_bytes() == b"d" * 4096                # 用户文档一个字节没动
    assert "没有找到可以安全清理" in out.text


def test_nothing_safe_reports_hands_off(world):
    out = reclaim({}, env=world["env"], disk=lambda: 100.0)
    assert "没有找到可以安全清理" in out.text and "没有被改动" in out.text


def test_noncritical_disk_respects_explicit_small_batch(world):
    for i in range(5): _mk(world["cache"] / f"f_{i:04d}", b"c" * 512)
    out = reclaim({"max_items": 2}, env=world["env"], disk=lambda: 100.0)
    assert "已把 2 个" in out.text
    assert len(Quarantine(world["home"]).held()) == 2


def test_critical_disk_exhausts_safe_candidates_without_model_batch_limit(world):
    for i in range(5): _mk(world["cache"] / f"critical_{i:04d}", b"c" * 512)
    out = reclaim({"max_items": 1}, env=world["env"], disk=lambda: 0.5)
    assert "已把 5 个" in out.text
    assert len(Quarantine(world["home"]).held()) == 5


def test_undo_restores_everything(world):
    data = b"r" * 3072
    _mk(world["cache"] / "f_0001", data)
    reclaim({}, env=world["env"], disk=lambda: 100.0)
    msg = restore_quarantine()
    assert "已还原 1 个" in msg
    back = world["cache"] / "f_0001"
    assert back.exists() and back.read_bytes() == data                    # 原样回来，逐字节一致


def test_undo_never_overwrites_what_reappeared(world):
    _mk(world["cache"] / "f_0001", b"a" * 1024)
    reclaim({}, env=world["env"], disk=lambda: 100.0)
    _mk(world["cache"] / "f_0001", b"new" * 512)                           # 同一个位置又出现了新文件
    restore_quarantine()
    assert (world["cache"] / "f_0001").read_bytes() == b"new" * 512        # 新内容不被覆盖
    assert any("restored" in p.name for p in world["cache"].iterdir())     # 还原到旁边的新名字


def test_undo_is_idempotent(world):
    _mk(world["cache"] / "f_0001", b"a" * 1024)
    reclaim({}, env=world["env"], disk=lambda: 100.0)
    restore_quarantine()
    assert "没有待还原" in restore_quarantine()


def test_journal_written_before_acting(world):
    _mk(world["cache"] / "f_0001", b"a" * 1024)
    reclaim({}, env=world["env"], disk=lambda: 100.0)
    rows = [json.loads(l) for l in (world["home"] / "quarantine" / "restore_map.jsonl").read_text("utf-8").splitlines() if l.strip()]
    assert rows and rows[0]["orig"].endswith("f_0001")


def test_disk_free_unreadable_returns_minus_one():
    assert actions.disk_free_gb("Z:/definitely-not-a-drive-xyz") == -1.0


def test_reclaim_reports_freed_space(world):
    for i in range(3): _mk(world["cache"] / f"f_{i:04d}", b"c" * 4096)
    seen = {"n": 0}
    def disk():
        seen["n"] += 1
        return 99.0 if seen["n"] == 1 else 100.5                         # 清理后多出 1.5GB
    out = reclaim({}, env=world["env"], disk=disk)
    assert "1.5GB" in out.text and "可还原" in out.text
