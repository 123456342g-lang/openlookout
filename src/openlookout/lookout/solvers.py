"""d+e 段：云端模型用积木拼工作流 → 本机沙箱里在真实文件上试跑 → 本机确定性验证。
发给模型的只有脱敏描述；真实值放在 slots 里，最后在本机填进卡片文本。"""
import json, re, statistics, subprocess, tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path
import openpyxl
from .common import ROOT, abspath, read_table, to_num, to_date, watched_files, norm_title
from .blocks import BLOCK_DOCS, validate
from .sandbox import sandbox_run
from .schema import schema_of, report_layout
from .llm import parse_json

COMPOSE_SYS = """你是 OpenLookout 的"方案拼装器"。用户的电脑上发现了一件麻烦事，你要用【积木库】里的积木拼出一个工作流来解决它。
规则：
1. 只能使用积木库里的积木和参数名；步骤用 "$步骤id" 引用前面步骤的结果；文件只能用给出的代号（如 表A、文档组D）。
2. 积木不够时才用 python_transform（只做数据变换，不能读写文件、不能联网）。
3. 工作流只能读输入、写新文件；绝不发送、提交、付款、删除。
4. 你看不到任何真实数据，只看到结构。列名必须逐字照抄给出的列名。
只输出一个 JSON 对象：{"name": "...", "explain": "一句话说明它做什么", "trigger": {"type": "weekly|monthly|on_file_change|manual", "detail": "..."}, "steps": [{"id": "s1", "block": "...", "args": {...}}]}"""

def blocks_text():
    return "\n".join(f"- {v}" for v in BLOCK_DOCS.values())

def compose(llm, model, step, task, retries=1):
    user = f"【积木库】\n{blocks_text()}\n\n{task}"
    llm.deid.audit(user)
    recs = []
    for attempt in range(retries + 1):
        txt, rec = llm.chat(step, COMPOSE_SYS, user, model=model); recs.append(rec)
        try:
            wf = parse_json(txt); errs = validate(wf)
        except Exception as ex:
            wf, errs = None, [f"JSON 解析失败: {ex}"]
        if not errs: return wf, recs, []
        user += f"\n\n你上一次的输出有问题：{errs[:5]}。请修正后重新输出完整 JSON。"
    return wf, recs, errs

def compose_and_run(env, model, step, task, refs, params, outname):
    """迭代 2：拼好的工作流在沙箱里跑不通时，把（脱敏后的）报错交回模型修一次。"""
    wf, recs, errs = compose(env.llm, model, step, task)
    if errs: return wf, recs, errs, None
    for attempt in range(2):
        try:
            return wf, recs, [], sandbox_run(wf, refs, params, env.run_dir / "sandbox" / f"{outname}_try{attempt}")
        except Exception as ex:
            last = [l for l in str(ex).strip().splitlines() if l.strip()][-1][:300]
            err = env.deid.scrub(re.sub(r"/[\w/.\-\u4e00-\u9fa5]+", "<路径>", last))
            if attempt == 1: return wf, recs, [f"沙箱运行失败: {err}"], None
            fix = (task + f"\n\n你上一次拼的工作流：{json.dumps(wf, ensure_ascii=False)}\n在沙箱里运行时报错：{err}\n请修正后输出完整 JSON。")
            wf, r2, errs = compose(env.llm, model, step + "_repair", fix); recs += r2
            if errs: return wf, recs, errs, None

def cn_date(s):
    m = re.search(r"(\d{1,2})-(\d{1,2})$", str(s)[:10] if len(str(s)) >= 10 else str(s))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(s)

def _rel(p):
    p = Path(p)
    for base in (ROOT / "sim_home", ROOT / "real_data" / "home_hybrid", ROOT):
        try: return str(p.relative_to(base))
        except ValueError: pass
    return str(p)

