"""回归门：学习信号的标签纪律 —— 沉默不是负例，观测不到有用不能让门槛变松。

真实事故（10-12）：
  * live.py 的 on_expire 对**所有**超时气泡一律记 "ignored"（包括从没给过选项的
    companion/say）；
  * timing.py 的 _NEGATIVE 又包含 "ignored"。
于是每 3 分钟一句 companion 只要没人打字就攒一个"负样本"：负例攒满 20 条 →
Wilson 下界 0 → 旧 learned_benefit_s 返回 benefit=300s → p* = 39/300 = 0.13，
比"证据不足"时的 39/60 = 0.65 松了 5 倍 —— **越没人理越爱开口**。

本文件钉住三件事：
  1. 没给过选项的气泡超时记 "unanswered"，不得成为负样本；只有真把选项摆出来才算 ignored。
  2. 观测正例为 0 时 stop_threshold 不得低于"证据不足"（出厂先验）时的值。
  3. on_expire 真的走了 expiry_outcome（只测 expiry_outcome 本身挡不住调用点被改回去）。

把 live.py 的 expiry_outcome/on_expire 或 timing.py 的 _NEGATIVE 改回旧写法，
下面 test_twenty_unanswered_rows_are_not_negative_evidence 等用例都会失败。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from sprite.proactive import live, timing


def _ledger(tmp_path: Path, outcomes: list[str]) -> Path:
    """造一份 outcomes.jsonl 账本（与三态落库同一格式）。"""
    path = tmp_path / "outcomes.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for i, outcome in enumerate(outcomes):
            handle.write(json.dumps({"id": f"o{i}", "t": float(i), "kind": "companion",
                                     "app": "notepad", "outcome": outcome},
                                    ensure_ascii=False) + "\n")
    return path


def _evidence_counts(path: Path) -> tuple[int, int, int]:
    positives = negatives = silent = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        outcome = str(json.loads(raw).get("outcome") or "")
        positives += outcome in timing._POSITIVE
        negatives += outcome in timing._NEGATIVE
        silent += outcome in timing._NO_EVIDENCE
    return positives, negatives, silent


# ---------- 1. 超时该记什么：只有真给过选项才算“明确的不要” ----------

def test_companion_bubble_timeout_is_unanswered_not_ignored():
    assert live.expiry_outcome({"kind": "companion", "text": "读挺久了，歇会儿吧"}) == "unanswered"


def test_say_bubble_timeout_is_unanswered():
    assert live.expiry_outcome({"kind": "say", "text": "我已经开始处理桌面整理，完成后告诉你。"}) == "unanswered"


def test_offer_with_shown_options_timeout_is_ignored():
    assert live.expiry_outcome({"kind": "offer", "text": "要我清一下吗？",
                               "options": ["清一下", "先不用"]}) == "ignored"


def test_offer_without_shown_options_is_not_a_rejection():
    # help.check_once / session._companion 写 offer 时都不带 options：选项从没摆到他面前，
    # 超时不能记成“他拒绝了”。
    assert live.expiry_outcome({"kind": "offer", "text": "C 盘快满了", "options": []}) == "unanswered"
    assert live.expiry_outcome({"kind": "offer", "text": "C 盘快满了"}) == "unanswered"


def test_expiry_outcome_survives_missing_offer():
    assert live.expiry_outcome(None) == "unanswered"


def test_on_expire_actually_uses_expiry_outcome():
    """调用点也要钉住：on_expire 是 Tkinter 回调闭包，无头环境里没法直接调，只能看源码。"""
    assert "expiry_outcome" in inspect.getsource(live.run_gui)


def test_timing_vocabulary_treats_silence_as_no_evidence():
    assert timing._NEGATIVE == {"rejected"}
    assert "ignored" not in timing._NEGATIVE
    assert "unanswered" not in timing._POSITIVE
    assert "unanswered" not in timing._NEGATIVE
    assert {"ignored", "unanswered"} <= timing._NO_EVIDENCE


# ---------- 2. 20 句 companion 超时不得变成 20 个负样本 ----------

def test_twenty_unanswered_rows_are_not_negative_evidence(tmp_path):
    label = live.expiry_outcome({"kind": "companion", "text": "读挺久了，歇会儿吧"})
    path = _ledger(tmp_path, [label] * 20)
    positives, negatives, silent = _evidence_counts(path)
    assert (positives, negatives) == (0, 0), "沉默被当成了负样本"
    assert silent == 20
    benefit, why = timing.learned_benefit_s(path)
    assert benefit == timing.BENEFIT_S, why           # 退回出厂先验：不收紧、也不放松
    assert "证据不足" in why
    assert "无证据" in why


def test_five_positives_in_twenty_row_ledger_is_still_not_enough(tmp_path):
    # 10-12 的真实账本：5 条 accepted + 15 条 companion 超时。旧代码把超时当负例，于是
    # total=20、positives=5 就“学”出了 300s（比先验还松）；正确读法是可判定样本只有 5 条。
    path = _ledger(tmp_path, ["accepted"] * 5 + ["ignored"] * 15)
    benefit, why = timing.learned_benefit_s(path)
    assert benefit == timing.BENEFIT_S, why
    assert "证据不足" in why


# ---------- 3. 观测不到有用：门槛只许更紧，不许更松 ----------

def test_zero_positives_never_loosens_the_threshold(tmp_path):
    factory = timing.stop_threshold("notepad", benefit_s=timing.BENEFIT_S)   # 39/60
    assert factory == pytest.approx(0.65, abs=1e-9)

    # (a) 明确的负证据：20 条 rejected → 取保守端，p* 顶到上限
    benefit, why = timing.learned_benefit_s(_ledger(tmp_path, ["rejected"] * 20))
    assert benefit == timing.BENEFIT_MIN_S, why
    assert timing.stop_threshold("notepad", benefit_s=benefit) >= factory
    assert (timing.stop_threshold("tabbit", benefit_s=benefit)
            >= timing.stop_threshold("tabbit", benefit_s=timing.BENEFIT_S))

    # (b) 只有沉默/无证据：退回出厂先验，同样不得放松
    benefit, why = timing.learned_benefit_s(_ledger(tmp_path, ["ignored"] * 20))
    assert benefit == timing.BENEFIT_S, why
    assert "证据不足" in why
    assert timing.stop_threshold("notepad", benefit_s=benefit) >= factory


def test_enough_positive_evidence_still_calibrates(tmp_path):
    benefit, why = timing.learned_benefit_s(_ledger(tmp_path, ["accepted"] * 18 + ["rejected"] * 2))
    assert timing.BENEFIT_MIN_S <= benefit <= timing.BENEFIT_MAX_S
    assert "由 r_t 校准" in why
    assert "Wilson 下界" in why


def test_passing_the_calibrated_benefit_explicitly_changes_nothing():
    """observe() 现在显式传 benefit_now() 的收益；这条钉住“传与不传同一个值，结果相同”。"""
    auto = timing.stop_threshold("notepad")
    explicit = timing.stop_threshold("notepad", benefit_s=timing.benefit_now()[0])
    assert auto == explicit
