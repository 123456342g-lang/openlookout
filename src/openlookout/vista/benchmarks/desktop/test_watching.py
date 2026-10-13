"""持续观察计时事实的测试。这里不测“读书”——那是模型和 VISTA 视觉上下文的事；
只测时间事实准不准：停了多久、算不算卡住、来回翻、阶段完成、人走了、以及
“顺手推进时什么都不说”（宁可安静）。

对抗重点：静止不等于卡住（人走了就是走了）；第一眼不构成任何事件；
来回只认“最近那一屏”，老早以前的画面翻回来不算。
"""
from __future__ import annotations

import json
from pathlib import Path

from vista.benchmarks.desktop.watching import DEFAULTS, Watcher, idle_seconds, load, save, state_path


def T(n: int, title: str = "e") -> list[int]:
    """一屏的假指纹：用内容不同的列表代表不同画面。"""
    return [i % 7 + n for i in range(24)]


# ---------------------------------------------------------------- 顺手推进：什么都不说
def test_smooth_progress_says_nothing():
    w = Watcher()
    w.observe(T(1), "a.py - Zed", now=0.0)
    for t in (60, 120, 180, 240, 300):
        s = w.observe(T(t // 60 + 1), "a.py - Zed", now=t)
    assert s.progressing and s.line() == "", s.line()          # 一直在动：安静陪伴，不出声


def test_first_observation_creates_no_event():
    w = Watcher()
    s = w.observe(T(1), "x", now=0.0)
    assert s.same_s == 0 and s.flaps == 0 and not s.phase and s.line() == ""


# ---------------------------------------------------------------- 卡住与来回
def test_stuck_needs_time_and_presence():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    s = w.observe(T(1), "x", now=60.0)
    assert not s.stuck and s.line() == ""                        # 才停 1 分钟，不算卡住，不打扰
    s = w.observe(T(1), "x", now=240.0)
    assert s.stuck and s.same_s >= DEFAULTS["stuck_s"]
    assert "停了" in s.line() and "卡住" in s.line()


def test_flap_back_to_recent_frame_counts():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    w.observe(T(2), "x", now=30.0)
    s = w.observe(T(1), "x", now=60.0)                           # 翻回刚才那一屏
    assert s.flaps == 1 and "来回" in s.line()
    s = w.observe(T(3), "x", now=100.0)                          # 又往前走了，不重复计数
    assert s.flaps == 1


def test_returning_to_an_old_frame_is_not_a_flap():
    w = Watcher(cfg={"flap_s": 180.0})
    w.observe(T(1), "x", now=0.0)
    w.observe(T(2), "x", now=10.0)
    s = w.observe(T(3), "x", now=20.0)
    assert s.flaps == 0                                          # 只走了两步，没回去


# ---------------------------------------------------------------- 阶段完成
def test_phase_completion_after_long_stability():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    w.observe(T(1), "x", now=100.0)                              # 稳了 100 秒
    s = w.observe(T(2), "x", now=240.0)                          # 然后变了
    assert s.phase and "阶段" in s.line()


def test_quick_change_is_not_a_phase_completion():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    s = w.observe(T(2), "x", now=10.0)                           # 只停 10 秒就变：不算做完一个阶段
    assert not s.phase and s.line() == ""


# ---------------------------------------------------------------- 人走了
def test_away_user_gets_quiet_and_no_stuck():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    s = w.observe(T(1), "x", now=100.0, idle_s=400.0)            # 人离开了，画面当然不变
    assert s.away and not s.stuck and "没操作电脑" in s.line()
    s = w.observe(T(1), "x", now=500.0, idle_s=800.0)
    assert "别打扰" in s.line()


def test_returning_resets_away():
    w = Watcher()
    w.observe(T(1), "x", now=0.0)
    w.observe(T(1), "x", now=400.0, idle_s=400.0)
    s = w.observe(T(2), "x", now=500.0, idle_s=0.0)
    assert not s.away and not s.line().startswith("【观察】用户")


# ---------------------------------------------------------------- 跨重启接着算
def test_persistence_round_trip(tmp_path: Path):
    w = Watcher()
    w.observe(T(1), "x", now=1000.0)
    save(w, tmp_path)
    assert state_path(tmp_path).exists()
    s = load(tmp_path).observe(T(1), "x", now=1030.0)
    assert s.same_s >= 30                                          # 接着上一段算，不归零


def test_state_json_is_serialisable():
    w = Watcher()
    w.observe(T(1), "x", now=100.0)
    d = w.to_dict()
    assert json.loads(json.dumps(d, ensure_ascii=False))["key"]
    assert Watcher.from_dict(d).key == w.key


def test_load_without_file_gives_fresh_watcher(tmp_path: Path):
    assert load(tmp_path).key == ""


def test_idle_seconds_is_a_number():
    assert isinstance(idle_seconds(), float)


def test_activity_trail_records_foreground_transitions_without_input_history():
    w = Watcher(clock=lambda: 180.0)
    w.observe(T(1), "Editor - report.md", proc="zed.exe", now=0.0)
    w.observe(T(2), "Browser - docs", proc="chrome.exe", now=120.0)
    line = w.activity_line
    assert "zed.exe" in line and "report.md" in line
    assert "当前 chrome.exe" in line
    assert "dwell_s" in json.dumps(w.to_dict())


def test_repeated_long_waits_become_a_generic_pattern_signal():
    w = Watcher()
    w.observe(T(1), "Appointment", proc="browser.exe", now=0.0)
    w.observe(T(2), "Other", proc="browser.exe", now=40.0)
    w.observe(T(1), "Appointment", proc="browser.exe", now=80.0)
    w.observe(T(2), "Other", proc="browser.exe", now=120.0)
    w.observe(T(1), "Appointment", proc="browser.exe", now=160.0)
    w.observe(T(2), "Other", proc="browser.exe", now=200.0)
    w.observe(T(1), "Appointment", proc="browser.exe", now=240.0)
    assert "规律线索" in w.pattern_line
    assert "继续收集" in w.pattern_line
