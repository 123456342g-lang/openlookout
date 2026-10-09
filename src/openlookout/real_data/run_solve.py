#!/usr/bin/env python3
"""End-to-end SOLVE run on hybrid (or other) capture with tight anti-annoyance.

Rules (user feedback):
  - Prefer fewer cards that deliver DONE work; no nagging reminders.
  - Only post when verification passes (or soft draft WITH artifact).
  - Observation-only / omit / far deadlines → silent drawer.
  - Daily card budget; score by frequency×value; suppress noisy same-kind spam.
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MAX_MAIN = 5

def to_num_safe(v):
    try:
        return float(v)
    except Exception:
        return 0.0

MIN_SCORE = 12
FAR_DEADLINE_DAYS = 14
OBSERVATION_KINDS = {"window_thrash", "recurring_doc_focus"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default=str(ROOT / "real_data" / "capture_hybrid"))
    ap.add_argument("--home", default="real_data/home_hybrid/admin")
    ap.add_argument("--tag", default="hybrid_solve")
    ap.add_argument("--judge-model", default="mimo-v2.6-flash")
    ap.add_argument("--writer-model", default="mimo-v2.6-flash")
    ap.add_argument("--compose-model", default="mimo-v2.6-pro")
    ap.add_argument("--max-findings", type=int, default=10)
    a = ap.parse_args()

    os.environ["LOOKOUT_CAPTURE"] = str(Path(a.capture).resolve())
    os.environ["LOOKOUT_HOME"] = a.home
    import lookout.common as common
    common.CAP = Path(os.environ["LOOKOUT_CAPTURE"])
    # Event paths are relative to the user home directory itself
    common.SIM = (ROOT / a.home).resolve()

    from lookout import run as runmod
    from lookout.common import load_events, load_meta
    from lookout.detectors import run_all
    from lookout.deid import Deid
    from lookout.llm import LLM, parse_json
    from lookout.solvers import SOLVERS
    from lookout import inbox

    run_dir = ROOT / "runs" / a.tag
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    t0 = time.time()
    evs, meta = load_events(), load_meta()
    deid = Deid(meta)
    llm = LLM(run_dir, a.judge_model); llm.deid = deid
    env = type("Env", (), {})()
    env.evs, env.meta, env.deid, env.llm, env.run_dir = evs, meta, deid, llm, run_dir
    env.recurring, env.dups = [], []

    fs = run_all(evs, meta)
    # Re-score lightly: frequency × value already in detector scores; boost solvable kinds
    for f in fs:
        if f["kind"] in ("periodic_assembly", "duplicate_charge", "price_change", "numeric_drift", "report_mismatch"):
            f["score"] *= 1.15
        if f["kind"] in OBSERVATION_KINDS:
            f["score"] *= 0.35  # demote thrash unless somehow solvable later

    # Diversity pick
    picked, per_kind = [], {}
    for f in sorted(fs, key=lambda x: -x["score"]):
        if f["score"] < MIN_SCORE:
            continue
        # Far deadlines never enter candidate set (anti-spam)
        if f["kind"] == "deadline" and f["local"].get("days_left", 0) > FAR_DEADLINE_DAYS:
            continue
        k = f["kind"]
        per_kind[k] = per_kind.get(k, 0) + 1
        if per_kind[k] > 2:
            continue
        picked.append(f)
        if len(picked) >= a.max_findings:
            break

    for i, f in enumerate(picked):
        f["id"] = f"S{i+1}"
    (run_dir / "all_findings.json").write_text(
        json.dumps([{k: f[k] for k in ("id", "kind", "score", "facts", "local")} for f in fs],
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    silent = [{"id": f.get("id", f["kind"]), "kind": f["kind"], "why": f"价值分 {f['score']:.1f} 未入选或低于阈值",
               "desc": runmod.describe(f, deid)} for f in fs if f not in picked]

    lines = "\n".join(f"- id={f['id']} 类型={f['kind']}：{runmod.describe(f, deid)}" for f in picked)
    deid.audit(lines)
    JUDGE = """你是 OpenLookout 的判断员。只把「能递上已经做好的东西」的麻烦标为 worth=true。
