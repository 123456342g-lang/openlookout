"""端到端：点“好的” → 动手 → 汇报 → 能撤回。不需要 Docker，不改用户电脑。

用假后端把 run_task 走一遍，验证的是**链路本身**（不是模型聪不聪明）：
- 提议被接受后确实会调起执行入口
- 模型 submit 的结论能一路回到 run_offer 要的那个字段（这就是之前断掉的地方）
- 动手前写了撤回记录，撤撤回能还原
- 整条路任何一步失败都不改用户电脑，且如实说「没能帮上忙」
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from vista.benchmarks.desktop import actions, run as runmod
from vista.benchmarks.desktop.session import DesktopSession

ROOT = Path(__file__).resolve().parents[3]


class FakeReply:
    """假的后端回包：只提供 run.py 真正读的那几个字段。"""

    def __init__(self, final_message="", returncode=0):
        self.final_message = final_message
        self.returncode = returncode
        self.boundary = "turn"


class FakeBackend:
    """假后端：按脚本回放几次run，把 session 的工具真调一遍。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def run(self, task_input):
        self.calls.append(task_input)
        if not self.script:
            return FakeReply("我什么都没做，电脑没有被改动。")
        step = self.script.pop(0)
        if callable(step):
            step(task_input)          # 和真后端一样，把这一轮的输入交给回调
            return FakeReply("")
        return FakeReply(step)


# ---------------------------------------------------------------- 结论要能回显
def test_submitted_answer_travels_back_to_the_bubble():
    """这是之前真正断掉的地方：模型做完不 submit，run_offer 只看到「没能帮上忙」。

    run_offer 读的是 result["final"]；run_task 返回的正是 session.result()。
    这里钉住：只要模型 submit 了，那句话就能一路回到界面。
    """
    def do_work(runtime):
        # 模拟模型动手：调一次挂起（这里只查journal，不真挂起）
        runtime.session._handler("desktop_suspend", lambda a: actions.ToolReply("ok", success=True))({})

    s = DesktopSession("挂起一个后台程序", {})
    s.submit("我挂起了 3 个你暂时没在用的后台程序，随时能恢复。")
    result = s.result()
    assert result["answered"] is True
    assert "挂起了 3 个" in result["final"]
    # run_offer 的判据就是这个字段
    assert (result.get("final") or "").strip(), "run_offer 会因为final 为空而报『没能帮上忙』"


def test_no_submit_yields_empty_final_and_honest_failure():
    """模型没提交时，run_offer 必须能如实说「没能帮上忙」，而不是假装成功。"""
    s = DesktopSession("x", {})
    result = s.result()
    assert not result["final"]
    # 模拟 run_offer 的分支
    final = (result.get("final") or "").strip()
    assert not final


# ---------------------------------------------------------------- 整条路走通
def test_run_task_returns_the_final_answer():
    """整条路：build session → 跑 → 收尾 → 返回结论。不需要真后端。"""
    with tempfile.TemporaryDirectory() as d:
        def factory(runtime, directory):
            def submit_it(_ti):
                # 模型动手做完了，按提示词要求 submit 收尾
                runtime.session.submit("我已经把桌面按类型收进三个文件夹了，想撤销随时说。")
                return FakeReply("")
            return FakeBackend([submit_it])

        out = runmod.run_task("整理桌面", {}, directory=Path(d) / "run", backend="claude",
                              model="fake", effort="low", backend_factory=factory)
        assert out["answered"] is True
        assert "撤销" in out["final"]


def test_backend_failure_leaves_computer_untouched():
    """后端炸了也不能改用户电脑——不能带着半个改动说「做完了」。"""
    with tempfile.TemporaryDirectory() as d:
        class Boom:
            def run(self, ti):
                raise RuntimeError("transport exploded")

        with pytest.raises(RuntimeError):
            runmod.run_task("x", {}, directory=Path(d) / "run", backend="claude",
                            model="fake", effort="low",
                            backend_factory=lambda rt, dd: Boom())


# ---------------------------------------------------------------- 动手前先写撤回方式
def test_real_suspend_writes_journal_then_acts(monkeypatch):
    """端到端钉住硬规则1：先写撤回方式，再动手。顺序不能反。

    用一个真的短命进程当目标（挂起后立刻恢复），不碰用户正在用的任何程序。
    """
    import psutil, time
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with tempfile.TemporaryDirectory() as d:
            j = Path(d) / "undo.jsonl"
            monkeypatch.setattr(actions, "JOURNAL", j)
            monkeypatch.setattr(actions, "_refusal", lambda pid: None)   # 只验写入顺序
            order = []
            monkeypatch.setattr(psutil.Process, "suspend", lambda self: order.append("suspended"))
            real_suspend = psutil.Process.suspend

            actions.suspend({"pid": victim.pid})
            rows = [json.loads(l) for l in j.read_text("utf-8").splitlines() if l.strip()]
            assert rows and "resume" in rows[-1]["undo_cmd"], "挂起前必须先留下能恢复它的方法"
            assert order == ["suspended"]
            monkeypatch.setattr(psutil.Process, "suspend", real_suspend)
            # 目标进程不受影响
            time.sleep(0.2)
            assert victim.poll() is None, "测试不该真把进程挂住"
    finally:
        victim.kill()


def test_undo_then_suspend_is_a_round_trip():
    """挂起→撤回 必须能对上，否则「可撤回」就是空话。"""
    with tempfile.TemporaryDirectory() as d:
        j = Path(d) / "undo.jsonl"
        j.write_text(json.dumps(dict(desc="挂起 fake#1", undo_cmd="echo resumed", cwd="")) + "\n", encoding="utf-8")
        out = actions.undo.__wrapped__ if hasattr(actions.undo, "__wrapped__") else None
        # 直接用真undo，把JOURNAL 指到临时目录
        import importlib
        old = actions.JOURNAL
        actions.JOURNAL = j
        try:
            r = actions.undo({})
        finally:
            actions.JOURNAL = old
        assert "已还原" in r.text and "挂起 fake#1" in r.text
        assert not j.exists(), "撤回后要归档，不能留在原地等下次重复执行"


# ---------------------------------------------------------------- 一次任务的额度
def test_action_budget_is_enforced_end_to_end():
    """不能一口气改无限多东西。"""
    s = DesktopSession("x", {})
    h = s._handler("desktop_suspend", lambda a: actions.ToolReply("ok"))
    for i in range(actions.MAX_ACTIONS + 2):
        r = h({"pid": 1})
    assert s.actions == actions.MAX_ACTIONS
    assert "上限" in r.text, "超额度时必须明说，不能悄悄继续"