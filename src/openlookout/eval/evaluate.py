"""对照 ground_truth 打分。只有这个脚本读 ground_truth/。
discovered = 检测器产出了匹配的发现；surfaced = 进了已办清单（主卡或"不急"区）；solved = 卡片状态为已验证。
用法：python3 eval/evaluate.py runs/<run>/result.json"""
import json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
gt = json.loads((ROOT / "ground_truth" / "ground_truth.json").read_text(encoding="utf-8"))

def match(f, rule):
    blob = json.dumps(f, ensure_ascii=False)
    return f["kind"] in rule["kinds"] and any(k in blob for k in rule["keywords"])

def evaluate(path):
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    cards = s["cards"]; res = s["results"]
    surfaced = {i for i in cards if i in res and res[i]["status"] not in ("failed", "skipped")}
    rows = []
    for g in gt["issues"]:
        fs = [f for f in s["findings"] if match(f, g["match"])]
        # GT9（还没报的发票）挂在复制粘贴发现上：要求 pending 非空并出现在卡片里
        if g["id"] == "GT9":
            fs = [f for f in s["findings"] if f["kind"] == "copy_paste_friction" and f["local"].get("pending")]
        sf = [f for f in fs if f["id"] in surfaced]
        solved = [f for f in sf if res[f["id"]]["status"] == "verified"]
        rows.append({"id": g["id"], "name": g["name"], "discovered": bool(fs), "surfaced": bool(sf), "solved": bool(solved),
                     "status": res[sf[0]["id"]]["status"] if sf else None})
    bad = []
    for d in gt["distractors"]:
        hits = [f["id"] for f in s["findings"] if f["id"] in surfaced and match(f, d["bad_if"])]
        if hits: bad.append({"id": d["id"], "name": d["name"], "cards": hits})
    gt_ids = set()
    for g in gt["issues"]:
        for f in s["findings"]:
            if match(f, g["match"]) or (g["id"] == "GT9" and f["kind"] == "copy_paste_friction" and f["local"].get("pending")): gt_ids.add(f["id"])
    extra = [{"id": i, "kind": next(f["kind"] for f in s["findings"] if f["id"] == i), "title": cards[i].get("title")} for i in surfaced if i not in gt_ids]
    llm = s["llm"]; by = defaultdict(lambda: {"calls": 0, "latency_s": 0, "prompt": 0, "completion": 0, "reasoning": 0})
    for x in llm:
        b = by[x["step"]]; b["calls"] += 1; b["latency_s"] += x["latency_s"]; b["prompt"] += x["prompt_tokens"] or 0
        b["completion"] += x["completion_tokens"] or 0; b["reasoning"] += x["reasoning_tokens"] or 0
    return {"run": str(path), "model": s["model"], "issues": rows, "bad_cards": bad, "extra_cards": extra,
            "n_discovered": sum(r["discovered"] for r in rows), "n_surfaced": sum(r["surfaced"] for r in rows),
            "n_solved": sum(r["solved"] for r in rows), "n_gt": len(rows), "llm_by_step": dict(by), "timing": s["timing"]}

if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = evaluate(p)
        print(f"== {r['run']} ({r['model']})  发现 {r['n_discovered']}/{r['n_gt']}  上卡 {r['n_surfaced']}/{r['n_gt']}  已验证解决 {r['n_solved']}/{r['n_gt']}")
        for x in r["issues"]: print(f"  {x['id']} {'D' if x['discovered'] else '-'}{'S' if x['surfaced'] else '-'}{'V' if x['solved'] else '-'} {x['status']}  {x['name'][:40]}")
        print("  误报(干扰项上卡):", r["bad_cards"] or "无"); print("  ground truth 之外的卡:", r["extra_cards"] or "无")
        for k, v in r["llm_by_step"].items(): print(f"  {k}: {v}")
        print("  timing", r["timing"])
        json.dump(r, open(Path(p).parent / "eval.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
