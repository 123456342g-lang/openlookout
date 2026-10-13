import json, os, time
from pathlib import Path
from sprite import eval_risk, risk as R
from sprite.framework import Engine, Registry, Scenario, Problem, Action
from sprite.pressure import PressureDetector
from sprite.sysstate import Snapshot, Proc, FakeController
from sprite.scenarios import resource, extras
from sprite.quarantine import Quarantine


def test_wrongful_action_rate_zero_on_adversarial_corpus():
    r = eval_risk.evaluate()
    assert r["must_not_touch"] > 100 and r["wrongful_action_rate"] == 0.0 and r["missed_safe_rate"] == 0.0, r


def test_proc_traps_never_safe():
    P = R.classify_proc
    assert P(Proc(1, "chrome", 900, idle_s=3000, cmdline="x --type=renderer")).level == "safe"
    for bad in (Proc(2, "chrome", 900, idle_s=3000, cmdline="--type=renderer", foreground_tree=True),
                Proc(3, "chrome", 900, idle_s=3000, cmdline="--type=renderer", audio=True),
                Proc(4, "chrome", 900, idle_s=30, cmdline="--type=renderer"),
                Proc(5, "winword", 900, idle_s=3000, has_window=True, title="a - Word *"),
                Proc(6, "node", 900, idle_s=3000, children=2), Proc(7, "explorer", 300, idle_s=9999),
                Proc(8, "unknown_tool", 900, idle_s=9999), Proc(9, "msedgewebview2", 300, idle_s=9999, parent_alive=True),
                Proc(10, "code", 900, idle_s=9999, has_window=True, title="main.py")):
        assert P(bad).level == "high", bad.name


def test_node_modules_in_use_not_touched(tmp_path):
    proj = tmp_path / "p"; (proj / "node_modules").mkdir(parents=True)
    for f in ("package.json", "package-lock.json"):
        (proj / f).write_text("{}"); os.utime(proj / f, (1, 1))
    env = R.Env(now=time.time(), running=[Proc(1, "node", 100, cwd=str(proj))])
    assert R.classify_dir(proj / "node_modules", env).level == "high"
    assert R.classify_dir(proj / "node_modules", R.Env(now=time.time())).level == "medium"       # 不在用也只是“要问”


def test_detector_is_edge_triggered_not_periodic():
    d = PressureDetector(); t = 1000.0
    S = lambda t, a: Snapshot(t, 16000, a, {"C:": (100, 50)})
    assert d.update(S(t, 9000)) == []
    assert len(d.update(S(t + 60, 1000))) == 1
    for i in range(5): assert d.update(S(t + 120 + i * 60, 1000)) == []        # 持续危急不重复
    d2 = PressureDetector(); d2.update(S(t, 9000))
    assert len(d2.update(S(t + 60, 4500))) == 1                                  # 还没到阈值，但下降太快


def _toy(calls):
    def mk(kind, risk, rev="full", fail=False):
        return Action(kind, kind, risk, rev, relief=1, run=lambda: calls.append(("run", kind)) or {},
                      verify=lambda r: not fail, undo=lambda r: calls.append(("undo", kind)), confident=True)
    def propose(pb, w): return [mk("a_safe", "safe"), mk("b_med", "medium"), mk("c_high", "high", "none"), mk("d_safe_irrev", "safe", "none"), mk("e_bad", "safe", fail=True)]
    return Scenario("toy", lambda w: [Problem("toy", 0.5, "x", need=3)] if w else [], propose)


def test_engine_policy_batch_and_learning(tmp_path):
    calls = []; reg = Registry(); reg.register(_toy(calls)); e = Engine(reg, tmp_path); e.cooldown_s = 0
    out = e.step(True)[0]
    ran = [c for c in calls if c[0] == "run"]
    assert ("run", "a_safe") in ran and ("run", "c_high") not in ran and ("run", "d_safe_irrev") not in ran and ("run", "b_med") in ran          # 中风险但可还原：直接做
    assert ("undo", "e_bad") in calls                               # 校验失败即回滚
    assert not out.asks and not hasattr(e, "approve")              # 没有询问流程
    assert len(out.skipped) >= 3
    # 学习：同类动作被撤销两次后改成“要问”，三次后停用
    a = out.acted[0]; e.undo(a.id)
    for _ in range(2):
        o = e.step(True)[0]
        if o.acted:
            e.undo(o.acted[0].id)
    assert e.ledger.trust("a_safe") == "off"
    o = e.step(True)[0]
    assert not any(x.kind == "a_safe" for x in o.acted)


def test_new_scenario_by_registration_only(tmp_path):
    # 日志暴涨
    logs = tmp_path / "logs"; logs.mkdir(); big = logs / "app.log"; big.write_bytes(b"a" * 1000)
    reg = Registry(); reg.register(extras.log_runaway(logs, grow_mb=1))
    from sprite.risk import Env
    w = resource.World(env=Env(now=time.time()), q=Quarantine(tmp_path / "h"))
    e = Engine(reg, tmp_path / "h2"); (tmp_path / "h2").mkdir(exist_ok=True)
    assert e.step(w) == []
    big.write_bytes(b"a" * (3 * 2**20)); orig = big.read_bytes()
    out = e.step(w)[0]
    assert out.acted and not big.exists()
    assert e.undo(out.acted[0].id) and big.read_bytes() == orig
    big.write_bytes(b"a" * (6 * 2**20)); w.env.open_paths = {str(big)}                # 正在被写入 -> 不碰
    out = e.step(w)[0]
    assert not out.acted and big.exists()
    # 桌面堆积
    desk = tmp_path / "Desktop"; desk.mkdir()
    for i in range(16):
        p = desk / f"f{i}.pdf"; p.write_text(str(i)); os.utime(p, (1, 1))
    (desk / "today.docx").write_text("fresh")                                         # 刚动过的不碰
    reg2 = Registry(); reg2.register(extras.desktop_pile(desk, 15)); e2 = Engine(reg2, tmp_path / "h2")
    out = e2.step(w)[0]; assert out.acted and (desk / "today.docx").exists()
    assert (desk / "整理" / "文档" / "f3.pdf").exists() and (desk / "整理" / "_还原映射.json").exists()
    assert e2.undo(out.acted[0].id) and (desk / "f3.pdf").read_text() == "3" and not (desk / "整理" / "_还原映射.json").exists()


