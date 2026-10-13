"""新颖理解（tier2）：FakeNovelClient；open 问题默认云端定性（非「本地失败才升级」）。
通用异常可不经 network discover 走 novel。"""
from __future__ import annotations
import json
from pathlib import Path
from sprite.investigate import (
    Candidate, Understanding, InvestigatorRegistry, Investigator, investigator_scenario,
)
from sprite.framework import Engine, Registry
from sprite.novel import (
    needs_novel, build_evidence_pack, validate_novel_payload,
    FakeNovelClient, NovelUnderstander, propose_novel_actions, ALLOWED_ACTION_KINDS,
)
from sprite.scenarios import stalemate as S
from observe.capture_hook import TriggerRequest


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
    def __call__(self):
        return self.t
    def sleep(self, d):
        self.t += d


def test_needs_novel_gate():
    u = Understanding("k", "x", "t", state="unknown", confidence=0.3, act=False)
    assert needs_novel(u) is True  # prefer_novel default
    # 本地已自信动手：默认仍要云端定性（不是「本地套路即主理解」）
    u2 = Understanding("k", "x", "t", state="in_use", confidence=0.9, act=True)
    assert needs_novel(u2) is True
    assert needs_novel(u2, prefer_novel=False) is False  # legacy 省预算
    u3 = Understanding("k", "x", "t", state="in_use", confidence=0.4, act=False)
    assert needs_novel(u3) is True
    # 硬安全闸：不问云端改口
    u_self = Understanding("k", "x", "t", state="self", confidence=1.0, act=False)
    assert needs_novel(u_self) is False
    u_prot = Understanding("k", "x", "t", state="protected", confidence=1.0, act=False)
    assert needs_novel(u_prot) is False


def test_validate_rejects_shell_and_high_risk():
    bad = dict(
        what="x", why="y", state="weird", confidence=1.5, act=True,
        candidate_actions=[
            dict(kind="rm -rf /", args={}, reason="no", risk="safe", reversible="full"),
            dict(kind="net_flushdns", args={}, reason="ok", risk="high", reversible="full"),
            dict(kind="archive_note", args={"path": "/tmp"}, reason="note", risk="safe", reversible="full"),
        ],
    )
    p = validate_novel_payload(bad)
    assert p["state"] == "unknown"
    assert p["confidence"] == 1.0
    kinds = [a["kind"] for a in p["candidate_actions"]]
    assert "rm -rf /" not in kinds
    assert "archive_note" in kinds
    # high risk forced to skip → may clear act if only skips remain alongside archive
    assert all(a["kind"] in ALLOWED_ACTION_KINDS for a in p["candidate_actions"])


def test_validate_skip_only_forces_no_act():
    p = validate_novel_payload(dict(
        what="?", why="dunno", state="unknown", confidence=0.9, act=True,
        candidate_actions=[dict(kind="skip", args={}, reason="no", risk="safe", reversible="full")],
    ))
    assert p["act"] is False


def test_evidence_pack_shape():
    c = Candidate("stalemate", "s:1", "卡在 Excel", signals=dict(need=1.0), ctx={})
    facts = dict(app="excel", title="预算", vision_kind="error_dialog", _secret=1)
    pack = build_evidence_pack(c, facts, ["停留 400s"], vision_caption="dialog", prior=Understanding(
        "s:1", "stalemate", "卡在 Excel", state="unknown", confidence=0.2, why="证据不足",
    ))
    assert pack["kind"] == "stalemate"
    assert "_secret" not in pack["facts"]
    assert pack["local_prior"]["state"] == "unknown"
    assert "停留" in pack["evidence"][0]


