"""隐性教练账本（issue #18）测试。

三层：
1. coach.py 纯函数：四态迁移、7 天过期、>=2 实例阈值、outcomes 回流、
   GUIDE.md 围栏块解析/渲染/剥离/合并（含模型全量覆盖后块不丢）。
2. 红线：决策夹具证明无锚点 / 已 spoken/cooldown / 流中三种情形不产生
   coach 开口路径（提示词路径 surface_note 为空，或状态不迁移）。
3. brain 薄接线：sync_coach 决策/outcome 回流，save/restore_guide 在模型
   全量 write_guide 后仍保住围栏块；profiles 身份段关键约束字符串钉死。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from vista.benchmarks.desktop import brain, coach, profiles

NOW = 1_790_000_000.0          # 固定时钟；任意未来时刻均可
DAY = 86400.0
PID = "manual-ctx"


def _quiet(pid: str, anchor: str, *, t: float = NOW, adopt: bool = False) -> dict:
    return {"kind": "quiet", "topic": ("coach^" if adopt else "coach:") + pid,
            "t": t, "state": anchor, "activity": "",
            "next_step": {"status": "waiting", "evidence": ""}}


def _speak(pid: str, say: str = "要我把这句改成一轮就对的版本吗", *, t: float = NOW) -> dict:
    return {"kind": "companion", "topic": "coach:" + pid, "t": t, "say": say,
            "state": "刚才那三轮，第一轮就差这条报错", "activity": "他在提问"}


def _outcome(event_id: str, pid: str, result: str, *, t: float = NOW + 60) -> dict:
    return {"id": event_id, "t": t, "outcome": result, "kind": "companion",
            "topic": "coach:" + pid, "text": "..."}


# ────────────────────────────────────────────────────────────────────
# 1. 阈值 / 实例
# ────────────────────────────────────────────────────────────────────
def test_empty_ledger_cannot_speak():
    ledger = coach.new_ledger()
    ok, reason = coach.can_speak(ledger, "anything", NOW)
    assert not ok and reason == "unknown_pattern"
    assert coach.eligible_patterns(ledger, NOW) == []


def test_single_instance_is_below_threshold():
    ledger = coach.new_ledger()
    assert coach.add_instance(ledger, PID, NOW, "第一次提问只贴了半句报错")
    ok, reason = coach.can_speak(ledger, PID, NOW)
    assert not ok and reason == "below_threshold"
    assert coach.eligible_patterns(ledger, NOW) == []


def test_two_fresh_instances_unlock_one_speaking_opportunity():
    ledger = coach.new_ledger()
    coach.add_instance(ledger, PID, NOW - DAY, "第一次提问只贴半句报错")
    coach.add_instance(ledger, PID, NOW, "又把同一段报错贴了两遍才补上下文")
    assert coach.can_speak(ledger, PID, NOW) == (True, "eligible")
    assert [pid for pid, _ in coach.eligible_patterns(ledger, NOW)] == [PID]
    assert coach.mark_spoken(ledger, PID, NOW, note="示范一轮就对的问法")
    assert ledger["patterns"][PID]["state"] == coach.SPOKEN
    # 开口一次之后资格立即消失——等结果，不重说。
    assert coach.can_speak(ledger, PID, NOW)[1] == "already_spoken"
    assert not coach.mark_spoken(ledger, PID, NOW + 10)


def test_instance_without_anchor_is_rejected():
    ledger = coach.new_ledger()
    assert not coach.add_instance(ledger, PID, NOW, "   ")
    assert not coach.add_instance(ledger, PID, NOW, "\n\t ")
    assert PID not in ledger["patterns"]


def test_invalid_ids_are_rejected_even_from_the_model():
    ledger = coach.new_ledger()
    for bad in ("", "UPPER", "-leading", "x" * 19, "a/b", "中文id", "coach:x"):
        assert not coach.valid_id(bad), bad
        assert not coach.add_instance(ledger, bad, NOW, "锚点")
    assert coach.valid_id("save_tpl-2")
    # coach: 前缀 6 字符 + 18 字符 id 恰好等于 schema topic maxLength=24。
    assert len("coach:" + "a" * 18) == 24


def test_instances_are_capped_newest_kept():
    ledger = coach.new_ledger()
    for i in range(coach.MAX_INSTANCES_KEPT + 5):
        coach.add_instance(ledger, PID, NOW + i, f"锚点{i}")
    pattern = ledger["patterns"][PID]
    assert len(pattern["instances"]) == coach.MAX_INSTANCES_KEPT
    assert pattern["instances"][-1]["anchor"] == f"锚点{coach.MAX_INSTANCES_KEPT + 4}"


# ────────────────────────────────────────────────────────────────────
# 2. 7 天过期与淡忘
# ────────────────────────────────────────────────────────────────────
def test_instances_older_than_seven_days_expire():
    ledger = coach.new_ledger()
    coach.add_instance(ledger, PID, NOW - 8 * DAY, "很久以前的一次摩擦")
    coach.add_instance(ledger, PID, NOW - 6 * DAY, "窗口内的一次摩擦")
    coach.prune(ledger, NOW)
    instances = coach.fresh_instances(ledger["patterns"][PID], NOW)
    assert len(instances) == 1
    assert "窗口内" in instances[0]["anchor"]
    assert coach.can_speak(ledger, PID, NOW)[1] == "below_threshold"


def test_one_off_friction_is_forgotten_entirely():
    ledger = coach.new_ledger()
    coach.add_instance(ledger, PID, NOW - 8 * DAY, "一次性摩擦，没攒起来")
    coach.prune(ledger, NOW)
    assert PID not in ledger["patterns"]


def test_concluded_patterns_survive_expiry_without_instances():
    ledger = coach.new_ledger()
    coach.add_instance(ledger, PID, NOW - 2 * DAY, "a")
    coach.add_instance(ledger, PID, NOW - 2 * DAY + 1, "b")
    coach.mark_spoken(ledger, PID, NOW - 2 * DAY + 2, note="说过")
    coach.cooldown(ledger, PID, NOW - 2 * DAY + 3, note="他没接")
    coach.prune(ledger, NOW + 30 * DAY)
    pattern = ledger["patterns"][PID]
    assert pattern["state"] == coach.COOLDOWN and pattern["instances"] == []
    coach.add_instance(ledger, "adopted-one", NOW - 30 * DAY, "早会了")
    coach.retire(ledger, "adopted-one", NOW - 29 * DAY, note="观察到他自己在用")
    coach.prune(ledger, NOW)
    assert ledger["patterns"]["adopted-one"]["state"] == coach.RETIRED


# ────────────────────────────────────────────────────────────────────
# 3. 四态迁移（含合法边表）
# ────────────────────────────────────────────────────────────────────
def _ripe(ledger, pid: str = PID, *, now: float = NOW) -> None:
    coach.add_instance(ledger, pid, now - DAY, "第一次")
    coach.add_instance(ledger, pid, now - 10, "第二次，带锚点")


def test_spoken_to_retired_on_acceptance():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW, note="示范")
    assert coach.retire(ledger, PID, NOW + 30, "用户采纳")
    assert ledger["patterns"][PID]["state"] == coach.RETIRED
    assert not coach.add_instance(ledger, PID, NOW + 31, "再观察也不复活")
    assert coach.can_speak(ledger, PID, NOW + 31)[1] == "retired"


def test_spoken_to_cooldown_clears_instances_and_mutes_forever():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW, note="示范")
    assert coach.cooldown(ledger, PID, NOW + 90, "超时无回应")
    pattern = ledger["patterns"][PID]
    assert pattern["state"] == coach.COOLDOWN and pattern["instances"] == []
    assert pattern["spoken_at"]  # 开口史不抹掉，这是永禁重说的依据
    # 新摩擦重新攒：状态回到 observing，但开口资格永远不恢复（冷却史不抹）。
    coach.add_instance(ledger, PID, NOW + 100, "又发生一次")
    coach.add_instance(ledger, PID, NOW + 101, "再发生一次")
    ok, reason = coach.can_speak(ledger, PID, NOW + 102)
    assert not ok and reason == "muted_after_cooldown"


def test_observing_can_retire_directly_when_user_already_does_it():
    ledger = coach.new_ledger()
    coach.add_instance(ledger, PID, NOW, "刚注意到他其实一直这样做")
    assert coach.retire(ledger, PID, NOW, "观察到用户已自改用同法")
    assert ledger["patterns"][PID]["state"] == coach.RETIRED


def test_illegal_transitions_raise():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW)
    with pytest.raises(ValueError):
        coach.transition(ledger, PID, coach.OBSERVING, NOW)      # spoken -> observing
    with pytest.raises(ValueError):
        coach.transition(ledger, PID, "nonsense", NOW)
    with pytest.raises(ValueError):
        coach.transition(ledger, "missing", coach.RETIRED, NOW)
    # 同态幂等
    assert coach.transition(ledger, PID, coach.SPOKEN, NOW)
    # 未攒够不许 observing -> spoken
    fresh = coach.new_ledger()
    coach.add_instance(fresh, "only-one", NOW, "一次")
    with pytest.raises(ValueError):
        coach.transition(fresh, "only-one", coach.SPOKEN, NOW)
    # cooldown 只能来自 spoken
    with pytest.raises(ValueError):
        coach.transition(fresh, "only-one", coach.COOLDOWN, NOW)


def test_retired_is_terminal_idempotent():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW)
    coach.retire(ledger, PID, NOW + 1)
    assert coach.retire(ledger, PID, NOW + 2)        # 重复退休不报错
    assert not coach.cooldown(ledger, PID, NOW + 3)  # 终态不可转冷却


# ────────────────────────────────────────────────────────────────────
# 4. outcomes.jsonl 回流
# ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("result,expected", [
    ("accepted", coach.RETIRED),
    ("rejected", coach.COOLDOWN),
    ("ignored", coach.COOLDOWN),       # 选项摆出却超时没选＝明确不要
    ("unanswered", coach.COOLDOWN),    # 没给选项的气泡超时＝超时无回应
])
def test_outcomes_drive_terminal_transitions(result, expected):
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW, note="示范")
    state = coach.apply_outcome(ledger, event_id="e1", topic="coach:" + PID,
                                outcome=result, now=NOW + 60)
    assert state == expected
    assert ledger["patterns"][PID]["state"] == expected


def test_ambiguous_outcomes_keep_pattern_spoken():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW)
    for result in ("acknowledged", "responded"):
        ledger["patterns"][PID]["state"] = coach.SPOKEN
        state = coach.apply_outcome(ledger, event_id=result, topic="coach:" + PID,
                                    outcome=result, now=NOW + 60)
        assert state == coach.SPOKEN


def test_outcome_is_applied_once_and_skips_non_coach_topics():
    ledger = coach.new_ledger()
    _ripe(ledger)
    coach.mark_spoken(ledger, PID, NOW)
    assert coach.apply_outcome(ledger, event_id="e1", topic="weather",
                               outcome="accepted", now=NOW) is None
    assert coach.apply_outcome(ledger, event_id="e1", topic="coach:" + PID,
                               outcome="accepted", now=NOW) == coach.RETIRED
    # 重放同一 id：已是 retired，不再产生迁移记录
    assert coach.apply_outcome(ledger, event_id="e1", topic="coach:" + PID,
                               outcome="accepted", now=NOW) is None
    assert ledger["seen_outcomes"].count("e1") == 1


def test_outcome_for_unknown_pattern_does_not_fabricate_one():
    ledger = coach.new_ledger()
    assert coach.apply_outcome(ledger, event_id="e9", topic="coach:ghost",
                               outcome="rejected", now=NOW) is None
    assert "ghost" not in ledger["patterns"]
    assert "e9" in ledger["seen_outcomes"]


# ────────────────────────────────────────────────────────────────────
# 5. topic 约定 / 决策夹具 / 红线
# ────────────────────────────────────────────────────────────────────
def test_parse_topic_convention():
    assert coach.parse_topic("coach:manual-ctx", "quiet") == ("observe", "manual-ctx")
    assert coach.parse_topic("coach:manual-ctx", "companion") == ("speak", "manual-ctx")
    assert coach.parse_topic("coach:manual-ctx", "offer") == ("speak", "manual-ctx")
    assert coach.parse_topic("coach^manual-ctx", "quiet") == ("adopt", "manual-ctx")
    for topic, kind in [("coach:manual-ctx", "weird"),
                        ("coach^manual-ctx", "companion"),   # 退休信号只许 quiet
                        ("coach:UPPER", "quiet"),
                        ("weather", "companion"),
                        ("coach:", "quiet")]:
        assert coach.parse_topic(topic, kind) is None


def test_decision_anchor_precedence():
    d = {"state": "刚保存的文件报错",
         "next_step": {"evidence": "证据文本"}, "activity": "活动"}
    assert coach.decision_anchor(d) == "刚保存的文件报错"
    d["state"] = "  "
    assert coach.decision_anchor(d) == "证据文本"
    assert coach.decision_anchor({"state": "", "activity": "活动"}) == "活动"
    assert coach.decision_anchor({}) == ""


def test_red_line_no_anchor_creates_no_speaking_path():
    """红线①：无锚点——实例进不了账本，开口撞 unknown_pattern，状态不迁移。"""
    ledger = coach.new_ledger()
    blocked = coach.apply_decisions(
        ledger,
        [{"kind": "quiet", "topic": "coach:" + PID, "t": NOW, "state": "   "},
         _speak(PID)],
        NOW, surface=True)
    assert [row["reason"] for row in blocked] == ["unknown_pattern"]
    assert PID not in ledger["patterns"]
    # 提示词侧：空账本在断点上也只给观察路径，不给开口路径。
    note = coach.surface_note(coach.new_ledger(), NOW, boundary=True)
    assert "本轮不做教练开口" in note and "coach:" not in note.replace(
        "topic=coach:<id>", "")


def test_red_line_already_spoken_pattern_does_not_reopen():
    """红线②：spoken/cooldown/retired 的模式不出现在可开口列表，开口被拦。"""
    ledger = coach.new_ledger()
    _ripe(ledger, "spk")
    _ripe(ledger, "cold")
    _ripe(ledger, "done")
    coach.mark_spoken(ledger, "spk", NOW, note="说过一次")
    coach.mark_spoken(ledger, "cold", NOW)
    coach.cooldown(ledger, "cold", NOW + 1)
    coach.mark_spoken(ledger, "done", NOW)
    coach.retire(ledger, "done", NOW + 1)
    note = coach.surface_note(ledger, NOW, boundary=True)
    assert "coach:spk" not in note and "coach:cold" not in note and "coach:done" not in note
    blocked = coach.apply_decisions(
        ledger,
        [_speak("spk"), _speak("cold"), _speak("done")], NOW, surface=True)
    assert {row["id"]: row["reason"] for row in blocked} == {
        "spk": "already_spoken", "cold": "muted_after_cooldown", "done": "retired"}
    assert all(ledger["patterns"][p]["state"] != coach.OBSERVING
               for p in ("spk", "cold", "done"))


def test_red_line_in_flow_has_no_coach_path_at_all():
    """红线③：操作流中——提示词段整段缺席；硬闯的 coach 开口被拦且状态不动。"""
    ledger = coach.new_ledger()
    _ripe(ledger)
    # 流中：surface_note 必须是空串，模型这一轮根本看不到教练通道。
    assert coach.surface_note(ledger, NOW, in_flow=True, boundary=True) == ""
    assert coach.surface_allowed(in_flow=True, boundary=True) == (False, "in_flow")
    blocked = coach.apply_decisions(ledger, [_speak(PID)], NOW, surface=False)
    assert blocked[0]["reason"] == "not_a_breakpoint"
    pattern = ledger["patterns"][PID]
    assert pattern["state"] == coach.OBSERVING and len(pattern["instances"]) == 2


def test_observe_and_speak_then_adopt_happy_path():
    """正常自衰减主线：quiet 攒实例 → 断点开口 → 采纳退休；adopt 也可直接退休。"""
    ledger = coach.new_ledger()
    coach.apply_decisions(ledger, [_quiet("tpl", "第一次手动重复填表头", t=NOW - DAY)],
                          NOW - DAY, surface=False)
    coach.apply_decisions(ledger, [_quiet("tpl", "又手动填了一次", t=NOW)],
                          NOW, surface=False)
    # 非断点轮即便攒够也不开口
    blocked = coach.apply_decisions(
        ledger, [{"kind": "companion", "topic": "coach:tpl", "say": "s", "t": NOW + 1,
                  "state": "锚点"}], NOW + 1, surface=False)
    assert blocked[0]["reason"] == "not_a_breakpoint"
    # action_boundary 断点轮：开口迁移
    blocked = coach.apply_decisions(
        ledger, [{"kind": "companion", "topic": "coach:tpl",
                  "say": "要我把这个存成模板吗", "t": NOW + 2, "state": "刚保存完"}],
        NOW + 2, surface=True)
    assert blocked == []
    assert ledger["patterns"]["tpl"]["state"] == coach.SPOKEN
    # outcome accepted → retired
    coach.apply_outcome(ledger, event_id="o1", topic="coach:tpl",
                        outcome="accepted", now=NOW + 200)
    assert ledger["patterns"]["tpl"]["state"] == coach.RETIRED
    # 观察到用户自发改用另一条模式 → 不经 spoken 直接退休
    coach.add_instance(ledger, "alt-search", NOW - 5, "他本来就这样搜")
    coach.apply_decisions(
        ledger, [_quiet("alt-search", "他连续三轮都自己先搜再问", adopt=True)],
        NOW, surface=False)
    assert ledger["patterns"]["alt-search"]["state"] == coach.RETIRED


# ────────────────────────────────────────────────────────────────────
# 6. 时刻闸
# ────────────────────────────────────────────────────────────────────
def test_surface_gate_priority_and_wait_moments():
    assert coach.surface_allowed(boundary=True) == (True, "boundary")
    assert coach.surface_allowed(settled=True) == (True, "settled")
    assert coach.surface_allowed() == (False, "no_breakpoint")
    # 回话轮优先级最高：他在等回答，不夹教练话
    assert coach.surface_allowed(boundary=True, reply_pending=True) == (False, "reply_pending")
    assert coach.surface_allowed(boundary=True, in_flow=True) == (False, "in_flow")
    assert coach.surface_allowed(settled=True, away=True) == (False, "away")


def test_surface_note_lists_only_eligible_with_anchors():
    ledger = coach.new_ledger()
    _ripe(ledger, "ripe-one")
    coach.add_instance(ledger, "lonely", NOW, "只有一条实例")
    note = coach.surface_note(ledger, NOW, boundary=True)
    assert "coach:ripe-one" in note
    assert "第二次，带锚点" in note          # 锚点要随列表进提示词
    assert "coach:lonely" not in note
    assert "topic=coach:<id>" in note             # 记实例的约定始终在


# ────────────────────────────────────────────────────────────────────
# 7. GUIDE.md 围栏块：渲染 / 解析 / 剥离 / 合并
# ────────────────────────────────────────────────────────────────────
def _full_ledger() -> dict:
    ledger = coach.new_ledger()
    coach.add_instance(ledger, "observing-p", NOW - 3600, "早先一次锚点")
    coach.add_instance(ledger, "observing-p", NOW - 60, "刚才那次锚点｜带竖线")
    coach.add_instance(ledger, "spoken-p", NOW - DAY, "s1")
    coach.add_instance(ledger, "spoken-p", NOW - DAY + 1, "s2")
    coach.mark_spoken(ledger, "spoken-p", NOW - 100, note="要我改成一轮就对的版本吗")
    coach.add_instance(ledger, "retired-p", NOW - 10 * DAY, "早就会了")
    coach.retire(ledger, "retired-p", NOW - 9 * DAY, note="观察到他已自己改用")
    coach.add_instance(ledger, "cold-p", NOW - 2 * DAY, "c1")
    coach.add_instance(ledger, "cold-p", NOW - 2 * DAY + 1, "c2")
    coach.mark_spoken(ledger, "cold-p", NOW - 2 * DAY + 2)
    coach.cooldown(ledger, "cold-p", NOW - 2 * DAY + 100, note="rejected")
    ledger["seen_outcomes"] = ["o1", "o2"]
    ledger["blocked"] = [{"t": NOW, "id": "cold-p", "reason": "already_spoken"}]
    return ledger


def test_render_parse_roundtrip_preserves_ledger():
    ledger = _full_ledger()
    block = coach.render_block(ledger, now=NOW)
    assert coach.BLOCK_OPEN in block and coach.BLOCK_CLOSE in block
    restored = coach.parse_block(block)
    assert set(restored["patterns"]) == {"observing-p", "spoken-p", "retired-p", "cold-p"}
    for pid in ("observing-p", "spoken-p", "retired-p", "cold-p"):
        a, b = ledger["patterns"][pid], restored["patterns"][pid]
        assert a["state"] == b["state"], pid
        assert bool(a["spoken_at"]) == bool(b["spoken_at"]), pid
        assert [(i["t"], i["anchor"]) for i in a["instances"]] == \
               [(i["t"], i["anchor"]) for i in b["instances"]], pid
    assert restored["seen_outcomes"] == ["o1", "o2"]
    assert restored["blocked"][0]["id"] == "cold-p"
    # 给模型看的四态中文说明在
    assert "observing" in block and "retired" in block


def test_render_empty_ledger_is_still_a_valid_block():
    block = coach.render_block(coach.new_ledger(), now=NOW)
    restored = coach.parse_block(block)
    assert restored == coach.new_ledger()
    assert "coach:<id>" in block


def test_parse_block_is_tolerant_and_optional():
    assert coach.parse_block("普通 GUIDE，没有块") is None
    block = coach.BLOCK_OPEN + "\n### observing — x\n垃圾行\n" + coach.BLOCK_CLOSE
    assert coach.parse_block(block) == coach.new_ledger()


def test_strip_block_removes_only_the_fenced_region():
    text = "# GUIDE\n\n## 偏好\n- 短一点\n\n" + coach.render_block(_full_ledger(), now=NOW)
    clean = coach.strip_block(text)
    assert coach.BLOCK_OPEN not in clean
    assert "短一点" in clean
    assert coach.strip_block("") == ""


def test_merge_appends_exactly_one_block():
    prose = "# GUIDE\n\n- 偏好：说人话\n"
    merged = coach.merge_block(prose, _full_ledger(), now=NOW)
    assert merged.count(coach.BLOCK_OPEN) == 1
    assert "说人话" in merged
    again = coach.merge_block(merged, coach.new_ledger(), now=NOW)
    assert again.count(coach.BLOCK_OPEN) == 1
    assert "说人话" in again


def test_model_full_rewrite_cannot_lose_the_block(tmp_path):
    """验收：模型全量 write_guide 覆盖 GUIDE.md，剥离/合并后机器块仍在且状态不丢。"""
    ledger = _full_ledger()
    guide = tmp_path / "GUIDE.md"
    guide.write_text(coach.merge_block("# GUIDE\n\n- 旧偏好\n", ledger, now=NOW),
                     encoding="utf-8")
    # 模型全量重写：块被它整段丢掉
    guide.write_text("# GUIDE（新版）\n\n- 新偏好：先做完再汇报\n", encoding="utf-8")
    recovered = coach.merge_block(guide.read_text(encoding="utf-8"), ledger, now=NOW)
    assert recovered.count(coach.BLOCK_OPEN) == 1
    assert "新偏好" in recovered and "旧偏好" not in recovered
    restored = coach.parse_block(recovered)
    assert set(restored["patterns"]) == {"observing-p", "spoken-p", "retired-p", "cold-p"}
    # 模型若自作主张仿造一个假块，也会被剥掉、以规范块为准
    fake = ("# GUIDE\n\n" + coach.BLOCK_OPEN + "\n- [fake] state=observing "
            "spoken_at=0 updated=1 instances=0\n" + coach.BLOCK_CLOSE + "\n")
    recovered2 = coach.merge_block(fake, ledger, now=NOW)
    assert "[fake]" not in recovered2
    assert coach.parse_block(recovered2)["patterns"]["spoken-p"]["state"] == coach.SPOKEN


# ────────────────────────────────────────────────────────────────────
# 8. brain 薄接线（不跑模型、不碰 live）
# ────────────────────────────────────────────────────────────────────
def _runtime(tmp_path):
    guide = tmp_path / "session" / "GUIDE.md"
    guide.parent.mkdir(parents=True, exist_ok=True)
    guide.write_text("# GUIDE\n\n- 人写的长期理解\n", encoding="utf-8")
    return SimpleNamespace(context=SimpleNamespace(guide_path=guide, working_path=None)), guide


def test_brain_wires_coach_into_loop_and_guide(tmp_path, monkeypatch):
    import time as _time
    recent = _time.time() - 60.0          # save_guide 渲染时按真实时钟 prune
    monkeypatch.setattr(brain, "COMPANION", tmp_path)
    monkeypatch.setattr(brain, "GUIDE", tmp_path / "GUIDE.saved.md")
    monkeypatch.setattr(brain, "WORKING", tmp_path / "no-working.md")
    ledger = coach.new_ledger()
    coach.apply_decisions(ledger, [_quiet(PID, "第一次只贴半句报错", t=recent)],
                          recent, surface=False)
    runtime, guide = _runtime(tmp_path)

    brain.save_guide(runtime, ledger)
    persisted = brain.GUIDE.read_text(encoding="utf-8")
    assert "人写的长期理解" in persisted and coach.BLOCK_OPEN in persisted

    # 重启：从持久块恢复账本，restore_guide 把块放回会话文件
    restarted = brain.load_coach_ledger()
    assert restarted["patterns"][PID]["state"] == coach.OBSERVING
    brain.restore_guide(runtime, restarted)
    assert coach.BLOCK_OPEN in guide.read_text(encoding="utf-8")

    # 模型全量 write_guide 覆盖会话文件后再存：块不丢
    guide.write_text("# GUIDE\n\n- 模型重写后的理解\n", encoding="utf-8")
    brain.save_guide(runtime, restarted)
    saved = brain.GUIDE.read_text(encoding="utf-8")
    assert "模型重写后的理解" in saved and saved.count(coach.BLOCK_OPEN) == 1
    restored_t = coach.parse_block(saved)["patterns"][PID]["instances"][0]["t"]
    assert abs(restored_t - recent) < 1     # 围栏块按整秒存储


def test_sync_coach_applies_decisions_and_outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "PERCEIVE", tmp_path)
    ledger = coach.new_ledger()
    session = SimpleNamespace(decisions=[])
    outcomes = tmp_path / "outcomes.jsonl"

    # 两个 quiet 实例（无符号时刻也可记账）
    session.decisions.append(_quiet(PID, "第一次只贴半句报错", t=NOW - DAY))
    seen = brain.sync_coach(ledger, session, seen_decisions=0, now=NOW - DAY,
                            surface=False, outcomes_path=outcomes)
    assert seen == 1 and len(ledger["patterns"][PID]["instances"]) == 1
    # 断点轮开口
    session.decisions.append(_quiet(PID, "又贴了两遍才补上下文", t=NOW))
    session.decisions.append({"kind": "companion", "topic": "coach:" + PID,
                              "say": "要我把这句改成一轮就对的版本吗", "t": NOW,
                              "state": "刚才三轮第一轮就差这条报错"})
    seen = brain.sync_coach(ledger, session, seen_decisions=seen, now=NOW,
                            surface=True, outcomes_path=outcomes)
    assert seen == 3 and ledger["patterns"][PID]["state"] == coach.SPOKEN
    # 重复 sync 不重复消费
    assert brain.sync_coach(ledger, session, seen_decisions=seen, now=NOW,
                            surface=True, outcomes_path=outcomes) == 3
    # outcomes 回流 accepted → retired，且幂等
    outcomes.write_text(json.dumps(_outcome("o1", PID, "accepted")) + "\n",
                        encoding="utf-8")
    brain.sync_coach(ledger, session, seen_decisions=seen, now=NOW + 60,
                     surface=True, outcomes_path=outcomes)
    assert ledger["patterns"][PID]["state"] == coach.RETIRED
    brain.sync_coach(ledger, session, seen_decisions=seen, now=NOW + 61,
                     surface=True, outcomes_path=outcomes)
    assert ledger["seen_outcomes"].count("o1") == 1


def test_sync_coach_non_coach_decisions_pass_through(tmp_path):
    ledger = coach.new_ledger()
    session = SimpleNamespace(decisions=[
        {"kind": "companion", "topic": "weather", "say": "今天挺热", "t": NOW,
         "state": "随口聊"},
        {"kind": "quiet", "topic": "", "t": NOW, "state": "后台维护完成"},
    ])
    seen = brain.sync_coach(ledger, session, seen_decisions=0, now=NOW,
                            surface=False, outcomes_path=tmp_path / "nope.jsonl")
    assert seen == 2 and ledger["patterns"] == {}


def test_legacy_save_restore_signature_still_plain_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "COMPANION", tmp_path)
    monkeypatch.setattr(brain, "GUIDE", tmp_path / "plain.md")
    monkeypatch.setattr(brain, "WORKING", tmp_path / "plain-working.md")
    runtime, guide = _runtime(tmp_path)
    brain.save_guide(runtime)                  # 不传 ledger：旧行为，纯拷贝
    assert brain.GUIDE.read_text(encoding="utf-8") == guide.read_text(encoding="utf-8")


def test_brain_source_carries_the_coach_wiring():
    import inspect
    src = inspect.getsource(brain)
    # 决策后迁移、outcome 回流、围栏剥离合并、时刻闸四件事缺一不可
    assert "sync_coach(" in src
    assert "coach.surface_note(" in src
    assert "coach.merge_block(" in src
    assert "load_coach_ledger(" in src


# ────────────────────────────────────────────────────────────────────
# 9. profiles 身份段：关键约束用字符串断言钉死（参照 test_bubble_and_loop）
# ────────────────────────────────────────────────────────────────────
SYSTEM = profiles.SYSTEM


def test_profile_has_coach_identity_not_a_checklist():
    assert "隐性教练" in SYSTEM
    # 自然三律的肉身
    assert "从刚发生的事里长出来" in SYSTEM
    assert "给汽车，不讲汽车原理" in SYSTEM
    assert "借断点开口，借安静隐身" in SYSTEM
    # 三条机械禁令
    assert "无锚点不说" in SYSTEM
    assert "不换说法重说" in SYSTEM
    assert "他在流里不说" in SYSTEM


def test_profile_names_the_real_failure_cases():
    assert "九点多" in SYSTEM and "今天这一天挺长的" in SYSTEM
    assert "隐私口径现状对照" in SYSTEM and "21:14" in SYSTEM and "21:17" in SYSTEM


def test_profile_explains_topic_convention_and_ledger_block():
    assert "<!-- coach:auto -->" in SYSTEM
    assert "topic=coach:<id>" in SYSTEM
    assert "topic=coach^<id>" in SYSTEM
    assert "7 天" in SYSTEM and "至少 2 个" in SYSTEM
    assert "永不再提" in SYSTEM
    # 结构修复型 offer 仍走同意门
    assert "同意门" in SYSTEM
    # 无配额：健康曲线靠自衰减，不靠预算
    assert "没有日配额" in SYSTEM


def test_profile_bans_anchorless_principle_sentences():
    assert "你要善于提供上下文" in SYSTEM  # 作为反面例子被点名禁止
