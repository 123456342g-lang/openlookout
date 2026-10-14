"""issue #15 ② 离线四指标的测试：全部用确定性纯函数 + 合成账本夹具。

覆盖：
* 间隔突发度：中位/p90/CV、≤120s 成簇（簇数/簇内轮次/长尾）、开口时刻来源；
* 无锚点占比：① 字段缺失时显式「不可算」，绝不伪造默认值；① 落地后按 kind 分列；
* 回应率双口径：沉默进/不进分母，两个分母必须是不同的数；
* receptivity 延迟：只数明确回应行，沉默与污染 latency 剔除；
* 样本不足（<20）一律「不能判断」；空账本不崩；① 字段（offer_t/reply_to）
  存在时自动启用（预留行为也钉死）。
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pytest

import sprite.proactive.outcome_report as rm


D1 = datetime(2026, 10, 10, 12, 0, 0).timestamp()


# ── 夹具工具 ──────────────────────────────────────────────────────────────────
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


# ── 1. 间隔突发度：成簇/分位数/CV/长尾 ────────────────────────────────────────
def test_burstiness_clusters_quantiles_cv_histogram(perceive: Path) -> None:
    # 开口时刻（offers 侧 t）：0,60,100 成一簇（3 轮）；500,620 成一簇（2 轮，gap 恰 =120）
    opens = [0.0, 60.0, 100.0, 500.0, 620.0]
    offers = [{"id": f"o{i}", "t": D1 + x, "kind": "companion",
               "result": "shown"} for i, x in enumerate(opens)]
    # outcomes 的 t 比开口晚 latency（30s）：join 到 offers 后必须用 offers 的 t，不被 30s 污染
    outcomes = [orow(f"o{i}", "unanswered", D1 + x + 30.0,
                     latency=30.0) for i, x in enumerate(opens)]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)

    rep = rm.summarize(perceive, timing_module=FakeTiming())
    burst = rep["burstiness"]
    assert burst["n_openings"] == 5
    assert burst["n_gaps"] == 4
    # gap = 40,60,120,400
    assert burst["gap_median_s"] == pytest.approx(90.0)
    assert burst["gap_p90_s"] == pytest.approx(400.0)   # 最近秩：ceil(.9*4)=4
    assert burst["gap_mean_s"] == pytest.approx(155.0)
    pstd = math.sqrt((95 ** 2 + 115 ** 2 + 245 ** 2 + 35 ** 2) / 4)
    assert burst["gap_std_s"] == pytest.approx(pstd)
    assert burst["gap_cv"] == pytest.approx(pstd / 155.0)
    # 成簇
    assert burst["cluster_n"] == 2
    assert burst["turns_in_clusters"] == 5
    assert burst["singleton_n"] == 0
    assert burst["largest_cluster_turns"] == 3
    assert burst["cluster_size_histogram"] == {"2": 1, "3": 1}
    # 长尾直方图：40/60 落 (30,60]，120 落 (60,120]，400 落 (300,600]
    hist = {b["bin_s"]: b["n"] for b in burst["gap_histogram"]}
    assert hist["(30, 60]s"] == 2
    assert hist["(60, 120]s"] == 1
    assert hist["(300, 600]s"] == 1
    # 开口时刻全部来自 offers join
    assert burst["timestamp_sources"] == {"offers_join": 5}
    md = rm.render_markdown(rep)
    assert "间隔突发度" in md and "突发簇 = **2 簇**" in md
    assert "CV 只监控、不拦截" in md


def test_burstiness_timestamp_sources_and_fallback(perceive: Path) -> None:
    # a: offers join；b: 无 offers 但 t-latency 可重构；
    # c: join 缺失 + latency 缺失 → P2-2 起不再退化读结果 t，按疑似污染剔除
    outcomes = [
        orow("a", "ignored", D1 + 100.0, latency=100.0),
        orow("b", "ignored", D1 + 260.0, latency=180.0),
        orow("c", "ignored", D1 + 500.0, latency=None),
    ]
    offers = [{"id": "a", "t": D1, "kind": "companion", "result": "shown"}]
    write_rows(perceive, "offers.jsonl", offers)
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    burst = rep["burstiness"]
    assert burst["timestamp_sources"] == {
        "offers_join": 1, "reconstructed_t_minus_latency": 1}
    # 重构出的 b 开口时刻 = 260-180 = D1+80；a 在 D1+0
    joined = rm.opening_moments(outcomes, rm._index_offers(offers))
    by_id = {m["id"]: m for m in joined["moments"]}
    assert by_id["a"]["source"] == "offers_join"
    assert by_id["b"]["source"] == "reconstructed_t_minus_latency"
    assert by_id["b"]["ts"] == pytest.approx(D1 + 80.0)
    # c 不进序列，进污染清单并点名
    assert "c" not in by_id
    assert joined["polluted_n"] == 1
    assert joined["polluted_rows"][0]["id"] == "c"
    assert "latency_s 缺失" in joined["polluted_rows"][0]["reason"]
    assert burst["n_openings"] == 2
    assert any("污染" in n and "c" in n for n in burst["notes"])


def _rows_of(directory: Path) -> list[dict]:
    rows, _ = rm.read_jsonl(directory / "outcomes.jsonl")
    return rows


def _offer_map(directory: Path) -> dict:
    rows, _ = rm.read_jsonl(directory / "offers.jsonl")
    return rm._index_offers(rows)


def test_burstiness_offer_t_preferred_and_reply_excluded(perceive: Path) -> None:
    # ① 落地后：offer_t 优先；reply_to 非空 / turn_trigger=reply 的行排除
    outcomes = [
        orow("p1", "responded", D1 + 5.0, latency=5.0, offer_t=D1,
             anchor={"app": "code", "type": "save", "title": "x"},
             turn_trigger="action_boundary"),
        orow("p2", "responded", D1 + 105.0, latency=5.0,
             offer_t=D1 + 100.0, turn_trigger="action_boundary"),
        orow("r1", "responded", D1 + 108.0, latency=2.0,
             offer_t=D1 + 106.0, turn_trigger="reply", reply_to="p2"),
        orow("r2", "responded", D1 + 112.0, latency=1.0,
             offer_t=D1 + 111.0, reply_to="r1"),
    ]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    moments = rm.opening_moments(_rows_of(perceive), {})
    assert moments["excluded_reply_rows"] == 2
    assert moments["excluded_reply_rows_outcomes"] == 2
    assert moments["excluded_reply_rows_offers"] == 0
    assert moments["reply_outcomes_present"] is True
    ids = [m["id"] for m in moments["moments"]]
    assert ids == ["p1", "p2"]
    assert all(m["source"] == "offer_t" for m in moments["moments"])
    assert rep["burstiness"]["excluded_reply_rows"] == 2
    assert any("排除对话簇开口 2 行" in n for n in rep["burstiness"]["notes"])


def test_burstiness_insufficient_sample_says_cannot_judge(perceive: Path) -> None:
    outcomes = [orow(f"o{i}", "unanswered", D1 + 1000 * i,
                     latency=180.0) for i in range(5)]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    verdict = rep["burstiness"]["verdict"]
    assert "不能判断" in verdict and "5" in verdict
    # 数字仍照给（描述性），但不能给结论
    assert rep["burstiness"]["gap_median_s"] is not None


def test_burstiness_descriptive_with_20_openings(perceive: Path) -> None:
    outcomes = [orow(f"o{i}", "accepted", D1 + 1000 * i, latency=10.0)
                for i in range(20)]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    assert "不能判断" not in rep["burstiness"]["verdict"]
    assert rep["burstiness"]["n_openings"] == 20
    assert rep["burstiness"]["cluster_n"] == 0
    assert rep["burstiness"]["singleton_n"] == 20
    assert rep["burstiness"]["gap_cv"] == pytest.approx(0.0)


# ── 2. 无锚点占比 ─────────────────────────────────────────────────────────────
def test_anchor_missing_field_is_explicitly_not_computable(perceive: Path) -> None:
    outcomes = [orow(f"o{i}", "unanswered", D1 + i, kind=k)
                for i, k in enumerate(["companion"] * 10 + ["offer"] * 3)]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    anchors = rep["anchors"]
    assert anchors["computable"] is False
    assert anchors["anchorless_rate_overall"] is None
    assert "锚点字段缺失（①未落地）" in anchors["verdict"]
    assert "不可算" in anchors["verdict"]
    assert "0/13" in anchors["verdict"]
    md = rm.render_markdown(rep)
    assert "锚点字段缺失（①未落地）" in md
    # 字段盘点也照实（按数据源分列：outcomes / offers）
    assert rep["ledger_fields"]["outcomes"]["anchor"]["rows_with_key"] == 0
    assert rep["ledger_fields"]["outcomes"]["offer_t"]["rows_with_key"] == 0
    assert rep["ledger_fields"]["offers"]["anchor"]["rows_with_key"] == 0


def test_anchor_rate_by_kind_when_field_present(perceive: Path) -> None:
    outcomes = []
    for i in range(10):  # companion：8 带锚点，2 行字段缺失（①灰度历史行）
        extra = {"anchor": {"app": "chrome", "type": "focus", "title": "t"}} \
            if i < 8 else {}
        outcomes.append(orow(f"c{i}", "accepted", D1 + i, kind="companion",
                             **extra))
    for i in range(5):  # offer：全带锚点
        outcomes.append(orow(f"f{i}", "accepted", D1 + 100 + i, kind="offer",
                             anchor={"app": "term", "type": "clipboard",
                                     "title": ""}))
    # 空 dict 锚点 = 字段存在但确认为空（与「字段缺失」严格区分，P2-5）
    outcomes.append(orow("c-empty", "accepted", D1 + 200, kind="companion",
                         anchor={}))
    write_rows(perceive, "outcomes.jsonl", outcomes)
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    anchors = rep["anchors"]
    assert anchors["computable"] is True
    # companion 11 行：8 有锚点、1 确认空、2 字段缺失；分母只数有字段的 9 行
    comp = anchors["by_kind"]["companion"]
    assert comp["n"] == 11 and comp["with_field"] == 9
    assert comp["anchored"] == 8 and comp["anchorless_confirmed"] == 1
    assert comp["missing_field"] == 2
    assert comp["coverage"] == pytest.approx(9 / 11)
    assert comp["anchorless_rate"] == pytest.approx(1 / 9)
    offer = anchors["by_kind"]["offer"]
    assert offer["with_field"] == 5 and offer["missing_field"] == 0
    assert offer["anchorless_rate"] == 0.0
    # 整体：确认空 1 / 有字段 14；字段缺失 2 行进覆盖率但不进占比
    assert anchors["coverage"] == pytest.approx(14 / 16)
    assert anchors["anchorless_rate_overall"] == pytest.approx(1 / 14)


def test_anchor_empty_ledger_graceful(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [])
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    assert rep["anchors"]["computable"] is False
    assert "不能判断" in rep["anchors"]["verdict"]
    rm.render_markdown(rep)  # 不崩


# ── 3. 回应率双口径 ───────────────────────────────────────────────────────────
def test_response_rates_two_denominators_differ() -> None:
    rates = rm.response_rates(
        {"positive": 2, "negative": 1, "silence": 4, "ambiguous": 1, "unknown": 1})
    obs = rates["observed_response_rate"]
    ev = rates["evidence_positive_rate"]
    assert obs["numerator"] == 3 and obs["denominator"] == 7
    assert obs["rate"] == pytest.approx(3 / 7)
    assert ev["numerator"] == 2 and ev["denominator"] == 3
    assert ev["rate"] == pytest.approx(2 / 3)
    assert obs["rate"] != ev["rate"]
    assert rates["excluded_from_both"] == {"ambiguous": 1, "unknown": 1}
    assert "不能判断" in rates["verdict"]  # 分母都 <20


def test_response_rates_silence_only() -> None:
    rates = rm.response_rates(
        {"positive": 0, "negative": 0, "silence": 10, "ambiguous": 0, "unknown": 0})
    assert rates["observed_response_rate"]["rate"] == 0.0
    assert rates["observed_response_rate"]["denominator"] == 10
    assert rates["evidence_positive_rate"]["rate"] is None
    assert rates["evidence_positive_rate"]["denominator"] == 0


def test_response_rates_descriptive_with_enough_sample() -> None:
    rates = rm.response_rates(
        {"positive": 12, "negative": 8, "silence": 5, "ambiguous": 0, "unknown": 0})
    assert "不能判断" not in rates["verdict"]
    assert rates["observed_response_rate"]["rate"] == pytest.approx(20 / 25)
    assert rates["evidence_positive_rate"]["rate"] == pytest.approx(12 / 20)


def test_dual_rates_rendered_side_by_side(perceive: Path) -> None:
    outcomes = [orow("a", "accepted", D1), orow("r", "rejected", D1 + 1),
                orow("s1", "ignored", D1 + 2, latency=180.0),
                orow("s2", "unanswered", D1 + 3, latency=180.0)]
    write_rows(perceive, "outcomes.jsonl", outcomes)
    md = rm.render_markdown(rm.summarize(perceive, timing_module=FakeTiming()))
    assert "观测回应率（三类标签）" in md
    assert "有证据正面率" in md
    assert "2/4" in md   # 观测口径：(1+1)/(1+1+2)
    assert "1/2" in md   # 有证据口径：1/(1+1)


# ── 4. receptivity 延迟 ───────────────────────────────────────────────────────
def test_latency_percentiles_exclude_silence_and_pollution() -> None:
    outcomes = [
        orow("a", "accepted", D1, latency=10.0),
        orow("b", "accepted", D1, latency=20.0),
        orow("c", "rejected", D1, latency=30.0),
        orow("d", "responded", D1, latency=40.0),
        orow("s1", "ignored", D1, latency=180.0),     # 沉默：剔除
        orow("s2", "unanswered", D1, latency=362.0),  # 沉默：剔除
        orow("x", "rejected", D1, latency=1.79e9),    # 污染（实测 o-rej）：剔除计数
        orow("y", "accepted", D1, latency=None),      # 缺失：剔除计数
    ]
    out = rm.receptivity_latency(outcomes)
    assert out["n"] == 4
    assert out["by_class"] == {"negative": 1, "positive": 3}
    assert out["median_s"] == pytest.approx(20.0)
    assert out["p75_s"] == pytest.approx(30.0)
    assert out["p90_s"] == pytest.approx(40.0)
    assert out["excluded_silence_rows"] == 2
    assert out["excluded_invalid_latency_rows"] == 2
    assert "不能判断" in out["verdict"]  # n=4 <20


def test_latency_descriptive_with_20() -> None:
    outcomes = [orow(f"o{i}", "accepted", D1, latency=float(i + 1))
                for i in range(20)]
    out = rm.receptivity_latency(outcomes)
    assert out["n"] == 20
    assert "不能判断" not in out["verdict"]
    assert out["median_s"] == pytest.approx(10.0)   # ceil(.5*20)=10
    assert out["p90_s"] == pytest.approx(18.0)      # ceil(.9*20)=18


def test_latency_empty() -> None:
    out = rm.receptivity_latency([])
    assert out["n"] == 0 and out["median_s"] is None
    assert "不能判断" in out["verdict"]


# ── 5. 端到端：合成账本全绿 + JSON 可序列化 + 只读 ─────────────────────────────
def test_full_report_synthetic_all_sections(perceive: Path) -> None:
    # 20 个开口、间隔 1000s、全部 accepted 且 latency 10s
    write_rows(perceive, "offers.jsonl", [
        {"id": f"o{i}", "t": D1 + 1000 * i, "kind": "companion",
         "result": "shown"} for i in range(20)])
    write_rows(perceive, "outcomes.jsonl", [
        orow(f"o{i}", "accepted", D1 + 1000 * i + 10, latency=10.0)
        for i in range(20)])
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    assert rep["burstiness"]["n_openings"] == 20
    assert "不能判断" not in rep["burstiness"]["verdict"]
    assert "不能判断" not in rep["response_rates"]["verdict"]
    assert "不能判断" not in rep["receptivity_latency"]["verdict"]
    # 锚点仍缺失 → 必须继续显式不可算，即使其他指标已够样本
    assert rep["anchors"]["computable"] is False
    assert "不可算" in rep["anchors"]["verdict"]
    md = rm.render_markdown(rep)
    assert "## 2b. 离线四指标" in md
    json.dumps(rep, ensure_ascii=False)  # 全结构可序列化


def test_no_files_all_metrics_graceful(tmp_path: Path) -> None:
    rep = rm.summarize(tmp_path / "nope", timing_module=FakeTiming())
    assert rep["burstiness"]["n_openings"] == 0
    assert "不能判断" in rep["burstiness"]["verdict"]
    assert rep["anchors"]["computable"] is False
    assert rep["response_rates"]["observed_response_rate"]["rate"] is None
    assert rep["receptivity_latency"]["n"] == 0
    assert rm.render_markdown(rep)
    json.dumps(rep, ensure_ascii=False)


def test_metrics_are_read_only(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl",
               [orow(f"o{i}", "ignored", D1 + i, latency=180.0)
                for i in range(3)])
    before = {p.name: (p.stat().st_size, p.read_bytes())
              for p in perceive.iterdir() if p.is_file()}
    rep = rm.summarize(perceive, timing_module=FakeTiming())
    rm.render_markdown(rep)
    after = {p.name: (p.stat().st_size, p.read_bytes())
             for p in perceive.iterdir() if p.is_file()}
    assert before == after