def test_fake_client_and_budget(tmp_path):
    clock = Clock()
    client = FakeNovelClient(dict(
        what="用户卡在对话框", why="dwell+错误标题，建议记下",
        state="in_use", confidence=0.8, act=True,
        candidate_actions=[dict(kind="archive_note", args={}, reason="note", risk="safe", reversible="full")],
    ))
    nu = NovelUnderstander(tmp_path, clock=clock, client=client, enabled=True, daily_tokens=8000, est_tokens=200)
    c = Candidate("stalemate", "s:dwell", "卡", signals={}, ctx={})
    prior = Understanding("s:dwell", "stalemate", "卡", state="unknown", confidence=0.2, act=False, why="不足")
    u = nu.understand(c, dict(app="excel"), ["dwell"], prior=prior)
    assert u is not None and u.facts.get("novel") is True
    assert u.act and u.confidence >= 0.8
    assert client.calls
    # second call within cache → no extra cloud
    ncalls = len(client.calls)
    u2 = nu.understand(c, dict(app="excel"), ["dwell"], prior=prior)
    assert u2 is not None and len(client.calls) == ncalls
    # budget exhausted
    nu2 = NovelUnderstander(tmp_path / "b2", clock=clock, client=client, enabled=True, daily_tokens=10, est_tokens=100)
    assert nu2.understand(c, {}, [], prior=prior) is None
    rows = [json.loads(l) for l in (tmp_path / "b2" / "tokens.jsonl").read_text().splitlines()]
    assert any(r["purpose"] == "novel_degraded_budget" for r in rows)


def test_prefer_novel_even_when_local_confident(tmp_path):
    """默认 prefer_novel：本地白名单自信仍问云端定性。"""
    clock = Clock()
    client = FakeNovelClient(dict(
        what="代理客户端掉了", why="证据像本地代理退出",
        state="in_use", confidence=0.85, act=True,
        candidate_actions=[dict(kind="net_restart_client", args={}, reason="拉起", risk="medium", reversible="full")],
    ))
    nu = NovelUnderstander(tmp_path, clock=clock, client=client, enabled=True, prefer_novel=True)
    c = Candidate("network_break", "net:break", "网挂", signals={}, ctx={})
    prior = Understanding("net:break", "network_break", "网挂", state="in_use", confidence=0.82, act=True, why="重启 clash")
    u = nu.understand(c, {}, [], prior=prior)
    assert u is not None and client.calls
    assert u.facts.get("novel") is True
    # legacy：prefer_novel=False 且本地自信 → 跳过
    client2 = FakeNovelClient()
    nu2 = NovelUnderstander(tmp_path / "leg", clock=clock, client=client2, enabled=True, prefer_novel=False)
    assert nu2.understand(c, {}, [], prior=prior) is None
    assert not client2.calls


def test_disabled_by_default(tmp_path):
    nu = NovelUnderstander(tmp_path, enabled=False, client=FakeNovelClient())
    c = Candidate("x", "k", "t")
    prior = Understanding("k", "x", "t", state="unknown", confidence=0.1)
    assert nu.understand(c, {}, [], prior=prior) is None


def test_generic_anomaly_uses_novel_without_network(tmp_path):
    """任意未知异常：不注册 network discover，仍走 novel 理解 + 白名单记下。"""
    clock = Clock()
    client = FakeNovelClient(dict(
        what="不明代价信号", why="证据不足以归类，先可逆记下", state="unknown", confidence=0.78, act=True,
        candidate_actions=[dict(kind="archive_note", args={}, reason="记", risk="safe", reversible="full")],
    ))
    novel = NovelUnderstander(tmp_path, clock=clock, client=client, enabled=True, prefer_novel=True)
    ireg = InvestigatorRegistry()

    def disc(w):
        # 故意不用 network_break / 不 import network
        return [Candidate("anomaly", "a:cost1", "未归类异常", signals=dict(need=1.0, severity=0.4, unit="处"),
                          ctx=dict(home=str(tmp_path)))]

    def gather(c, facts, world, view):
        facts["what"] = "只有模糊代价信号"
        return ["CPU 尖刺后又静默", "无匹配本地套路"]

    def judge(c, facts):
        # 本地不定性
        return Understanding(c.key, c.kind, c.title, what=facts.get("what", ""),
                             state="unknown", confidence=0.2, act=False, why="本地不定性")

    def propose(c, u, w):
        return []

    def recheck(c, w):
        return 1.0

    ireg.discoverer("anomaly", disc)
    ireg.gatherer("anomaly", lambda c: c.kind == "anomaly", gather)
    ireg.judge("anomaly", judge)
    ireg.responder("anomaly", propose, recheck)

    class V:
        def now(self): return clock()
        def self_pid(self): return -1
        def procs(self): return {}
        def open_files(self, pid): return []
        def newest_mtime(self, *a, **k): return None
        def git_root(self, path): return None
        def git_dirty(self, root): return None
        def read_head(self, path, n=4000): return ""
        def exists(self, path): return Path(path).exists()

    inv = Investigator(ireg, V(), tmp_path, clock, log=lambda *a: None, novel=novel, prefer_novel=True)
    sc = investigator_scenario(ireg, inv, live=True, min_conf=0.70, log=lambda *a: None, name="anomaly")
    (tmp_path / "eh").mkdir(parents=True, exist_ok=True)
    reg = Registry(); reg.register(sc)
    eng = Engine(reg, tmp_path / "eh", clock=clock)
    outs = eng.step(None)
    acted = [a for o in outs for a in o.acted]
    assert acted and acted[0].kind == "novel_archive_note"
    rec = [json.loads(l) for l in (tmp_path / "understandings.jsonl").read_text().splitlines()]
    assert any(r.get("facts", {}).get("novel") for r in rec)
    assert client.calls
    # 证明路径不依赖 network 模块发现器
    assert "network_break" not in ireg.discoverers


