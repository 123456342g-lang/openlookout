"""User-facing speech never carries internal bookkeeping."""
from __future__ import annotations

from sprite.i18n import t
from sprite.proactive import live
from sprite.proactive.public_speech import (
    QUIET_DIALOG,
    dialog_status,
    leaks_internal,
    offer_is_safe_reclaim,
    user_label,
)


def test_dialog_ignores_internal_fields():
    current = {
        "activity": "心跳轮无新证据：trim-trae-idle 连续 4 次被「现场已变化」拦下",
        "state": "本轮不再重试；无待回应话轮，保持安静",
        "next_step": {"action": "等下一批可执行窗口时再判断是否值得重试一次 trim", "status": "ready"},
        "speech": {"kind": "quiet", "say": ""},
    }
    text = dialog_status(current)
    assert text == QUIET_DIALOG
    for leaked in ("心跳轮", "trim-trae", "现场已变化", "next_step", "可执行窗口"):
        assert leaked not in text


def test_dialog_shows_a_real_spoken_line():
    current = {"activity": "内部记账不出口", "speech": {"kind": "companion", "say": "这段报错是少了一个引号。"}}
    assert dialog_status(current) == "这段报错是少了一个引号。"


def test_dialog_drops_a_spoken_line_that_still_leaks():
    current = {"speech": {"kind": "companion", "say": "我要做这 2 件 medium 风险的事，见 issue #15"}}
    assert dialog_status(current) == QUIET_DIALOG


def test_leak_patterns_cover_the_reported_phrases():
    assert leaks_internal("Trae 想拿 PR #15 当证据，outcomes.jsonl 60 行")
    assert leaks_internal("调用 desktop_reclaim 然后写 WORKING.md")
    assert leaks_internal("risk:high")
    assert not leaks_internal("这段报错是少了一个引号。")


def test_user_label_hides_risk_topics():
    assert user_label("risk:high") == t("this_thing")
    assert user_label("磁盘清理") == "磁盘清理"
    assert user_label("") == t("this_thing")


def test_safe_reclaim_is_narrow():
    assert offer_is_safe_reclaim({"text": "我帮你把缓存和回收站收进隔离区"})
    assert offer_is_safe_reclaim({"text": "清理临时文件"})
    assert not offer_is_safe_reclaim({"text": "结束这个进程"})
    assert not offer_is_safe_reclaim({"text": "清理缓存", "items": [{"tool": "desktop_reclaim"}]})


def test_safe_reclaim_runs_the_tool_not_a_model(monkeypatch):
    calls = []

    class Reply:
        success = True
        text = "已收好 2 个临时文件，随时可以还原。"

    def fake_reclaim(args):
        calls.append(args)
        return Reply()

    monkeypatch.setattr("vista.benchmarks.desktop.actions.reclaim", fake_reclaim)
    shown = []
    recorded = []
    monkeypatch.setattr(live, "record_offer_result", lambda offer, result, **kw: recorded.append(result))
    live.run_safe_reclaim({"id": "c1", "text": "清理缓存"}, shown.append)
    assert calls == [{}]
    assert recorded == ["auto_completed"]
    assert shown and "临时文件" in shown[0]["text"]
    assert "desktop_" not in shown[0]["text"]
