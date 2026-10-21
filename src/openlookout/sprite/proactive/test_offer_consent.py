"""回归门：offer 必须用户点头才动手（同意门）。

现场（sprite_home/perceive/offers.jsonl，320 条）：
    shown 220 / auto_started 54 / auto_failed 36 / auto_completed 9 / retracted 1
    带 options 字段的 0 条；outcomes.jsonl 里 accepted 0 次、rejected 0 次。

原因在 live.py 的 GUI tick()：读到 kind=="offer" 且状态不在豁免表里，就直接
record_offer_result(offer, "auto_started") 起线程跑 run_offer，全程无交互。
于是 gui.py:197 里画「好的/不用」的分支从来没被走到过（死代码）——没有选项，
用户就没有可点的东西，accepted/rejected 永远不会产生。54 次自动执行里
包含把 4959 个文件（约 3.8GB）收进隔离区 reclaim（desktop_runs/20261011-073031）。

本文件钉住修复后的契约：
  1. offer 弹泡真的带「好的/不用」，且 gui 真的会把它画成可点的按钮；
  2. 只有点了第一个选项才执行；点第二个绝不执行；
  3. 用户不响应 → 到期作废，不执行，并落账（窗口重启也不会复活这条提议）；
  4. options 真的写进 offer 记录（否则以后统计不出正负证据）；
  5. 撤回能力保留；
  6. tick 不再自动启动执行。

这些是纯逻辑 + 源码断言，无头可跑；真实点击链路由 test_offer_consent_e2e.py 驱动。
"""
from __future__ import annotations

import inspect
import json
import subprocess

import pytest

from sprite.gui import SpriteWindow
from sprite.i18n import t
from sprite.proactive import conversation, help as helpmod, live
from vista.benchmarks.desktop import session as sessionmod

# ── 1. 选项真的存在，且画成可点的按钮 ─────────────────────────────────────────

def test_offer_options_are_defined_and_ordered(monkeypatch):
    """第一个选项必须是「同意」——live.on_choice 用 index==0 判定执行。"""
    monkeypatch.setenv("OPENLOOKOUT_LANG", "zh")
    assert list(helpmod.OFFER_OPTIONS) == ["好的", "不用"]
    monkeypatch.setenv("OPENLOOKOUT_LANG", "en")
    assert list(helpmod.OFFER_OPTIONS) == ["OK", "No thanks"]
    assert list(helpmod.OFFER_OPTIONS)[0] != list(helpmod.OFFER_OPTIONS)[1]


def test_gui_renders_offer_options_as_choice_buttons():
    """gui._buttons 见到 options 就画 choice 按钮；这条分支以前永远走不到。"""
    w = SpriteWindow.__new__(SpriteWindow)
    w.msg = {"kind": "offer", "text": "C 盘快满了，要我清一下吗？",
             "options": ["好的", "不用"]}
    assert w._buttons() == [("好的", ("choice", 0)), ("不用", ("choice", 1))]


def test_gui_gives_options_bubble_five_times_the_wait():
    """带选项 = 要人做决定，多留一会儿。

    PR #16 后的实挂口径是 live.OFFER_ASK_S×2=120s（gui.show 的系数已从
    ×5 收为 ×2，见 issue #11 新发现 2）；本用例只钉 show 对 options 有
    特殊时长分支，120s 算式由 test_bubble_and_loop 钉死。
    """
    assert "options" in inspect.getsource(SpriteWindow.show)


# ── 2. tick 只摆选项，不自动执行 ─────────────────────────────────────────────

def test_tick_no_longer_auto_starts_offers():
    """同意门的核心：tick 里不得再出现 auto_started 这种自动开跑。"""
    src = inspect.getsource(live.run_gui)
    assert '"auto_started"' not in src
    assert "start_offer(offer)" in src, "执行只能由用户点头触发"


def test_tick_presents_offer_with_options():
    src = inspect.getsource(live.run_gui)
    assert "options=options" in src
    assert "OFFER_ASK_S" in src


def test_settled_states_block_a_resurfacing_offer():
    """窗口重启不得把同一条提议再问一遍（offer_status 只认已落盘的结果行）。"""
    for word in ("started", "expired", "accepted", "rejected"):
        assert word in live.SETTLED_OFFER_STATES, word
    # 同意门之前的历史词也得留着，老记录才不会在重启后复活
    assert {"auto_started", "auto_completed", "auto_errored"} <= live.SETTLED_OFFER_STATES


def test_run_offer_still_reports_reversible_result(tmp_path, monkeypatch):
    """点头之后那条执行链路本身不能坏（终态词表回归）。"""
    monkeypatch.setattr(live, "DIR", tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, '{"final":"已整理，随时可以撤回。"}', "")

    monkeypatch.setattr(live.subprocess, "run", fake_run)
    messages = []
    live.run_offer({"id": "offer-1", "text": "整理桌面", "kind": "offer"}, messages.append)

    assert calls, "点了好的之后必须真的执行"
    rows = [json.loads(line) for line in (tmp_path / "offers.jsonl").read_text("utf-8").splitlines()]
    assert rows[-1]["result"] == "auto_completed"
    assert messages[0]["kind"] == "action"


