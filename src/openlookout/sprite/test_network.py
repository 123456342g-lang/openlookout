"""network_break 场景：假探针测试（不碰真实网络/VPN）。"""
from __future__ import annotations
import json
from pathlib import Path
from sprite.framework import Engine, Registry
from sprite.investigate import InvestigatorRegistry, Investigator, investigator_scenario
from sprite.scenarios import network as N


class Clock:
    def __init__(s, t=1_800_000_000.0): s.t = t
    def __call__(s): return s.t
    def sleep(s, d): s.t += d


class FakeNet:
    def __init__(s, clock):
        s.clock = clock
        s.route_ok = True
        s.proxy = dict(env_http="", env_https="", enable=False, server="", pac="")
        s.listen = set()
        s.dns = {}          # host -> (ok, addrs, err)
        s.tcp = {}           # host -> (ok, ms, err)
        s.clients_rows = []  # for procs_blob
        s._win_vpns = []
        s.ras = []
        s.flushed = 0
        s.started = []
        s.stopped = []
        s.ras_connects = []
        s.ras_disconnects = []
        s._pid = 5000
    def now(s): return s.clock()
    def resolve(s, host): return s.dns.get(host, (True, ["1.2.3.4"], ""))
    def tcp443(s, host): return s.tcp.get(host, (True, 10.0, ""))
    def default_route(s): return s.route_ok
    def system_proxy(s): return dict(s.proxy)
    def port_listening(s, port): return int(port) in s.listen
    def listen_ports_by_pid(s):
        # map fake pids from rows
        out = {}
        for pid, name, exe, cmd in s.clients_rows:
            if "mihomo" in name.lower() or "clash" in name.lower():
                out[pid] = list(s.listen) or [7897]
        return out
    def procs_blob(s): return list(s.clients_rows)
    def win_vpns(s): return list(s._win_vpns)
    def rasdial_status(s): return list(s.ras)
    def flush_dns(s): s.flushed += 1; return True
    def start_exe(s, path):
        s._pid += 1; s.started.append(path)
        # simulate client now running
        s.clients_rows.append((s._pid, Path(path).name, path, path))
        s.listen.add(7897)
        return s._pid
    def stop_pid(s, pid): s.stopped.append(pid); s.clients_rows = [r for r in s.clients_rows if r[0] != pid]; return True
    def rasdial_connect(s, name):
        s.ras_connects.append(name); s.ras = [name]
        for v in s._win_vpns:
            if v.name == name: v.status = "Connected"
        return True
    def rasdial_disconnect(s, name):
        s.ras_disconnects.append(name); s.ras = [x for x in s.ras if x != name]
        for v in s._win_vpns:
            if v.name == name: v.status = "Disconnected"
        return True


def fail_all(view):
    for h in ("www.baidu.com", "www.qq.com", "www.google.com", "github.com", "1.1.1.1"):
        view.dns[h] = (True, ["9.9.9.9"], "")
        view.tcp[h] = (False, 2500.0, "Timeout")


def mk(tmp_path, view, live=True, poll_s=0):
    clock = view.clock; home = tmp_path / "h"; home.mkdir()
    kit = N.NetworkKit(view, home, clock, sleep=clock.sleep)
    ireg = InvestigatorRegistry(); N.register_all(ireg, kit, clock, poll_s=poll_s)
    # skip generic pid gatherers noise
    inv = Investigator(ireg, view, home, clock, log=lambda *a: None)
    sc = investigator_scenario(ireg, inv, live=live, log=lambda *a: None, name="investigate_network")
    reg = Registry(); reg.register(sc)
    (home / "eh").mkdir(); eng = Engine(reg, home / "eh", clock=clock)
    return eng, kit, inv, home, sc


def test_healthy_network_no_action(tmp_path):
    view = FakeNet(Clock())
    for h in ("www.baidu.com", "www.qq.com", "www.google.com", "github.com", "1.1.1.1"):
        view.tcp[h] = (True, 5.0, "")
    e, kit, inv, home, sc = mk(tmp_path, view)
    assert [a for o in e.step(None) for a in o.acted] == []
    assert kit.discover(None) == []


def test_unreachable_flushdns_then_open_until_resolved(tmp_path):
    view = FakeNet(Clock()); fail_all(view)
    e, kit, inv, home, sc = mk(tmp_path, view)
    outs = e.step(None)
    acted = [a for o in outs for a in o.acted]
    assert acted and acted[0].kind == "net_flushdns" and view.flushed == 1
    # still broken -> open problem keeps trying; next step may restart if we seed seen client
    rec = [json.loads(l) for l in (home / "understandings.jsonl").read_text("utf-8").splitlines()]
    assert rec and rec[-1]["act"] and rec[-1]["kind"] == "network_break"


