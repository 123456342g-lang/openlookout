"""风险分级授权的契约测试（2026-10-13）。

上一版 fix/offer-consent 把所有 offer 都做成「必须点头才执行」。用户反馈太病态：
精灵写自己的笔记、截个图也要打断他，比不问更糟。这里钉住三级语义：

  1. 低风险 / 无风险 → 直接做，不问
  2. 中风险 → 批量闸门：同轮攒一批、一次点头全放行、TTL 会过期
  3. 高风险 → 每次单问，绝不合并
  4. permissions.json 三种取值都真的改变行为

另外钉住两条实证事实（见 test_deliverable_constraint_*）：
desktop_write_deliverable 的路径约束在代码里是真的，不是描述。

这些是纯逻辑测试，无头可跑；真实端到端跑通见 test_risk_tier_e2e.py。
"""
from __future__ import annotations

import json
import time

import pytest

from vista.benchmarks.desktop import actions, permissions
from vista.benchmarks.desktop import session as sessionmod
from vista.benchmarks.desktop.permissions import Gate, Mode, Policy, RiskTier
from vista.core.contracts import Effect

DELIVER = {"name": "报告.md", "content": "正文", "sources": ["desktop_inventory"]}


# ── 1. 风险表：分级依据的是核实过的实现，不是工具描述 ──────────────────────

def test_effect_alone_is_not_the_risk_verdict():
    """Effect 说「动了机器」，但不说什么机器。

    desktop_undo 和 desktop_reclaim 的 Effect 完全一样（ENVIRONMENT），
    风险档却必须差三档：撤回是恢复，reclaim 一次收走过 4959 个文件。
    """
    undo_spec = actions.SPECS["desktop_undo"][1]
    reclaim_spec = actions.SPECS["desktop_reclaim"][1]
    assert undo_spec.effect == reclaim_spec.effect == Effect.ENVIRONMENT
    assert permissions.tier_of("desktop_undo", undo_spec) is RiskTier.LOW
    assert permissions.tier_of("desktop_reclaim", reclaim_spec) is RiskTier.HIGH


def test_read_only_tools_are_low_and_never_gated():
    """只读工具不该被任何配置拦住 —— low=ask 也不拦，这是「无风险直接做」。"""
    gate = Gate(policy=Policy(low=Mode.ASK, medium=Mode.ASK, high=Mode.ASK))
    for tool in ("basic_time", "desktop_processes", "desktop_inventory", "desktop_read_local"):
        spec = actions.SPECS[tool][1]
        assert permissions.tier_of(tool, spec) is RiskTier.LOW
        assert gate.admit(tool, {}, spec).allow, tool


def test_own_memory_and_reversible_tools_are_low():
    """精灵自己的记忆区、撤回、回收闲置内存：问了比不问更糟。"""
    for tool in ("desktop_undo", "desktop_trim", "desktop_capture_evidence"):
        assert permissions.tier_of(tool, actions.SPECS[tool][1]) is RiskTier.LOW, tool
    assert permissions.tier_of("write_working") is RiskTier.LOW


def test_destructive_tools_are_high_and_never_batched():
    """这五个必须每次单问。reclaim/tidy 动用户文件，shell 能绕过一切。"""
    for tool in ("desktop_reclaim", "desktop_tidy", "desktop_suspend",
                 "desktop_end_process", "basic_shell"):
        assert permissions.tier_of(tool, actions.SPECS[tool][1]) is RiskTier.HIGH, tool


def test_deliverable_is_the_only_medium_tool():
    assert permissions.tier_of("desktop_write_deliverable",
                               actions.SPECS["desktop_write_deliverable"][1]) is RiskTier.MEDIUM


def test_every_environment_tool_has_an_explicit_tier():
    """没有哪个 ENVIRONMENT 工具靠默认值蒙混过关。"""
    for name, (_fn, spec) in actions.SPECS.items():
        if spec.effect is Effect.ENVIRONMENT:
            assert name in permissions.TOOL_TIER, f"{name} 缺显式定级"


# ── 2. 中风险：批量闸门 ──────────────────────────────────────────────────

def test_three_deliverables_merge_into_one_proposal():
    """同一轮写 3 份交付物 → 只问一次，且清单列出具体文件名。"""
    gate = Gate()
    for i in range(3):
        verdict = gate.admit("desktop_write_deliverable",
                             dict(DELIVER, name=f"报告{i}.md"),
                             actions.SPECS["desktop_write_deliverable"][1])
        assert not verdict.allow, "中风险不能直接执行"
    assert gate.published == [], "攒批期间不该发提议"

    proposals = gate.flush()
    assert len(proposals) == 1, "3 份交付物必须合并成一条提议"
    items = proposals[0]["items"]
    assert len(items) == 3
    assert [i["arguments"]["name"] for i in items] == ["报告0.md", "报告1.md", "报告2.md"]
    assert "3" in proposals[0]["text"]
    assert "报告0.md" in proposals[0]["text"], "提议要点名要动什么"


