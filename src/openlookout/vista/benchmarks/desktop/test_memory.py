"""记忆摘要的测试：只做一件事——把最近的结果变成每轮一句话，且严格保守。

保守在哪：只看最近 7 天；同一话题一次拒绝不算数（手滑也常见）；
输出必须短（不能把提示词撑爆）；没有数据时必须是空串（宁可安静）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from vista.benchmarks.desktop.memory import RECENT_S, brief


def _offer(tmp_path: Path, topic: str, result: str, t: float, text: str = "") -> None:
    d = tmp_path / "perceive"; d.mkdir(parents=True, exist_ok=True)
    with (d / "offers.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(id="x", t=t, topic=topic, kind="offer", text=text, confidence=0.8, result=result), ensure_ascii=False) + "\n")


def test_no_data_says_nothing(tmp_path: Path):
    assert brief(tmp_path) == ""


def test_accepts_listed(tmp_path: Path):
    now = time.time()
    for _ in range(2): _offer(tmp_path, "清理内存", "accepted", now - 60)
    out = brief(tmp_path, now)
    assert "接受过" in out and "清理内存" in out, out


def test_one_dismissal_is_not_a_ban(tmp_path: Path):
    now = time.time()
    _offer(tmp_path, "桌面归类", "dismissed", now - 60)
    assert brief(tmp_path, now).strip().endswith("。") and "桌面归类" not in brief(tmp_path, now)


def test_repeated_dismissal_keeps_his_words(tmp_path: Path):
    now = time.time()
    _offer(tmp_path, "定时提醒", "dismissed", now - 100, text="到点提醒你休息")
    _offer(tmp_path, "定时提醒", "dismissed", now - 50, text="到点提醒你休息")
    out = brief(tmp_path, now)
    assert "拒绝过" in out and "别换说法再提" in out and "到点提醒" in out, out


def test_old_results_drop_off(tmp_path: Path):
    now = time.time()
    _offer(tmp_path, "定时提醒", "dismissed", now - RECENT_S - 100, text="到点")
    _offer(tmp_path, "定时提醒", "dismissed", now - RECENT_S - 50, text="到点")
    assert brief(tmp_path, now) == ""


def test_output_is_short(tmp_path: Path):
    now = time.time()
    for i in range(10):
        _offer(tmp_path, f"话题{i}", "dismissed", now - 10, text="海" * 60)
        _offer(tmp_path, f"话题{i}", "dismissed", now - 20, text="海" * 60)
    assert len(brief(tmp_path, now)) <= 400, len(brief(tmp_path, now))


def test_broken_lines_are_skipped(tmp_path: Path):
    now = time.time()
    d = tmp_path / "perceive"; d.mkdir(parents=True)
    (d / "offers.jsonl").write_text("不是 json\n" + json.dumps(dict(t=now - 5, topic="清理内存", result="accepted")) + "\n", encoding="utf-8")
    assert "清理内存" in brief(tmp_path, now)
