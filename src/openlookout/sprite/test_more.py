import json, time
from sprite import eval_all, tiers, sim_tokens
from sprite.framework import Engine, Registry, Scenario, Problem, Action


def test_all_scenarios_zero_wrongful_actions():
    r = eval_all.evaluate()
    assert r["traps"] >= 300 and r["wrongful"] == 0 and r["missed"] == 0, r


def test_value_gate_skips_trivial_and_logs_estimates(tmp_path):
    ran = []
    big = Action("big", "big", "safe", "full", relief=5, run=lambda: ran.append("big") or {}); tiny = Action("tiny", "tiny", "safe", "full", relief=0.001, run=lambda: ran.append("tiny") or {})
    zero = Action("later", "later", "safe", "full", relief=0.001, value_s=100, later="你迟早得自己整理", run=lambda: ran.append("later") or {})
    sc = Scenario("t", lambda w: [Problem("p", 0.6, "x", need=10)], lambda pb, w: [big, tiny, zero])
    reg = Registry(); reg.register(sc); e = Engine(reg, tmp_path); out = e.step(True)[0]
    assert "big" in ran and "tiny" not in ran and "later" in ran
    log = [json.loads(l) for l in (tmp_path / "judgments_actions.jsonl").read_text().splitlines()]
    assert any(x["decision"] == "skip_low_value" and x["action"] == "tiny" for x in log)
    assert all("value_s" in x for x in log if x["decision"] == "auto") and next(x for x in log if x["action"] == "later")["later"]


def test_model_can_never_promote_to_safe_and_rules_cache(tmp_path):
    calls = []
    def cloud(s, u): calls.append(1); return ('{"verdict":"safe","reason":"随便"}', 100, 50)
    r = tiers.Router(tmp_path, cloud=cloud)
    v, _ = r.classify_unknown("sigA", "ctx", 500)
    assert v == "high" and len(calls) == 1                     # 模型说 safe，也只会被当成 high
    v, _ = r.classify_unknown("sigA", "ctx", 500); assert len(calls) == 1          # 第二次命中缓存，0 token
    r2 = tiers.Router(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, cloud=lambda s, u: ('{"verdict":"ask","reason":"像缓存"}', 100, 50))
    assert r2.classify_unknown("sigB", "ctx", 500)[0] == "ask"
    assert r2.classify_unknown("sigC", "ctx", 5)[0] == "high"                       # 价值太低：连模型都不问
    assert tiers.sig_of(__import__("pathlib").Path("/Users/bob/AppData/x/cache_ab12cd34ef.bin"), 5 * 2**20).count("bob") == 0       # 签名不含用户名


def test_budget_degrades_gracefully(tmp_path):
    r = tiers.Router(tmp_path, cloud=lambda s, u: ('{"verdict":"ask","reason":"x"}', 400, 300), daily_tokens=1000)
    vs = [r.classify_unknown(f"s{i}", "c", 900)[0] for i in range(6)]
    assert vs.count("ask") == 1 and vs.count("high") == 5                          # 第二次起预算不够，降级为保守
    assert r.meter.today()["tokens"] <= 1000
    rep = r.meter.report(); assert sum(d["tier2"] for d in rep.values()) == 1


def test_phrase_uses_cloud_only_for_valuable_topics(tmp_path):
    n = []
    r = tiers.Router(tmp_path, cloud=None)
    llm = lambda t, f, p, s: (n.append(t) or ("云端", 300, 60))
    local = lambda t, f, p, s: "本地"
    assert r.phrase("report", {}, None, "s", 999, local, llm) == "本地"
    assert r.phrase("disagree", {}, None, "s", 999, local, llm) == "云端"
    assert r.phrase("disagree", {}, None, "s", 5, local, llm) == "本地" and n == ["disagree"]


def test_token_simulation_orders_of_magnitude():
    res = sim_tokens.simulate(days=14, seed=3)
    assert res["naive_avg_per_day"] > 100 * res["ours_avg_per_day"]
    assert res["ours_avg_per_day"] < 5000 and res["rules_learned"] > 10
    tight = sim_tokens.simulate(days=14, seed=3, daily_tokens=1000)
    assert tight["ours_avg_per_day"] <= 1000


def test_unknown_big_file_is_not_touched_and_not_asked(tmp_path):
    import os
    from sprite.scenarios import resource
    from sprite.risk import Env
    from sprite.quarantine import Quarantine
    from sprite.sysstate import Snapshot, FakeController
    dl = tmp_path / "Downloads"; dl.mkdir(); f = dl / "weights.bin"
    with open(f, "wb") as h: h.truncate(150 * 2**20)
    os.utime(f, (time.time() - 90 * 86400,) * 2)
    w = resource.World(env=Env(now=time.time(), downloads=dl), q=Quarantine(tmp_path / "q"), ctrl=FakeController(), home=tmp_path,
                       snap=Snapshot(time.time(), 16384, 8000, {"C:": (100, 2)}, []))
    w.router = tiers.Router(tmp_path / "r" if (tmp_path / "r").mkdir() is None else tmp_path, cloud=lambda s, u: ('{"verdict":"ask","reason":"像模型缓存"}', 120, 60))
    reg = Registry(); reg.register(resource.make()); e = Engine(reg, tmp_path)
    w.snap = Snapshot(time.time(), 16384, 8000, {"C:": (10, 5)}, []); e.step(w)
    w.snap = Snapshot(time.time(), 16384, 8000, {"C:": (10, 0.5)}, [])
    out = e.step(w)[0]
    assert f.exists() and not out.acted and not out.asks                  # 模型只是“觉得像缓存”不是硬证据：不做，也不问