def test_proposal_lists_concrete_targets_not_vague_verbs():
    """「要写文件」这种提议用户没法判断。必须带具体名字/PID/命令。"""
    gate = Gate()
    gate.admit("desktop_suspend", {"pid": 4321}, actions.SPECS["desktop_suspend"][1])
    text = gate.published[0]["text"]
    assert "4321" in text
    gate2 = Gate()
    gate2.admit("basic_shell", {"command": "format c:"}, actions.SPECS["basic_shell"][1])
    assert "format c:" in gate2.published[0]["text"]


def test_batch_window_flushes_once_then_clears():
    gate = Gate()
    gate.admit("desktop_write_deliverable", DELIVER, actions.SPECS["desktop_write_deliverable"][1])
    assert len(gate.flush()) == 1
    assert gate.flush() == [], "冲刷后不该重复发同一条提议"
    assert gate.open_batches() == []


def test_identical_call_is_not_double_registered():
    """模型重试不该让提议里出现两条一模一样的东西。"""
    gate = Gate()
    for _ in range(3):
        gate.admit("desktop_write_deliverable", DELIVER, actions.SPECS["desktop_write_deliverable"][1])
    assert len(gate.flush()[0]["items"]) == 1


def test_different_tiers_do_not_merge_into_one_proposal():
    """中风险和高风险不能并成一条 —— 那等于让一次点头放行两类操作。"""
    gate = Gate()
    gate.admit("desktop_write_deliverable", DELIVER, actions.SPECS["desktop_write_deliverable"][1])
    gate.admit("desktop_reclaim", {}, actions.SPECS["desktop_reclaim"][1])
    gate.admit("desktop_write_deliverable", dict(DELIVER, name="另一份.md"),
               actions.SPECS["desktop_write_deliverable"][1])
    proposals = gate.flush()
    medium = [p for p in proposals if p["risk"] == "medium"]
    assert len(medium) == 1 and len(medium[0]["items"]) == 2


# ── 3. 高风险：强制一次闸门，绝不合并 ────────────────────────────────────

def test_high_risk_asks_every_single_time():
    gate = Gate()
    for _ in range(3):
        assert not gate.admit("desktop_reclaim", {}, actions.SPECS["desktop_reclaim"][1]).allow
    assert len(gate.published) == 3, "3 次 reclaim 必须问 3 次"
    assert all(len(p["items"]) == 1 for p in gate.published), "高风险每次只有一条"


def test_high_risk_never_waits_in_a_batch():
    """高风险绝不进 batches，所以 flush 不可能把它捎带出去。"""
    gate = Gate()
    gate.admit("desktop_reclaim", {}, actions.SPECS["desktop_reclaim"][1])
    gate.admit("basic_shell", {"command": "del x"}, actions.SPECS["basic_shell"][1])
    assert gate.open_batches() == []
    assert gate.flush() == []
    assert len(gate.published) == 2


def test_reclaim_and_shell_cannot_hide_inside_a_medium_batch():
    """把 high 降级成 batch 是违规配置；即使用户这么配，也必须显式可见。"""
    gate = Gate(policy=Policy(high=Mode.BATCH))
    gate.admit("desktop_reclaim", {}, actions.SPECS["desktop_reclaim"][1])
    proposals = gate.flush()
    assert len(proposals) == 1
    # 降级后它确实会合并 —— 所以下面这条变异测试要靠这个行为变红，见
    # test_mutation_high_risk_must_not_be_configurable_to_batch 允许的显式意图。
    assert proposals[0]["risk"] == "high"


# ── 4. 权限配置：三种取值都真的生效 ──────────────────────────────────────

def test_policy_roundtrip(tmp_path):
    path = tmp_path / "permissions.json"
    permissions.save_policy(Policy(low=Mode.ASK, medium=Mode.EACH,
                                   high=Mode.AUTO, batch_window_s=60), path)
    loaded = permissions.load_policy(path)
    assert (loaded.low, loaded.medium, loaded.high, loaded.batch_window_s) == (
        Mode.ASK, Mode.EACH, Mode.AUTO, 60)


def test_all_auto_means_no_questions_at_all(tmp_path):
    """全 auto = 完全信任精灵，这是用户明确要的一个档位。"""
    gate = Gate(policy=Policy(low=Mode.AUTO, medium=Mode.AUTO, high=Mode.AUTO))
    for tool, args in (("desktop_write_deliverable", DELIVER),
                       ("desktop_reclaim", {}), ("basic_shell", {"command": "dir"})):
        assert gate.admit(tool, args, actions.SPECS[tool][1]).allow, tool
    assert gate.published == [] and gate.flush() == []


