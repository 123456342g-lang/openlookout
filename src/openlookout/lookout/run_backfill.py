"""[非 V1 主入口] 产品主路径请用 `python3 -m lookout.v1`。历史回溯模式的流水线：读 backfill_win 的输出 → 原有检测器 + 历史检测器 → 判断 → 准备成品 → 已办清单。
用法：
  python3 -m lookout.run_backfill --capture /path/to/backfill --tag bf --no-llm      # 不调云端模型，规则判断 + 模板卡片
  python3 -m lookout.run_backfill --capture /path/to/backfill --tag bf               # 判断和写卡片用 MiMo（只发脱敏统计）
与实时模式的区别：没有剪贴板/窗口焦点，跳过“窗口来回撕扯”“复制粘贴”这类分钟级检测；新增 5 个按天/周找节律的检测器（lookout/history.py）。"""
import argparse, json, os, shutil, time
from collections import Counter
from datetime import datetime
from pathlib import Path
import lookout.common as common
from . import history as H

MIN_SCORE = 8
SKIP_KINDS = {"window_thrash", "copy_paste_friction",   # 浏览器“页面加载”不是窗口切换，回溯数据上不可靠
              "recurring_doc_focus"}   # 第 9 轮：回溯里的 dur_s 是浏览器标签页“开着”的时长（visit_duration），不是看它的时间；真实数据上这类发现全是一直开着的网页

