"""回归测试：对话已被销毁后，live.py 的 after 回调 / 气泡更新仍会碰到它。

现场（sprite_home/perceive/child_gui.log）::

    live.py tick -> present -> dialog.set_history -> TclError:
    invalid command name ".!toplevel4.!frame.!frame3.!text"

``opened["dlg"]`` 是一个 Tk 引用，但用户随时可以点 × 或按 Esc 关掉那个 toplevel，
而 offer 线程仍在往 transcript 里写。这里锁住两件事：

1. ChatDialog 每个碰 Tk 的方法在窗口/控件/整个 Tk 应用都没了之后都不抛异常；
2. ``live.py`` 丢弃失效引用（``drop_dead_dialog``）这条路径真的会执行、且真的吞掉异常。

Tk 需要一个显示环境；无头机器上整组跳过，不让 GUI 测试把纯逻辑测试跑挂。
"""
from __future__ import annotations

import pytest

from sprite.proactive import live
from sprite.proactive.dialog import ChatDialog

tk = pytest.importorskip("tkinter")

HISTORY = [{"role": "assistant", "text": "我已经把桌面整理好了", "time": "2026-10-12 09:30:00"}]


@pytest.fixture
def root():
    """A withdrawn Tk root so the tests never steal a visible window."""
    import tkinter as tk
    try:
        r = tk.Tk()
    except tk.TclError:                       # 无显示环境
        pytest.skip("no display available for tkinter")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _dialog(root):
    return ChatDialog(root, 10, 10, "我判断你现在在：写代码", lambda _t: "", [])


def test_set_history_after_close_is_a_noop(root):
    """关掉对话框后 set_history 不抛 —— 这正是日志里那次崩溃的形状。"""
    dlg = _dialog(root)
    dlg.close()
    assert dlg.win.winfo_exists() == 0
    dlg.set_history(HISTORY)                  # 旧代码在这里 TclError


def test_every_touch_is_safe_once_toplevel_is_destroyed(root):
    """toplevel 被销毁后，公开方法一个都不许炸。"""
    dlg = _dialog(root)
    dlg.win.destroy()
    dlg.set_history(HISTORY)
    dlg.set_status("新状态")
    dlg.send()
    dlg._append_local("user", "你好")
    dlg._place()
    dlg._focus()
    dlg.close()                                # 幂等
    dlg.close()


def test_every_touch_is_safe_once_whole_app_is_destroyed(root):
    """整个 Tk 应用销毁后同样不许炸。

    这是旧守卫真正漏掉的那一层：``winfo_exists()`` 自己就是一次 Tcl 调用，
    应用没了以后它抛 ``can't invoke "winfo" command: application has been destroyed``，
    守卫先炸，等于没守卫。
    """
    dlg = _dialog(root)
    root.destroy()
    dlg.set_history(HISTORY)
    dlg.set_status("新状态")
    dlg.send()
    dlg._append_local("user", "你好")
    dlg._place()
    dlg._focus()
    dlg.close()


def test_focus_callback_after_immediate_close(root):
    """``win.after(50, self._focus)`` 打在已关闭的窗口上。

    用户点开对话框后 50ms 内点 ×，这个延迟回调就会落到已销毁的控件上。
    """
    dlg = _dialog(root)
    dlg.close()
    dlg._focus()


def test_live_drops_stale_reference_even_when_close_raises():
    """present() 撞上失效引用时，异常被吞掉且 opened["dlg"] 被清成 None。

    用一个「close() 一调用就抛 TclError」的假 dialog 复刻现场。关键在顺序：
    必须**先**把引用置空再 close，否则一次抛异常的 close 会把 stale 引用
    留给下一拍 tick。
    """
    closed = []

    class DeadDialog:
        def close(self):
            closed.append(True)
            raise tk.TclError('invalid command name ".!toplevel4.!frame.!frame3.!text"')

    opened = {"dlg": DeadDialog()}
    live.drop_dead_dialog(opened)
    assert opened["dlg"] is None
    assert closed == [True], "close 应该被尝试过一次"


def test_live_drop_dead_dialog_is_idempotent_when_empty():
    """没有对话框时必须是纯 no-op。"""
    opened = {"dlg": None}
    live.drop_dead_dialog(opened)
    assert opened["dlg"] is None


def test_live_drop_dead_dialog_closes_a_live_dialog(root):
    """引用还活着时，drop 真的把它关掉。"""
    dlg = _dialog(root)
    opened = {"dlg": dlg}
    live.drop_dead_dialog(opened)
    assert opened["dlg"] is None
    assert dlg.win.winfo_exists() == 0


def test_live_drop_dead_dialog_survives_destroyed_app(root):
    """整个 Tk 应用销毁后再 drop —— 复刻 present() 的收尾，不许抛。"""
    dlg = _dialog(root)
    opened = {"dlg": dlg}
    root.destroy()
    live.drop_dead_dialog(opened)
    assert opened["dlg"] is None


# ── 错过提议的补点区（issue #26）────────────────────────────────────────

PENDING_OFFER = {"id": "late-1", "text": "我想帮你做这件事：清一下回收站，要我开始吗？",
                 "options": ["好的", "不用"]}


def _all_children(w):
    out = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(_all_children(c))
    return out


def _buttons(dlg, text):
    return [w for w in _all_children(dlg.win)
            if w.winfo_class() == "Button" and w.cget("text") == text]


def test_pending_dialog_renders_nothing_without_pending(root):
    dlg = _dialog(root)
    assert _buttons(dlg, "好的") == [], "没有未决提议时不该出现补点按钮"


def test_pending_card_yes_invokes_callback_and_removes_card(root):
    calls = []
    dlg = ChatDialog(root, 10, 10, "状态", lambda _t: "", [],
                     pending=[PENDING_OFFER],
                     on_decide=lambda offer, ok: calls.append((offer["id"], ok)))
    yes = _buttons(dlg, "好的")
    assert len(yes) == 1
    card = yes[0].master.master                 # row -> card
    yes[0].invoke()
    assert calls == [("late-1", True)]
    assert card.winfo_exists() == 0, "点完卡片应移除，不让同一件事重复批准"


def test_pending_card_no_records_rejection(root):
    calls = []
    dlg = ChatDialog(root, 10, 10, "状态", lambda _t: "", [],
                     pending=[PENDING_OFFER],
                     on_decide=lambda offer, ok: calls.append((offer["id"], ok)))
    _buttons(dlg, "不用")[0].invoke()
    assert calls == [("late-1", False)]


def test_pending_callback_error_keeps_card_and_does_not_raise(root):
    def boom(_offer, _ok):
        raise RuntimeError("账本满了")

    dlg = ChatDialog(root, 10, 10, "状态", lambda _t: "", [],
                     pending=[PENDING_OFFER], on_decide=boom)
    yes = _buttons(dlg, "好的")[0]
    card = yes.master.master
    yes.invoke()                                 # 异常被吞进日志，不抛给 Tk
    assert card.winfo_exists() == 1, "失败时卡片留着，下次打开还能再点"