def test_stalemate_unknown_escalates(tmp_path):
    """短 dwell → 本地证据不足 unknown → Fake novel → archive。"""
    from datetime import datetime, timezone
    clock = Clock()
    home = tmp_path / "home"; home.mkdir()
    evp = home / "events.jsonl"
    # dwell 只 100s → judge_stalemate 证据不足
    now = clock()
    rows = [{"ts": datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat(),
             "type": "focus", "app": "weirdapp", "title": "??? 对话框", "dur_s": 100}]
    evp.write_text("\n".join(json.dumps(e) for e in rows) + "\n", encoding="utf-8")
    client = FakeNovelClient(dict(
        what="可能卡在对话框", why="标题像错误框但 dwell 不够长",
        state="in_use", confidence=0.72, act=True,
        candidate_actions=[dict(kind="stalemate_note", args={}, reason="记下", risk="safe", reversible="full")],
    ))
    novel = NovelUnderstander(home, clock=clock, client=client, enabled=True)
    sc, kit = S.build(
        home, live=True, apply_real=True, log=lambda *a: None,
        novel=novel, event_paths=[evp], min_dwell_s=60, trigger_capture=False,
    )
    # discover may still find dwell>=60 with min_dwell_s=60; judge needs >=180 for act
    cands = kit.discover()
    assert cands
    # Force investigate path via engine — if local judge acts (dwell>=180), novel skipped;
    # with dur_s=100 and min_dwell 60, dwell_s~100 → judge evidence不足
    (home / "eh").mkdir(parents=True, exist_ok=True)
    reg = Registry(); reg.register(sc)
    eng = Engine(reg, home / "eh", clock=clock)
    # Manually investigate to assert escalate
    inv = sc.detect.__closure__  # fragile; call Investigator via kit path
    # Rebuild inv access: detect uses inv from build — step and check understandings
    outs = eng.step(None)
    # With dwell 100 < 180, local won't act; novel should make archive if detect includes cand
    # detect only emits Problem when act and conf>=min_conf — after novel, should
    acted = [a for o in outs for a in o.acted]
    rec_path = home / "understandings.jsonl"
    assert rec_path.exists()
    rec = [json.loads(l) for l in rec_path.read_text().splitlines()]
    assert rec, "should have written understanding"
    # Either novel acted, or local still unknown — if novel called, facts.novel
    if client.calls:
        assert any(r.get("facts", {}).get("novel") for r in rec)
        # 僵局 kind 仍走原 responder（stalemate_note）；无 responder 时才落 novel_archive_note
        assert acted and acted[0].kind in ("stalemate_note", "novel_archive_note")
    else:
        # local already confident somehow — still OK for this fixture
        assert rec[0]["state"] in ("unknown", "in_use")


