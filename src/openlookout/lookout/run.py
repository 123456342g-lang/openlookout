"""[非 V1 主入口] 模拟人物/实时流水线。产品主路径：`python3 -m lookout.v1`（见 V1.md）。
"""
import argparse, json, time
from datetime import datetime
from pathlib import Path
from .common import ROOT, load_events, load_meta
from .detectors import run_all
from .deid import Deid
from .llm import LLM, parse_json
from .solvers import SOLVERS
from . import inbox

MIN_SCORE = 8          # 低于这个价值分的发现直接留在本机日志里，不去问模型、不打扰人
MAX_MAIN_CARDS = 5     # 每天最多 5 张需要确认的卡

def slot_type(v):
    import re
    v = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*|\d{1,2}月\d{1,2}日", v): return "日期"
    if re.fullmatch(r"[¥]?-?[\d.,]+\s*(元|分钟|%)?", v): return "数字"
    if re.search(r"\.(xlsx|csv|txt|md|js|svg|pdf)$", v): return "文件名"
    return "文本"

def describe(f, deid):
    k, F, L = f["kind"], f["facts"], f["local"]
    if k == "periodic_assembly":
        s = (f"用户每{F['weekday']}手工新建一份同一命名模式的报告文件，已连续 {F['occurrences']} 周；每次约 {F['avg_minutes']} 分钟，"
             f"期间在 {F['n_inputs']} 个表格之间切换窗口约 {F['avg_window_switches']} 次、复制粘贴约 {F['avg_pastes']} 次，还开了计算器。"
             + ("今天就是该做的日子，本周的还没做。" if F["due_today"] else ""))
    elif k == "copy_paste_friction":
        s = (f"用户从{F['src_kind']}复制内容粘贴到{F['dst_kind']}，{F['days']} 天里共 {F['pastes']} 次"
             + (f"，涉及 {F['docs']} 份同类文档、每份 {F['fields_per_doc']} 个字段（网页字段：{'、'.join(F['field_labels'])}），估计花了 {F['minutes_spent_est']} 分钟" if F["docs"] else "")
             + (f"；同一文件夹里还有 {F['pending_docs']} 份同类文档从没被处理过" if F["pending_docs"] else "") + "。")
    elif k == "repeated_lookup":
        if F["attribute"]:
            s = (f"用户在 {F['days']} 个不同的日子里搜索了 {F['searches']} 次「某物质 + {F['attribute']}」这类问题（只有 {F['distinct_answers']} 个不同答案），"
                 f"每次停留约 {F['median_dwell_s']} 秒，搜完把数值粘贴进一个表格。")
        else:
            s = f"用户在 {F['days']} 个不同的日子里搜索了 {F['searches']} 次完全相同的问题「{L['queries'][0][0]}」，每次停留约 {F['median_dwell_s']} 秒，没有复制任何内容。"
    elif k == "duplicate_charge":
        s = f"账单里一个{F['merchant_type']}（{F['merchant']}）在同一天被扣了两次相同金额，两个不同订单号，相隔不到一分钟；之前的月份都只扣一次。"
    elif k == "price_change":
        s = f"账单里{F['merchant']}的{F['merchant_type']}金额，{F['months'][1]} 比 {F['months'][0]} 上涨了 {F['change_pct']}%，用户没有任何相关操作。"
    elif k == "deadline":
        import re
        sent = re.sub(r"(?:20\d\d\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]", "⟨日期⟩", L["sentence"])
        s = (f"{F['source']}（{L['noted_on']} 记录）里有一句：「{sent}」。其中截止日距今天 {F['days_left']} 天"
             + ("，任务派给了用户本人" if F["assigned_to_user"] else "") + ("；记录之后用户电脑上没有任何与此相关的操作" if not F["has_followup_activity"] else "；之后有相关操作") + "。")
    elif k == "numeric_drift":
        s = (f"一张实验记录表里，'{L['group_col']}={L['group_val']}' 这组行的 '{L['value_col']}' 从某天起持续偏离：之前 {F['points_before']} 个点非常稳定，"
             f"之后 {F['points_after']} 个点偏离了 {F['z']} 个标准差（最新值比基线高 {F['pct_change']}%），{int(F['trend_monotonic_ratio']*100)}% 的相邻点在上升；"
             f"从那天起表里还有 {F['other_rows_since_change']} 行其它记录。")
    elif k == "report_mismatch":
        s = (f"按用户自己的源表重算过去 {F['weeks']} 份手工报告，共 {F['cells_total']} 格；其中 1 份报告的「{F['label']}」一格比源表算出来的少 {F['diff_pct']}%，"
             "差额正好等于源表里某一行的值（像是复制时漏了一行" + (f"；但符合这个差额的候选行有 {F['candidates']} 条，没法确定是哪一条" if F["candidates"] > 1 else "") + "），其余格子全部一致。")
    elif k == "window_thrash":
        s = (f"用户在 {F['days']} 天里，在「{F['title_a_short']}」({F['app_a']}) 和「{F['title_b_short']}」({F['app_b']}) "
             f"两个窗口之间来回切换了约 {F['switches']} 次，像是在对照着搬内容或核对。")
    elif k == "recurring_doc_focus":
        s = (f"用户在 {F['days']} 天里反复打开同一类窗口「{F['title_short']}」({F['app']})，累计停留约 {F['minutes']} 分钟"
             + (f"，间隔中位数约 {F['median_gap_days']} 天" if F.get("median_gap_days") else "") + "。")
    else:
        s = json.dumps(F, ensure_ascii=False)
    return deid.scrub(s)