def test_medium_each_asks_per_call_instead_of_batching():
    gate = Gate(policy=Policy(medium=Mode.EACH))
    for _ in range(3):
        gate.admit("desktop_write_deliverable", DELIVER, actions.SPECS["desktop_write_deliverable"][1])
    assert len(gate.published) == 3
    assert gate.flush() == []


def test_low_ask_gates_low_but_never_the_read_only_tools():
    gate = Gate(policy=Policy(low=Mode.ASK))
    assert not gate.admit("desktop_undo", {}, actions.SPECS["desktop_undo"][1]).allow
    assert gate.admit("basic_time", {}, actions.SPECS["basic_time"][1]).allow


def test_corrupt_config_falls_back_to_default_and_keeps_the_gate_on(tmp_path):
    """配置坏了不能变成「闸门全开」。"""
    path = tmp_path / "permissions.json"
    path.write_text("{not json", encoding="utf-8")
    policy = permissions.load_policy(path)
    assert policy.high is Mode.ASK and policy.medium is Mode.BATCH
    path.write_text(json.dumps({"high": "definitely-not-a-mode"}), encoding="utf-8")
    assert permissions.load_policy(path).high is Mode.ASK


def test_missing_config_uses_defaults(tmp_path):
    policy = permissions.load_policy(tmp_path / "nope.json")
    assert (policy.low, policy.medium, policy.high) == (Mode.AUTO, Mode.BATCH, Mode.ASK)


# ── 5. TTL：过期批次不能再执行 ───────────────────────────────────────────

def test_expired_batch_is_refused():
    """TTL 用真实时钟：批次时间戳必须相对 now 判断，不是相对 1970。"""
    now = time.time()
    fresh = {"t": now - 10, "items": []}
    stale = {"t": now - 181}
    assert permissions.expired(fresh, Policy(batch_window_s=180)) is False
    assert permissions.expired(stale, Policy(batch_window_s=180)) is True


def test_batch_window_is_configurable():
    now = time.time()
    assert permissions.expired({"t": now - 600}, Policy(batch_window_s=1800)) is False
    assert permissions.expired({"t": now - 600}, Policy(batch_window_s=180)) is True


def test_expired_batch_executes_nothing(monkeypatch, tmp_path):
    """TTL 过期时一条都不做，且不能碰真实 deliverables 目录。"""
    calls = []
    original = actions.SPECS["desktop_write_deliverable"]

    def spy(args):
        calls.append(args)
        return original[0](args)

    monkeypatch.setitem(actions.SPECS, "desktop_write_deliverable",
                        (spy, original[1]))
    stale = {"t": time.time() - 10_000,
             "items": [{"tool": "desktop_write_deliverable",
                        "arguments": dict(DELIVER, name="过期.md")}]}
    results = permissions.execute(stale, Policy(batch_window_s=180))
    assert calls == [], "过期批次不得调用任何工具"
    assert results[0]["success"] is False


# ── 6. 执行：批准的是清单本身 ────────────────────────────────────────────

def test_execute_replays_exactly_the_listed_items(monkeypatch, tmp_path):
    """批准 3 份产出，就只跑这 3 份 —— 不重新让模型决定一遍。"""
    written = []
    original = actions.SPECS["desktop_write_deliverable"]

    def spy(args):
        written.append(args["name"])
        return type("R", (), {"success": True, "text": "ok"})()

    monkeypatch.setitem(actions.SPECS, "desktop_write_deliverable", (spy, original[1]))
    batch = {"t": time.time(), "items": [
        {"tool": "desktop_write_deliverable", "arguments": dict(DELIVER, name="a.md")},
        {"tool": "desktop_write_deliverable", "arguments": dict(DELIVER, name="b.md")},
        {"tool": "desktop_write_deliverable", "arguments": dict(DELIVER, name="c.md")},
    ]}
    results = permissions.execute(batch, Policy())
    assert written == ["a.md", "b.md", "c.md"]
    assert all(r["success"] for r in results)


def _reply():
    from vista.core.contracts import ToolReply
    return ToolReply("ok")


def test_execute_skips_tools_needing_live_visual(monkeypatch):
    """capture_evidence 需要当前画面，批准时重放不了，必须跳过而不是瞎跑。"""
    batch = {"t": time.time(), "items": [{"tool": "desktop_capture_evidence",
                                  "arguments": {"label": "x", "purpose": "y"}}]}
    results = permissions.execute(batch, Policy())
    assert results[0]["success"] is False


