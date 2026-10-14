"""issue #15 PR#19 第二轮对抗审查（P2-1~P2-6）的回归测试。

全部确定性纯函数 + 合成账本夹具：
* P2-1 对话簇排除同时查 offers join 侧的 reply_to（outcomes 侧①字段优先），
  字段盘点按 outcomes/offers 两个数据源分列；
* P2-2 join 缺失 + latency 缺失/非法的行单列为疑似污染并从开口序列剔除；
* P2-3 跨时刻来源的 gap 给来源对标注与计数；
* P2-4 burstiness 内部先排序，喂乱序输入结果不变；
* P2-5 anchor 部分覆盖时占比分母只数字段存在的行，缺失/确认空严格分开。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import sprite.proactive.outcome_report as rm


D1 = datetime(2026, 10, 10, 12, 0, 0).timestamp()


def write_rows(directory: Path, name: str, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def orow(oid: str, outcome: str, t: float, *, kind: str = "companion",
         latency: float | None = 10.0, topic: str = "", text: str = "…",
         **extra) -> dict:
    row = {"id": oid, "t": t, "outcome": outcome, "latency_s": latency,
           "kind": kind, "topic": topic, "text": text}
    row.update(extra)
    return row


@pytest.fixture()
def perceive(tmp_path: Path) -> Path:
    d = tmp_path / "perceive"
    d.mkdir()
    return d


class FakeTiming:
    OUTCOMES_PATH = Path("/nonexistent/outcomes.jsonl")
    _POSITIVE = {"accepted", "responded"}
    _NEGATIVE = {"rejected"}
    MIN_OUTCOMES = 20

    def benefit_now(self):
        return 60.0, "合成测试"

    def stop_threshold(self, app, *, benefit_s=None):
        return 0.5


# ── P2-1：offers join 侧 reply_to 排除 ────────────────────────────────────────
def test_reply_cluster_excluded_from_offer_side(perceive: Path) -> None:
    # outcomes 行都不带①字段；reply_to 只存在于 join 到的 offer 行（生产现状）
    offers = [
        {"id": "a", "t": D1, "kind": "companion", "result": "shown"},
        {"id": "b", "t": D1 + 100, "kind": "companion", "result": "shown",
         "reply_to": "message:100"},
        {"id": "c", "t": D1 + 200, "kind": "companion", "result": "shown",
         "reply_to": "message:200"},
    ]
    outcomes = [
        orow("a", "unanswered", D1 + 180, latency=180.0),
        orow("b", "unanswered", D1 + 280, latency=180.0),
        orow("c", "unanswered", D1 + 380, latency=180.0),
    ]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    moments = rm.opening_moments(outcomes, rm._index_offers(offers))
    assert moments["excluded_reply_rows"] == 2
    assert moments["excluded_reply_rows_outcomes"] == 0
    assert moments["excluded_reply_rows_offers"] == 2
    assert moments["reply_outcomes_present"] is False
    assert moments["reply_offers_present"] is True
    assert [m["id"] for m in moments["moments"]] == ["a"]

    rep = rm.summarize(perceive, timing_module=FakeTiming())
    burst = rep["burstiness"]
    assert burst["excluded_reply_rows_offers"] == 2
    note = "；".join(burst["notes"])
    assert "offers.jsonl join 侧 reply_to 2 行" in note
    # 不能再笼统声称「字段缺失无法排除」：offers 侧明明有标记
    assert "两侧都没有" not in note
    # 但要如实说明 outcomes 侧①字段仍缺
    assert "outcomes 侧 reply_to/turn_trigger 仍缺失" in note
    md = rm.render_markdown(rep)
    assert "已排除对话簇 2 行" in md


def test_outcome_side_reply_takes_precedence(perceive: Path) -> None:
    # 同一开口两侧都有标记时只计一次，且归 outcomes 侧（①字段优先）
    offers = [{"id": "a", "t": D1, "kind": "companion", "result": "shown",
               "reply_to": "message:1"}]
    outcomes = [orow("a", "responded", D1 + 5, latency=5.0,
                     reply_to="message:1", turn_trigger="reply")]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    moments = rm.opening_moments(outcomes, rm._index_offers(offers))
    assert moments["excluded_reply_rows"] == 1
    assert moments["excluded_reply_rows_outcomes"] == 1
    assert moments["excluded_reply_rows_offers"] == 0
    assert moments["moments"] == []


def test_field_inventory_split_by_source(perceive: Path) -> None:
    outcomes = [orow("a", "ignored", D1, latency=180.0)]
    offers = [{"id": "a", "t": D1, "kind": "companion",
               "reply_to": "message:1", "result": "shown"}]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    assert rep["ledger_fields"]["outcomes"]["reply_to"]["rows_nonempty"] == 0
    assert rep["ledger_fields"]["offers"]["reply_to"]["rows_nonempty"] == 1
    assert rep["ledger_fields"]["offers"]["anchor"]["rows_with_key"] == 0
    md = rm.render_markdown(rep)
    assert "offers.jsonl（reply_to 今天已随 offer 落盘）" in md


def test_no_reply_markers_either_side_says_cannot_identify(perceive: Path) -> None:
    outcomes = [orow("a", "ignored", D1, latency=180.0),
                orow("b", "ignored", D1 + 1000, latency=180.0)]
    write_rows(perceive, "offers.jsonl",
               [{"id": "a", "t": D1, "kind": "companion", "result": "shown"},
                {"id": "b", "t": D1 + 1000, "kind": "companion",
                 "result": "shown"}])
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    assert any("两侧都没有" in n for n in rep["burstiness"]["notes"])


# ── P2-2：污染行剔除 ──────────────────────────────────────────────────────────
def test_orej_style_polluted_row_excluded(perceive: Path) -> None:
    # o-rej：offers 无此 id，latency=1.79e9 —— 不得静默读结果 t
    good = [orow(f"g{i}", "accepted", D1 + 1000 * i, latency=10.0)
            for i in range(3)]
    orej = orow("o-rej", "rejected", D1 + 500, latency=1.79e9)
    write_rows(perceive, "outcomes.jsonl", good + [orej])
    moments = rm.opening_moments(good + [orej], {})
    ids = [m["id"] for m in moments["moments"]]
    assert ids == ["g0", "g1", "g2"]
    assert moments["polluted_n"] == 1
    poll = moments["polluted_rows"][0]
    assert poll["id"] == "o-rej"
    assert "offers_join 缺失" in poll["reason"] and "非法" in poll["reason"]

    rep = rm.summarize(perceive, timing_module=FakeTiming())
    burst = rep["burstiness"]
    assert burst["n_openings"] == 3 and burst["polluted_n"] == 1
    assert any("o-rej" in n and "污染" in n for n in burst["notes"])
    md = rm.render_markdown(rep)
    assert "疑似污染 1 行" in md and "o-rej" in md


def test_missing_latency_without_join_is_pollution(perceive: Path) -> None:
    outcomes = [orow("a", "ignored", D1 + 100, latency=None)]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    moments = rm.opening_moments(outcomes, {})
    assert moments["moments"] == []
    assert moments["polluted_n"] == 1
    assert "latency_s 缺失" in moments["polluted_rows"][0]["reason"]


def test_joined_row_with_huge_latency_is_kept(perceive: Path) -> None:
    # join 命中时 offer t 直接可信：latency 再离谱也不影响开口时刻，不得误剔
    offers = [{"id": "a", "t": D1, "kind": "companion", "result": "shown"}]
    outcomes = [orow("a", "rejected", D1 + 200, latency=1.79e9)]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    moments = rm.opening_moments(outcomes, rm._index_offers(offers))
    assert moments["polluted_n"] == 0
    assert moments["moments"][0]["source"] == "offers_join"
    assert moments["moments"][0]["ts"] == pytest.approx(D1)


def test_valid_reconstructed_row_is_kept(perceive: Path) -> None:
    # join 缺失但 latency 合法（0~24h）：t-latency 是精确换算，不是污染
    outcomes = [orow("a", "ignored", D1 + 260, latency=180.0)]
    moments = rm.opening_moments(outcomes, {})
    assert moments["polluted_n"] == 0
    assert moments["moments"][0]["source"] == "reconstructed_t_minus_latency"
    assert moments["moments"][0]["ts"] == pytest.approx(D1 + 80)


# ── P2-4：内部排序，乱序输入不影响簇/gap ─────────────────────────────────────
def test_burstiness_sorts_internally() -> None:
    ordered = [
        {"id": "a", "ts": 0.0, "source": "offers_join"},
        {"id": "b", "ts": 60.0, "source": "offers_join"},
        {"id": "c", "ts": 100.0, "source": "offers_join"},
        {"id": "d", "ts": 500.0, "source": "offers_join"},
        {"id": "e", "ts": 620.0, "source": "offers_join"},
    ]
    shuffled = [ordered[i] for i in (3, 0, 4, 2, 1)]
    out_sorted = rm.burstiness({"moments": ordered, "timestamp_sources":
                                {"offers_join": 5}})
    out_shuffled = rm.burstiness({"moments": shuffled, "timestamp_sources":
                                  {"offers_join": 5}})
    for key in ("gap_median_s", "gap_p90_s", "gap_cv", "cluster_n",
                "turns_in_clusters", "singleton_n", "largest_cluster_turns",
                "cluster_size_histogram", "gap_histogram", "n_gaps"):
        assert out_sorted[key] == out_shuffled[key], key
    assert out_sorted["cluster_n"] == 2
    assert out_sorted["largest_cluster_turns"] == 3
    assert out_sorted["cluster_size_histogram"] == {"2": 1, "3": 1}


def test_burstiness_equal_timestamps_form_zero_gap_cluster() -> None:
    moments = [{"id": "a", "ts": 10.0, "source": "offers_join"},
               {"id": "b", "ts": 10.0, "source": "offers_join"}]
    out = rm.burstiness({"moments": moments,
                         "timestamp_sources": {"offers_join": 2}})
    assert out["n_gaps"] == 1 and out["gap_histogram"][0]["n"] == 1
    assert out["cluster_n"] == 1 and out["turns_in_clusters"] == 2


# ── P2-3：混合来源 gap 标注 ──────────────────────────────────────────────────
def test_mixed_source_gaps_are_counted(perceive: Path) -> None:
    # 排序后：offers_join(0) → reconstructed(500) → offers_join(1000)
    offers = [{"id": "a", "t": D1, "kind": "companion", "result": "shown"},
              {"id": "c", "t": D1 + 1000, "kind": "companion",
               "result": "shown"}]
    outcomes = [
        orow("a", "ignored", D1 + 180, latency=180.0),
        orow("b", "ignored", D1 + 680, latency=180.0),   # 重构 → D1+500
        orow("c", "ignored", D1 + 1180, latency=180.0),
    ]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    burst = rm.summarize(perceive, timing_module=FakeTiming())["burstiness"]
    assert burst["timestamp_sources"] == {"offers_join": 2,
                                          "reconstructed_t_minus_latency": 1}
    assert burst["gap_mixed_source_n"] == 2
    pairs = burst["gap_source_pairs"]
    assert pairs["offers_join→reconstructed_t_minus_latency"] == 1
    assert pairs["reconstructed_t_minus_latency→offers_join"] == 1
    assert any("2 个 gap 的两个端点来自不同时刻来源" in n
               for n in burst["notes"])


def test_homogeneous_source_gaps_not_flagged() -> None:
    moments = [{"id": str(i), "ts": 1000.0 * i, "source": "offers_join"}
               for i in range(5)]
    out = rm.burstiness({"moments": moments,
                         "timestamp_sources": {"offers_join": 5}})
    assert out["gap_mixed_source_n"] == 0
    assert out["gap_source_pairs"] == {"offers_join→offers_join": 4}


# ── P2-5：部分覆盖时缺字段的 kind 占比为 None ─────────────────────────────────
def test_anchor_rate_none_for_kind_without_field(perceive: Path) -> None:
    outcomes = [
        orow("c0", "accepted", D1, kind="companion",
             anchor={"app": "chrome", "type": "focus", "title": "t"}),
        orow("f0", "accepted", D1 + 1, kind="offer"),   # 该 kind 整列缺字段
        orow("f1", "accepted", D1 + 2, kind="offer"),
    ]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    anchors = rm.summarize(perceive, timing_module=FakeTiming())["anchors"]
    assert anchors["computable"] is True
    offer = anchors["by_kind"]["offer"]
    assert offer["with_field"] == 0 and offer["missing_field"] == 2
    assert offer["coverage"] == 0.0 and offer["anchorless_rate"] is None
    comp = anchors["by_kind"]["companion"]
    assert comp["anchorless_rate"] == 0.0
    # 整体分母不含 offer 那 2 行
    assert anchors["anchorless_rate_overall"] == 0.0
    md = rm.render_markdown(rm.summarize(perceive, timing_module=FakeTiming()))
    assert "字段覆盖率" in md and "确认无锚点" in md