def test_toctou_file_changed_after_planning_is_skipped(tmp_path):
    T = tmp_path / "Temp"; T.mkdir(); f = T / "a.tmp"; f.write_text("x"); os.utime(f, (1, 1))
    env = R.Env(now=time.time(), temp_dirs=[T]); w = resource.World(env=env, q=Quarantine(tmp_path / "h"))
    items = [(f, R.classify_file(f, env))]
    act = resource._mk_quarantine_action(w, items, "临时文件", "safe")
    os.utime(f, None)                                   # 用户此刻又改了它
    assert not act.dry_run()
    r = act.run(); assert f.exists() and r["ids"] == []


def test_quarantine_restore_never_overwrites_and_verifies(tmp_path):
    q = Quarantine(tmp_path / "h"); f = tmp_path / "x.bin"; f.write_bytes(b"1234")
    e = q.put(f, "t"); assert not f.exists()
    f.write_bytes(b"new")                                # 原位置已被占用
    dst = q.restore(e["id"]); assert f.read_bytes() == b"new" and dst.read_bytes() == b"1234" and dst != f


def test_demo_end_to_end(tmp_path):
    from sprite import demo_pressure
    res, s = demo_pressure.main(tmp_path / "out")
    assert res["trap_changed"] == [] and res["undo_ok"] and res["safes_restored"] and res["resumed_on_foreground"]
    assert len(res["first_say"]) == 1 and "可还原" in res["first_say"][0] and "要你定" not in res["first_say"][0] and len(res["first_say"][0]) <= 40   # 只汇报一行，不问
    assert 101 in res["suspended_pids"] and 104 not in res["suspended_pids"] and 106 not in res["suspended_pids"]


def test_no_pressure_no_cleanup_and_stop_when_relieved(tmp_path):
    calls = []; level = [0.0]; need = [100.0]
    def mk(kind, relief):
        def run():
            calls.append(kind); need[0] = max(0.0, need[0] - relief); return {}
        return Action(kind, kind, "safe", "full", relief=relief, run=run, undo=lambda r: None)
    def propose(pb, w): return [mk("small", 1), mk("big", 60), mk("mid", 30), mk("tiny", 3)]
    def detect(w): return [Problem("p", 0.8, "x", need=100, key="p1", recheck=lambda: need[0] if level[0] else 0)]
    reg = Registry(); reg.register(Scenario("t", detect, propose, auto_caps=dict(items=9, bytes=1 << 40)))
    e = Engine(reg, tmp_path, gate=dict(min_value_s=0)); e.batch_interval_s = 0; e.retry_interval_s = 0; e.resolved_cool_s = 0
    outs0 = e.step(1); assert (outs0 == [] or outs0[0].acted == []) and calls == []  # 没压力：什么都不做、不挂起
    level[0] = 1.0
    out = e.step(1)[0]
    assert calls and calls[0] == "big"                               # 先做回收量最大的
    assert "tiny" not in calls and "small" not in calls              # 边际收益太小的不做


def test_open_problem_keeps_going_until_resolved(tmp_path):
    """检测器只边沿报一次；问题未解除时 Engine 持续推进，找不到动作也不长冷却闭嘴。"""
    calls = []; need = [100.0]; allow = [False]
    def mk(kind, relief):
        def run():
            if not allow[0]:
                raise RuntimeError("not yet")
            calls.append(kind); need[0] = max(0.0, need[0] - relief); return {}
        return Action(kind, kind, "safe", "full", relief=relief, run=run, verify=lambda r: True, undo=lambda r: None)
    fired = [False]
    def detect(w):
        if fired[0]:
            return []
        fired[0] = True
        return [Problem("mem", 0.9, "edge", need=100, key="mem", recheck=lambda: need[0])]
    def propose(pb, w):
        return [mk("big", 60), mk("mid", 40)]
    reg = Registry(); reg.register(Scenario("t", detect, propose, auto_caps=dict(items=9, bytes=1 << 40)))
    e = Engine(reg, tmp_path, gate=dict(min_value_s=0)); e.batch_interval_s = 0; e.retry_interval_s = 0; e.resolved_cool_s = 0
    out1 = e.step(1)
    assert e.open
    assert calls == []
    allow[0] = True
    out2 = e.step(1)
    assert out2 and out2[0].acted and calls[0] == "big"
    for _ in range(5):
        if not e.open:
            break
        e.step(1)
    assert need[0] <= 0 and not e.open
    n = len(calls)
    later = e.step(1)
    assert later == [] or all(not o.acted for o in later)
    assert len(calls) == n