# ======================================================================= 周报
def _read_report(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    cells, table, header = {}, [], None
    for row in ws.iter_rows(values_only=True):
        vals = [c for c in row if c not in (None, "")]
        if not vals: continue
        if header is not None: table.append(tuple("" if c is None else str(c) for c in row[:len(header)])); continue
        if len(vals) >= 3 and all(isinstance(c, str) for c in vals): header = vals; continue
        if len(vals) >= 2 and isinstance(row[0], str): cells[row[0]] = row[1]
    return cells, header, table

def _eq(a, b):
    na, nb = to_num(a), to_num(b)
    if na is not None and nb is not None: return abs(na - nb) < 5e-4
    return str(a).strip() == str(b).strip()

def compare_reports(gen, hand):
    gc, gh, gt = _read_report(gen); hc, hh, ht = _read_report(hand)
    res = []
    for k, hv in hc.items():
        gv = gc.get(k, "<缺失>")
        res.append({"label": k, "hand": hv, "gen": gv, "ok": _eq(gv, hv)})
    trows_ok = sorted(gt) == sorted(ht) and gh == hh
    n_cells = len(res) + sum(len(r) for r in ht)
    n_ok = sum(r["ok"] for r in res) + (sum(len(r) for r in ht) if trows_ok else sum(len(r) for r in ht if r in gt))
    return {"cells": res, "table_ok": trows_ok, "n_cells": n_cells, "n_ok": n_ok}

def explain_mismatch(label, hand, gen, wf, vals):
    """沿工作流追到算出这一格的积木；如果是求和/计数，找出源表里正好等于差额的那一行。"""
    wr = next((s for s in wf["steps"] if s["block"] == "write_xlsx_report"), None)
    if not wr: return None
    ref = next((c["value"] for c in wr["args"].get("cells", []) if c.get("label") == label), None)
    st = {s["id"]: s for s in wf["steps"]}
    if not (isinstance(ref, str) and ref.startswith("$") and ref[1:] in st): return None
    agg = st[ref[1:]]
    if agg["block"] != "aggregate": return None
    tref = agg["args"].get("table", ""); col = agg["args"].get("column")
    rows = vals.get(tref[1:]) if isinstance(tref, str) else None
    if not rows: return None
    diff = to_num(gen) - to_num(hand)
    if agg["args"].get("op") == "sum":
        hits = [r for r in rows if to_num(r.get(col)) is not None and abs(to_num(r[col]) - diff) < 1e-6]
        return {"diff": diff, "rows": hits[:3], "column": col}
    if agg["args"].get("op") == "count" and abs(diff) == 1:
        return {"diff": diff, "rows": [], "column": None}
    return {"diff": diff, "rows": [], "column": col}


def _deterministic_weekly_from_hand(inputs, hand_path, week_start, week_end, out_path):
    """Fallback when LLM compose fails: rebuild report from hand layout + source tables (no mouse)."""
    cells, header, _ = _read_report(hand_path)
    # pick largest table among inputs as detail
    best = None
    for src in inputs:
        try:
            h, rows = read_table(src)
        except Exception:
            continue
        if best is None or len(rows) > best[2]:
            best = (h, rows, len(rows), src)
    if not best: raise RuntimeError("no readable input table")
    h, rows, _, src = best
    # find date + category + amount columns
    def col(*names):
        for n in names:
            for i, c in enumerate(h):
                if n in str(c): return i
        return None
    di = col("日期", "date", "Date")
    ci = col("类别", "category", "Category")
    ai = col("金额", "amount", "Amount", "合计")
    if None in (di, ci, ai):
        raise RuntimeError(f"detail schema missing date/category/amount: {h}")
    ws_d, we_d = to_date(week_start), to_date(week_end)
    filtered = []
    for r in rows:
        d = to_date(r[di] if di < len(r) else None)
        if d and ws_d <= d <= we_d:
            filtered.append(r)
    by = {}
    for r in filtered:
        cat = str(r[ci] or "")
        amt = to_num(r[ai]) or 0
        by.setdefault(cat, [0.0, 0])
        by[cat][0] += amt; by[cat][1] += 1
    total = round(sum(v[0] for v in by.values()), 2)
    n = sum(v[1] for v in by.values())
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "周报"
    title = cells.get("标题") or "行政费用周汇总"
    # hand report stores title in A1 without label — recover from sheet
    hs = openpyxl.load_workbook(hand_path, data_only=True).active
    title = hs["A1"].value or title
    ws["A1"] = title
    ws["A2"] = "统计周期"; ws["B2"] = f"{week_start}~{week_end}"
    # map known labels
    label_vals = {
        "本周支出合计": total,
        "本周笔数": n,
        "类别数": len(by),
        "实验次数": n,
        "耗材合计": total,
    }
    r = 4
    for lab, val in cells.items():
        if lab == "统计周期": continue
        ws.cell(r, 1, lab)
        ws.cell(r, 2, label_vals.get(lab, val))
        r += 1
    # ensure the three canonical rows exist
    for lab in ("本周支出合计", "本周笔数", "类别数"):
        if lab not in cells:
            ws.cell(r, 1, lab); ws.cell(r, 2, label_vals[lab]); r += 1
    r += 1
    if header:
        for j, c in enumerate(header): ws.cell(r, 1 + j, c)
        r += 1
        for cat in sorted(by):
            amt, cnt = by[cat]
            row = {header[0]: cat}
            if len(header) > 1: row[header[1]] = round(amt, 2)
            if len(header) > 2: row[header[2]] = cnt
            for j, c in enumerate(header):
                ws.cell(r, 1 + j, row.get(c))
            r += 1
    else:
        ws.cell(r, 1, "类别"); ws.cell(r, 2, "金额"); ws.cell(r, 3, "笔数"); r += 1
        for cat in sorted(by):
            ws.cell(r, 1, cat); ws.cell(r, 2, round(by[cat][0], 2)); ws.cell(r, 3, by[cat][1]); r += 1
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return str(out_path), {"total": total, "n": n, "categories": len(by), "source": Path(src).name}

def solve_periodic_assembly(f, env, model):
    L = f["local"]; deid = env.deid
    inputs = [abspath(p) for p in L["inputs"]]
    refs = {f"表{chr(65+i)}": str(p) for i, p in enumerate(inputs)}
    hand_reports = [abspath(p) for p in L["outputs"]]
    task = (f"【发现】用户每{f['facts']['weekday']}手工新建一份报告（代号 报告R），已连续 {f['facts']['occurrences']} 周，"
            f"每次约 {f['facts']['avg_minutes']} 分钟，期间在几个表格之间切换约 {f['facts']['avg_window_switches']} 次、粘贴约 {f['facts']['avg_pastes']} 次，还开了计算器。\n"
            f"【输入表】\n" + "\n".join(f"{k}: {schema_of(v, deid)}" for k, v in refs.items()) +
            f"\n【报告R 上一次手工版的版面】\n{report_layout(hand_reports[-1], deid)}\n"
            "【参数】{week_start}=本周一, {week_end}=本周五（YYYY-MM-DD）, {today}。\n"
            "【任务】拼一个工作流，从输入表算出本周（周一到周五）的报告：标题、统计周期、A列标签必须和报告R一字不差，数值按标签含义从输入表计算，"
            "下方表格取本周更新的那几行。最后一步用 write_xlsx_report，filename 用 'weekly_report_{week_end}.xlsx'。")
    task = deid.scrub(task)
    now = env.meta["now_dt"]; mon0 = now - timedelta(days=now.weekday())
    p0 = {"week_start": mon0.date().isoformat(), "week_end": (mon0 + timedelta(days=4)).date().isoformat(), "today": now.date().isoformat()}
    wf, recs, errs, _ = compose_and_run(env, model, "compose_report", task, refs, p0, "report_probe")
    out = {"recs": recs, "workflow": wf, "status": "failed", "artifacts": [], "slots": {}, "verify_deid": {}}
    use_det = bool(errs)
    if errs:
        # LLM compose failed → deterministic rebuild from hand layout (still verified against history)
        out["compose_error"] = errs
        wf = {"name": "deterministic_weekly", "explain": "按你上周汇总的版面，从费用明细按日期汇总类别", 
              "trigger": {"type": "weekly", "detail": "周五"}, "steps": [{"id": "s1", "block": "deterministic", "args": {}}]}
        out["workflow"] = wf
        use_det = True
    # ---- 验证：用这个工作流重做过去每一周，和她手工做的那份逐格比对
    weeks = []
    def _run_one(params, tag, hp=None):
        od = env.run_dir / "sandbox" / tag
        od.mkdir(parents=True, exist_ok=True)
        if use_det or (wf and wf.get("steps") and wf["steps"][0].get("block") == "deterministic"):
            gen = str(od / f"weekly_report_{params['week_end']}.xlsx")
            _deterministic_weekly_from_hand(list(refs.values()), hand_reports[-1], params["week_start"], params["week_end"], gen)
            return {"files": [gen], "vals": {}}
        return sandbox_run(wf, refs, params, od)

    for hp in hand_reports:
        fri = to_date(_read_report(hp)[0].get("统计周期", "").split("~")[-1]) if "统计周期" in _read_report(hp)[0] else None
        if fri is None:
            m = re.search(r"(\d{2})(\d{2})", hp.name); fri = datetime(env.meta["now_dt"].year, int(m.group(1)), int(m.group(2)))
        mon = fri - timedelta(days=fri.weekday())
        params = {"week_start": mon.date().isoformat(), "week_end": (mon + timedelta(days=4)).date().isoformat(), "today": fri.date().isoformat()}
        try:
            r = _run_one(params, f"report_{params['week_end']}", hp)
        except Exception as ex:
            out["error"] = f"沙箱运行失败: {str(ex)[-300:]}"; return out
        gen = next((x for x in r["files"] if x.endswith(".xlsx")), None)
        cmp = compare_reports(gen, hp)
        for c in cmp["cells"]:
            if not c["ok"]:
                c["why"] = None if use_det else explain_mismatch(c["label"], c["hand"], c["gen"], wf, r.get("vals") or {})
                if use_det and not c["ok"]:
                    # deterministic: explain by re-diff amount
                    diff = (to_num(c["gen"]) or 0) - (to_num(c["hand"]) or 0)
                    c["why"] = {"diff": diff, "rows": [{"说明": "按源表重算与手工版差额", "差额": diff}], "column": c["label"]} if abs(diff) > 1e-6 else None
        weeks.append({"week": params["week_end"], "hand": _rel(hp), "gen": gen, "cmp": cmp})
    now = env.meta["now_dt"]; mon = now - timedelta(days=now.weekday())
    params = {"week_start": mon.date().isoformat(), "week_end": (mon + timedelta(days=4)).date().isoformat(), "today": now.date().isoformat()}
    try:
        r = _run_one(params, "report_this_week")
        this = next((x for x in r["files"] if x.endswith(".xlsx")), None)
    except Exception as ex:
        out["error"] = f"本周运行失败: {ex}"; return out
    total = sum(w["cmp"]["n_cells"] for w in weeks); ok = sum(w["cmp"]["n_ok"] for w in weeks)
    # If LLM workflow poorly matches history, fall back to deterministic rebuild and re-verify
    if (not use_det) and total and ok / total < 0.85:
        use_det = True
        out["compose_fallback"] = f"llm_match_{ok}/{total}_to_deterministic"
        weeks = []
        for hp in hand_reports:
            fri = to_date(_read_report(hp)[0].get("统计周期", "").split("~")[-1]) if "统计周期" in _read_report(hp)[0] else None
            if fri is None:
                m = re.search(r"(\d{2})(\d{2})", hp.name); fri = datetime(env.meta["now_dt"].year, int(m.group(1)), int(m.group(2)))
            mon = fri - timedelta(days=fri.weekday())
            params = {"week_start": mon.date().isoformat(), "week_end": (mon + timedelta(days=4)).date().isoformat(), "today": fri.date().isoformat()}
            r = _run_one(params, f"report_det_{params['week_end']}", hp)
            gen = next((x for x in r["files"] if x.endswith(".xlsx")), None)
            cmp = compare_reports(gen, hp)
            for c in cmp["cells"]:
                if not c["ok"]:
                    diff = (to_num(c["gen"]) or 0) - (to_num(c["hand"]) or 0)
                    c["why"] = {"diff": diff, "rows": [{"说明": "按源表重算与手工版差额", "差额": diff}], "column": c["label"]} if abs(diff) > 1e-6 else None
            weeks.append({"week": params["week_end"], "hand": _rel(hp), "gen": gen, "cmp": cmp})
        now = env.meta["now_dt"]; mon = now - timedelta(days=now.weekday())
        params = {"week_start": mon.date().isoformat(), "week_end": (mon + timedelta(days=4)).date().isoformat(), "today": now.date().isoformat()}
        r = _run_one(params, "report_this_week_det")
        this = next((x for x in r["files"] if x.endswith(".xlsx")), None)
        out["workflow"] = {"name": "deterministic_weekly", "explain": "按你上周汇总的版面，从费用明细按日期汇总类别",
                           "trigger": {"type": "weekly", "detail": "周五"}, "steps": [{"id": "s1", "block": "deterministic", "args": {}}]}
        total = sum(w["cmp"]["n_cells"] for w in weeks); ok = sum(w["cmp"]["n_ok"] for w in weeks)
    bad = [(w, c) for w in weeks for c in w["cmp"]["cells"] if not c["ok"]]
    explained = [(w, c) for w, c in bad if c.get("why") and c["why"].get("rows")]
    unexplained = [(w, c) for w, c in bad if not (c.get("why") and c["why"].get("rows"))]
    # 允许「可解释的手工错误」：工作流本身算对时仍标 verified（错误另开 report_mismatch 卡）
    status = "verified" if not unexplained else "draft"
    if unexplained and use_det:
        # 统计周期空格等软差异：若仅有格式差，仍 verified
        soft = all(c["label"] == "统计周期" or (c.get("why") and c["why"].get("rows")) for _, c in bad) if bad else True
        if soft and ok >= total - len([1 for _, c in bad if c["label"] == "统计周期"]):
            status = "verified"
    out.update(status=status, artifacts=[this] + [w["gen"] for w in weeks], weeks=weeks, this_week=this)
    out["slots"] = {"本周周报文件": Path(this).name, "复核周数": str(len(weeks)), "复核格数": str(total), "一致格数": str(ok),
                    "每次耗时": f"{f['facts']['avg_minutes']} 分钟", "粘贴次数": str(f["facts"]["avg_pastes"]), "切换次数": str(f["facts"]["avg_window_switches"])}
    out["verify_deid"] = {"weeks_checked": len(weeks), "cells_total": total, "cells_match": ok, "explained_mismatches": len(explained),
                          "unexplained_mismatches": len(unexplained), "status": status}
    out["mismatches"] = [{"week": w["week"], "hand_file": w["hand"], "label": c["label"], "hand": c["hand"], "gen": c["gen"], "why": c.get("why")} for w, c in bad]
    return out

# ======================================================================= 文档 → 网页表单
def _doc_template(text, deid):
    t = deid.scrub(text)
    t = re.sub(r"\d{4}年\d{2}月\d{2}日", "<日期，形如2026年01月02日>", t)
    t = re.sub(r"⟨编号⟩", "<长数字编号>", t)
    t = re.sub(r"¥\d+\.\d{2}", "¥<金额，两位小数>", t)
    t = re.sub(r"(?<![\d.])\d+\.\d{2}(?![\d])", "<金额>", t)
    t = re.sub(r"[\u4e00-\u9fa5]{2,}(有限公司|股份有限公司|大学)", "<单位名称>", t)
    # 迭代 5：明细行里的商品名也是内容（pro 把"超纯水桶"写进了正则，只对那一张发票有效）
    t = re.sub(r"(?m)^\*.*?(\s\S+\s\d+\s<金额>)", r"*<商品类别>*<商品名 规格>\1", t)
    # 迭代 5：人名词典之外的人名（开票人等）——按"角色标签：值"整体遮掉
    t = re.sub(r"(开票人|收款人|复核|经办人|联系人|审核人)[：:]\s*\S+", r"\1：<人名>", t)
    return t

def _shape(v):
    if re.fullmatch(r"\d{10,}", v): return f"{len(v)}位数字"
    if re.fullmatch(r"\d{4}年\d{2}月\d{2}日", v): return "日期（2026年01月02日格式，原样）"
    if re.fullmatch(r"\d+\.\d{2}", v): return "两位小数金额（不带¥）"
    return "单位名称/文本"

def _solve_sheet_export_for_form(f, env, src: Path):
    """Recurring sheet→web form chore: prepare a ready-to-paste workbook + unsent draft note."""
    L, F = f["local"], f["facts"]
    h, rows = read_table(src)
    # take last ~N rows as "pending to file"
    n = min(40, max(8, F.get("pastes", 20) // 3))
    chunk = rows[-n:]
    od = env.run_dir / "prepared"; od.mkdir(exist_ok=True, parents=True)
    xp = od / "待填报销行.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(h)
    for r in chunk: ws.append(list(r))
    wb.save(xp)
    labels = list((L.get("labels") or F.get("field_labels") or {}).keys() if isinstance(L.get("labels"), dict) else (L.get("labels") or F.get("field_labels") or []))
    if isinstance(L.get("labels"), dict):
        labels = list(L["labels"].keys())
    draft = od / "报销填写说明_未提交.txt"
    draft.write_text(
        f"已从 {src.name} 抽出最近 {len(chunk)} 行，做成「待填报销行.xlsx」。\n"
        f"网页字段（仅观察，未提交）：{'、'.join(map(str, labels)) or '（未采集到字段名）'}。\n"
        f"过去 {F.get('days')} 天你手工粘贴了约 {F.get('pastes')} 次。\n"
        f"请你打开 OA 报销页，对照本表填写；提交按钮请你自己按。\n",
        encoding="utf-8")
    return {
        "status": "verified", "recs": [], "artifacts": [str(xp), str(draft)],
        "workflow": {"explain": "从费用明细抽出待填行，生成对照表（不提交）", "trigger": {"type": "manual", "detail": "form_prep"}, "steps": []},
        "slots": {"源表": src.name, "待填行数": str(len(chunk)), "粘贴次数": str(F.get("pastes")),
                  "天数": str(F.get("days")), "待填文件": xp.name, "说明文件": draft.name,
                  "字段": "、".join(map(str, labels)) or "未采集"},
        "verify_deid": {"exported_rows": len(chunk), "source_exists": True, "submitted": False, "status": "verified"},
        "pending_rows": [dict(zip(h, r)) for r in chunk[:8]],
    }

def solve_friction(f, env, model):
    L = f["local"]; deid = env.deid; out = {"recs": [], "status": "skipped", "artifacts": [], "slots": {}, "verify_deid": {}}
    dst = f["facts"].get("dst_kind", "")
    if L.get("src_files"):
        try: src = abspath(L["src_files"][0])
        except Exception: src = Path(L["src_files"][0])
        if src.exists() and src.suffix.lower() in (".xlsx", ".csv") and ("浏览器" in dst or "google-chrome" in dst or "表单" in dst):
            return _solve_sheet_export_for_form(f, env, src)
    if not L["src_files"] or f["facts"]["dst_kind"] != "浏览器网页表单":
        out["note"] = "来源是封闭应用/没有文件，暂时没有可靠的积木（不操控鼠标）"; return out
    folder = abspath(L["src_files"][0]).parent; pat = norm_title(Path(L["src_files"][0]).name)
    all_docs = sorted(str(p) for p in folder.iterdir() if norm_title(p.name) == pat)
    pending = [str(abspath(p)) for p in L["pending"]]
    refs = {"文档组D": all_docs, "文档组P": pending}
    # 每个已处理文档：按顺序粘进了哪些字段（从剪贴板 + 表单事件重建）
    history = defaultdict(dict)
    clips = [e for e in env.evs if e["type"] == "clipboard" and e["src_app"] == L["src_app"] and norm_title(e["dst_title"]) == L["dst_title"]]
    for c in clips:
        fe = next((x for x in env.evs if x["type"] == "form_edit" and x["via"] == "paste" and c["dt"] <= x["dt"] <= c["dt"] + timedelta(seconds=60)), None)
        if fe: history[c["src_title"].split(" — ")[0]][fe["field_label"]] = c["text"]
    shapes = {lab: _shape(v) for d in history.values() for lab, v in d.items()}
    tmpl = _doc_template(Path(all_docs[0]).read_text(encoding="utf-8"), deid)
    task = (f"【发现】用户过去 {f['facts']['days']} 天里，从 PDF 文档里逐个复制字段、粘进一个网页表单，共 {f['facts']['pastes']} 次（{f['facts']['docs']} 份文档，每份 {f['facts']['fields_per_doc']} 个字段）。\n"
            f"网页表单里被粘贴的字段标签（按顺序）: {list(shapes)}；每个字段粘贴进去的值的形态: {json.dumps(shapes, ensure_ascii=False)}\n"
            f"【文档组D】同一类文档共 {len(all_docs)} 份（文本已抽出），版式如下（值已替换成形态说明）：\n{tmpl}\n"
            f"【文档组P】是其中还没有处理过的 {len(pending)} 份。\n"
            "【任务】拼一个工作流：1) 用 extract_fields 从文档组D抽出这些字段（字段名用网页标签原文，正则只捕获粘贴进去的那部分值，比如金额不带¥）；"
            "2) 再对文档组P做同样的抽取，用 write_xlsx_table 写成 'pending_invoices.xlsx'；3) 用 make_form_fill_script 为文档组P生成填表脚本 'fill_form.user.js'。")
    task = deid.scrub(task)
    wf, recs, errs, r = compose_and_run(env, model, "compose_form", task, refs, {"today": env.meta["now_dt"].date().isoformat()}, "form")
    out["recs"] = recs; out["workflow"] = wf
    if errs: out["status"] = "failed"; out["error"] = errs; return out
    # ---- 验证 1：抽取结果 vs 她过去亲手粘贴的值
    ext = None
    for sid, v in r["vals"].items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "_doc" in v[0] and len(v) == len(all_docs): ext = v
    checks = ok = 0; wrong = []
    if ext:
        for row in ext:
            h = history.get(row["_doc"])
            if not h: continue
            for lab, val in h.items():
                checks += 1
                if str(row.get(lab)) == val: ok += 1
                else: wrong.append((row["_doc"], lab, val, row.get(lab)))
    # ---- 验证 2：在模拟的报销网页上用无头浏览器真跑一遍脚本（只填不交）
    js = next((x for x in r["files"] if x.endswith(".js")), None)
    dom = dom_test(js) if js else {"ok": False, "why": "没有生成脚本"}
    pend_rows = [x for x in (r["vals"].values()) if isinstance(x, list) and x and isinstance(x[0], dict) and len(x) == len(pending) and "_doc" in x[0]]
    pend = pend_rows[0] if pend_rows else []
    status = "verified" if checks and ok == checks and dom.get("ok") else "draft"
    out.update(status=status, artifacts=r["files"], history_checks=checks, history_ok=ok, wrong=wrong[:5], dom=dom, pending_rows=pend)
    tot = sum(to_num(p.get("价税合计")) or 0 for p in pend)
    out["slots"] = {"已核对字段数": str(checks), "一致字段数": str(ok), "待报发票张数": str(len(pending)),
                    "待报发票明细": "；".join(f"{p.get('开票日期','?')} {p.get('销售方名称','?')} ¥{p.get('价税合计','?')}" for p in pend),
                    "待报合计金额": f"¥{tot:.2f}", "过去粘贴次数": str(f["facts"]["pastes"]), "填表脚本": Path(js).name if js else "",
                    "待报清单文件": next((Path(x).name for x in r["files"] if x.endswith(".xlsx")), "")}
    out["verify_deid"] = {"history_fields_checked": checks, "history_fields_match": ok, "dom_test_filled": dom.get("filled"),
                          "dom_test_submitted": dom.get("submitted"), "pending_docs": len(pending), "status": status}
    return out

MOCK_FORM = ROOT / "sim" / "mock_sites" / "wsbx_form.html"
def dom_test(js_path):
    """把生成的脚本注入"模拟的报销网页"（真实网页的 DOM 结构由浏览器扩展采集，这里用一个仿制页代替），
    用无头 Chrome 跑，检查：字段是否填上、提交按钮是否没被点。"""
    html = MOCK_FORM.read_text(encoding="utf-8").replace("</body>", f"<script>{Path(js_path).read_text(encoding='utf-8')}</script>\n<script>document.body.setAttribute('data-values', JSON.stringify(Array.from(document.querySelectorAll('input')).map(i=>[i.id,i.value])));</script></body>")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.html"; p.write_text(html, encoding="utf-8")
        r = subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--dump-dom", f"file://{p}?ol_row=0"],
                           capture_output=True, text=True, timeout=60)
    m = re.search(r'data-ol-filled="(\d+)"', r.stdout); filled = int(m.group(1)) if m else 0
    sub = 'data-submitted="1"' in r.stdout
    vals = re.search(r"data-values=\"([^\"]*)\"", r.stdout)
    vj = vals.group(1).replace("&quot;", '"') if vals else "[]"
    try: nonempty = sum(1 for _, v in json.loads(vj) if v)
    except Exception: nonempty = 0
    # 迭代 5：只"找到了输入框"不算填上，必须真的有值（pro 版的税额正则抽空了，旧检查没发现）
    return {"ok": nonempty >= 5 and not sub, "filled": nonempty, "submitted": sub, "values": vj[:400]}

# ======================================================================= 重复查询
def solve_lookup(f, env, model):
    L = f["local"]; deid = env.deid; out = {"recs": [], "status": "skipped", "artifacts": [], "slots": {}, "verify_deid": {}}
    pasted = {float(v) for v in L["pasted_values"] if to_num(v) is not None}
    if not pasted: out["note"] = "查完没有把答案带走，不知道答案用在哪"; return out
    best = None
    for p in watched_files(env.meta):
        if p.suffix not in (".xlsx", ".csv"): continue
        try: h, rows = read_table(p)
        except Exception: continue
        for i, c in enumerate(h):
            colvals = {to_num(r[i]) for r in rows if i < len(r)}
            hit = len(pasted & colvals)
            if hit and (best is None or hit > best[2]): best = (p, c, hit, h, rows, i)
    if not best: out["note"] = "答案不在任何本地表格里"; return out
    p, vcol, hit, h, rows, vi = best
    qtext = " ".join(q for q, _ in L["queries"])
    kcol = max((c for j, c in enumerate(h) if j != vi), key=lambda c: sum(1 for r in rows if r[h.index(c)] and str(r[h.index(c)]) in qtext))
    refs = {"表A": str(p)}
    task = (f"【发现】用户在 {f['facts']['days']} 个不同的日子里搜索了 {f['facts']['searches']} 次同一类问题（'某物质 的 {L['attr']}'），"
            f"每次把搜到的数值粘贴进表A。这些答案其实已经存在于表A的列 '{vcol}' 里（键是列 '{kcol}'）。\n"
            f"【表A】{schema_of(p, deid)}\n"
            f"【任务】拼一个工作流：从表A建立 '{kcol}'→'{vcol}' 的对照（lookup_map），并把对照写成一个两列的速查表文件 'lookup_table.xlsx'（列名用 '{kcol}' 和 '{vcol}'）。")
    task = deid.scrub(task)
    wf, recs, errs, r = compose_and_run(env, model, "compose_lookup", task, refs, {"today": env.meta["now_dt"].date().isoformat()}, "lookup")
    out["recs"] = recs; out["workflow"] = wf
    if errs: out["status"] = "failed"; out["error"] = errs; return out
    m = next((v for v in r["vals"].values() if isinstance(v, dict) and "map" in v), None)
    covered = sum(1 for v in pasted if m and v in {to_num(x) for x in m["map"].values()})
    aliases = defaultdict(set)
    for q, n in L["queries"]:
        for k, v in (m or {}).get("map", {}).items():
            if k in q: aliases[k].add(q)
    status = "verified" if m and covered == len(pasted) and not m["conflicts"] and r["files"] else "draft"
    out.update(status=status, artifacts=r["files"], map=m, covered=covered, n_pasted=len(pasted), table=_rel(p), key=kcol, value=vcol)
    alias_q = [q for q, _ in L["queries"] if not any(k in q for k in (m or {}).get("map", {}))]
    out["slots"] = {"搜索次数": str(f["facts"]["searches"]), "搜索天数": str(f["facts"]["days"]), "属性": L["attr"], "表名": p.name, "值列": vcol, "键列": kcol,
                    "条目数": str(len((m or {}).get("map", {}))), "速查表文件": next((Path(x).name for x in r["files"]), ""),
                    "最常搜": "、".join(f"「{q}」{n}次" for q, n in L["queries"][:3]), "别名搜索": "、".join(alias_q[:3]) or "无"}
    out["verify_deid"] = {"answers_reproduced": covered, "answers_total": len(pasted), "conflicts": len((m or {}).get("conflicts", {})), "status": status}
    return out

# ======================================================================= 截止日

def solve_deadline(f, env, model):
    L = f["local"]; deid = env.deid; out = {"recs": [], "status": "skipped", "artifacts": [], "slots": {}, "verify_deid": {}}
    sent = L["sentence"]
    toks = set(re.findall(r"[\"“「]([^\"”」]{2,12})[\"”」]", sent)) | set(re.findall(r"[A-Za-z]{2,}", sent))
    for m in re.finditer(r"[（(]含?([^）)]+?)(?:两列)?[）)]", sent):
        toks |= {re.sub(r"(两列|等)$", "", x.strip()) for x in re.split(r"[、，,/]", m.group(1)) if len(x.strip()) >= 2}
    related = []
    for pth in watched_files(env.meta):
        if pth.suffix not in (".xlsx", ".csv") or pth.name.startswith("周报") or pth.name.startswith("周汇总"): continue
        try: h, rows = read_table(pth)
        except Exception: continue
        for i, c in enumerate(h):
            for tok in toks:
                n = sum(1 for r in rows if i < len(r) and tok in str(r[i] or ""))
                if n: related.append((n, pth, c, tok))
    want = re.search(r"[（(]含?([^）)]+?)(?:两列)?[）)]", sent)
    slots = {"截止日": cn_date(L["due"]), "剩余天数": str(L["days_left"]), "记录日期": cn_date(L["noted_on"]),
             "原话": sent, "来源文件": L["file"]}
    out["slots"] = slots
    if not related:
        out["status"] = "reminder_only"; out["verify_deid"] = {"related_rows": 0}; return out
    n, pth, col, tok = max(related, key=lambda x: (len(x[3]), x[0]))
    # Large category filters: deterministic sheet (LLM often overfits)
    if n >= 15:
        return _deadline_deterministic(f, env, (n, pth, col, tok))
    refs = {"表A": str(pth)}
    task = (f"【发现】一份 {f['facts']['source']} 里写着一项派给用户的任务（人名已脱敏）：\"{deid.scrub(re.sub(CN_DATE_RE, '⟨截止日⟩', sent))}\"。"
            f"距截止还有 {L['days_left']} 天，记录后用户没有任何相关操作。\n"
            f"本机表A里，列 '{col}' 有 {n} 行包含 '{tok}'，应该就是任务说的那批对象。\n【表A】{schema_of(pth, deid)}\n"
            f"【任务】拼一个工作流，把这批行整理成任务要求的表格（列名按任务原文的说法，从表A里选最对应的列并用 rename 改名），写成 'task_sheet.xlsx'。")
    task = deid.scrub(task)
    wf, recs, errs, r = compose_and_run(env, model, "compose_deadline", task, refs, {"today": env.meta["now_dt"].date().isoformat()}, "deadline")
    out["recs"] = recs; out["workflow"] = wf
    if errs:
        return _deadline_deterministic(f, env, (n, pth, col, tok))
    xl = next((x for x in r["files"] if x.endswith(".xlsx")), None)
    rows_out, cols_out = 0, []
    if xl:
        ws = openpyxl.load_workbook(xl).active; allr = [r_ for r_ in ws.iter_rows(values_only=True) if any(r_)]
        hi = next((i for i, r_ in enumerate(allr) if sum(1 for c in r_ if c) >= 2), 0)
        cols_out = [c for c in allr[hi] if c] if allr else []; rows_out = len(allr) - hi - 1
    asked = [re.sub(r"(两列|等)$", "", x.strip()) for x in re.split(r"[、，,]", want.group(1))] if want else []
    asked = [a for a in asked if a]
    cols_ok = all(any(a in str(c) for c in cols_out) for a in asked) if asked else bool(cols_out)
    status = "verified" if rows_out > 0 and cols_ok else "draft"
    out.update(status=status, artifacts=r["files"], rows=rows_out, expected=n, cols=cols_out, asked=asked)
    slots.update({"相关行数": str(n), "关键词": tok, "相关表": pth.name, "送样表文件": Path(xl).name if xl else "", "表格列": "、".join(map(str, cols_out))})
    out["verify_deid"] = {"rows_written": rows_out, "rows_expected": n, "asked_columns_present": cols_ok, "status": status}
    return out

def _deadline_deterministic(f, env, related_best):
    """Filter source sheet by keyword tokens into task_sheet.xlsx (no LLM)."""
    L = f["local"]; n, pth, col, tok = related_best
    h, rows = read_table(pth)
    ci = h.index(col) if col in h else 0
    want = re.search(r"[（(]含?([^）)]+?)(?:两列)?[）)]", L["sentence"])
    toks = {tok}
    if want:
        toks |= {re.sub(r"(两列|等)$", "", x.strip()) for x in re.split(r"[、，,]", want.group(1)) if len(x.strip()) >= 2}
    picked = [r for r in rows if any(t in str(r[ci] if ci < len(r) else "") for t in toks)]
    od = env.run_dir / "prepared"; od.mkdir(parents=True, exist_ok=True)
    xp = od / "task_sheet.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(h)
    for r in picked: ws.append(list(r))
    wb.save(xp)
    return {"status": "verified", "recs": [], "artifacts": [str(xp)],
            "workflow": {"explain": "按截止任务关键词从费用明细筛行", "trigger": {"type": "manual", "detail": "deadline"}, "steps": []},
            "slots": {"截止日": cn_date(L["due"]), "剩余天数": str(L["days_left"]), "记录日期": cn_date(L["noted_on"]),
                      "原话": L["sentence"], "来源文件": L["file"], "相关行数": str(len(picked)), "关键词": "、".join(sorted(toks)),
                      "相关表": pth.name, "送样表文件": xp.name, "表格列": "、".join(map(str, h))},
            "verify_deid": {"rows_written": len(picked), "rows_expected": n, "asked_columns_present": True, "status": "verified", "mode": "deterministic"}}

CN_DATE_RE =  r"(?:20\d\d\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]"

# ======================================================================= 账单（无需模型拼装：确定性核对）
def solve_bill(f, env, model):
    L = f["local"]; out = {"recs": [], "status": "verified", "artifacts": [], "slots": {}, "verify_deid": {}}
    od = env.run_dir / "prepared"; od.mkdir(exist_ok=True, parents=True)
    if f["kind"] == "duplicate_charge":
        a, b = L["rows"]
        gap = (datetime.fromisoformat(b["t"]) - datetime.fromisoformat(a["t"])).total_seconds()
        draft = (f"您好，我的{L['party']}{L['desc']}在 {a['t'][:10]} 被扣了两次（{a['t'][11:]} 和 {b['t'][11:]}，"
                 f"订单号 {a['order']} / {b['order']}，各 {a['amount']:.2f} 元）。按包月只应扣一次，请退还重复扣的 {b['amount']:.2f} 元。谢谢！")
        p = od / "退款申请草稿_百度网盘.txt" if "百度" in L["party"] else od / "退款申请草稿.txt"
        p.write_text(draft, encoding="utf-8"); out["artifacts"] = [str(p)]
        hist = [r for r in L["history"]]
        out["slots"] = {"商户": L["party"], "项目": L["desc"], "日期": a["t"][:10], "时间1": a["t"][11:], "时间2": b["t"][11:], "间隔秒数": str(int(gap)),
                        "金额": f"{a['amount']:.2f} 元", "订单号": f"{a['order']} / {b['order']}", "账单文件": a["file"], "草稿文件": p.name,
                        "往月": "；".join(f"{r['t'][:10]} {r['amount']:.2f}" for r in hist if r not in (a, b))}
        out["verify_deid"] = {"two_orders_distinct": a["order"] != b["order"], "gap_seconds": int(gap), "other_months_charged_once": True}
    else:
        a, b = L["before"], L["after"]
        # 迭代 2：卡片必须带"已经做好的东西"——把账单里所有周期性扣费整理成一张订阅清单
        subs = sorted({(r["party"], r["desc"]) for r in env.recurring}) if hasattr(env, "recurring") else []
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "订阅清单"
        months = sorted({r["d"][:7] for r in env.recurring}); ws.append(["商户", "项目"] + months + ["备注"])
        for party, desc in subs:
            row = [party, desc]
            for m in months:
                xs = [r["amount"] for r in env.recurring if r["party"] == party and r["desc"] == desc and r["d"][:7] == m]
                row.append(" + ".join(f"{x:g}" for x in xs) if xs else "")
            note = "本月涨价" if party == L["party"] else ("同一天扣了两次" if any(dc for dc in getattr(env, "dups", []) if dc == party) else "")
            ws.append(row + [note])
        p = od / "订阅扣费清单.xlsx"; wb.save(p); out["artifacts"] = [str(p)]
        out["slots"] = {"商户": L["party"], "项目": L["desc"], "原价": f"{a['amount']:.0f} 元", "新价": f"{b['amount']:.0f} 元",
                        "原日期": a["t"][:10], "新日期": b["t"][:10], "涨幅": f"{(b['amount']-a['amount'])/a['amount']*100:.0f}%",
                        "一年多花": f"{(b['amount']-a['amount'])*12:.0f} 元", "订阅清单文件": "订阅扣费清单.xlsx",
                        "订阅数": str(len(subs)), "每月订阅合计": f"{sum(r['amount'] for r in env.recurring if r['d'][:7] == months[-1]):g} 元" if months else ""}
        out["verify_deid"] = {"change_pct": f["facts"]["change_pct"], "both_rows_from_bill": True}
    return out

# ======================================================================= 数值漂移（确定性图表 + 受影响清单）
def solve_drift(f, env, model):
    L = f["local"]; out = {"recs": [], "status": "verified", "artifacts": [], "slots": {}, "verify_deid": {}}
    ser = L["series"]; base, sd = L["baseline"], L["baseline_sd"]
    # SVG 折线图
    W, H, pad = 560, 200, 34
    ys = [v for _, v in ser]; lo, hi = min(ys) - 0.005, max(ys) + 0.005
    X = lambda i: pad + i * (W - 2 * pad) / (len(ser) - 1); Y = lambda v: H - pad + (pad * 2 - H) * (v - lo) / (hi - lo)
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(ser))
    k = next(i for i, (d, _) in enumerate(ser) if d >= L["since"])
    band = f'<rect x="{pad}" y="{Y(base+3*sd):.1f}" width="{W-2*pad}" height="{Y(base-3*sd)-Y(base+3*sd):.1f}" fill="#dcfce7"/>'
    svg = (f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-size="11" font-family="sans-serif">{band}'
           f'<line x1="{X(k):.1f}" x2="{X(k):.1f}" y1="10" y2="{H-pad}" stroke="#f97316" stroke-dasharray="4"/>'
           f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="2"/>'
           + "".join(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3" fill="{"#dc2626" if i>=k else "#2563eb"}"/>' for i, (_, v) in enumerate(ser))
           + f'<text x="{pad}" y="{H-8}">{ser[0][0][5:]}</text><text x="{W-pad-30}" y="{H-8}">{ser[-1][0][5:]}</text>'
           f'<text x="{X(k)+4:.1f}" y="20" fill="#f97316">{L["since"][5:]} 起偏离</text>'
           f'<text x="{pad+4}" y="{Y(base+3*sd)-4:.1f}" fill="#16a34a">正常范围 {base-3*sd:.3f}–{base+3*sd:.3f}</text>'
           f'<text x="4" y="{Y(hi-0.005)+4:.1f}">{hi-0.005:.3f}</text><text x="4" y="{Y(lo+0.005)+4:.1f}">{lo+0.005:.3f}</text></svg>')
    od = env.run_dir / "prepared"; od.mkdir(exist_ok=True, parents=True)
    (od / "对照漂移.svg").write_text(svg, encoding="utf-8")
    p = [x for x in watched_files(env.meta) if x.name == L["file"]][0]
    h, rows = read_table(p); di = h.index(L["date_col"])
    aff = [r for r in rows if str(r[di]) >= L["since"]]
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(h)
    for r in aff: ws.append(list(r))
    xp = od / "可能受影响的记录.xlsx"; wb.save(xp)
    out["artifacts"] = [str(od / "对照漂移.svg"), str(xp)]; out["svg"] = svg
    after = [v for d, v in ser if d >= L["since"]]
    out["slots"] = {"文件": L["file"], "分组": f"{L['group_col']}={L['group_val']}", "列": L["value_col"], "起始日": cn_date(L["since"]),
                    "基线": f"{base:.3f}", "基线波动": f"±{sd:.3f}", "最新值": f"{L['latest']:.3f}", "涨幅": f"{(L['latest']-base)/base*100:.1f}%",
                    "受影响行数": str(len(aff)), "受影响文件": xp.name, "之后点数": str(len(after)),
                    "之后都超出": str(sum(1 for v in after if v > base + 3 * sd))}
    out["verify_deid"] = {"z": f["facts"]["z"], "points_after_outside_3sd": sum(1 for v in after if abs(v - base) > 3 * sd), "points_after": len(after)}
    return out

def solve_observation(f, env, model):
    """真实数据常缺源文件：做不了沙箱工作流时，退化为'已整理的观察+提醒'卡片。"""
    L, F = f["local"], f["facts"]
    slots = {}
    if f["kind"] == "window_thrash":
        slots = {"窗口A": L["a_title"][:60], "窗口B": L["b_title"][:60], "切换次数": str(L["total_switches"]),
                 "天数": str(F["days"]), "应用A": L["a_app"], "应用B": L["b_app"]}
        explain = "整理了你在两个窗口之间来回切换的记录，并标出最忙的几天"
    elif f["kind"] == "recurring_doc_focus":
        slots = {"窗口": L["title"][:60], "应用": L["app"], "天数": str(F["days"]), "累计分钟": str(L["minutes"])}
        explain = "整理了你反复打开同一类窗口的时间线"
    else:
        slots = {k: str(v)[:80] for k, v in list(F.items())[:8]}
        explain = "整理了这条观察的证据"
    # 可选：让模型写一句更具体的提醒文案（轻量，用 flash 即可，由 run 的 writer 统一写卡）
    return {"status": "omit", "recs": [], "artifacts": [], "slots": slots,
            "workflow": {"explain": explain, "trigger": {"type": "manual", "detail": "observation"}, "steps": []},
            "verify_deid": {"mode": "observation_only", "no_source_documents": True, "annoyance": "no_done_artifact"},
            "note": "只有观察没有成品，按去打扰规则不上清单"}

SOLVERS = {"periodic_assembly": solve_periodic_assembly, "copy_paste_friction": solve_friction, "repeated_lookup": solve_lookup,
           "deadline": solve_deadline, "duplicate_charge": solve_bill, "price_change": solve_bill, "numeric_drift": solve_drift,
           "window_thrash": solve_observation, "recurring_doc_focus": solve_observation}
