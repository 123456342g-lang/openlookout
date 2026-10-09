"""Convert project-pivot/labelled-awt-data → OpenLookout events.jsonl.
License: GPL-3.0 (repo LICENSE). Source: https://github.com/project-pivot/labelled-awt-data
Gaps vs native recorder: no clipboard, no file_open/save paths, no browser URLs, no form_edit.
"""
from __future__ import annotations
import json, re
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "awt/data/awt_data_1_pseudonymized.csv"
OUT = ROOT / "capture_awt"

APP_MAP = {
    "Google Chrome": "google-chrome",
    "Microsoft Edge": "msedge",
    "Microsoft Outlook": "outlook",
    "Microsoft Word": "winword",
    "Microsoft Excel": "excel",
    "Microsoft PowerPoint": "powerpnt",
    "Microsoft Teams": "teams",
    "Windows Explorer": "explorer",
    "Adobe Acrobat": "acrobat",
    "Notepad": "notepad",
    "Microsoft Power BI Desktop": "powerbi",
}

def parse_dt(s):
    s = str(s).strip()
    for fmt in ("%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(s)

def main():
    df = pd.read_csv(SRC, sep=";", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    evs = []
    for _, r in df.iterrows():
        try:
            b, e = parse_dt(r["Begin"]), parse_dt(r["End"])
        except ValueError:
            continue
        dur = max(0, int((e - b).total_seconds()))
        app = APP_MAP.get(str(r["App"]), re.sub(r"[^a-z0-9]+", "-", str(r["App"]).lower()).strip("-") or "unknown")
        title = str(r["Title"] or "")
        if title in ("NO_TITLE", "nan"):
            title = str(r["App"])
        # Heuristic: Chrome titles that look like search pages
        url = None
        if app == "google-chrome" and " - Google Search" in title:
            q = title.split(" - Google Search")[0].strip()
            url = "https://www.google.com/search?q=" + q.replace(" ", "+")
        elif app == "google-chrome" and title.endswith(" - Google Chrome"):
            # leave url None; still useful as focus
            pass
        ev = {"ts": b.isoformat(), "type": "focus", "app": app, "title": title, "dur_s": dur or 1}
        if url:
            ev["url"] = url
        # Keep labelled activity for analysis (not used by detectors)
        ev["_awt_activity"] = str(r.get("Activity") or "")
        ev["_awt_case"] = str(r.get("Case") or "")
        evs.append(ev)
    evs.sort(key=lambda e: e["ts"])
    with open(OUT / "events.jsonl", "w", encoding="utf-8") as f:
        for e in evs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    now = max(e["ts"] for e in evs)
    meta = {
        "now": now[:19],
        "user_home": "real_data/home_awt",
        "watched_dirs": ["文档", "下载"],
        "user_aliases": ["Iris", "Beerepoot", "i.m.beerepoot"],
        "source": {
            "dataset": "project-pivot/labelled-awt-data",
            "license": "GPL-3.0",
            "url": "https://github.com/project-pivot/labelled-awt-data",
            "file": "awt_data_1_pseudonymized.csv",
            "gaps": ["no clipboard", "no file paths", "no form_edit", "URLs only for Google Search titles"],
        },
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "home_awt" / "文档").mkdir(parents=True, exist_ok=True)
    (ROOT / "home_awt" / "下载").mkdir(parents=True, exist_ok=True)
    print(f"AWT → {OUT}/events.jsonl  n={len(evs)}  span={evs[0]['ts']} .. {evs[-1]['ts']}")

if __name__ == "__main__":
    main()
