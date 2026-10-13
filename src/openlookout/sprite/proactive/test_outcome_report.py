"""outcome_report 的测试：口径纪律比功能多。

被钉住的四件事（都来自真实事故）：
1. 全是 ignored 时**不能**算出任何「有效率」——沉默是无证据，不是拒绝；
2. 正面/负面混合时，「有证据分母」与「把沉默算进分母」必须是两个不同的数；
3. 未知/新 outcome 字符串（T1 的 ``unanswered``、以及任何别的）必须被计数并单列，
   不得静默丢弃，也不得混进任何分子/分母；
4. 文件缺失/为空/坏行都要优雅降级，且**绝不写入** perceive/。

另外钉住：校准状态在 timing 不可用时降级为「校准状态未知」而不是崩。
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

import sprite.proactive.outcome_report as reportmod


D1 = datetime(2026, 10, 10, 12, 0, 0).timestamp()
D2 = D1 + 86400.0


# ── 夹具 ────────────────────────────────────────────────────────────────────
class FakeTiming:
    """一个可控的 timing 替身：不读真实账本，不保温。"""

    OUTCOMES_PATH = Path("/nonexistent/outcomes.jsonl")
    _POSITIVE = {"accepted", "responded"}
    _NEGATIVE = {"ignored", "rejected"}      # 模拟 timing 把沉默当负面证据的旧口径
    MIN_OUTCOMES = 20

    def __init__(self, why: str | None = None, boom: bool = False) -> None:
        self._why = why if why is not None else (
            "真实结果行只有 5 条（<20），证据不足，仍用出厂先验 60s——这不是学出来的")
        self._boom = boom

    def benefit_now(self):
        if self._boom:
            raise RuntimeError("boom")
        return 60.0, self._why

    def stop_threshold(self, app, *, benefit_s=None):
        if self._boom:
            raise RuntimeError("boom")
        return 0.39


def write_rows(directory: Path, name: str, rows: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def outcome_row(i: int, outcome: str, *, t: float, kind: str = "companion",
                latency: float | None = 180.4, text: str = "…", **extra) -> dict:
    row = {"id": f"o{i}", "t": t, "outcome": outcome, "latency_s": latency,
           "kind": kind, "topic": "", "text": text}
    row.update(extra)
    return row


@pytest.fixture()
def perceive(tmp_path: Path) -> Path:
    d = tmp_path / "perceive"
    d.mkdir()
    return d


# ── 1. 全是 ignored ─────────────────────────────────────────────────────────
def test_all_ignored_yields_no_evidence_and_no_rate(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl",
               [outcome_row(i, "ignored", t=D1 + i) for i in range(5)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())

    ev = rep["evidence"]
    assert rep["total"] == 5
    assert ev["silence"] == 5
    assert ev["evidence_n"] == 0
    # 没有证据就没有「接受率」这种东西
    assert ev["positive_rate_evidence_only"] is None
    assert ev["denominator_evidence_only"] == 0
    # 误导口径确实存在，值也确实是 0/5 —— 报告必须把它点名而不是藏起来
    assert ev["positive_rate_including_silence"] == 0.0
    assert ev["denominator_including_silence"] == 5

    md = reportmod.render_markdown(rep)
    assert "无回应不等于拒绝" in md
    assert "误导" in md
    assert "不能" in rep["conclusion"]


def test_all_ignored_trend_is_insufficient(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl",
               [outcome_row(i, "ignored", t=D1 + i) for i in range(5)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["trend"]["verdict"] == "样本不足"
    assert "不画趋势" in rep["trend"]["reason"]
    assert "不画趋势" in reportmod.render_markdown(rep)


def test_silence_is_not_counted_as_negative(perceive: Path) -> None:
    """ignored 绝不能进负面证据——这是本模块存在的理由。"""
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["evidence"]["negative"] == 0
    assert rep["classes"]["silence"] == 1


# ── 2. 正负混合 ─────────────────────────────────────────────────────────────
def test_mixed_evidence_separates_the_two_denominators(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [
        outcome_row(1, "accepted", t=D1 + 1),
        outcome_row(2, "responded", t=D1 + 2),
        outcome_row(3, "rejected", t=D1 + 3),
        outcome_row(4, "ignored", t=D1 + 4),
    ])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    ev = rep["evidence"]
    assert ev["positive"] == 2 and ev["negative"] == 1 and ev["silence"] == 1
    assert ev["evidence_n"] == 3
    assert ev["positive_rate_evidence_only"] == pytest.approx(2 / 3)
    assert ev["positive_rate_including_silence"] == pytest.approx(2 / 4)
    assert ev["positive_rate_evidence_only"] != ev["positive_rate_including_silence"]
    md = reportmod.render_markdown(rep)
    assert "接受率（有证据口径）" in md
    assert "2 / 3" in md


# ── 3. 未知 / 新标签 ────────────────────────────────────────────────────────
def test_unknown_label_is_counted_and_listed(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [
        outcome_row(1, "accepted", t=D1),
        outcome_row(2, "gibberish_new_value", t=D1 + 1),
    ])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["unknown_labels"] == {"gibberish_new_value": 1}
    # 未知既不进正面也不进负面，也不掉进沉默
    assert rep["evidence"]["positive"] == 1
    assert rep["evidence"]["negative"] == 0
    assert rep["evidence"]["silence"] == 0
    assert rep["classes"]["unknown"] == 1
    assert "gibberish_new_value" in reportmod.render_markdown(rep)
    # 总数守恒：没有任何一行被静默丢弃
    assert rep["total"] == sum(rep["classes"].values())


def test_new_unanswered_value_is_treated_as_silence(perceive: Path) -> None:
    """T1 会引入 unanswered：它必须算沉默，不能算负面，也不能算未知。"""
    write_rows(perceive, "outcomes.jsonl",
               [outcome_row(1, "unanswered", t=D1),
                outcome_row(2, "UNANSWERED", t=D1 + 1)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["evidence"]["silence"] == 2
    assert rep["evidence"]["negative"] == 0
    assert rep["classes"]["unknown"] == 0
    assert rep["unknown_labels"] == {}


def test_empty_outcome_value_is_unknown_not_dropped(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [
        {"id": "o1", "t": D1, "kind": "companion"},
        {"id": "o2", "t": D1 + 1, "outcome": "", "kind": "companion"},
    ])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["total"] == 2
    assert rep["unknown_labels"] == {"(空)": 2}


# ── 4. 空 / 缺失 / 坏行 ─────────────────────────────────────────────────────
def test_all_files_missing_is_graceful(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    rep = reportmod.summarize(missing, timing_module=FakeTiming())
    assert rep["total"] == 0
    assert all(not info["exists"] for info in rep["files"].values())
    assert rep["conclusion"].startswith("不能")
    assert reportmod.render_markdown(rep)          # 渲染不崩
    json.dumps(rep, ensure_ascii=False)            # JSON 可序列化


def test_empty_and_malformed_files_are_graceful(perceive: Path) -> None:
    (perceive / "outcomes.jsonl").write_text("", encoding="utf-8")
    (perceive / "offers.jsonl").write_text(
        "不是 json\n" + json.dumps({"id": "o1", "t": D1, "kind": "offer"}) + "\n",
        encoding="utf-8")
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["total"] == 0
    assert rep["files"]["offers.jsonl"]["rows"] == 1
    assert rep["files"]["offers.jsonl"]["malformed"] == 1


def test_read_jsonl_missing_file_returns_empty(tmp_path: Path) -> None:
    rows, bad = reportmod.read_jsonl(tmp_path / "nope.jsonl")
    assert rows == [] and bad == 0


# ── 5. 按 kind 分列 ─────────────────────────────────────────────────────────
def test_buckets_split_companion_options_and_other(perceive: Path) -> None:
    write_rows(perceive, "offers.jsonl", [
        {"id": "o1", "t": D1, "kind": "offer", "options": ["清一下", "不用"], "result": "shown"},
        {"id": "o2", "t": D1, "kind": "offer", "result": "shown"},          # 无选项 → other
    ])
    write_rows(perceive, "outcomes.jsonl", [
        outcome_row(1, "accepted", t=D1, kind="companion"),
        outcome_row(2, "accepted", t=D1, kind="offer", id="o1"),   # 对上 offers.jsonl 的 o1
        outcome_row(3, "ignored", t=D1, kind="offer"),
        outcome_row(4, "ignored", t=D1, kind=""),                            # 缺 kind → other
        outcome_row(5, "ignored", t=D1, kind="什么鬼"),                       # 未知 kind → other
    ])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    buckets = rep["buckets"]
    assert buckets["companion"]["n"] == 1
    assert buckets["offer_with_options"]["n"] == 1
    assert buckets["offer_with_options"]["classes"]["positive"] == 1
    assert buckets["other"]["n"] == 3
    assert buckets["other"]["raw_kinds"] == {"(缺失)": 1, "offer": 1, "什么鬼": 1}
    assert sum(b["n"] for b in buckets.values()) == rep["total"]


# ── 6. 按天趋势 ─────────────────────────────────────────────────────────────
def test_trend_insufficient_when_only_one_day(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl",
               [outcome_row(i, "accepted", t=D1 + i) for i in range(3)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["trend"]["verdict"] == "样本不足"
    assert "只有 1 天" in rep["trend"]["reason"]


def test_trend_insufficient_when_daily_sample_thin(perceive: Path) -> None:
    rows = [outcome_row(i, "accepted", t=D1 + i) for i in range(2)]
    rows += [outcome_row(10 + i, "accepted", t=D2 + i) for i in range(2)]
    write_rows(perceive, "outcomes.jsonl", rows)
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert rep["trend"]["verdict"] == "样本不足"
    assert "单日结果" in rep["trend"]["reason"]


def test_trend_gives_verdict_only_with_enough_evidence(perceive: Path) -> None:
    rows = [outcome_row(i, "accepted", t=D1 + i) for i in range(5)]
    rows += [outcome_row(20 + i, "rejected", t=D2 + i) for i in range(5)]
    write_rows(perceive, "outcomes.jsonl", rows)
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    assert not str(rep["trend"]["verdict"]).startswith("样本不足")
    assert rep["trend"]["first_rate"] == pytest.approx(1.0)
    assert rep["trend"]["last_rate"] == pytest.approx(0.0)


# ── 7. 沉默明细 / 交叉核对 ──────────────────────────────────────────────────
def test_silence_details_flag_bubble_timeout(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [
        outcome_row(1, "ignored", t=D1, latency=181.3, text="清了 Temp：C 盘 1.96G→3.04G"),
        outcome_row(2, "ignored", t=D1 + 1, latency=30.0, text="短静默"),
    ])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    details = rep["silence_details"]
    assert [d["suspected_timeout"] for d in details] == [True, False]
    md = reportmod.render_markdown(rep)
    assert "清了 Temp" in md


def test_late_user_reply_after_silence_is_surfaced(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl",
               [outcome_row(1, "ignored", t=D1, latency=180.0)])
    write_rows(perceive, "conversation.jsonl",
               [{"t": D1 + 120, "role": "user", "text": "好，谢谢", "kind": "message"}])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    late = rep["conversation"]["late_user_replies"]
    assert len(late) == 1
    assert late[0]["outcome_class"] == "silence"
    assert "谢谢" in reportmod.render_markdown(rep)


# ── 8. 校准状态（timing 弱依赖）─────────────────────────────────────────────
def test_calibration_records_why_and_mismatch(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    calib = rep["calibration"]
    assert calib["available"] is True
    assert calib["benefit_s"] == 60.0
    assert "证据不足" in calib["benefit_why"]
    assert calib["why_says_insufficient"] is True
    assert calib["insufficient"] is True
    # timing 自己的旧口径把 ignored 当负面证据 → 报告必须点名
    assert "ignored" in calib["timing_vocabulary"]["negative"]
    assert "ignored" not in reportmod.NEGATIVE
    md = reportmod.render_markdown(rep)
    assert "证据不足" in md
    assert "把 `ignored`（沉默）也算作负面证据" in md


def test_calibration_marks_insufficient_from_our_own_evidence(perceive: Path) -> None:
    """即使 why 不说证据不足，只要我们自己有证据的开口 <20，也得标证据不足。"""
    write_rows(perceive, "outcomes.jsonl", [
        outcome_row(1, "accepted", t=D1), outcome_row(2, "rejected", t=D1 + 1)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming(why="由 r_t 校准：1/2 正面"))
    assert rep["calibration"]["why_says_insufficient"] is False
    assert rep["calibration"]["insufficient"] is True
    assert "有明确证据的开口只有 2 条" in rep["calibration"]["insufficient_reason"]


def test_calibration_survives_broken_timing(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    rep = reportmod.summarize(perceive, timing_module=FakeTiming(boom=True))
    calib = rep["calibration"]
    assert calib["available"] is True
    assert calib["benefit_why"] is None
    assert "RuntimeError" in calib["benefit_error"]
    assert calib["p_star"] is None
    assert "RuntimeError" in calib["p_star_error"]
    assert reportmod.render_markdown(rep)


@pytest.fixture()
def timing_blocked(monkeypatch):
    """让 ``from . import timing`` **真的**拿不到 —— 与 collection 顺序无关。

    只把 ``sys.modules["sprite.proactive.timing"]`` 设成 ``None`` 是**挡不住**的：
    ``outcome_report.py:220`` 的 ``from . import timing`` 先走父包属性
    ``getattr(sprite.proactive, "timing")``，只要进程里任何一方 import 过这个子模块
    （T1 的 ``test_outcome_labels.py``、生产路径 ``vista/benchmarks/desktop/brain.py``），
    父包属性就被永久绑定，毒化随即失效——测试的红绿于是变成 collection 顺序的函数
    （T6 的根因）。所以这里**两处一起清**，并交给 monkeypatch 在用例结束后原样还原
    （父包属性存在则回填、不存在则不动；sys.modules 同理），保证可重入。

    这也正是选「修测试隔离」而不是改 ``outcome_report.py`` 的理由：坏的只是
    「我模拟不可用」的手法，产线的取用路径本身没缺陷，生产文件因此零改动。
    """
    parent = importlib.import_module("sprite.proactive")
    monkeypatch.setitem(sys.modules, "sprite.proactive.timing", None)
    monkeypatch.delattr(parent, "timing", raising=False)
    return parent


def test_calibration_degrades_when_timing_unimportable(perceive: Path,
                                                       timing_blocked) -> None:
    """sprite.proactive.timing 拿不到 → 「校准状态未知」，不崩。

    （signal-fixer 在并行改 timing.py；导入失败必须只是降级。）
    本用例刻意**不**依赖「timing 有没有被别处 import 过」：
    无论父包属性在不在、sys.modules 里原先有没有真模块，都必须降级。
    """
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    rep = reportmod.summarize(perceive)
    assert rep["calibration"]["available"] is False
    assert rep["calibration"]["status"] == "校准状态未知"
    assert "降级" in rep["calibration"]["reason"]
    assert "校准状态未知" in reportmod.render_markdown(rep)
    # 报告主体（分母纪律）不因 timing 不可用而失效
    assert rep["conclusion"].startswith("不能")


# ── 9. 只读纪律 + CLI ───────────────────────────────────────────────────────
def _snapshot(directory: Path) -> dict:
    return {p.name: (p.stat().st_size, p.read_bytes())
            for p in directory.iterdir() if p.is_file()}


def test_never_writes_into_perceive(perceive: Path) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    write_rows(perceive, "offers.jsonl", [{"id": "o1", "t": D1, "kind": "companion"}])
    before = _snapshot(perceive)
    rep = reportmod.summarize(perceive, timing_module=FakeTiming())
    reportmod.render_markdown(rep)
    assert _snapshot(perceive) == before
    assert sorted(p.name for p in perceive.iterdir()) == sorted(before)


def test_cli_writes_report_only_to_given_path(perceive: Path, tmp_path: Path,
                                             capsys) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    before = _snapshot(perceive)
    out = tmp_path / "reports" / "outcome.md"
    rc = reportmod.main(["--perceive", str(perceive), "--report", str(out)])
    assert rc == 0
    assert out.exists()
    assert "# 开口质量度量" in out.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert "无回应不等于拒绝" in captured.out
    assert _snapshot(perceive) == before


def test_cli_refuses_to_write_inside_perceive(perceive: Path, capsys) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    target = perceive / "evil.md"
    rc = reportmod.main(["--perceive", str(perceive), "--report", str(target)])
    assert rc == 2
    assert not target.exists()
    assert "拒绝写入 perceive/" in capsys.readouterr().err


def test_cli_json_is_machine_readable(perceive: Path, capsys) -> None:
    write_rows(perceive, "outcomes.jsonl", [outcome_row(1, "ignored", t=D1)])
    rc = reportmod.main(["--perceive", str(perceive), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out[:out.rindex("}") + 1])
    assert payload["evidence"]["evidence_n"] == 0
    assert payload["unknown_labels"] == {}


def test_cli_defaults_to_missing_dir_without_crash(tmp_path: Path, capsys) -> None:
    rc = reportmod.main(["--perceive", str(tmp_path / "nope")])
    assert rc == 0
    assert "不能" in capsys.readouterr().out


# ── 10. 隔离可重入（T6：毒化不得泄漏给后续用例）─────────────────────────────
_MISSING = object()


def test_timing_poison_does_not_leak(perceive: Path) -> None:
    """``timing_blocked`` 用过的毒化必须已被 monkeypatch 原样还原。

    放在文件最后：上面的 CLI 用例已经真实 import 过 timing，
    所以这两条断言在「单独跑本文件」与「全量跑」两种情况下都不空转。

    判据：
      * sys.modules 里不能残留毒值 ``None``（``setitem`` 泄漏）；
      * 父包属性与 sys.modules 必须一致——有真模块 ⇔ 有属性，
        只还原一边就是泄漏（``delattr`` 泄漏会表现为 entry 真而属性缺）。
    """
    parent = importlib.import_module("sprite.proactive")
    entry = sys.modules.get("sprite.proactive.timing", _MISSING)
    assert entry is not None, "sys.modules 里残留了毒值 None（fixture 未还原）"
    assert hasattr(parent, "timing") == (entry is not _MISSING), (
        "父包属性与 sys.modules 不一致：毒化只还原了一边")