JUDGE_SYS = """你是 OpenLookout 的"判断员"。本机程序在用户电脑上统计出了一些规律（已脱敏）。对每一条判断：值不值得主动去打扰用户、帮他处理。
标准：能帮用户省时间/省钱/避免损失或错误的才值得；正常的生活习惯、娱乐、学习阅读不值得；没法可靠解决的（比如需要操控封闭的聊天软件）也标为不值得或低优先。
用户本人很可能没注意到这些。只输出 JSON 数组：[{"id": "...", "worth": true/false, "urgency": "高|中|低", "why": "一句话理由"}]"""

WRITER_SYS = """你是 OpenLookout，一个在用户电脑上"瞭望"的助手。你要写"已办清单"里的卡片，口吻像一位细心、靠谱、说话简短的同事（简体中文，用"你"）。
每张卡：我注意到了什么（具体、带证据）→ 我已经准备好了什么（已经做好的东西，不是建议）→ 验证结果 → 一个问题让用户点选。
硬规则：
- 真实数值你看不到，只能用给出的占位符，原样写成 {占位符名}，本机会替换成真实值。不要编造任何数字、日期、人名或文件名。
- 绝不出现内部代号（表A、表B、文档组D、报告R、F1、id 之类），用占位符里的真实文件名或日常说法。
- 先用一句话讲清"这件事对你意味着什么"（参考"为什么重要"），再给证据。
- 不夸大：验证状态是 draft 就说"做了个草稿，有几处不一样"；没有准备文件就不要说准备了。
- 付款、发送、提交、删除都由用户自己做，你只说"已经帮你准备好"。
- 东西已经做好了，就用"已经做好"的说法；最后的问题问的是"以后要不要每次自动做/要不要用它"，不要问"要不要现在生成"。
- 占位符后面括号里标了它的类型（数字/日期/文件名/文本），按类型使用，比如日期不能当成份数。
- 每段不超过两句话。title 不超过 22 个字，要让人一眼看懂。
只输出 JSON 数组：[{"id": "...", "title": "...", "noticed": "...", "prepared": "...", "verified": "...", "question": "...", "options": ["...", "..."]}]"""

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model", default="mimo-v2.6-flash"); ap.add_argument("--tag", default="dev")
    ap.add_argument("--judge-model", default=None); ap.add_argument("--writer-model", default=None)
    a = ap.parse_args()
    run_dir = ROOT / "runs" / f"{a.tag}_{a.model.split('-')[-1]}"
    if run_dir.exists():
        import shutil; shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    t0 = time.time()
    evs, meta = load_events(), load_meta()
    deid = Deid(meta)
    llm = LLM(run_dir, a.model); llm.deid = deid
    env = type("Env", (), {})(); env.evs, env.meta, env.deid, env.llm, env.run_dir = evs, meta, deid, llm, run_dir
    timing = {}
    # 账单类发现共享的"周期性扣费"清单（给订阅清单用）
    env.recurring, env.dups = [], []
    # ---- b 找规律
    t = time.time(); fs = run_all(evs, meta); timing["detect_s"] = round(time.time() - t, 2)
    for f in fs:
        if f["kind"] == "duplicate_charge": env.dups.append(f["local"]["party"])
        if f["kind"] in ("duplicate_charge", "price_change"):
            for r in f["local"].get("history", []) + [f["local"].get("before"), f["local"].get("after")]:
                if r and r not in env.recurring: env.recurring.append(r)
    from .detectors import recurring_charges
    env.recurring = [dict(r, d=str(r["d"])) for r in recurring_charges(meta)]
    cands = [f for f in fs if f["score"] >= MIN_SCORE]
    silent = [{"id": f["id"], "kind": f["kind"], "why": f"价值分 {f['score']:.1f} 低于阈值，只记录不打扰", "desc": describe(f, deid)} for f in fs if f["score"] < MIN_SCORE]
    # ---- c 判断（一次调用判断全部）
    lines = "\n".join(f"- id={f['id']} 类型={f['kind']}：{describe(f, deid)}" for f in cands)
    deid.audit(lines)
    txt, rec = llm.chat("judge", JUDGE_SYS, f"今天是用户电脑上的周五早上。以下是本机统计出的规律：\n{lines}", model=a.judge_model)
    judge = {j["id"]: j for j in parse_json(txt)}
    # ---- d+e 拼工作流、沙箱试跑、验证
    results = {}
    for f in cands:
        if f["id"] in results: continue   # 验证中派生出来的发现（已经带着结果）
        j = judge.get(f["id"], {"worth": False, "why": "模型没有回复"})
        if not j.get("worth"):
            silent.append({"id": f["id"], "kind": f["kind"], "why": "判断员认为不值得打扰：" + j.get("why", ""), "desc": describe(f, deid)}); continue
        t = time.time()
        try:
            res = SOLVERS[f["kind"]](f, env, a.model)
        except Exception as ex:
            res = {"status": "failed", "error": repr(ex)[:300], "recs": [], "artifacts": [], "slots": {}, "verify_deid": {}}
        res["solve_s"] = round(time.time() - t, 1)
        results[f["id"]] = res
        # 验证周报时顺带发现的"手工报告和源表对不上"→ 单独成为一个发现
        if f["kind"] == "periodic_assembly":
            for m in res.get("mismatches", []):
                w = m.get("why") or {}
                if not w.get("rows"): continue
                row = w["rows"][0]
                nf = {"id": f"{f['id']}m", "kind": "report_mismatch", "score": 200,
                      "facts": {"candidates": len(w["rows"]), "weeks": res["verify_deid"]["weeks_checked"], "cells_total": res["verify_deid"]["cells_total"], "label": m["label"],
                                "diff_pct": round(abs(w["diff"]) / max(1e-9, abs(float(m["gen"]))) * 100)},
                      "local": m}
                fs.append(nf); cands.append(nf); judge[nf["id"]] = {"worth": True, "urgency": "高", "why": "本地验证发现的错误"}
                results[nf["id"]] = {"status": "verified", "recs": [], "artifacts": [res["weeks"][[x["week"] for x in res["weeks"]].index(m["week"])]["gen"]],
                    "slots": {"报告文件": Path(m["hand_file"]).name, "格子": m["label"], "手工值": str(m["hand"]), "正确值": str(m["gen"]),
                              "差额": f"{abs(w['diff']):g}", "漏掉的行": ("；或 ".join("，".join(f"{k}:{v}" for k, v in rw.items() if v not in (None, "")) for rw in w["rows"])),
                              "候选行数": str(len(w["rows"])),
                              "一致格数": res["slots"]["一致格数"], "复核格数": res["slots"]["复核格数"], "统计周": m["week"]},
                    "verify_deid": {"diff_equals_one_source_row": True, "other_cells_all_match": True}}
    # ---- f 写卡片（一次调用）
    todo = [f for f in cands if f["id"] in results]
    blocks = []
    for f in todo:
        r = results[f["id"]]
        blocks.append(f"### id={f['id']} 类型={f['kind']} 紧急度={judge[f['id']].get('urgency')}\n发现：{describe(f, deid)}\n为什么重要：{judge[f['id']].get('why', '')}\n"
                      f"准备状态：{r['status']}；验证摘要：{json.dumps(r.get('verify_deid', {}), ensure_ascii=False)}\n"
                      f"已准备的文件数：{len(r.get('artifacts', []))}；工作流说明：{(r.get('workflow') or {}).get('explain', '无')}\n"
                      f"可用占位符：{', '.join('{'+k+'}' + '(' + slot_type(v) + ')' for k, v in r.get('slots', {}).items())}")
    body = deid.scrub("\n\n".join(blocks)); deid.audit(body)
    txt, rec = llm.chat("write_cards", WRITER_SYS, "给下面每一条写一张卡片：\n\n" + body, model=a.writer_model, max_tokens=6000)
    cards = {c["id"]: c for c in parse_json(txt)}
    timing["total_s"] = round(time.time() - t0, 1)
    summary = {"tag": a.tag, "model": a.model, "generated_at": datetime.now().isoformat(timespec="seconds"), "now": meta["now"], "timing": timing,
               "findings": [{"id": f["id"], "kind": f["kind"], "score": f["score"], "desc": describe(f, deid),
                             "local": json.loads(json.dumps(f["local"], ensure_ascii=False, default=str))} for f in fs],
               "judge": judge, "silent": silent,
               "results": {k: {kk: vv for kk, vv in v.items() if kk not in ("recs",)} for k, v in results.items()},
               "cards": cards, "llm": [json.loads(l) for l in open(run_dir / "llm_log.jsonl", encoding="utf-8")]}
    (run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    inbox.render(summary, run_dir)
    print(f"done: {run_dir}  findings={len(fs)} cards={len(cards)} llm_calls={len(summary['llm'])} total={timing['total_s']}s")

if __name__ == "__main__":
    main()