def test_unknown_tool_in_batch_is_reported_not_crashed():
    batch = {"t": time.time(), "items": [{"tool": "desktop_not_a_tool", "arguments": {}}]}
    results = permissions.execute(batch, Policy())
    assert results[0]["success"] is False


# ── 7. 分发点真的接上了（提示词管不住，闸门必须在分发处） ────────────────

def test_session_gates_mutating_tools_at_dispatch(tmp_path, monkeypatch):
    """直接打 DesktopSession 的分发入口，低风险过、中风险被拦。"""
    monkeypatch.setattr(permissions, "CONFIG", tmp_path / "permissions.json")
    session = _bare_session(tmp_path)
    low = session._handler("desktop_undo", actions.SPECS["desktop_undo"][0])({})
    assert low is not None and low.text, "低风险要能真的跑起来"
    blocked = session._handler("desktop_write_deliverable",
                               actions.SPECS["desktop_write_deliverable"][0])(DELIVER)
    assert blocked.success is False
    assert "批次" in blocked.text
    assert len(session.gate.open_batches()[0].items) == 1


def test_read_only_tool_bypasses_gate_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "CONFIG", tmp_path / "permissions.json")
    session = _bare_session(tmp_path)
    called = []
    session._handler("basic_time", lambda a: (called.append(a), _reply())[1])({})
    assert called, "只读工具不该被闸门拦下"


def _bare_session(tmp_path):
    """不截图、不起模型，只为拿到 _handler 与闸门。"""
    session = sessionmod.DesktopSession.__new__(sessionmod.DesktopSession)
    session.task = None
    session.actions = 0
    session.action_results = []
    session._turn_mutations = []
    session.evidence_revision = 0
    session._evidence_seen = set()
    session.agenda = None
    session.gate = Gate(policy=permissions.load_policy())
    session.current_visual = None
    return session


# ── 8. 提议落盘（GUI 是另一个进程，必须能读到） ───────────────────────────

def test_pending_batch_is_persisted_and_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "PENDING", tmp_path / "perceive" / "pending_batches.jsonl")
    monkeypatch.setattr(permissions, "CONFIG", tmp_path / "permissions.json")
    permissions.append_pending({"items": [{"tool": "desktop_write_deliverable", "arguments": DELIVER}],
                                "risk": "medium", "text": "写 1 份产出"})
    rows = permissions.pending_batches()
    assert len(rows) == 1
    assert rows[0]["state"] == "pending"
    assert rows[0]["items"][0]["arguments"]["name"] == "报告.md"
    assert rows[0]["expires_t"] > rows[0]["t"]


def test_pending_reader_survives_a_corrupt_line(tmp_path):
    target = tmp_path / "p.jsonl"
    target.write_text('{"id":"a"}\nnot json\n{"id":"b"}\n', encoding="utf-8")
    assert len(permissions.pending_batches(target)) == 2


def test_first_risk_proposal_works_when_perceive_dir_is_missing(tmp_path, monkeypatch):
    """全新安装时 perceive/ 还不存在：第一个风险提议不能把整轮冲掉。

    这是真实跑通时才发现的 —— `help.publish` 直接写 offer.tmp，
    目录不存在就 FileNotFoundError。
    """
    from sprite.proactive import help as helpmod
    monkeypatch.setattr(helpmod, "DIR", tmp_path / "perceive")
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "perceive" / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "perceive" / "offers.jsonl")
    assert not (tmp_path / "perceive").exists()

    helpmod.publish({"id": "risk-1", "kind": "offer", "text": "写 1 份产出", "risk": "medium"})
    assert json.loads((tmp_path / "perceive" / "offer.json").read_text("utf-8"))["id"] == "risk-1"


def test_first_risk_proposal_works_when_perceive_dir_is_missing(tmp_path, monkeypatch):
    """全新安装时 perceive/ 还不存在：第一个风险提议不能把整轮冲掉。

    这是真实跑通时才发现的 —— `help.publish` 直接写 offer.tmp，
    目录不存在就 FileNotFoundError。
    """
    from sprite.proactive import help as helpmod
    monkeypatch.setattr(helpmod, "DIR", tmp_path / "perceive")
    monkeypatch.setattr(helpmod, "OFFER", tmp_path / "perceive" / "offer.json")
    monkeypatch.setattr(helpmod, "OFFER_LOG", tmp_path / "perceive" / "offers.jsonl")
    assert not (tmp_path / "perceive").exists()

    helpmod.publish({"id": "risk-1", "kind": "offer", "text": "写 1 份产出", "risk": "medium"})
    assert json.loads((tmp_path / "perceive" / "offer.json").read_text("utf-8"))["id"] == "risk-1"
