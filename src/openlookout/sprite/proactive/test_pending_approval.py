"""issue #26：气泡错过后，对话框「它刚问你的事」仍能补点好的/不用。

测的是 live.pending_approval_offers 这个纯列表函数：账本（offers.jsonl +
pending_batches.jsonl）→ 未决提议列表。规则：
- expired/ignored（没看见、没选）**不是**拒绝，补点窗口内仍列；
- started/rejected/已执行（DECIDED_OFFER_STATES）才移出；
- 超出补点窗口、当前正在屏上的气泡不列；
- 风险批次与最近一条普通 offer 合并，按时间升序、最多 3 条。
"""
from __future__ import annotations

import json

import pytest

from sprite.proactive import live
from vista.benchmarks.desktop import permissions

WINDOW = 7200.0
NOW = 1_000_000.0


@pytest.fixture
def books(tmp_path, monkeypatch):
    perceive = tmp_path / "perceive"
    perceive.mkdir()
    monkeypatch.setattr(live, "DIR", perceive)
    # pending_batches() 默认读模块全局 PENDING，指到沙盒，绝不扫真实账本。
    monkeypatch.setattr(permissions, "PENDING", perceive / "pending_batches.jsonl")
    return perceive


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def offer_row(oid, t, *, result="shown", kind="offer", **extra):
    row = {"id": oid, "t": t, "kind": kind, "topic": "清理",
           "text": f"提议 {oid}", "options": ["好的", "不用"], "result": result}
    row.update(extra)
    return row


def batch_row(bid, t, **extra):
    row = {"id": bid, "state": "pending", "t": t, "expires_t": t + WINDOW,
           "risk": "medium", "text": f"批次 {bid}",
           "items": [{"tool": "desktop_write_deliverable", "args": {}}]}
    row.update(extra)
    return row


def pending(books, **kw):
    return live.pending_approval_offers(now=NOW, window_s=WINDOW, **kw)


def test_no_books_means_nothing_pending(books):
    assert pending(books) == []


def test_undecided_batch_within_window_is_listed(books):
    _write_jsonl(permissions.PENDING, [batch_row("batch-1", NOW - 60)])
    out = pending(books)
    assert [o["id"] for o in out] == ["batch-1"]
    assert out[0]["kind"] == "offer"
    assert out[0]["options"] == ["好的", "不用"]
    assert out[0]["items"], "批次清单必须原样带上，批准的是这份清单"


def test_batch_older_than_window_is_gone(books):
    _write_jsonl(permissions.PENDING, [batch_row("batch-old", NOW - WINDOW - 1)])
    assert pending(books) == []


def test_batch_started_or_rejected_is_gone_but_expired_stays(books):
    _write_jsonl(permissions.PENDING, [
        batch_row("b-started", NOW - 100),
        batch_row("b-rejected", NOW - 90),
        batch_row("b-expired", NOW - 80),   # 气泡过期：没看见，不是拒绝
    ])
    _write_jsonl(books / "offers.jsonl", [
        offer_row("b-started", NOW - 100, result="started"),
        offer_row("b-rejected", NOW - 90, result="rejected"),
        offer_row("b-expired", NOW - 80, result="shown"),
        offer_row("b-expired", NOW - 80 + live.OFFER_ASK_S, result="expired"),
    ])
    assert [o["id"] for o in pending(books)] == ["b-expired"]


def test_active_bubble_is_not_duplicated_in_dialog(books):
    _write_jsonl(permissions.PENDING, [batch_row("batch-live", NOW - 5)])
    assert pending(books, active_id="batch-live") == []


def test_latest_plain_offer_after_bubble_expiry_is_listed(books):
    _write_jsonl(books / "offers.jsonl", [
        offer_row("offer-1", NOW - 300, result="shown"),
        offer_row("offer-1", NOW - 300 + live.OFFER_ASK_S, result="expired"),
    ])
    out = pending(books)
    assert [o["id"] for o in out] == ["offer-1"]
    assert "items" not in out[0]


def test_only_the_latest_plain_offer_is_considered(books):
    # 最近一条普通 offer 已拒绝：不回头翻更老的未决旧账。
    _write_jsonl(books / "offers.jsonl", [
        offer_row("offer-old", NOW - 500, result="shown"),
        offer_row("offer-old", NOW - 490, result="expired"),
        offer_row("offer-new", NOW - 100, result="shown"),
        offer_row("offer-new", NOW - 90, result="rejected"),
    ])
    assert pending(books) == []


def test_companion_and_say_lines_are_not_approvable(books):
    _write_jsonl(books / "offers.jsonl", [
        offer_row("c-1", NOW - 60, kind="companion", result="shown"),
    ])
    assert pending(books) == []


def test_broken_lines_never_block_the_list(books):
    (books / "offers.jsonl").write_text('{"oops":\nnot json\n', encoding="utf-8")
    permissions.PENDING.write_text("garbage\n\n", encoding="utf-8")
    assert pending(books) == []


def test_list_is_time_ascending_and_capped_at_three(books):
    rows = [batch_row(f"batch-{i}", NOW - 1000 + i * 100) for i in range(4)]
    _write_jsonl(permissions.PENDING, rows)
    out = pending(books)
    ids = [o["id"] for o in out]
    assert ids == ["batch-1", "batch-2", "batch-3"]
    assert [o["t"] for o in out] == sorted(o["t"] for o in out)
