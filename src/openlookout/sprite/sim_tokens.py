"""多日、大量问题事件的 token 模拟：分层架构 vs “LLM 盯着一切”的朴素基线。
每次调用的 token 用量取自真实 MiMo 校准（--calibrate 会真实调用几次并写入 calib.json），否则用默认。
python -m sprite.sim_tokens [--days 30] [--calibrate]"""
from __future__ import annotations
import argparse, json, random, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
from .tiers import Router, Meter, PRICE

DEFAULT_CALIB = dict(classify=(520, 60), phrase=(430, 70), watch_poll=(1500, 150), watch_event=(900, 150))


def calibrate(out: Path):
    from .tiers import mimo_cloud, SYSTEM_CLASSIFY
    from . import voice
    call = mimo_cloud(); res = {}
    cs = []
    for sig in (".tmp|cache|<hex>|1e8", ".log|logs|app-<n>|1e9", ".bin|models|weights|1e9"):
        t, a, b = call(SYSTEM_CLASSIFY, f"签名：{sig}\n上下文：位于用户目录下，30 天未改，体积 {sig[-3:]} 字节量级"); cs.append((a, b))
    res["classify"] = [sum(x[0] for x in cs) // 3, sum(x[1] for x in cs) // 3]
    ps = []
    for topic, facts in (("challenge", dict(kind="sunk_cost", evidence=["投入在涨：前两周 17 小时 → 后两周 30 小时", "成果证据没跟上：前两周 2 个、后两周 0 个"], counter="反方观点：也许要熬过平台期")),
                         ("disagree", dict(claim="going_well", verdict="stalling", conf=0.9, evidence=["后两周投入 24 小时", "成果 前两周 2 → 后两周 0"], source="user"))):
        j = call(voice.SYSTEM, json.dumps(dict(topic=topic, project="项目A", facts=facts), ensure_ascii=False)); ps.append((j[1], j[2]))
    res["phrase"] = [sum(x[0] for x in ps) // len(ps), sum(x[1] for x in ps) // len(ps)]
    # “盯着一切”的一次轮询：把一份典型系统快照（进程/磁盘/内存/窗口）发给模型让它判断
    snap = json.dumps(dict(mem=dict(total_mb=16384, avail_mb=6100), disks={"C:": [476, 61]}, procs=[dict(pid=1000 + i, name=n, rss_mb=r, idle_s=i * 60, title="") for i, (n, r) in enumerate([("chrome", 900), ("chrome", 800), ("code", 1200), ("winword", 600), ("node", 500)] * 6)]), ensure_ascii=False)
    t, a, b = call("你是电脑管家，看系统快照，判断有没有需要处理的问题，简短回答。", snap); res["watch_poll"] = [a, b]
    out.write_text(json.dumps(res), "utf-8"); return res


def simulate(days=30, seed=1, calib=None, daily_tokens=20000, polls_per_day=192, events_per_day=40, utter_per_day=6, n_classes=300):
    calib = dict(DEFAULT_CALIB, **(calib or {})); rnd = random.Random(seed)
    home = Path(tempfile.mkdtemp(prefix="tiersim_")); __import__("atexit").register(__import__("shutil").rmtree, home, True); now = [datetime(2026, 9, 1, 9).timestamp()]
    # 模拟的云端：只统计 token（用校准值），返回 ask
    cin, cout = calib["classify"]
    cloud = lambda s, u: ('{"verdict":"ask","reason":"像可再生缓存"}', cin, cout)
    r = Router(home, clock=lambda: now[0], cloud=cloud, daily_tokens=daily_tokens, daily_usd=0.05)
    pin, pout = calib["phrase"]
    llm_compose = lambda t, f, p, s: ("（模拟措辞）", pin, pout)
    weights = [1 / (i + 1) for i in range(n_classes)]                    # Zipf：少数类别占大多数事件
    naive = dict(tokens=0, usd=0.0); per_day = []
    wi, wo = calib["watch_poll"]; ei, eo = calib["watch_event"]
    for d in range(days):
        now[0] = datetime(2026, 9, 1, 9).timestamp() + d * 86400
        day_before = len(r.meter.rows())
        # 朴素基线：每次轮询一次调用 + 每个事件一次调用 + 每次说话一次调用
        n_ev = max(5, int(rnd.gauss(events_per_day, 8))); n_ut = max(1, int(rnd.gauss(utter_per_day, 2)))
        nt = polls_per_day * (wi + wo) + n_ev * (ei + eo) + n_ut * (pin + pout)
        naive["tokens"] += nt; naive["usd"] += (polls_per_day * wi + n_ev * ei + n_ut * pin) * PRICE["in_per_m"] / 1e6 + (polls_per_day * wo + n_ev * eo + n_ut * pout) * PRICE["out_per_m"] / 1e6
        # 分层：轮询=tier0（0 token）；事件=tier0 规则，只有“不认识的类别”才可能走 classify；话术只有高价值话题才用 tier2
        for _ in range(n_ev):
            if rnd.random() < 0.25:                                       # 25% 的事件落在“不认识”的类别
                k = rnd.choices(range(n_classes), weights)[0]; value = rnd.lognormvariate(4.5, 1.2)
                r.classify_unknown(f"sig{k}", "抽象上下文", value)
            else: r.meter.record(0, "tier0_rule", decision="builtin")
        for _ in range(n_ut):
            topic = rnd.choices(["report", "check_in", "challenge", "disagree", "offer_help"], [40, 25, 10, 10, 15])[0]
            r.phrase(topic, {}, None, "s", rnd.lognormvariate(4.5, 1.2), lambda *a: "本地措辞", llm_compose)
        rows = r.meter.rows()[day_before:]
        per_day.append(dict(day=d + 1, ours_tokens=sum(x["tin"] + x["tout"] for x in rows if x["tier"] == 2), naive_tokens=nt,
                            cloud_calls=sum(1 for x in rows if x["tier"] == 2), cache_hits=sum(1 for x in rows if x["cached"])))
    ours = sum(x["ours_tokens"] for x in per_day); usd = sum(x["usd"] for x in r.meter.rows())
    return dict(days=days, ours_total_tokens=ours, ours_avg_per_day=ours / days, ours_usd=usd, naive_total_tokens=naive["tokens"], naive_avg_per_day=naive["tokens"] / days,
                naive_usd=naive["usd"], ratio=naive["tokens"] / max(ours, 1), first7_ours=sum(x["ours_tokens"] for x in per_day[:7]) / 7, last7_ours=sum(x["ours_tokens"] for x in per_day[-7:]) / 7,
                rules_learned=len(r.rules.d), budget_cap=daily_tokens, per_day=per_day, calib=calib)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=30); ap.add_argument("--calibrate", action="store_true"); ap.add_argument("--out", default="/workspace/openlookout/demo_private")
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    calib = DEFAULT_CALIB
    cf = out / "token_calib.json"
    if cf.exists() and not a.calibrate: calib = json.loads(cf.read_text())
    if a.calibrate: calib = calibrate(out / "token_calib.json"); print("真实校准：", calib)
    res = simulate(a.days, calib=calib)
    # 小预算压力测试：预算很小时降级
    tight = simulate(a.days, calib=calib, daily_tokens=1500)
    (out / "token_sim.json").write_text(json.dumps(dict(main=res, tight_budget=tight), ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items() if k not in ("per_day", "calib")}, ensure_ascii=False, indent=1))
    print("tight:", json.dumps({k: round(v, 1) for k, v in tight.items() if k in ("ours_avg_per_day", "naive_avg_per_day")}))