def test_restart_seen_client_when_down(tmp_path):
    clock = Clock(); view = FakeNet(clock); fail_all(view)
    exe = str(tmp_path / "ClashVergeRev" / "clash-verge.exe")
    Path(exe).parent.mkdir(parents=True); Path(exe).write_text("x")
    # previously seen running
    home = tmp_path / "h"; home.mkdir()
    (home / "network_seen_clients.json").write_text(json.dumps({
        "clash_verge": dict(label="Clash Verge", start_exe=exe, install=str(Path(exe).parent), last_seen=clock()-100, listen_ports=[7897])
    }), "utf-8")
    kit = N.NetworkKit(view, home, clock, sleep=clock.sleep)
    ireg = InvestigatorRegistry(); N.register_all(ireg, kit, clock, poll_s=0)
    inv = Investigator(ireg, view, home, clock, log=lambda *a: None)
    sc = investigator_scenario(ireg, inv, live=True, log=lambda *a: None)
    reg = Registry(); reg.register(sc); (home / "eh").mkdir()
    e = Engine(reg, home / "eh", clock=clock)
    # first action flushdns
    outs = e.step(None); kinds = [a.kind for o in outs for a in o.acted]
    assert "net_flushdns" in kinds
    # Engine batch_interval_s=15：推时钟再试下一拍
    clock.t += 20
    outs2 = e.step(None); kinds2 = [a.kind for o in outs2 for a in o.acted]
    assert kinds2 == ["net_restart_client"] and view.started == [exe]
    # undo stops the pid we started
    aid = [a.id for o in outs2 for a in o.acted][0]
    assert e.undo(aid) and view.stopped


def test_rasdial_when_win_vpn_disconnected(tmp_path):
    clock = Clock(); view = FakeNet(clock); fail_all(view)
    # foreign blocked pattern: domestic ok foreign fail — but fail_all fails all; set domestic ok
    view.tcp["www.baidu.com"] = (True, 5.0, ""); view.tcp["www.qq.com"] = (True, 5.0, "")
    view._win_vpns = [N.WinVpn("WorkVPN", "Disconnected", "vpn.example.com")]
    e, kit, inv, home, sc = mk(tmp_path, view)
    # may flushdns first
    outs = e.step(None); kinds = [a.kind for o in outs for a in o.acted]
    assert kinds[0] in ("net_flushdns", "net_rasdial")
    if kinds[0] == "net_flushdns":
        view.clock.t += 20
        outs = e.step(None); kinds = [a.kind for o in outs for a in o.acted]
    assert kinds == ["net_rasdial"] and view.ras_connects == ["WorkVPN"]
    aid = [a.id for o in outs for a in o.acted][0]
    assert e.undo(aid) and view.ras_disconnects == ["WorkVPN"]


def test_no_route_does_not_act(tmp_path):
    view = FakeNet(Clock()); fail_all(view); view.route_ok = False
    e, kit, inv, home, sc = mk(tmp_path, view)
    assert [a for o in e.step(None) for a in o.acted] == []
    rec = [json.loads(l) for l in (home / "understandings.jsonl").read_text("utf-8").splitlines()]
    assert rec and not rec[-1]["act"] and rec[-1]["confidence"] < 0.75


def test_dry_mode_plans_only(tmp_path):
    view = FakeNet(Clock()); fail_all(view)
    e, kit, inv, home, sc = mk(tmp_path, view, live=False)
    assert [a for o in e.step(None) for a in o.acted] == [] and sc.plans
    assert (home / "understandings.jsonl").exists()


def test_recheck_clears_when_half_ok(tmp_path):
    view = FakeNet(Clock()); fail_all(view)
    e, kit, inv, home, sc = mk(tmp_path, view)
    cands = kit.discover(None); assert cands
    assert kit.recheck(cands[0], None) == 1.0
    for h in ("www.baidu.com", "www.qq.com", "www.google.com"):
        view.tcp[h] = (True, 5.0, "")
    assert kit.recheck(cands[0], None) == 0.0


def test_proxy_dead_port_signal(tmp_path):
    view = FakeNet(Clock()); fail_all(view)
    view.proxy = dict(env_http="", env_https="", enable=1, server="127.0.0.1:7897", pac="")
    # port not listening
    e, kit, inv, home, sc = mk(tmp_path, view)
    cands = kit.discover(None)
    assert cands and cands[0].signals.get("proxy_dead") == [7897]


def test_never_deletes_or_installs(tmp_path):
    """Responders only flushdns / start_exe / rasdial — no delete/install kinds."""
    view = FakeNet(Clock()); fail_all(view)
    exe = str(tmp_path / "v2rayN" / "v2rayN.exe"); Path(exe).parent.mkdir(); Path(exe).write_bytes(b"x")
    home = tmp_path / "h"; home.mkdir()
    (home / "network_seen_clients.json").write_text(json.dumps({
        "v2rayn": dict(label="v2rayN", start_exe=exe, install=str(Path(exe).parent), last_seen=1, listen_ports=[10808])
    }), "utf-8")
    kit = N.NetworkKit(view, home, view.clock, sleep=view.clock.sleep)
    u_facts = dict(cause="proxy_or_client_down", restartable=[dict(family="v2rayn", label="v2rayN", start_exe=exe)], disconnected_vpns=[], what="x", owner="y")
    from sprite.investigate import Understanding, Candidate
    c = Candidate("network_break", "net:break", "t", dict(need=1.0), {})
    u = Understanding("net:break", "network_break", "t", act=True, confidence=0.9, why="test", facts=u_facts)
    acts = kit.propose(c, u, None)
    assert all(a.kind in ("net_flushdns", "net_restart_client", "net_rasdial") for a in acts)
