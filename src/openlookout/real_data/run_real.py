"""Run OpenLookout on a converted real capture; keep API modest by capping candidates."""
from __future__ import annotations
import argparse, json, os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--model", default="mimo-v2.6-flash")
    ap.add_argument("--writer-model", default="mimo-v2.6-flash")
    ap.add_argument("--judge-model", default="mimo-v2.6-flash")
    ap.add_argument("--compose-model", default="mimo-v2.6-pro")
    ap.add_argument("--max-findings", type=int, default=8)
    a = ap.parse_args()

    os.environ["LOOKOUT_CAPTURE"] = str(Path(a.capture).resolve())
    os.environ["LOOKOUT_HOME"] = a.home
    import lookout.common as common
    common.CAP = Path(os.environ["LOOKOUT_CAPTURE"])
    common.SIM = (ROOT / a.home).parent
    # Prefer observation solver for friction without forms — still use real solvers
    from lookout import run as runmod
    from lookout.common import load_events, load_meta
    from lookout.detectors import run_all
    from lookout.deid import Deid
    from lookout.llm import LLM, parse_json
    from lookout.solvers import SOLVERS
    from lookout import inbox

    # Monkeypatch: use compose model name via env for solvers that call env.llm with a.model
    # We'll pass compose model as --model when we want pro for workflow; for real data most are observations.
    # Strategy: flash for judge/writer; for solvers needing compose, temporarily use pro.

    run_dir = ROOT / "runs" / a.tag
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    t0 = time.time()
    evs, meta = load_events(), load_meta()
    deid = Deid(meta)
    llm = LLM(run_dir, a.model); llm.deid = deid
    env = type("Env", (), {})()
    env.evs, env.meta, env.deid, env.llm, env.run_dir = evs, meta, deid, llm, run_dir
    env.recurring, env.dups = [], []

    fs = run_all(evs, meta)
    # Diversity pick: at most 2 per kind, prefer higher score, drop obvious noise scores already filtered
    picked, per_kind = [], {}
    for f in sorted(fs, key=lambda x: -x["score"]):
        k = f["kind"]
        per_kind[k] = per_kind.get(k, 0) + 1
        if per_kind[k] > 2: continue
        # Skip same-app pycharm paste as low surprise for demo
        if k == "copy_paste_friction" and f["facts"].get("src_kind") == f["facts"].get("dst_kind") == "pycharm":
            continue
        picked.append(f)
        if len(picked) >= a.max_findings: break
    # Always include deadline if present and not picked
    for f in fs:
        if f["kind"] == "deadline" and f not in picked:
            picked.append(f)

    # Re-id picked as F1.. for this run
    for i, f in enumerate(picked):
        f["id"] = f"R{i+1}"
    (run_dir / "all_findings.json").write_text(json.dumps([{k: f[k] for k in ("id","kind","score","facts","local")} for f in fs], ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    cands = [f for f in picked if f["score"] >= 8]
    silent = [{"id": f["id"], "kind": f["kind"], "why": f"价值分 {f['score']:.1f} 低于阈值或未入选", "desc": runmod.describe(f, deid)} for f in fs if f not in cands]

    lines = "\n".join(f"- id={f['id']} 类型={f['kind']}：{runmod.describe(f, deid)}" for f in cands)
    deid.audit(lines)
    JUDGE_REAL = """你是 OpenLookout 的"判断员"。本机程序在用户电脑上统计出了一些规律（已脱敏，来自真实使用痕迹）。
对每一条判断：值不值得做成一张"已办/观察"卡片主动递给用户。
放宽标准（这是真实数据评估，不要只保留灾难级问题）：
- 明显的重复劳动、跨应用搬内容、两个文件来回对照切换 → worth=true（哪怕用户已经习惯）
- 反复打开同一工作文档且累计很久 → 若像在手工维护某件事，worth=true；纯刷网页/看视频 → false
- 截止日：超过 60 天可标 worth=false；30 天内 worth=true
- 正常通信、娱乐、偶尔搜索 → false
只输出 JSON 数组：[{"id":"...","worth":true/false,"urgency":"高|中|低","why":"一句话"}]"""
    txt, rec = llm.chat("judge", JUDGE_REAL, f"今天是用户电脑上的工作日早上。以下是本机统计出的规律（真实开源数据集）：\n{lines}", model=a.judge_model)
    judge = {j["id"]: j for j in parse_json(txt)}

    results = {}
    for f in cands:
        j = judge.get(f["id"], {"worth": False, "why": "模型没有回复"})
        if not j.get("worth"):
            silent.append({"id": f["id"], "kind": f["kind"], "why": "判断员认为不值得打扰：" + j.get("why", ""), "desc": runmod.describe(f, deid)})
            continue
        t = time.time()
        compose_model = a.compose_model if f["kind"] in ("periodic_assembly", "copy_paste_friction", "repeated_lookup", "deadline", "numeric_drift") else a.model
        try:
            # For observation kinds, no compose needed
            if f["kind"] in ("window_thrash", "recurring_doc_focus"):
                res = SOLVERS[f["kind"]](f, env, a.model)
            elif f["kind"] == "copy_paste_friction" and not f["local"].get("labels") and not f["local"].get("src_files"):
                # No form fields / source docs → observation card, avoid useless compose
                from lookout.solvers import solve_observation
                res = solve_observation(f, env, a.model)
                res["status"] = "draft"
            else:
                res = SOLVERS[f["kind"]](f, env, compose_model)
        except Exception as ex:
            from lookout.solvers import solve_observation
            res = solve_observation(f, env, a.model)
            res["error"] = repr(ex)[:300]
            res["status"] = "draft"
        res["solve_s"] = round(time.time() - t, 1)
        results[f["id"]] = res

    todo = [f for f in cands if f["id"] in results]
    blocks = []
    for f in todo:
        r = results[f["id"]]
        blocks.append(f"### id={f['id']} 类型={f['kind']} 紧急度={judge[f['id']].get('urgency')}\n发现：{runmod.describe(f, deid)}\n为什么重要：{judge[f['id']].get('why', '')}\n"
                      f"准备状态：{r['status']}；验证摘要：{json.dumps(r.get('verify_deid', {}), ensure_ascii=False)}\n"
                      f"已准备的文件数：{len(r.get('artifacts', []))}；工作流说明：{(r.get('workflow') or {}).get('explain', '无')}\n"
                      f"可用占位符：{', '.join('{'+k+'}' + '(' + runmod.slot_type(v) + ')' for k, v in r.get('slots', {}).items())}")
    body = deid.scrub("\n\n".join(blocks)); deid.audit(body)
    txt, rec = llm.chat("write_cards", runmod.WRITER_SYS, "给下面每一条写一张卡片：\n\n" + body, model=a.writer_model, max_tokens=6000)
    cards = {c["id"]: c for c in parse_json(txt)}
    # Fill slots
    for cid, card in cards.items():
        slots = (results.get(cid) or {}).get("slots") or {}
        for field in ("title", "noticed", "prepared", "verified", "question"):
            if field in card:
                for k, v in slots.items():
                    card[field] = card[field].replace("{" + k + "}", str(v))
        if "options" in card:
            opts=[]
            for opt in card["options"]:
                for k,v in slots.items():
                    opt=opt.replace("{"+k+"}", str(v))
                opts.append(opt)
            card["options"]=opts

    timing = {"total_s": round(time.time() - t0, 1), "n_events": len(evs), "n_findings_all": len(fs), "n_cands": len(cands)}
    summary = {"tag": a.tag, "model": a.model, "generated_at": __import__('datetime').datetime.now().isoformat(timespec="seconds"),
               "now": meta["now"], "timing": timing, "source": meta.get("source"),
               "findings": [{"id": f["id"], "kind": f["kind"], "score": f["score"], "desc": runmod.describe(f, deid),
                             "local": json.loads(json.dumps(f["local"], ensure_ascii=False, default=str))} for f in picked],
               "judge": judge, "silent": silent[:30],
               "results": {k: {kk: vv for kk, vv in v.items() if kk not in ("recs",)} for k, v in results.items()},
               "cards": cards, "llm": [json.loads(l) for l in open(run_dir / "llm_log.jsonl", encoding="utf-8")]}
    (run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    inbox.render(summary, run_dir)
    print(f"done: {run_dir} findings_all={len(fs)} picked={len(picked)} cards={len(cards)} total={timing['total_s']}s")

if __name__ == "__main__":
    main()
