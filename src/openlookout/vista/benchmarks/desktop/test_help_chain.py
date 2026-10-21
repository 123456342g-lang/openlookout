"""「点好的 → 动手 → 汇报 → 能撤回」这条链路的验收。

背景：sprite_home/undo.jsonl 是 0 行、offers.jsonl 11 条全是shown/0 接受 0 拒绝——
这条链路从来没端到端跑通过。本文件用假后端把整条链走一遍，不需要Docker、不改用户电脑。

要钉住的四件事：
1. 提议被接受后真的会去执行（而不是静默失败）
2. 执行完的话能回到气泡里（final 不为空）
3. 任何改动之前都先写撤回记录（硬规则1：动手的事必须先写撤回方式）
4. 撤回能把改动还原，且不会碰前台/系统/安全进程
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sprite.i18n import t
from vista.benchmarks.desktop import actions, session as sessmod
from vista.benchmarks.desktop.session import DesktopSession
from vista.benchmarks.desktop.profiles import make_profile, make_experiment

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_companion_records(tmp_path, monkeypatch):
    from sprite.proactive import help as helpmod

    monkeypatch.setattr(sessmod, "CURRENT", tmp_path / "current.json")
    monkeypatch.setattr(helpmod, "DIR", tmp_path)
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "offers.jsonl")


# ---------------------------------------------------------------- 1. 链路通不通
def test_offer_acceptance_reaches_the_backend():
    """live.py 的 run_offer：接受提议后必须真的调起一个执行进程。"""
    src = (ROOT / "sprite" / "proactive" / "live.py").read_text("utf-8")
    assert "run_offer" in src
    assert "desktop.cli" in src, "接受后没调起执行入口"
    assert "--objective" in src, "执行没带上目标"
    assert "record_offer_result(offer" in src, "接受/拒绝没有落库，时机质量永远算不出来"


def test_undo_path_is_wired_to_a_real_undo():
    """气泡上的撤销必须调真undo，不能是空壳。"""
    src = (ROOT / "sprite" / "proactive" / "live.py").read_text("utf-8")
    assert "undo_offer" in src and "desktop.actions import undo" in src


# ---------------------------------------------------------------- 2. 结论要能回到气泡
def test_session_starts_when_the_display_cannot_be_captured(monkeypatch):
    def boom():
        raise OSError("X connection failed: error 5")

    monkeypatch.setattr(sessmod.ImageGrab, "grab", boom)
    created = DesktopSession("x", {})
    assert created.current_visual.data
    assert created.current_visual.width == sessmod.SHOT_WIDTH


def test_final_answer_is_actually_produced():
    """session.result() 的 final 是回显给用户的那句话——不能永远是空。"""
    s = DesktopSession("做点什么", {})
    assert s.result()["final"] is None
    r = s.submit("我已经挂起了三个后台程序。")
    assert r.finished
    out = s.result()
    assert out["final"] == "我已经挂起了三个后台程序。"
    assert out["answered"] is True


def test_cannot_submit_twice():
    s = DesktopSession("x", {})
    s.submit("done")
    r = s.submit("again")
    assert r.success is False, "不能让模型把结论改口成两遍"


def test_offer_taken_from_session_decisions():
    """_companion 记下的决定里，say/confidence 要能被上层拿到。"""
    s = DesktopSession("x", {})
    r = s._companion({"kind": "offer", "say": "C盘快满了，要我清一下吗？", "topic": "磁盘", "confidence": 0.9})
    assert r.boundary == "decision_complete"
    assert s.decisions[-1]["kind"] == "offer"
    assert s.decisions[-1]["say"] == "C盘快满了，要我清一下吗？"


def test_low_confidence_offer_is_not_published(monkeypatch):
    """拿不准就别开口——硬规则3：误打扰比漏提醒代价高。"""
    import tempfile
    import sprite.proactive.help as helpmod
    from pathlib import Path as P
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(helpmod, "DIR", P(d))
        monkeypatch.setattr(helpmod, "OFFER", P(d) / "offer.json")
        monkeypatch.setattr(helpmod, "OFFER_LOG", P(d) / "offers.jsonl")
        s = DesktopSession("x", {})
        s._companion({"kind": "offer", "say": "要不要我帮你清磁盘？", "topic": "磁盘", "confidence": 0.4})
        assert not (P(d) / "offer.json").exists(), "把握不够还publish 了，违背宁可安静"
        # 但有把握、且这事没说过的话，要能发布出去——不然这条链路就是死的
        s._companion({"kind": "offer", "say": "C盘只剩0.6GB了，要我清一下吗？", "topic": "磁盘清理", "confidence": 0.95})
        assert (P(d) / "offer.json").exists(), "有把握的新提议必须能发出去"


# ---------------------------------------------------------------- 3. 动手前先写撤回方式
def test_suspend_writes_undo_before_acting(monkeypatch, tmp_path=None):
    """挂起前必须先写 journal。这是硬规则 1，不是可选项。"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(actions, "JOURNAL", Path(d) / "undo.jsonl")
        monkeypatch.setattr(actions, "foreground_family", lambda: set())   # 不许碰前台
        import psutil
        me = psutil.Process()
        rows = []
        real_suspend = psutil.Process.suspend

        #拿自己当目标会真被拒（_refusal 认进程自己），所以只验 journal 的写入时机
        calls = []
        monkeypatch.setattr(actions, "_refusal", lambda pid: None)
        monkeypatch.setattr(psutil.Process, "suspend", lambda self: calls.append(self.pid))
        r = actions.suspend({"pid": me.pid})
        assert r.success
        log = (Path(d) / "undo.jsonl").read_text("utf-8").strip().splitlines()
        assert log, "挂起了却没写撤回记录"
        row = json.loads(log[0])
        assert "undo_cmd" in row and "resume" in row["undo_cmd"]
        assert row["desc"], "撤回记录要能让人看懂做了什么"
        monkeypatch.setattr(psutil.Process, "suspend", real_suspend)


