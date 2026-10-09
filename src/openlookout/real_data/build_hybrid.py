#!/usr/bin/env python3
"""Build hybrid eval set: REAL open-license spreadsheets + reconstructed multi-week activity.

Honesty:
  - Document numbers come from Dublin City Council «Councillor Allowance and Expenses 2024» (CC-BY).
  - Activity events are RECONSTRUCTED from those documents (weekly consolidation pattern),
    not a real person's screen recording. Paths and timestamps are invented to match the files.
  - Hand-made weekly summaries and a small bank CSV are DERIVED works (CC-BY attribution).
"""
from __future__ import annotations
import csv, hashlib, io, json, math, shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "hybrid" / "raw" / "councillor-expenses-2024.csv"
HOME = ROOT / "home_hybrid" / "admin"
CAP = ROOT / "capture_hybrid"
MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}
# Map DCC fields → Chinese office categories (same numeric values)
CAT_MAP = [
    ("Subistence & Travel", "差旅补贴"),
    ("Petty Cash Expenses", "小额现金"),
    ("Vouched Expenses", "凭票报销"),
    ("Training & Miscellaneous", "培训杂费"),
    ("SPC Chair Allowance", "专项津贴"),
]


def _f(v):
    try:
        return float(str(v or "0").replace(",", "").strip())
    except ValueError:
        return 0.0


def load_dcc():
    raw = RAW.read_bytes().decode("latin-1")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out = []
    for r in rows:
        mo = MONTHS.get((r.get("Month") or "").strip())
        name = (r.get("Councillor") or "").strip()
        if not mo or not name or name == "Total":
            continue
        for eng, zh in CAT_MAP:
            amt = _f(r.get(eng))
            if amt <= 0:
                continue
            out.append({"year": 2024, "month": mo, "person": name, "category": zh, "amount": round(amt, 2), "eng": eng})
    return out


def expand_line_items(dcc_rows):
    """Deterministically expand monthly category totals into weekday line items."""
    items = []
    for i, r in enumerate(dcc_rows):
        # 2–4 slices across the month (stable from hash)
        h = int(hashlib.md5(f"{r['person']}|{r['month']}|{r['category']}".encode()).hexdigest()[:8], 16)
        n = 2 + (h % 3)
        weights = [1 + ((h >> (k * 3)) % 5) for k in range(n)]
        s = sum(weights)
        parts = [round(r["amount"] * w / s, 2) for w in weights]
        parts[-1] = round(r["amount"] - sum(parts[:-1]), 2)
        days_in_month = (datetime(2024, r["month"] % 12 + 1, 1) - timedelta(days=1)).day if r["month"] < 12 else 31
        for j, amt in enumerate(parts):
            if amt <= 0:
                continue
            day = 1 + ((h + j * 7) % min(28, days_in_month))
            dt = datetime(2024, r["month"], day, 9 + (j % 6), 10 + (j * 3) % 40)
            # skip weekends → shift to Monday
            while dt.weekday() >= 5:
                dt += timedelta(days=1)
            items.append({
                "date": dt.date().isoformat(),
                "datetime": dt,
                "person": r["person"].replace("Councillor ", ""),
                "category": r["category"],
                "amount": amt,
                "memo": f"{r['category']}-{r['person'].replace('Councillor ','')[:12]}",
            })
    items.sort(key=lambda x: x["datetime"])
    return items