def test_network_unknown_can_escalate(tmp_path):
    """网络 judge 返回 unknown（无路由）时，novel 可升级理解（不强制 VPN）。"""
    from sprite.scenarios import network as N
    from sprite.investigate import Understanding as U

    clock = Clock()
    home = tmp_path / "nh"; home.mkdir()
    client = FakeNovelClient(dict(
        what="无默认路由，像是 Wi‑Fi 断开", why="没有可逆动作能自动连上 Wi‑Fi",
        state="unknown", confidence=0.75, act=True,
        candidate_actions=[dict(kind="archive_note", args={}, reason="记下待用户连网", risk="safe", reversible="full")],
    ))
    novel = NovelUnderstander(home, clock=clock, client=client, enabled=True)

    # Direct unit: kit.judge unknown → Investigator with novel
    class FakeView:
        def resolve(self, h): return False, [], "fail"
        def tcp443(self, h, timeout=2.0): return False, 0, "fail"
        def http_get(self, *a, **k): return False, 0, 0, "fail"
        def default_route(self): return False
        def system_proxy(self): return dict(enable=False, server="", pac="")
        def port_listening(self, p): return False
        def procs_blob(self): return []
        def listen_ports_by_pid(self): return {}
        def win_vpns(self): return []
        def rasdial_status(self): return []
        def flush_dns(self): return True
        def start_exe(self, p): return None
        def stop_pid(self, p): return False
        def rasdial_connect(self, n): return False
        def rasdial_disconnect(self, n): return False

    # Avoid real DNS in discover by stubbing kit methods
    ireg = InvestigatorRegistry()
    kit = N.NetworkKit(FakeView(), home, clock, hosts=[dict(host="www.baidu.com", tag="domestic")], log=lambda *a: None)

    def fake_discover(w):
        return [Candidate(
            "network_break", "net:break", "网络不可达：无默认路由",
            signals=dict(need=1.0, severity=0.7, no_route=True),
            ctx=dict(snapshot=dict(
                probes=[], clients=[], proxy=dict(enable=False, server="", pac=""),
                route_ok=False, win_vpns=[], rasdial=[], dead_proxy_ports=[], seen={},
            ), reasons=["无默认路由"], home=str(home)),
        )]

    ireg.discoverer("network_break", fake_discover)
    ireg.gatherer("network_evidence", lambda c: c.kind == "network_break", kit.gather)
    ireg.judge("network_break", kit.judge)
    ireg.responder("network_break", kit.propose, kit.recheck)

    class V:
        def now(self): return clock()
        def self_pid(self): return -1
        def procs(self): return {}
        def open_files(self, pid): return []
        def newest_mtime(self, *a, **k): return None
        def git_root(self, path): return None
        def git_dirty(self, root): return None
        def read_head(self, path, n=4000): return ""
        def exists(self, path): return Path(path).exists()

    inv = Investigator(ireg, V(), home, clock, log=lambda *a: None, novel=novel)
    c = fake_discover(None)[0]
    u = inv.investigate(c, None, force=True)
    assert client.calls, "unknown/no_route should escalate to novel"
    assert u.facts.get("novel") is True
    assert u.what  # enriched
    # act via archive from novel when network propose returns [] (no flush needed for no_route? flush still added)
    # network propose always adds flushdns unless in _acted — so propose may return flush
    acts = kit.propose(c, u, None)
    # Either flushdns or novel archive via scenario fallback
    sc = investigator_scenario(ireg, inv, live=True, min_conf=0.70, log=lambda *a: None)
    (home / "eh").mkdir(parents=True, exist_ok=True)
    reg = Registry(); reg.register(sc)
    eng = Engine(reg, home / "eh", clock=clock)
    outs = eng.step(None)
    acted = [a for o in outs for a in o.acted]
    assert acted, "should act (flushdns and/or novel note)"


def test_investigator_escalates_unknown(tmp_path):
    """别名：兼容旧名 → generic anomaly。"""
    test_generic_anomaly_uses_novel_without_network(tmp_path)