标准更严（去打扰）：
- 周期性拼表/周报、账单重复扣费或涨价、能从本地表生成成品的复制粘贴 → worth=true
- 截止日：只剩 ≤7 天且能整理出表格 → worth=true；只剩提醒、做不出文件 → worth=false
- 窗口来回撕扯、反复打开同一文件、纯观察 → worth=false（没有成品就不要打扰）
- 正常吃饭、娱乐、偶发操作 → false
只输出 JSON 数组：[{"id":"...","worth":true/false,"urgency":"高|中|低","why":"一句话"}]"""
    txt, _ = llm.chat("judge", JUDGE, f"今天是工作日早上。规律如下：\n{lines}", model=a.judge_model)
    judge = {j["id"]: j for j in parse_json(txt)}
    for f in picked:
        k = f["kind"]
        if k in ("periodic_assembly", "duplicate_charge", "price_change", "numeric_drift"):
            judge[f["id"]] = {**judge.get(f["id"], {}), "worth": True,
                              "urgency": judge.get(f["id"], {}).get("urgency") or "高",
                              "why": judge.get(f["id"], {}).get("why") or "可产出已验证成品"}
        if k == "copy_paste_friction" and f["local"].get("src_files") and (
            "浏览器" in str(f["facts"].get("dst_kind", "")) or "表单" in str(f["facts"].get("dst_kind", ""))
            or "google-chrome" in str(f["facts"].get("dst_kind", ""))):
            judge[f["id"]] = {"worth": True, "urgency": "中", "why": "有源表，可导出待填行成品"}
        if k == "deadline" and f["local"].get("days_left", 99) <= 7:
            judge[f["id"]] = {**judge.get(f["id"], {}), "worth": True, "urgency": "高",
                              "why": judge.get(f["id"], {}).get("why") or "临近截止，尝试整理表格"}

    from lookout.detectors import recurring_charges
    env.recurring = [dict(r, d=str(r["d"])) for r in recurring_charges(meta)]

    results = {}
    for f in picked:
        if f["id"] in results:
            continue
        j = judge.get(f["id"], {"worth": False, "why": "模型没有回复"})
        if not j.get("worth"):
            silent.append({"id": f["id"], "kind": f["kind"],
                           "why": "判断员认为不值得打扰：" + j.get("why", ""),
                           "desc": runmod.describe(f, deid)})
            continue
        # Observation kinds: never call compose; mark omit
        if f["kind"] in OBSERVATION_KINDS:
            from lookout.solvers import solve_observation
            res = solve_observation(f, env, a.judge_model)
            results[f["id"]] = res
            silent.append({"id": f["id"], "kind": f["kind"], "why": "只有观察没有成品，已按去打扰规则省略",
                           "desc": runmod.describe(f, deid)})
            continue
        t = time.time()
        compose_model = a.compose_model if f["kind"] in (
            "periodic_assembly", "copy_paste_friction", "repeated_lookup", "deadline") else a.judge_model
        try:
            res = SOLVERS[f["kind"]](f, env, compose_model)
        except Exception as ex:
            res = {"status": "failed", "error": repr(ex)[:300], "recs": [], "artifacts": [],
                   "slots": {}, "verify_deid": {}}
        res["solve_s"] = round(time.time() - t, 1)
        results[f["id"]] = res

        # Derived report_mismatch from weekly verify
        if f["kind"] == "periodic_assembly":
            for m in res.get("mismatches", []):
                w = m.get("why") or {}
                if not w.get("rows"):
                    continue
                nf = {"id": f"{f['id']}m", "kind": "report_mismatch", "score": 200,
                      "facts": {"candidates": len(w["rows"]), "weeks": res["verify_deid"].get("weeks_checked"),
                                "cells_total": res["verify_deid"].get("cells_total"), "label": m["label"],
                                "diff_pct": round(abs(w["diff"]) / max(1e-9, abs(float(to_num_safe(m["gen"])))) * 100)},
                      "local": m}
                picked.append(nf)
                judge[nf["id"]] = {"worth": True, "urgency": "高", "why": "本地验证发现手工周报和源表对不上"}
                results[nf["id"]] = {
                    "status": "verified", "recs": [],
                    "artifacts": [res["weeks"][[x["week"] for x in res["weeks"]].index(m["week"])]["gen"]],
                    "slots": {"报告文件": Path(m["hand_file"]).name, "格子": m["label"], "手工值": str(m["hand"]),
                              "正确值": str(m["gen"]), "差额": f"{abs(w['diff']):g}",
                              "漏掉的行": ("；或 ".join("，".join(f"{k}:{v}" for k, v in rw.items() if v not in (None, ""))
                                          for rw in w["rows"])),
                              "候选行数": str(len(w["rows"])),
                              "一致格数": res["slots"].get("一致格数", ""), "复核格数": res["slots"].get("复核格数", ""),
                              "统计周": m["week"]},
                    "verify_deid": {"diff_equals_one_source_row": True, "other_cells_all_match": True},
                }

    # Anti-annoyance gate: only post DONE (verified) or soft draft with real artifacts
    postable = []
    for f in picked:
        if f["id"] not in results:
            continue
        r = results[f["id"]]
        st = r.get("status")
        arts = [x for x in (r.get("artifacts") or []) if x and Path(x).exists()]
        if st == "omit" or st == "skipped" or st == "failed":
            silent.append({"id": f["id"], "kind": f["kind"],
                           "why": f"求解状态={st}，不上清单（{r.get('note') or r.get('error') or '无成品'})",
                           "desc": runmod.describe(f, deid)})
            continue
        if st == "reminder_only":
            # soft: only if ≤3 days left — still prefer artifact; else omit
            days = f["local"].get("days_left", 99)
            if days > 3 or not arts:
                silent.append({"id": f["id"], "kind": f["kind"],
                               "why": "只有提醒没有成品/太远，已省略以免像软件弹窗",
                               "desc": runmod.describe(f, deid)})
                continue
        if st == "draft" and not arts:
            silent.append({"id": f["id"], "kind": f["kind"],
                           "why": "草稿且无文件，已省略", "desc": runmod.describe(f, deid)})
            continue
        if st == "verified" or (st in ("draft", "reminder_only") and arts):
            postable.append(f)

    # Sort by urgency then score; cap
    postable.sort(key=lambda f: (
        {"高": 0, "中": 1, "低": 2}.get(judge.get(f["id"], {}).get("urgency"), 3),
        results[f["id"]]["status"] != "verified",
        -f["score"],
    ))
    main_cards = postable[:MAX_MAIN]
    for f in postable[MAX_MAIN:]:
        silent.append({"id": f["id"], "kind": f["kind"], "why": f"超过每日卡片上限 {MAX_MAIN}，压到抽屉",
                       "desc": runmod.describe(f, deid)})

    # Write cards only for main_cards
    blocks = []
    for f in main_cards:
        r = results[f["id"]]
        blocks.append(
            f"### id={f['id']} 类型={f['kind']} 紧急度={judge[f['id']].get('urgency')}\n"
            f"发现：{runmod.describe(f, deid)}\n为什么重要：{judge[f['id']].get('why', '')}\n"
            f"准备状态：{r['status']}；验证摘要：{json.dumps(r.get('verify_deid', {}), ensure_ascii=False)}\n"
            f"已准备的文件数：{len(r.get('artifacts', []))}；工作流说明：{(r.get('workflow') or {}).get('explain', '无')}\n"
            f"可用占位符：{', '.join('{'+k+'}' + '(' + runmod.slot_type(v) + ')' for k, v in r.get('slots', {}).items())}"
        )
    cards = {}
    if blocks:
        body = deid.scrub("\n\n".join(blocks)); deid.audit(body)
        WRITER = runmod.WRITER_SYS + "\n额外：这是去打扰模式——语气短、先亮已经做好的文件，不要像系统弹窗那样催促。"
        txt, _ = llm.chat("write_cards", WRITER, "给下面每一条写一张卡片：\n\n" + body,
                          model=a.writer_model, max_tokens=6000)
        cards = {c["id"]: c for c in parse_json(txt)}

    timing = {"total_s": round(time.time() - t0, 1), "n_events": len(evs),
              "n_findings_all": len(fs), "n_picked": len(picked), "n_posted": len(main_cards)}
    summary = {
        "tag": a.tag, "model": a.compose_model, "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "now": meta["now"], "timing": timing, "source": meta.get("source"),
        "annoyance": {"max_main": MAX_MAIN, "min_score": MIN_SCORE, "far_deadline_days": FAR_DEADLINE_DAYS,
                      "posted": len(main_cards), "silenced": len(silent)},
        "findings": [{"id": f["id"], "kind": f["kind"], "score": f["score"], "desc": runmod.describe(f, deid),
                      "local": json.loads(json.dumps(f["local"], ensure_ascii=False, default=str))} for f in picked],
        "judge": judge, "silent": silent[:40],
        "results": {k: {kk: vv for kk, vv in v.items() if kk not in ("recs", "svg")} for k, v in results.items()},
        "cards": cards,
        "llm": [json.loads(l) for l in open(run_dir / "llm_log.jsonl", encoding="utf-8")],
    }
    # keep svg in results for drift if any
    for k, v in results.items():
        if "svg" in v:
            summary["results"][k]["svg"] = v["svg"]

    (run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    inbox.render(summary, run_dir, title_note="去打扰·只上已验证成品")
    print(json.dumps({
        "run_dir": str(run_dir), "findings_all": len(fs), "picked": len(picked),
        "posted": len(main_cards), "silent": len(silent), "total_s": timing["total_s"],
        "posted_kinds": [f["kind"] for f in main_cards],
        "statuses": {f["id"]: results[f["id"]]["status"] for f in main_cards},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