def write_detail_xlsx(items, path: Path):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "明细"
    ws.append(["日期", "经办人", "类别", "金额", "摘要"])
    for it in items:
        ws.append([it["date"], it["person"], it["category"], it["amount"], it["memo"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_category_map(path: Path):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "对照"
    ws.append(["类别", "科目代码", "是否需发票"])
    for zh, code, inv in [
        ("差旅补贴", "TRAVEL", "否"),
        ("小额现金", "PETTY", "否"),
        ("凭票报销", "VOUCHED", "是"),
        ("培训杂费", "TRAIN", "是"),
        ("专项津贴", "SPC", "否"),
    ]:
        ws.append([zh, code, inv])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def week_bounds(d: datetime.date):
    mon = d - timedelta(days=d.weekday())
    fri = mon + timedelta(days=4)
    return mon, fri


def build_hand_weekly(items, out_dir: Path, fridays):
    """Create hand-made weekly summaries; inject one undercount error on the middle Friday."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_day = defaultdict(list)
    for it in items:
        by_day[it["date"]].append(it)
    reports = []
    for idx, fri in enumerate(fridays):
        mon, fri_d = week_bounds(fri)
        rows = [it for it in items if mon <= datetime.fromisoformat(it["date"]).date() <= fri_d]
        by_cat = defaultdict(lambda: [0.0, 0])
        for it in rows:
            by_cat[it["category"]][0] += it["amount"]
            by_cat[it["category"]][1] += 1
        total = round(sum(v[0] for v in by_cat.values()), 2)
        n = sum(v[1] for v in by_cat.values())
        # intentional miss: drop ~one small category line equivalent (~200-ish) on week 3
        error_note = None
        if idx == 2 and by_cat:
            # undercount by the smallest category amount (or 200 if large)
            cat = min(by_cat.items(), key=lambda kv: kv[1][0])
            miss = round(min(cat[1][0], max(80.0, cat[1][0] * 0.35)), 2)
            if miss > 0 and cat[1][0] > miss:
                by_cat[cat[0]][0] = round(by_cat[cat[0]][0] - miss, 2)
                total = round(total - miss, 2)
                error_note = {"label": "本周支出合计", "missed": miss, "category": cat[0]}
        name = f"周汇总_{fri_d.strftime('%m%d')}.xlsx"
        path = out_dir / name
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "周报"
        ws["A1"] = "行政费用周汇总"
        ws["A2"] = "统计周期"; ws["B2"] = f"{mon.isoformat()}~{fri_d.isoformat()}"
        ws["A4"] = "本周支出合计"; ws["B4"] = total
        ws["A5"] = "本周笔数"; ws["B5"] = n
        ws["A6"] = "类别数"; ws["B6"] = len(by_cat)
        ws["A8"] = "类别"; ws["B8"] = "金额"; ws["C8"] = "笔数"
        r = 9
        for cat in sorted(by_cat):
            amt, cnt = by_cat[cat]
            ws.cell(r, 1, cat); ws.cell(r, 2, round(amt, 2)); ws.cell(r, 3, cnt); r += 1
        wb.save(path)
        reports.append({"path": path, "fri": fri_d, "mon": mon, "rows": rows, "total": total, "error": error_note, "by_cat": dict(by_cat)})
    return reports


def write_bank_csv(path: Path, fridays):
    """Derived bank CSV: recurring charges using real Petty Cash amounts (80) + price bump + duplicate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    # monthly "小额备用金自动划转" at 80 for Jul–Sep, then 95 in Oct (price_change)
    for mo, day, amt in [(7, 5, 80.0), (8, 5, 80.0), (9, 5, 80.0), (10, 5, 95.0)]:
        rows.append({
            "交易时间": f"2024-{mo:02d}-{day:02d} 10:12:00",
            "交易对方": "行政备用金账户",
            "商品说明": "小额备用金自动划转 续费",
            "金额": f"{amt:.2f}",
            "订单号": f"PC2024{mo:02d}{day:02d}001",
        })
    # duplicate charge on Oct 5 (same day, second order)
    rows.append({
        "交易时间": "2024-10-05 10:12:41",
        "交易对方": "行政备用金账户",
        "商品说明": "小额备用金自动划转 续费",
        "金额": "95.00",
        "订单号": "PC20241005002",
    })
    # noise: cafeteria (high frequency — should NOT become bill findings)
    for i in range(20):
        d = datetime(2024, 9, 2) + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        rows.append({
            "交易时间": d.strftime("%Y-%m-%d") + " 12:05:00",
            "交易对方": "机关食堂",
            "商品说明": "午餐",
            "金额": f"{18 + (i % 5):.2f}",
            "订单号": f"FOOD{d.strftime('%m%d')}{i:02d}",
        })
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["交易时间", "交易对方", "商品说明", "金额", "订单号"])
        w.writeheader(); w.writerows(rows)


def write_notes(path: Path, due_day: datetime.date, noted_on: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"# 工作备忘\n\n"
        f"- {noted_on.strftime('%m-%d')}：整理了本周费用明细。\n"
        f"- 别忘了：请行政助理在 {due_day.month}月{due_day.day}日前交齐下月预算表（含差旅、凭票报销两列）。\n"
        f"- 日常：每周五下午做费用周汇总。\n"
    )
    path.write_text(text, encoding="utf-8")


def emit(evs, **kw):
    e = dict(kw)
    if "ts" not in e:
        e["ts"] = e.pop("dt").isoformat(timespec="seconds")
    evs.append(e)


def reconstruct_events(items, reports, detail_rel, cat_rel, notes_rel, bank_rel, now: datetime):
    """Reconstruct multi-week desktop activity matching the real files."""
    evs = []
    home = "文档"
    # daily light browsing / opens of detail sheet across weeks
    days = sorted({it["date"] for it in items if "2024-09" <= it["date"] <= "2024-10-25"})
    for d in days[::2]:
        dt = datetime.fromisoformat(d + "T09:20:00")
        emit(evs, type="focus", dt=dt, app="libreoffice-calc", title=f"费用明细.xlsx — LibreOffice Calc", url=None)
        emit(evs, type="file_open", dt=dt + timedelta(seconds=2), app="libreoffice-calc", path=detail_rel)
        emit(evs, type="focus", dt=dt + timedelta(minutes=12), app="google-chrome", title="机关 OA — 首页", url="https://oa.example.gov/home")

    # Friday assembly sessions for each hand report
    for ri, rep in enumerate(reports):
        fri = rep["fri"]
        t0 = datetime(fri.year, fri.month, fri.day, 14, 5, 0)
        # open inputs
        emit(evs, type="focus", dt=t0, app="libreoffice-calc", title="费用明细.xlsx — LibreOffice Calc")
        emit(evs, type="file_open", dt=t0 + timedelta(seconds=1), app="libreoffice-calc", path=detail_rel)
        emit(evs, type="focus", dt=t0 + timedelta(minutes=1), app="libreoffice-calc", title="类别对照.xlsx — LibreOffice Calc")
        emit(evs, type="file_open", dt=t0 + timedelta(seconds=65), app="libreoffice-calc", path=cat_rel)
        # thrash + paste between sheets into new weekly report
        out_name = rep["path"].name
        out_rel = f"文档/费用/周汇总/{out_name}"
        # Work in untitled buffer first (pastes target the future filename in window title),
        # then first_open+save within 60s so detector treats it as a newly created file.
        n_paste = 18 + ri * 2
        for k in range(n_paste):
            ct = t0 + timedelta(minutes=3 + k * 0.35)
            emit(evs, type="focus", dt=ct, app="libreoffice-calc", title="费用明细.xlsx — LibreOffice Calc")
            emit(evs, type="clipboard", dt=ct + timedelta(seconds=2), src_app="libreoffice-calc",
                 src_title="费用明细.xlsx — LibreOffice Calc", dst_app="libreoffice-calc",
                 dst_title=f"{out_name} — LibreOffice Calc", text=f"{12.5 + k}")
            emit(evs, type="focus", dt=ct + timedelta(seconds=4), app="libreoffice-calc", title=f"{out_name} — LibreOffice Calc")
        for k in range(6):
            ct = t0 + timedelta(minutes=4 + k * 1.2)
            emit(evs, type="focus", dt=ct, app="libreoffice-calc", title="类别对照.xlsx — LibreOffice Calc")
            emit(evs, type="focus", dt=ct + timedelta(seconds=8), app="libreoffice-calc", title=f"{out_name} — LibreOffice Calc")
            emit(evs, type="clipboard", dt=ct + timedelta(seconds=10), src_app="libreoffice-calc",
                 src_title="类别对照.xlsx — LibreOffice Calc", dst_app="libreoffice-calc",
                 dst_title=f"{out_name} — LibreOffice Calc", text="TRAVEL")
        emit(evs, type="focus", dt=t0 + timedelta(minutes=22), app="gnome-calculator", title="计算器")
        emit(evs, type="focus", dt=t0 + timedelta(minutes=23), app="libreoffice-calc", title=f"{out_name} — LibreOffice Calc")
        # first_open then save within 60s → counts as new file for periodic_assembly
        save_t = t0 + timedelta(minutes=28)
        emit(evs, type="focus", dt=save_t - timedelta(seconds=20), app="libreoffice-calc", title=f"{out_name} — LibreOffice Calc")
        emit(evs, type="file_open", dt=save_t - timedelta(seconds=18), app="libreoffice-calc", path=out_rel)
        emit(evs, type="file_save", dt=save_t, app="libreoffice-calc", path=out_rel)
        # leave window
        emit(evs, type="focus", dt=save_t + timedelta(minutes=1), app="google-chrome", title="邮箱 — Inbox", url="https://mail.example.gov")

    # notes save with deadline
    note_t = datetime(2024, 10, 18, 16, 40, 0)
    emit(evs, type="focus", dt=note_t, app="gedit", title="工作备忘.md")
    emit(evs, type="file_open", dt=note_t + timedelta(seconds=1), app="gedit", path=notes_rel)
    emit(evs, type="file_save", dt=note_t + timedelta(minutes=4), app="gedit", path=notes_rel)

    # bank CSV open (so bills are "seen")
    for mo in (9, 10):
        bt = datetime(2024, mo, 6, 9, 0, 0)
        emit(evs, type="focus", dt=bt, app="libreoffice-calc", title="银行流水_行政备用金.csv — LibreOffice Calc")
        emit(evs, type="file_open", dt=bt + timedelta(seconds=2), app="libreoffice-calc", path=bank_rel)

    # cross-app paste: detail → browser reimbursement form (solvable with DOM blocks if we add docs;
    # here we also paste category lookups — keeps friction detector fed with files)
    for day in (datetime(2024, 10, 8), datetime(2024, 10, 15), datetime(2024, 10, 22)):
        t0 = datetime(day.year, day.month, day.day, 11, 0, 0)
        for k in range(12):
            ct = t0 + timedelta(minutes=k * 1.5)
            emit(evs, type="focus", dt=ct, app="libreoffice-calc", title="费用明细.xlsx — LibreOffice Calc")
            emit(evs, type="clipboard", dt=ct + timedelta(seconds=3), src_app="libreoffice-calc",
                 src_title="费用明细.xlsx — LibreOffice Calc", dst_app="google-chrome",
                 dst_title="报销填报 — 机关OA", text=f"{100 + k}.00")
            emit(evs, type="focus", dt=ct + timedelta(seconds=5), app="google-chrome",
                 title="报销填报 — 机关OA", url="https://oa.example.gov/expense/new")
            emit(evs, type="form_edit", dt=ct + timedelta(seconds=6), via="paste",
                 field_label=["报销金额", "事由", "类别", "经办人"][k % 4], url="https://oa.example.gov/expense/new")

    evs.sort(key=lambda e: e["ts"])
    return evs


def main():
    assert RAW.exists(), f"missing {RAW}"
    if HOME.exists():
        shutil.rmtree(HOME)
    if CAP.exists():
        shutil.rmtree(CAP)
    HOME.mkdir(parents=True)
    CAP.mkdir(parents=True)

    dcc = load_dcc()
    items = expand_line_items(dcc)
    # focus window: Sep–Oct 2024 for multi-week volume but manageable
    items_win = [it for it in items if it["date"] >= "2024-09-01" and it["date"] <= "2024-10-25"]
    # keep enough volume: if too few, widen
    if len(items_win) < 200:
        items_win = [it for it in items if it["date"] >= "2024-07-01" and it["date"] <= "2024-10-25"]

    detail = HOME / "文档" / "费用" / "费用明细.xlsx"
    cat = HOME / "文档" / "费用" / "类别对照.xlsx"
    write_detail_xlsx(items_win, detail)
    write_category_map(cat)

    # Fridays in window that have data
    fridays = []
    d0 = datetime(2024, 9, 6).date()  # first Friday in Sep 2024
    while d0 <= datetime(2024, 10, 18).date():
        fridays.append(d0)
        d0 += timedelta(days=7)
    reports = build_hand_weekly(items_win, HOME / "文档" / "费用" / "周汇总", fridays)

    bank = HOME / "下载" / "银行流水_行政备用金.csv"
    write_bank_csv(bank, fridays)

    due = datetime(2024, 10, 25).date()
    noted = datetime(2024, 10, 18, 16, 40, 0)
    notes = HOME / "文档" / "笔记" / "工作备忘.md"
    write_notes(notes, due, noted)

    # relative paths as stored in events (relative to user_home)
    detail_rel = "文档/费用/费用明细.xlsx"
    cat_rel = "文档/费用/类别对照.xlsx"
    notes_rel = "文档/笔记/工作备忘.md"
    bank_rel = "下载/银行流水_行政备用金.csv"

    now = datetime(2024, 10, 25, 8, 50, 0)  # Friday morning after last hand report week
    evs = reconstruct_events(items_win, reports, detail_rel, cat_rel, notes_rel, bank_rel, now)

    with open(CAP / "events.jsonl", "w", encoding="utf-8") as f:
        for e in evs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    meta = {
        "now": now.isoformat(timespec="seconds"),
        "user_home": "real_data/home_hybrid/admin",
        "watched_dirs": ["文档", "下载"],
        "user_aliases": ["行政助理", "助理"],
        "source": {
            "dataset": "hybrid-dcc-expenses-2024",
            "license": "CC-BY-4.0 (Dublin City Council Councillor Allowance and Expenses 2024); activity reconstructed",
            "documents": "real_data/hybrid/raw/councillor-expenses-2024.csv → 费用明细.xlsx / 周汇总 / 银行流水(派生)",
            "activity": "reconstructed multi-week events mapped to real spreadsheet contents (not a live screen recording)",
            "url": "https://data.gov.ie/dataset/councillor-allowance-and-expenses-dcc",
        },
    }
    (CAP / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ground truth for our own eval (detectors must not read this)
    gt = {
        "n_dcc_source_rows": len(dcc),
        "n_line_items": len(items_win),
        "n_events": len(evs),
        "fridays": [f.isoformat() for f in fridays],
        "hand_reports": [{"file": r["path"].name, "error": r["error"]} for r in reports],
        "expected_kinds": ["periodic_assembly", "duplicate_charge", "price_change", "deadline", "copy_paste_friction"],
    }
    (ROOT / "hybrid" / "GROUND_TRUTH_hybrid.json").write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "home": str(HOME), "capture": str(CAP),
        "line_items": len(items_win), "events": len(evs),
        "reports": len(reports), "date_span": [items_win[0]["date"], items_win[-1]["date"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