# ── 3. options 真的写进 offer 记录 ───────────────────────────────────────────

def test_session_publishes_offer_with_options(tmp_path, monkeypatch):
    """brain 发的 offer（session._companion）必须自带 options。"""
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "perceive" / "current.json")
    published: list[dict] = []
    monkeypatch.setattr(helpmod, "publish", lambda o: published.append(o))
    monkeypatch.setattr(helpmod, "record", lambda row: None)
    monkeypatch.setattr(helpmod, "worth_saying", lambda *a, **k: True)

    session = sessionmod.DesktopSession.__new__(sessionmod.DesktopSession)
    session.decisions, session.suppressed, session.reports = [], 0, []
    session.agenda = session.policy_context = session.closed = None
    session.final, session.actions, session.action_results = None, 0, []
    session.reports, session._turn_mutations = [], []
    session.work_summary = lambda: {"status": "idle"}

    session._companion({"kind": "offer", "say": "C 盘快满了，要我清一下吗？", "topic": "C盘",
                        "confidence": 0.9})

    assert published, "offer 应当被发布"
    assert published[0]["options"] == list(helpmod.OFFER_OPTIONS)
    assert published[0]["kind"] == "offer"


def test_companion_never_gets_options(tmp_path, monkeypatch):
    """companion 只是说句话，不改机器 —— 不该被摆成一次待批准的动作。"""
    monkeypatch.setattr(sessionmod, "CURRENT", tmp_path / "perceive" / "current.json")
    published: list[dict] = []
    monkeypatch.setattr(helpmod, "publish", lambda o: published.append(o))
    monkeypatch.setattr(helpmod, "record", lambda row: None)
    monkeypatch.setattr(helpmod, "conversation_worth_saying", lambda *a, **k: True)

    session = sessionmod.DesktopSession.__new__(sessionmod.DesktopSession)
    session.decisions, session.suppressed, session.reports = [], 0, []
    session.agenda = session.policy_context = session.closed = None
    session.final, session.actions, session.action_results = None, 0, []
    session.reports, session._turn_mutations = [], []
    session.work_summary = lambda: {"status": "idle"}

    session._companion({"kind": "companion", "say": "读挺久了，歇会儿吧", "topic": "阅读",
                        "confidence": 0.8})
    assert published and "options" not in published[0]


def test_offer_goal_no_longer_says_do_not_wait_for_confirmation():
    """执行提示词里那句「不等待用户确认」必须删掉——现在正是等过了才跑。"""
    assert "不等待用户确认" not in live.OFFER_GOAL
    assert "可撤回" in live.OFFER_GOAL


# ── 4. 到期作废：不响应就不执行 ──────────────────────────────────────────────

def test_offer_expiry_counts_as_a_rejection_signal():
    """摆过选项却没人点 = 一次明确的「不要」（ignored），这正是我们要的正负证据。"""
    assert live.expiry_outcome({"kind": "offer", "text": "清一下 C 盘？",
                                "options": ["好的", "不用"]}) == "ignored"


def test_expired_offer_is_recorded_as_a_settled_state():
    assert "expired" in live.SETTLED_OFFER_STATES


# ── 5. 撤回能力保留 ──────────────────────────────────────────────────────────

def test_undo_path_is_still_wired():
    src = inspect.getsource(live.run_gui)
    assert "def on_undo" in src
    assert '"undo_requested"' in src
    assert '"undone"' in src
    assert "undo_offer()" in src


def test_undo_button_is_still_rendered_on_action_bubbles():
    w = SpriteWindow.__new__(SpriteWindow)
    w.msg = {"kind": "action", "text": "已整理，随时可以撤回。", "action_id": "offer-1"}
    assert w._buttons()[0] == (t("undo"), ("undo", "offer-1"))


# ── 6. 词表自洽：accepted/rejected 能被统计到 ────────────────────────────────

def test_outcome_report_can_bucket_options_offers():
    """outcome_report 按 options 分桶；没有 options 就永远落在 other，出不了统计。"""
    from sprite.proactive import outcome_report
    offers = {"o1": {"id": "o1", "kind": "offer", "options": ["好的", "不用"]}}
    assert outcome_report.bucket_of({"id": "o1", "kind": "offer"}, offers) == "offer_with_options"
    assert outcome_report.bucket_of({"id": "o2", "kind": "offer"}, {}) == "other"


def test_conversation_renders_new_consent_states(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, "DIR", tmp_path)
    monkeypatch.setattr(conversation, "LOG", tmp_path / "conversation.jsonl")
    rows = [
        {"id": "a", "t": 1, "text": "清一下 C 盘", "kind": "offer", "result": "shown"},
        {"id": "a", "t": 1, "text": "清一下 C 盘", "kind": "offer", "result": "started",
         "t_answer": 2},
        {"id": "b", "t": 3, "text": "整理桌面", "kind": "offer", "result": "expired",
         "t_answer": 4},
    ]
    (tmp_path / "offers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    labels = [r["text"] for r in conversation.history()]
    assert t("started_hist", text="清一下 C 盘") in labels, labels
    assert t("expired_hist", text="整理桌面") in labels, labels
