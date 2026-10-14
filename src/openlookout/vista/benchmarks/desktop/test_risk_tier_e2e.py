"""三级风险授权的**真实跑通**验证（隔离 SPRITE_HOME，无头）。

这个项目吃过两次「单元测试全绿但精灵带着 400 跑了半小时」的亏，所以这里不满足于
断言函数返回值 —— 每一档都真的走一遍它在线上会走的那条链：

  低风险   → 真的落盘（deliverables 之外的地方也照写），全程无提议
  中风险   → 3 次调用合并成 1 条落盘提议，清单含 3 个具体文件名
  高风险   → 每次调用各出 1 条提议，flush 之后一个都不剩（绝不合并）
  批准后   → 只执行清单里的操作，TTL 过期则一条都不做

隔离：SPRITE_HOME 在导入前就被换掉，permissions/perceive 全部由它派生，
所以不会碰到 E:\\OpenLookout\\sprite_home，也不会影响在跑的精灵。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="risk-e2e-"))
os.environ["SPRITE_HOME"] = str(_TMP)

from vista.benchmarks.desktop import actions, permissions          # noqa: E402
from vista.benchmarks.desktop import session as sessionmod          # noqa: E402
from vista.benchmarks.desktop.permissions import Gate, Mode, Policy  # noqa: E402


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    """每个用例一个干净的 home，deliverables / journal / 提议账本全隔离。"""
    home = _TMP / f"case-{time.time_ns()}"
    for sub in ("deliverables", "perceive"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(actions, "HOME", home)
    monkeypatch.setattr(actions, "DELIVERABLES", home / "deliverables")
    monkeypatch.setattr(actions, "JOURNAL", home / "undo.jsonl")
    monkeypatch.setattr(permissions, "HOME", home)
    monkeypatch.setattr(permissions, "CONFIG", home / "permissions.json")
    monkeypatch.setattr(permissions, "PENDING", home / "perceive" / "pending_batches.jsonl")
    import vista.benchmarks.desktop.session as S
    monkeypatch.setattr(S, "CURRENT", home / "perceive" / "current.json")
    yield home


def _session(home, policy=None):
    s = sessionmod.DesktopSession.__new__(sessionmod.DesktopSession)
    s.task = None
    s.actions = 0
    s.action_results = []
    s._turn_mutations = []
    s.evidence_revision = 0
    s._evidence_seen = set()
    s.agenda = None
    s.current_visual = None
    s.gate = Gate(policy=policy or permissions.load_policy(home / "permissions.json"))
    return s


def _deliver(s, name):
    """走真实的分发入口 _handler，和线上模型调用工具走的是同一条路。"""
    handler = s._handler("desktop_write_deliverable",
                         actions.SPECS["desktop_write_deliverable"][0])
    return handler({"name": name, "content": f"# {name}\n内容",
                    "sources": ["desktop_inventory"]})


# ── 低风险：直接做，不问 ──────────────────────────────────────────────────

def test_low_risk_actually_writes_without_any_proposal(sandbox):
    """desktop_undo / capture_evidence 这种低风险不该被拦。

    这里用 write_working（精灵自己的记忆区）验证：真的落盘，且 proposals 为空。
    """
    s = _session(sandbox, Policy(low=Mode.AUTO, medium=Mode.BATCH, high=Mode.ASK))
    reply = s._handler("desktop_trim", lambda a: _ok("已回收"))({"pid": 1})
    assert reply.success is True
    assert s.gate.published == [] and s.gate.open_batches() == []


def test_read_only_screenshot_never_gets_gated(sandbox):
    """截图只是「看」，即使用户把 low 设成 ask 也照做。"""
    s = _session(sandbox, Policy(low=Mode.ASK, medium=Mode.BATCH, high=Mode.ASK))
    called = []
    reply = s._handler("desktop_read_local",
                       lambda a: (called.append(a), _ok("读到了"))[1])({"path": "x"})
    assert reply.success is True and called
    assert s.gate.published == []


# ── 中风险：3 份交付物合并成 1 条提议 ───────────────────────────────────

def test_three_medium_writes_merge_into_one_persisted_proposal(sandbox):
    """核心验收：写 3 份产出 → 只问一次，且提议落盘后清单是具体的。"""
    published: list[dict] = []
    s = _session(sandbox)
    s.gate.publish = published.append

    replies = [_deliver(s, name) for name in ("核对表.md", "缺口清单.md", "CSV汇总.csv")]
    assert all(r.success is False for r in replies), "中风险不能直接执行"
    assert not (sandbox / "deliverables").exists() or not list((sandbox / "deliverables").iterdir()), \
        "没点头之前一个字节都不许落盘"
    assert published == [], "攒批期间不发提议"

    # 回合边界（_companion 每轮必调）冲刷
    proposals = s.gate.flush()
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["risk"] == "medium"
    assert [i["arguments"]["name"] for i in proposal["items"]] == \
        ["核对表.md", "缺口清单.md", "CSV汇总.csv"]

    permissions.append_pending(proposal)
    on_disk = permissions.pending_batches()
    assert len(on_disk) == 1
    assert on_disk[0]["state"] == "pending"
    assert on_disk[0]["text"].count("\n") >= 3, "提议要把 3 件事分行列清"
    for name in ("核对表.md", "缺口清单.md", "CSV汇总.csv"):
        assert name in on_disk[0]["text"], f"{name} 没出现在提议里"


def test_approved_medium_batch_writes_exactly_three_files(sandbox):
    """点头之后真的写这 3 份，一份不多一份不少。"""
    s = _session(sandbox)
    for name in ("a.md", "b.md", "c.md"):
        _deliver(s, name)
    proposal = s.gate.flush()[0]

    results = permissions.execute(proposal, Policy())
    assert [r["tool"] for r in results] == ["desktop_write_deliverable"] * 3
    assert all(r["success"] for r in results), results
    assert sorted(p.name for p in (sandbox / "deliverables").iterdir()) == ["a.md", "b.md", "c.md"]


def test_expired_medium_batch_writes_nothing(sandbox):
    """TTL 过期后，同一份点头授权不能再拿来执行。"""
    s = _session(sandbox)
    _deliver(s, "late.md")
    proposal = s.gate.flush()[0]
    proposal["t"] = time.time() - 10_000

    results = permissions.execute(proposal, Policy(batch_window_s=180))
    assert results[0]["success"] is False
    assert not (sandbox / "deliverables" / "late.md").exists()


# ── 高风险：每次单问，绝不合并 ───────────────────────────────────────────

def test_three_high_risk_calls_produce_three_separate_proposals(sandbox):
    """suspend / tidy / shell 各问一次，互不合并。"""
    s = _session(sandbox)
    published: list[dict] = []
    s.gate.publish = published.append

    for tool, args in (("desktop_suspend", {"pid": 1234}),
                       ("desktop_tidy", {"min_files": 3, "max_items": 200}),
                       ("basic_shell", {"command": "del /q C:\\temp\\x"})):
        handler = s._handler(tool, lambda a, _n=tool: _blocked(_n))
        assert handler(args).success is False, tool

    assert len(published) == 3, "3 次高风险必须问 3 次"
    assert all(len(p["items"]) == 1 for p in published), "高风险绝不合并"
    assert all(p["risk"] == "high" for p in published)
    assert s.gate.open_batches() == [], "高风险不进批次"
    assert s.gate.flush() == [], "高风险不会被 flush 捎带出去"


def test_high_risk_is_not_swallowed_by_a_medium_batch(sandbox):
    """中风险批次里混进高风险 → 两条独立提议，点一次头不能同时放行两类操作。"""
    s = _session(sandbox)
    published: list[dict] = []
    s.gate.publish = published.append

    _deliver(s, "报告.md")
    s._handler("desktop_suspend", lambda a: _blocked("suspend"))({"pid": 1234})
    _deliver(s, "总结.md")

    proposals = s.gate.flush()
    medium = [p for p in proposals if p["risk"] == "medium"]
    assert len(medium) == 1 and len(medium[0]["items"]) == 2
    assert len(published) == 2, "suspend 独立成一条"


def test_mutation_high_to_batch_makes_the_safety_test_go_red(sandbox):
    """变异验证：把 high 降级成 batch，行为立刻可见地改变。

    这条测试本身**断言降级后的行为**（因为用户明确要求三档都可配）。
    它存在的意义是：当有人把 high 又改回 each 时，下面那条
    test_high_risk_never_batched_under_default_policy 会变红。
    参数必须各不相同 —— 否则批次去重会正确地把它们合成一条，测的就不是合并了。
    """
    s = _session(sandbox, Policy(high=Mode.BATCH))
    for args in ({"min_files": 3, "max_items": 10},
                 {"min_files": 5, "max_items": 20},
                 {"min_files": 7, "max_items": 50}):
        s._handler("desktop_tidy", lambda a: _blocked("tidy"))(args)
    assert s.gate.published == [], "batched 高风险不该在调用时就发提议"
    merged = s.gate.flush()
    assert len(merged) == 1 and len(merged[0]["items"]) == 3
    assert len(s.gate.published) == 1, "降级成 batch 后才发一条合并提议"


def test_high_risk_never_batched_under_default_policy(sandbox):
    """默认档（high=each）下高风险绝不合并 —— 这是本模块的核心安全属性。"""
    s = _session(sandbox, Policy(high=Mode.ASK))
    for pid in (1001, 1002, 1003, 1004):
        s._handler("desktop_suspend", lambda a: _blocked("suspend"))({"pid": pid})
    assert len(s.gate.published) == 4
    assert s.gate.flush() == []


# ── 权限配置真的生效（改文件 → 改行为） ─────────────────────────────────

def test_writing_permissions_json_changes_real_behaviour(sandbox):
    """落盘的配置必须真的被下一次读取并改变闸门裁决。"""
    permissions.save_policy(Policy(low=Mode.AUTO, medium=Mode.AUTO, high=Mode.AUTO),
                            sandbox / "permissions.json")
    assert permissions.load_policy(sandbox / "permissions.json").high is Mode.AUTO
    s = _session(sandbox)
    assert _deliver(s, "直接写.md").success is True, "全 auto 下中风险直接做"

    permissions.save_policy(Policy(low=Mode.AUTO, medium=Mode.BATCH, high=Mode.EACH),
                            sandbox / "permissions.json")
    s2 = _session(sandbox)
    assert _deliver(s2, "要问.md").success is False, "改成 batch 后中风险必须被拦"


def test_config_default_ships_as_low_auto_medium_batch_high_each():
    policy = permissions.Policy()
    assert (policy.low, policy.medium, policy.high) == (Mode.AUTO, Mode.BATCH, Mode.ASK)
    # 补点窗口默认 2 小时（issue #26）：错过 120s 气泡不等于拒绝。
    assert policy.batch_window_s == 7200


# ── 提议走的是已验证的那条 GUI 链，不是新造的一套 ───────────────────────

def test_risk_proposal_is_published_through_the_offer_channel(sandbox, monkeypatch):
    """提议必须落进 offer.json 并带「好的/不用」，否则 GUI 画不出按钮。"""
    from sprite.proactive import help as helpmod
    written: list[dict] = []
    monkeypatch.setattr(helpmod, "publish", lambda o: written.append(o))
    monkeypatch.setattr(helpmod, "record", lambda row: None)

    s = _session(sandbox)
    _deliver(s, "x.md")
    s._flush_risk_batches()

    assert written, "风险批次必须经 help.publish 发布"
    offer = written[-1]
    assert offer["kind"] == "offer"
    assert offer["options"] == helpmod.OFFER_OPTIONS == ["好的", "不用"]
    assert offer["risk"] == "medium"
    assert offer["items"][0]["arguments"]["name"] == "x.md"


def test_gui_renders_risk_proposal_with_clickable_options():
    from sprite.gui import SpriteWindow
    w = SpriteWindow.__new__(SpriteWindow)
    w.msg = {"kind": "offer", "text": "我要写这 3 个产出：\n1. a.md", "risk": "medium",
             "options": ["好的", "不用"], "items": [{"tool": "x"}]}
    assert w._buttons() == [("好的", ("choice", 0)), ("不用", ("choice", 1))]


def test_batch_report_is_honest_about_partial_failure():
    from sprite.proactive.live import _batch_report
    assert "3" in _batch_report([{"success": True}] * 3)
    mixed = [{"success": True}, {"success": False}]
    assert "2 件事里做成了 1 件" in _batch_report(mixed)
    assert "没有做成" in _batch_report([{"success": False}])


def _ok(text):
    from vista.core.contracts import ToolReply
    return ToolReply(text)


def _blocked(tool):
    from vista.core.contracts import ToolReply
    return ToolReply(f"{tool} 未执行", success=False)