def build_tree(cap):
    """--with-content 复制来的文件按事件里的 path 摆成目录树（符号链接），让原有求解器按原路径找到它们。"""
    tree = cap / "_tree"
    if tree.exists(): shutil.rmtree(tree)
    tree.mkdir()
    mp = cap / "content_manifest.json"
    n = 0
    if mp.exists():
        for x in json.loads(mp.read_text(encoding="utf-8")):
            dst = tree / x["path"]; dst.parent.mkdir(parents=True, exist_ok=True)
            src = (cap / x["stored"]).resolve()
            if src.exists() and not dst.exists(): dst.symlink_to(src); n += 1
    return tree, n

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--capture", required=True); ap.add_argument("--tag", default="backfill")
    ap.add_argument("--model", default="mimo-v2.6-flash"); ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--max-cards", type=int, default=5)
    ap.add_argument("--prepared", default=None, help="把上清单的成品另拷一份到这个目录")
    a = ap.parse_args()
    cap = Path(a.capture).resolve(); common.CAP = cap
    tree, n_content = build_tree(cap); common.SIM = tree
    run_dir = common.ROOT / "runs" / a.tag
    if run_dir.exists(): shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    t0 = time.time()
    evs, meta = common.load_events(), common.load_meta()
    n_raw = len(evs); evs, noise = H.filter_noise(evs)
    print(f"noise filter: {n_raw} -> {len(evs)} events; dropped {noise}")
    meta["user_home"] = str(tree); meta["watched_dirs"] = sorted(p.name for p in tree.iterdir() if p.is_dir())
    meta["user_aliases"] = meta.get("user_aliases") or []
    from .detectors import run_all
    from .deid import Deid
    from . import run as R, inbox
    deid = Deid(meta)
    allf = run_all(evs, meta)
    skipped = Counter(f["kind"] for f in allf if f["kind"] in SKIP_KINDS)
    fs = [f for f in allf if f["kind"] not in SKIP_KINDS]
    print(f"skipped in backfill mode: {dict(skipped)}; navigational searches dropped: {meta.get('_navigational_searches', {})}")
    hfs = H.run_history(evs, meta)
    from .sheet_audit import detect_manual_summary
    hfs += detect_manual_summary(evs, meta)
    rhythm_titles = {f["local"]["title"] for f in hfs if f["kind"] == "site_rhythm"}
    fs = [f for f in fs if not (f["kind"] == "recurring_doc_focus" and any(f["local"]["title"] == common.norm_title(t) for t in rhythm_titles))]
    fs = sorted(fs + hfs, key=lambda f: -f["score"])
    for i, f in enumerate(fs, 1): f["id"] = f"H{i}"
    desc = lambda f: H.describe(f) if f["kind"] in H.KIND_CN else R.describe(f, deid)
    cands = [f for f in fs if f["score"] >= MIN_SCORE]
    silent = [{"id": f["id"], "kind": f["kind"], "why": f"价值分 {f['score']:.1f} 低于阈值，只记录不打扰", "desc": desc(f)} for f in fs if f["score"] < MIN_SCORE]
    env = type("Env", (), {})(); env.evs, env.meta, env.deid, env.run_dir, env.tree = evs, meta, deid, run_dir, tree
    env.recurring, env.dups = [], []
    llm = None
    if not a.no_llm:
        from .llm import LLM, parse_json
        llm = LLM(run_dir, a.model); llm.deid = deid; env.llm = llm
    # ---- 判断
    if llm:
        lines = "\n".join(f"- id={f['id']} 类型={f['kind']}：{desc(f)}" for f in cands); deid.audit(lines)
        txt, _ = llm.chat("judge", R.JUDGE_SYS, "这是从用户电脑过去几个月的历史痕迹（不是实时记录）里统计出的规律：\n" + lines)
        judge = {j["id"]: j for j in parse_json(txt)}
    else:
        judge = {f["id"]: {"worth": True, "why": "规则判断",
                           "urgency": "高" if f["facts"].get("due_today_or_overdue") or f["facts"].get("final_is_not_newest") else "中"} for f in cands}
    # ---- 准备成品
    results = {}
    for f in cands:
        j = judge.get(f["id"], {"worth": False, "why": "模型没有回复"})
        if not j.get("worth"):
            silent.append({"id": f["id"], "kind": f["kind"], "why": "判断：不值得打扰。" + j.get("why", ""), "desc": desc(f)}); continue
        t = time.time()
        try:
            if f["kind"] in H.KIND_CN: res = H.solve(f, env)
            elif llm:
                from .solvers import SOLVERS
                res = SOLVERS[f["kind"]](f, env, a.model)
            else:
                from .solvers import solve_observation
                res = solve_observation(f, env, a.model)
        except Exception as ex:
            res = {"status": "failed", "error": repr(ex)[:300], "artifacts": [], "slots": {}, "verify_deid": {}}
        res["solve_s"] = round(time.time() - t, 2); results[f["id"]] = res
        if res["status"] in ("omit", "failed"):
            silent.append({"id": f["id"], "kind": f["kind"], "why": "没有能替你做好的成品，按“不打扰”规则不上清单", "desc": desc(f)})
    # ---- 卡片（只给能上清单的写）
    # 去打扰（和第 7 轮一致）：只有 verified，或带成品文件的 draft 才上清单；只做了提醒（reminder_only）的不上；每天最多 max_cards 张
    ready = [f for f in cands if f["id"] in results and (results[f["id"]]["status"] == "verified" or (results[f["id"]]["status"] == "draft" and results[f["id"]].get("artifacts")))]
    for f in cands:
        if f["id"] in results and results[f["id"]]["status"] == "reminder_only":
            silent.append({"id": f["id"], "kind": f["kind"], "why": "只做到了提醒，没有替你做好的成品，按“只上已验证成品”的规则不上清单", "desc": desc(f)})
    show = ready[:a.max_cards]
    for f in ready[a.max_cards:]:
        silent.append({"id": f["id"], "kind": f["kind"], "why": f"成品已验证，但今天已满 {a.max_cards} 张，压到下次", "desc": desc(f)})
    if a.prepared:   # 成品另存一份到指定目录（例如 capture/prepared，不进 git）
        pdir = Path(a.prepared); pdir.mkdir(parents=True, exist_ok=True)
        for f in show:
            for art in results[f["id"]].get("artifacts", []):
                dst = pdir / f["id"] / Path(art).name; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(art, dst)
    if llm and show:
        body = "\n\n".join(f"### id={f['id']} 类型={f['kind']} 紧急度={judge[f['id']].get('urgency')}\n发现：{desc(f)}\n为什么重要：{judge[f['id']].get('why', '')}\n"
                           f"准备状态：{results[f['id']]['status']}；验证摘要：{json.dumps(results[f['id']].get('verify_deid', {}), ensure_ascii=False)}\n"
                           f"已准备的文件数：{len(results[f['id']].get('artifacts', []))}；工作流说明：{(results[f['id']].get('workflow') or {}).get('explain', '无')}\n"
                           f"可用占位符：{', '.join('{'+k+'}' + '(' + R.slot_type(v) + ')' for k, v in results[f['id']].get('slots', {}).items())}" for f in show)
        body = deid.scrub(body); deid.audit(body)
        txt, _ = llm.chat("write_cards", R.WRITER_SYS + "\n补充：status=reminder_only 的只做了提醒，不能说“已经做好”。", "给下面每一条写一张卡片：\n\n" + body, max_tokens=5000)
        cards = {c["id"]: c for c in parse_json(txt)}
        # 标题里的数字不交给模型：有确定性模板的类型，标题用模板（第 9 轮：模型把“解释不了的格数”当成了“对不上的格数”写进标题）
        for fid, c in cards.items():
            f0 = next((x for x in show if x["id"] == fid), None)
            if f0 and f0["kind"] in H.KIND_CN:
                c["title_llm"] = c.get("title"); c["title"] = H.template_card(f0, results[fid])["title"]
        # 模型有时把提示里的占位符类型也抄进正文：“{文件}(文件名)”→“{文件}”
        import re as _re
        for c in cards.values():
            for k2, v in list(c.items()):
                if isinstance(v, str): c[k2] = _re.sub(r"(\{[^{}]+\})\s*[（(](?:文件名|数字|文本|日期|金额|名称)[)）]", r"\1", v)
    else:
        cards = {f["id"]: H.template_card(f, results[f["id"]]) for f in show}
    # ---- 已办清单
    inbox.KIND_CN.update(H.KIND_CN)
    _ev = inbox.evidence
    inbox.evidence = lambda f, r: H.evidence(f) if f["kind"] in H.KIND_CN else _ev(f, r)
    llm_log = run_dir / "llm_log.jsonl"
    summary = {"tag": a.tag, "model": a.model if llm else "不调用模型（规则+模板）", "generated_at": datetime.now().isoformat(timespec="seconds"),
               "now": meta["now"], "mode": "backfill", "timing": {"total_s": round(time.time() - t0, 2), "events": len(evs), "events_raw": n_raw, "noise_dropped": noise, "skipped_kinds": dict(skipped), "navigational_searches": len(meta.get("_navigational_searches", {})), "content_files": n_content},
               "source": {"dataset": "本机历史回溯（backfill_win）", "license": "你自己的数据，只在本机",
                          "participant": f"回看 {meta.get('source', {}).get('lookback_days', '?')} 天"},
               "findings": [{"id": f["id"], "kind": f["kind"], "score": f["score"], "desc": desc(f), "facts": f["facts"],
                             "local": json.loads(json.dumps(f["local"], ensure_ascii=False, default=str))} for f in fs],
               "judge": judge, "silent": silent, "results": results, "cards": cards,
               "llm": [json.loads(l) for l in open(llm_log, encoding="utf-8")] if llm_log.exists() else []}
    (run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    inbox.render(summary, run_dir, title_note="从你电脑过去的痕迹里找到的，不需要一直开着监控")
    for fn in ("inbox.html", "inbox.md"):   # inbox.render 的横幅是给开源数据集写的，这里改成回溯模式的说法
        p = run_dir / fn; t = p.read_text(encoding="utf-8")
        t = t.replace("已办清单 · 真实数据 ·", "已办清单 · 历史回溯 ·").replace("真实数据实测 · 真实开源数据 ", "")
        p.write_text(t, encoding="utf-8")
    print(f"done: {run_dir} events={len(evs)} findings={len(fs)} candidates={len(cands)} cards={len(cards)} llm_calls={len(summary['llm'])} total={summary['timing']['total_s']}s")
    for f in fs: print(f"  {f['id']} {f['kind']:<20} {f['score']:6.1f} {results.get(f['id'], {}).get('status', '-'):<14} {desc(f)[:110]}")

if __name__ == "__main__":
    main()
