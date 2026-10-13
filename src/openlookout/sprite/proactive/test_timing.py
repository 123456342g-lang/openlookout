"""「看准时机」的核心纪律：同一件事没得到回应之前不重复说。

真实数据里出过事故：同一句「C盘快满了，要我清一下吗？」连发4 次。
这不是关心，是骚扰。本文件把那条事故做成回归——闸必须挡住它。

被钉住的三条：
1. 同topic 在冷却窗口内不重复说（offer 5 分钟 / companion 10 分钟）
2. 他点过「不用」之后，同一件事在 30 分钟内不再提——换说法也不行
3. 两条出提议的路（brain 的 session._companion、旧 help.check_once）都必须过这道闸
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

import sprite.proactive.help as helpmod


@pytest.fixture()
def log(tmp_path, monkeypatch):
    """把 offers.jsonl 隔离到临时目录，测试不碰真实数据。"""
    d = tmp_path / "perceive"
    d.mkdir()
    j = d / "offers.jsonl"
    monkeypatch.setattr(helpmod, "DIR", d)
    monkeypatch.setattr(helpmod, "OFFER", d / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", j)
    monkeypatch.setattr(helpmod, "OFFER_COOLDOWN_S", 300)
    monkeypatch.setattr(helpmod, "COMPANION_COOLDOWN_S", 600)
    monkeypatch.setattr(helpmod, "DISMISS_S", 1800)
    return j


def _rows(j: Path) -> list:
    if not j.exists(): return []
    return [l for l in j.read_text("utf-8").splitlines() if l.strip()]


def _row(j: Path, topic: str, result: str, kind: str = "offer", t: float | None = None, text: str = "…") -> None:
    with j.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(id="1", t=t if t is not None else time.time(), text=text,
                                topic=topic, kind=kind, confidence=0.9, result=result), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 真实事故的回归
def test_empty_topic_repeats_are_blocked_too(log):
    """真实事故：模型忘了给 topic，同一句「C盘快满了」说了 4 次。

    空标签不能等于「不受约束」——退化成用话本身当标识，重复的就拦得住。
    """
    for _ in range(4):
        _row(log, "", "shown", t=time.time(), text="C盘快满了，要我清一下吗？")
    assert not helpmod.worth_saying("", "offer", "C盘快满了，要我清一下吗？")


def test_missing_topic_key_still_blocked(log):
    """更老的数据里可能连 topic 字段都没有——也得拦得住。"""
    with log.open("a", encoding="utf-8") as f:
        for _ in range(4):
            f.write(json.dumps(dict(id="1", t=time.time(), text="C盘快满了，要我清一下吗？",
                                    kind="offer", confidence=0.9, result="shown"), ensure_ascii=False) + "\n")
    assert not helpmod.worth_saying("", "offer", "C盘快满了，要我清一下吗？")


def test_wording_differences_are_not_over_blocked(log):
    """闸不能变成「只要沾磁盘就闭嘴」——真正不同的事还是要能说。"""
    _row(log, "", "shown", t=time.time(), text="C盘快满了，要我清一下吗？")
    assert helpmod.worth_saying("", "offer", "内存只剩0.5GB 了，要不要挂起几个后台程序？")


def test_empty_topic_really_blocked_through_brain(log):
    """走brain 那条路（历史记录里topic 为空的真实格式）也要拦得住。"""
    from vista.benchmarks.desktop.session import DesktopSession
    for _ in range(4):
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dict(id="1", t=time.time(), text="C盘快满了，要我清一下吗？",
                                    topic="", kind="offer", confidence=0.9, result="shown"), ensure_ascii=False) + "\n")
    s = DesktopSession("x", {})
    s._companion({"kind": "offer", "say": "C盘快满了，要我清一下吗？", "confidence": 0.95})
    assert s.suppressed == 1, "没给topic 的重复提议没有被拦下"
    assert len(_rows(log)) == 4, "不该再往日志里写第 5 条"


# ---------------------------------------------------------------- 核心事故的回归
def test_same_offer_is_not_repeated(log):
    """真实事故：同一句「C盘快满了」连发 4 次。第二句就必须被挡住。"""
    _row(log, "磁盘", "shown", t=time.time())
    assert not helpmod.worth_saying("磁盘", "offer", "C盘快满了，要我清一下吗？")


def test_different_topic_can_still_speak(log):
    """拦的是「同一件事」，不是「不让他说话」。"""
    _row(log, "磁盘", "shown", t=time.time())
    assert helpmod.worth_saying("休息", "offer", "读了挺久了，让眼睛歇会儿吧")


def test_same_text_different_topic_is_allowed_but_not_relied_on(log):
    """模型没给 topic 时不该被误伤——宁可放过，不要把正常关心也掐掉。"""
    _row(log, "磁盘", "shown", t=time.time())
    assert helpmod.worth_saying("", "offer", "磁盘快满了")


# ---------------------------------------------------------------- 拒绝过就不再提
def test_dismissed_topic_is_never_repeated(log):
    """他说不用，就安静。"""
    _row(log, "桌面整理", "dismissed", t=time.time())
    assert not helpmod.worth_saying("桌面整理", "offer", "桌面有点乱，要我收一下吗？")


def test_dismissal_outside_window_expires(log):
    """很久之后可以再提——但要重新掂量，不要条件反射。"""
    _row(log, "桌面整理", "dismissed", t=time.time() - 2000)   # 超过 DISMISS_S
    assert helpmod.worth_saying("桌面整理", "offer", "桌面还是有点乱，要我收一下吗？")


def test_accepted_topic_is_not_repeated(log):
    """已经接受并处理过的事，不要反复邀功。"""
    _row(log, "磁盘", "accepted", t=time.time())
    assert not helpmod.worth_saying("磁盘", "offer", "磁盘的事我帮你看看？")


def test_reshuffled_wording_still_blocked(log):
    """换个说法不算新提议——看的是 topic，不是话术。"""
    _row(log, "磁盘", "dismissed", t=time.time())
    assert not helpmod.worth_saying("磁盘", "offer", "我看你硬盘快撑爆了，要不我腾点地方？")


# ---------------------------------------------------------------- 窗口长度
def test_offer_and_companion_use_different_windows(log):
    """提议要问「好的」，所以更克制（5 分钟）；关心可以更频繁（10 分钟）。"""
    # 7 分钟前说过一次：offer 窗口已过，companion 窗口还没到
    _row(log, "阅读", "shown", kind="offer", t=time.time() - 420)
    assert helpmod.worth_saying("阅读", "offer", "这段要我讲讲吗？")
    assert not helpmod.worth_saying("阅读", "companion", "这一章读完了呀")


def test_brevity_is_enforced_by_the_gate(log):
    """空话不该出口。"""
    assert not helpmod.worth_saying("随便", "offer", "   ")


# ---------------------------------------------------------------- brain 那条路也必须过闸
def test_brain_path_is_throttled_too(log):
    """回归真实断点：session._companion 曾经直接 publish，完全绕过冷却。"""
    from vista.benchmarks.desktop.session import DesktopSession
    _row(log, "磁盘", "shown", t=time.time())
    s = DesktopSession("x", {})
    r = s._companion({"kind": "offer", "say": "C盘快满了，要我清一下吗？", "topic": "磁盘", "confidence": 0.95})
    assert not log_with_new(log), "同一件事被重复说出来了"
    assert s.suppressed == 1, "被压掉必须留痕，否则时机质量永远算不出来"
    assert "suppressed" in (r.event_text or "")


def test_brain_path_still_speaks_when_it_should(log):
    """闸不能把正常功能也掐死——空日志时第一次说就该放出去。"""
    from vista.benchmarks.desktop.session import DesktopSession
    s = DesktopSession("x", {})
    s._companion({"kind": "offer", "say": "C盘只剩0.6GB了，要我清一下吗？", "topic": "磁盘", "confidence": 0.95})
    assert len(_rows(log)) == 1, "第一次说就该放出去"
    assert s.suppressed == 0


def log_with_new(j: Path) -> bool:
    """fixture 里预先写过 1 行（当已说过的历史）；这里问有没有多出新行。"""
    return len(_rows(j)) > 1


def test_quiet_is_always_allowed(log):
    """安静永远不该被拦——这是默认档。"""
    from vista.benchmarks.desktop.session import DesktopSession
    s = DesktopSession("x", {})
    s._companion({"kind": "quiet", "confidence": 0.9})
    assert s.suppressed == 0
    assert _rows(log) == []