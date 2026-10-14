"""记忆摘要的测试：只做一件事——把最近的结果变成每轮一句话，且严格保守。

保守在哪：只看最近 7 天；同一话题一次拒绝不算数（手滑也常见）；
输出必须短（不能把提示词撑爆）；没有数据时必须是空串（宁可安静）。

issue #15 ②：事实线改读 perceive/outcomes.jsonl 的 accepted/rejected
（同意门后 offers.jsonl 的 accepted/dismissed 生产 0 行，继续读会恒空）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from vista.benchmarks.desktop.memory import RECENT_S, brief


def _outcome(tmp_path: Path, topic: str, outcome: str, t: float,
             text: str = "", *, oid: str | None = None) -> None:
    d = tmp_path / "perceive"; d.mkdir(parents=True, exist_ok=True)
    row = dict(id=oid or f"o-{topic}-{outcome}-{t}", t=t, topic=topic,
               kind="offer", text=text, outcome=outcome, latency_s=1.5)
    with (d / "outcomes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_no_data_says_nothing(tmp_path: Path):
    # perceive/ 都不存在：宁可安静
    assert brief(tmp_path) == ""


def test_empty_ledger_says_nothing(tmp_path: Path):
    d = tmp_path / "perceive"; d.mkdir(parents=True)
    (d / "outcomes.jsonl").write_text("", encoding="utf-8")
    assert brief(tmp_path) == ""


def test_accepts_listed(tmp_path: Path):
    now = time.time()
    _outcome(tmp_path, "清理内存", "accepted", now - 60)
    _outcome(tmp_path, "清理内存", "accepted", now - 30)
    out = brief(tmp_path, now)
    assert "接受过" in out and "清理内存" in out, out


def test_single_accepted_is_listed_without_min_count(tmp_path: Path):
    """P2-6：accepted 侧有意不设 MIN_COUNT（与 rejected 不对称，见 brief docstring）。

    接住过一次的话题就值得记住；旧 offers 口径同样是 1 条即进【记忆】，不是回归。
    """
    now = time.time()
    _outcome(tmp_path, "清理内存", "accepted", now - 60, oid="only-one")
    out = brief(tmp_path, now)
    assert "接受过" in out and "清理内存" in out, out


def test_one_rejection_is_not_a_ban(tmp_path: Path):
    now = time.time()
    _outcome(tmp_path, "桌面归类", "rejected", now - 60)
    # 不足 MIN_COUNT=2：没有任何可说的 → 空串（宁可安静），且 topic 不得出现
    assert brief(tmp_path, now) == ""


def test_repeated_rejection_keeps_his_words(tmp_path: Path):
    now = time.time()
    _outcome(tmp_path, "定时提醒", "rejected", now - 100, text="到点提醒你休息")
    _outcome(tmp_path, "定时提醒", "rejected", now - 50, text="到点提醒你休息")
    out = brief(tmp_path, now)
    assert "拒绝过" in out and "别换说法再提" in out and "到点提醒" in out, out


def test_rejected_topic_flows_back_from_outcomes(tmp_path: Path):
    """issue #15 ② 的核心修复：被拒 topic 必须能从 outcomes.jsonl 回流进 brief。"""
    now = time.time()
    _outcome(tmp_path, "C盘清理", "rejected", now - 120,
             text="清一下 C 盘？", oid="o-rej-1")
    _outcome(tmp_path, "C盘清理", "rejected", now - 60,
             text="清一下 C 盘？", oid="o-rej-2")
    out = brief(tmp_path, now)
    assert "C盘清理" in out and "清一下 C 盘" in out


def test_responded_is_not_accepted(tmp_path: Path):
    """responded（用户打字）语义不是明确接受，不进「接受过」；更不进拒绝线。"""
    now = time.time()
    _outcome(tmp_path, "实验6", "responded", now - 60, text="哪里有问题")
    _outcome(tmp_path, "实验6", "responded", now - 30, text="具体点")
    assert brief(tmp_path, now) == ""


def test_old_results_drop_off(tmp_path: Path):
    now = time.time()
    _outcome(tmp_path, "定时提醒", "rejected", now - RECENT_S - 100, text="到点")
    _outcome(tmp_path, "定时提醒", "rejected", now - RECENT_S - 50, text="到点")
    assert brief(tmp_path, now) == ""


def test_window_boundary_keeps_recent(tmp_path: Path):
    now = time.time()
    _outcome(tmp_path, "桌面归类", "rejected", now - 100)
    _outcome(tmp_path, "桌面归类", "rejected", now - 10)
    out = brief(tmp_path, now)
    assert "桌面归类" in out, out


def test_output_is_short(tmp_path: Path):
    now = time.time()
    for i in range(10):
        _outcome(tmp_path, f"话题{i}", "rejected", now - 20, text="海" * 60,
                 oid=f"a{i}")
        _outcome(tmp_path, f"话题{i}", "rejected", now - 10, text="海" * 60,
                 oid=f"b{i}")
    assert len(brief(tmp_path, now)) <= 400, len(brief(tmp_path, now))


def test_broken_lines_are_skipped(tmp_path: Path):
    now = time.time()
    d = tmp_path / "perceive"; d.mkdir(parents=True)
    (d / "outcomes.jsonl").write_text(
        "不是 json\n"
        + json.dumps(dict(t=now - 5, topic="清理内存", outcome="accepted"),
                     ensure_ascii=False) + "\n",
        encoding="utf-8")
    assert "清理内存" in brief(tmp_path, now)


def test_non_numeric_timestamp_skipped_not_crash(tmp_path: Path):
    now = time.time()
    d = tmp_path / "perceive"; d.mkdir(parents=True)
    (d / "outcomes.jsonl").write_text(
        json.dumps(dict(t="not-a-time", topic="清理内存", outcome="accepted"),
                   ensure_ascii=False) + "\n"
        + json.dumps(dict(t=now - 5, topic="真话题", outcome="accepted"),
                     ensure_ascii=False) + "\n",
        encoding="utf-8")
    out = brief(tmp_path, now)
    assert "真话题" in out and "清理内存" not in out


def test_offers_jsonl_is_no_longer_the_source(tmp_path: Path):
    """旧数据源 offers.jsonl 里即便写着 accepted/dismissed 也不再被采信。"""
    now = time.time()
    d = tmp_path / "perceive"; d.mkdir(parents=True)
    with (d / "offers.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(dict(id="x", t=now - 5, topic="清理内存",
                                kind="offer", result="accepted")) + "\n")
        f.write(json.dumps(dict(id="y", t=now - 4, topic="定时提醒",
                                kind="offer", result="dismissed",
                                text="到点提醒")) + "\n")
        f.write(json.dumps(dict(id="z", t=now - 3, topic="定时提醒",
                                kind="offer", result="dismissed",
                                text="到点提醒")) + "\n")
    assert brief(tmp_path, now) == ""
