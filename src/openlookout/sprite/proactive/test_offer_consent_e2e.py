"""端到端：真跑一次「精灵提议 → 用户点好的 → 记账 → 执行」。

这是本项目第一次能产出 accepted/rejected 数据，所以不满足于源码断言：
这里真的起 Tk、真的把 offer 写进隔离的 SPRITE_HOME、真的调用 gui 画出来的按钮
（SpriteWindow._click），然后检查两个账本里到底落了什么。

隔离：SPRITE_HOME 在导入前就被换掉，perceive.DIR 由它派生，因此不会碰到
E:\\OpenLookout\\sprite_home 的真实账本；桌面任务 run_offer 被打桩，
只验证「它被调用了」，不在测试里真的去清 C 盘。

做法：Tk 必须在主线程，所以 run_gui 在主线程跑，只把 mainloop 换成一个脚本化的
「泵事件循环」——泵够若干拍后按剧本做事（看气泡 / 点按钮 / 再泵），然后收摊。
这走的仍是 tick → present → w.show → _click → on_choice 的真实路径。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="ol_offer_consent_"))
os.environ["SPRITE_HOME"] = str(_HOME)

from sprite.gui import SpriteWindow as _SpriteWindow          # noqa: E402
from sprite.i18n import t                                      # noqa: E402
from sprite.proactive import conversation                     # noqa: E402
from sprite.proactive import help as helpmod                  # noqa: E402
from sprite.proactive import live                             # noqa: E402

tk = pytest.importorskip("tkinter")

# 隔离不靠 SPRITE_HOME 环境变量：整套测试一起跑时 perceive 可能早被别的模块导入，
# 那时 DIR 已经指向真实账本，改环境变量来不及了（曾经就这样整组被跳过）。
# 直接把各模块的路径常量重新绑到临时目录，与导入顺序无关。
# live 的 OUTCOMES/CURRENT 是模块级常量，help/conversation 的也一样，都要一起搬。
DIR = _HOME / "perceive"
DIR.mkdir(parents=True, exist_ok=True)
live.DIR = DIR
live.OUTCOMES = DIR / "outcomes.jsonl"
live.CURRENT = DIR / "current.json"
live.SUP_LOG = DIR / "supervisor.log"
helpmod.DIR = DIR
helpmod.OFFER = DIR / "offer.json"
helpmod.OFFER_LOG = DIR / "offers.jsonl"
helpmod.ACT_JSONL = DIR / "activity.jsonl"
conversation.DIR = DIR
conversation.LOG = DIR / "conversation.jsonl"


def _tk_usable() -> bool:
    """Tcl 装不全时（精简环境 / 沙箱）init.tcl 读不到，整组跳过而不是红一片。"""
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    try:
        root.withdraw()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    return True


pytestmark = [
    pytest.mark.skipif(not str(DIR).startswith(str(_HOME)),
                       reason="隔离目录未生效，拒绝碰真实账本"),
    pytest.mark.skipif(not _tk_usable(), reason="Tcl/tkinter 不可用（无 init.tcl 或无显示环境）"),
]


def _reset() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for path in DIR.glob("*"):
        if path.is_file():
            path.unlink()
    # _RECORDED 是 live.py 的模块级去重集合：同一条 id 只记一行。
    # 测试之间换 id 还不够，得把它清掉，否则第二次跑同一个 id 会被静默丢掉。
    live._RECORDED.clear()
    live._RECORDED_STAMP = ()


def _rows(name: str) -> list[dict]:
    path = DIR / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


_SEQ = {"n": 0}


def _publish(**over) -> dict:
    _SEQ["n"] += 1
    offer = dict(id=f"e2e-{_SEQ['n']}", t=time.time(), text="C 盘快满了，要我清一下吗？",
                 topic="C盘", kind="offer", confidence=0.9,
                 options=list(helpmod.OFFER_OPTIONS))
    offer.update(over)
    helpmod.publish(offer)
    # 真实链路里 session._companion 发布后会记一行 shown；这里照样补上。
    helpmod.record(dict(offer, result="shown"))
    return offer


def _drive(script, monkeypatch, executed: list[dict]) -> dict:
    """跑一次真的 run_gui，按剧本操作窗口。返回抓到的 SpriteWindow。

    script(window, pump) —— pump() 泵事件循环若干拍。
    """
    captured: dict = {}

    def fake_run_offer(offer, show):
        # 不碰 Tk：report() 会 root.after(...)，而测试里没有真实 mainloop 在跑，
        # 跨线程调 Tk 会 RuntimeError。这里只验证「执行被触发了」，气泡由
        # start_offer 在主线程 present 的那条负责断言。
        executed.append(dict(offer))
        live.record_offer_result(offer, "auto_completed", report="清完了，随时可以撤回。")

    monkeypatch.setattr(live, "run_offer", fake_run_offer)
    monkeypatch.setattr(live, "OFFER_ASK_S", 600)

    real_init = _SpriteWindow.__init__

    def spy_init(self, *a, **k):
        real_init(self, *a, **k)
        captured["win"] = self

    monkeypatch.setattr(_SpriteWindow, "__init__", spy_init)

    def pump(root, n=10):
        for _ in range(n):
            try:
                root.update()
            except tk.TclError:
                return
            time.sleep(0.02)

    def fake_mainloop(self, *a, **k):
        try:
            # tick 挂在 root.after(300) 上，所以至少要泵过 300ms 才看得到 offer 气泡。
            pump(self, 40)
            script(captured["win"], lambda n=20: pump(self, n))
        finally:
            try:
                self.destroy()
            except tk.TclError:
                pass
        raise SystemExit(0)

    monkeypatch.setattr(tk.Tk, "mainloop", fake_mainloop)
    with pytest.raises(SystemExit):
        live.run_gui()
    return captured["win"]


def test_offer_bubble_shows_options_and_click_accept_executes(monkeypatch):
    """点「好的」：accepted 真的落进 outcomes.jsonl，执行真的被触发。"""
    _reset()
    offer = _publish()
    executed: list[dict] = []
    seen: dict = {}

    def script(win, pump):
        seen["buttons"] = win._buttons()
        seen["text"] = win.msg.get("text")
        win._click(("choice", 0))               # 和真人点「好的」同一条路径
        pump(14)

    win = _drive(script, monkeypatch, executed)

    # 气泡确实摆出了两个可点的选择
    assert seen["buttons"] == [(offer["options"][0], ("choice", 0)), (offer["options"][1], ("choice", 1))], seen
    assert "C 盘" in seen["text"]

    # 账本 1：outcomes.jsonl 里真的出现 accepted（本项目史上第一次）
    outcomes = _rows("outcomes.jsonl")
    assert [r["outcome"] for r in outcomes] == ["accepted"], outcomes
    row = outcomes[0]
    assert row["options"] == offer["options"], row
    assert row["choice_index"] == 0 and row["choice"] == offer["options"][0], row
    assert row["kind"] == "offer" and row["topic"] == "C盘", row
    assert row["latency_s"] is not None

    # 账本 2：执行侧的 started 行也落盘了（点完之后才允许动手）
    results = [r["result"] for r in _rows("offers.jsonl")]
    assert results[0] == "shown"
    assert "started" in results, results
    assert "auto_completed" in results, results

    # 而且执行链路真的被触发了
    assert executed and executed[0]["id"] == offer["id"]

    # 点完之后气泡换成了「我开始处理…」，没有把 offer 气泡留在屏幕上
    assert win.msg is not None
    assert win.msg["text"] == t("starting", label="C盘") or win.msg.get("kind") == "action", win.msg


def test_clicking_reject_records_rejected_and_never_executes(monkeypatch):
    """点「不用」：rejected 落账，而且一个动作都不许发生。"""
    _reset()
    offer = _publish()
    executed: list[dict] = []

    def script(win, pump):
        win._click(("choice", 1))
        pump(14)

    _drive(script, monkeypatch, executed)

    outcomes = _rows("outcomes.jsonl")
    assert [r["outcome"] for r in outcomes] == ["rejected"], outcomes
    assert outcomes[0]["choice_index"] == 1 and outcomes[0]["choice"] == offer["options"][1]

    # 关键：没有执行，也没有 started 行
    assert executed == [], "用户拒绝了却仍然执行了"
    results = [r["result"] for r in _rows("offers.jsonl")]
    assert "started" not in results, results
    assert "auto_completed" not in results, results


def test_no_response_expires_the_offer_without_executing(monkeypatch):
    """用户全程不响应：到期自动作废（ignored），不执行。"""
    _reset()
    _publish()
    executed: list[dict] = []

    def script(win, pump):
        assert win._buttons(), "带选项的 offer 必须摆出按钮"
        win.hide(expired=True)                  # 气泡超时消失 = 用户没点
        pump(10)

    _drive(script, monkeypatch, executed)

    outcomes = _rows("outcomes.jsonl")
    # 摆过选项却没点 = 明确的「不要」
    assert [r["outcome"] for r in outcomes] == ["ignored"], outcomes
    assert executed == [], "没点头却执行了"
    results = [r["result"] for r in _rows("offers.jsonl")]
    assert "expired" in results, results
    assert "started" not in results, results


def test_expired_offer_is_not_offered_again_after_restart(monkeypatch):
    """作废之后窗口重启，同一条提议不会再弹一次（offer_status 认已落盘的结果行）。"""
    _reset()
    offer = _publish()
    live.record_offer_result(offer, "expired")
    executed: list[dict] = []
    shown: dict = {}

    def script(win, pump):
        shown["msg"] = win.msg.get("text")

    _drive(script, monkeypatch, executed)

    # 重启后气泡回到常驻的招呼语，而不是把这条已被否决的提议再摆出来
    assert "C 盘快满了" not in str(shown["msg"]), shown
    assert executed == []


def test_companion_bubble_never_asks_for_permission(monkeypatch):
    """companion 只是说句话，不该被摆成待批准的动作，也不该被记成一次拒绝。"""
    _reset()
    _publish(kind="companion", text="读挺久了，歇会儿吧", topic="阅读",
             options=None)
    executed: list[dict] = []
    seen: dict = {}

    def script(win, pump):
        seen["buttons"] = win._buttons()
        seen["kind"] = win.msg.get("kind")
        win.hide(expired=True)
        pump(8)

    _drive(script, monkeypatch, executed)

    assert seen["kind"] == "say", seen
    assert seen["buttons"] == [], "陪伴语不该带任何按钮"
    outcomes = _rows("outcomes.jsonl")
    assert [r["outcome"] for r in outcomes] == ["unanswered"], outcomes