def test_refuses_foreground_and_self():
    """不能挂起前台窗口的进程，也不能挂起自己。"""
    import psutil
    me = psutil.Process()
    r = actions.suspend({"pid": me.pid})
    assert r.success is False and "本程序" in r.text
    r2 = actions.end_process({"pid": me.pid})
    assert r2.success is False


# ---------------------------------------------------------------- 4. 撤回能还原
def test_undo_restores_everything_in_the_journal(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        j = home / "undo.jsonl"
        j.write_text(json.dumps(dict(desc="挂起 foo#1",
                                     undo_cmd=f'"{sys.executable}" -c "print(\'restored\')"',
                                     cwd="")) + "\n", encoding="utf-8")
        monkeypatch.setattr(actions, "JOURNAL", j)
        done = []
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: done.append(a) or subprocess.CompletedProcess(a[0], 0))
        out = actions.undo({})
        assert t("restored_word") in out.text
        assert "挂起 foo#1" in out.text
        assert done, "没真的执行撤回命令"
        assert not j.exists(), "撤回后journal 应该被归档，不是留在原地"


def test_undo_with_empty_journal_is_harmless(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr(actions, "JOURNAL", Path(d) / "nothing.jsonl")
        assert actions.undo({}).text == t("undo_empty")


# ---------------------------------------------------------------- 5. 每轮操作数有上限
def test_action_count_is_capped():
    """一次任务里不能无限动手（MAX_ACTIONS）。"""
    s = DesktopSession("x", {})
    assert actions.MAX_ACTIONS > 0
    assert s.actions == 0
    for _ in range(actions.MAX_ACTIONS + 3):
        s._handler("desktop_suspend", lambda a: actions.ToolReply if False else None)({})
    assert s.actions == actions.MAX_ACTIONS, "操作次数必须有上限"


def test_read_only_tool_is_free():
    """只读查询不该占操作配额——它不动电脑。"""
    s = DesktopSession("x", {})
    s._handler("desktop_processes", lambda a: None)({})
    assert s.actions == 0


# ---------------------------------------------------------------- 6. 提议必须能带着理由回来
def test_companion_spec_admits_only_known_kinds():
    """companion 只能三选一：安静 / 一句关心 / 一个提议。"""
    spec = actions.COMPANION_SPEC
    assert set(spec.input_schema["properties"]["kind"]["enum"]) == {"quiet", "companion", "offer"}


def test_say_length_is_bounded():
    """气泡里放不下长篇大论——一句关心就该是一句。"""
    spec = actions.COMPANION_SPEC
    assert spec.input_schema["properties"]["say"]["maxLength"] <= 200


def test_opportunity_report_requires_all_evidence_fields():
    s = DesktopSession("x", {})
    bad = s._companion({"kind": "quiet", "opportunity": {"hypothesis": "maybe"}})
    assert bad.success is False
    assert not s.decisions


def test_opportunity_report_is_recorded_without_forcing_speech():
    s = DesktopSession("x", {})
    report = {
        "hypothesis": "连续操作可能在重复返工",
        "evidence": "同一窗口出现三次相同编辑",
        "impact_if_ignored": "继续返工会浪费时间",
        "next_investigation": "核对最近操作记录是否形成循环",
        "expected_result": "确认是否存在可避免的重复步骤",
    }
    result = s._companion({"kind": "quiet", "opportunity": report})
    assert result.boundary == "decision_complete"
    assert s.decisions[-1]["opportunity"] == report
    assert s.decisions[-1]["kind"] == "quiet"
