"""Convert RLKWiC (Zenodo, CC-BY-4.0) participant events → OpenLookout events.jsonl.
Source: https://zenodo.org/records/11059573  /  https://purl.org/RLKWiC
Clipboard has text but not src/dst apps — we infer from nearest window-focus events.
File contents are text extractions; we materialize them under home_*/文档 for deadline detectors.
"""
from __future__ import annotations
import hashlib, json, re, shutil
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "rlkwic/RLKWiC"
PARTICIPANT = "p1"

BROWSER = {"chrome", "msedge", "opera", "firefox", "default browser", "brave"}
DOC_EXT = re.compile(r"\.(py|pdf|docx?|xlsx?|csv|txt|md|ipynb|tex|pptx?|inp)$", re.I)

def ms_to_dt(ms):
    return datetime.fromtimestamp(int(ms) / 1000.0)

def app_norm(a):
    a = str(a or "unknown").strip()
    m = {
        "default browser": "google-chrome",
        "msedge": "msedge",
        "chrome": "google-chrome",
        "Code": "code",
        "pycharm64": "pycharm",
        "WINWORD": "winword",
        "Explorer": "explorer",
        "Telegram": "telegram",
        "Acrobat": "acrobat",
        "FoxitPDFReader": "foxit",
        "FOXITREADER": "foxit",
    }
    return m.get(a, re.sub(r"[^a-z0-9]+", "-", a.lower()).strip("-") or "unknown")

def is_browser(app):
    return app in ("google-chrome", "msedge", "opera", "firefox") or "browser" in app

def main():
    p = SRC / PARTICIPANT
    out = ROOT / f"capture_rlkwic_{PARTICIPANT}"
    home = ROOT / f"home_rlkwic_{PARTICIPANT}"
    doc_dir = home / "文档"
    dl_dir = home / "下载"
    if out.exists():
        shutil.rmtree(out)
    if home.exists():
        shutil.rmtree(home)
    out.mkdir(parents=True)
    doc_dir.mkdir(parents=True)
    dl_dir.mkdir(parents=True)

    ev = pd.read_csv(p / "events.csv")
    files = pd.read_csv(p / "files.csv")
    webs = pd.read_csv(p / "webs.csv")
    files_by_id = {int(r.native_resid): r for _, r in files.iterrows()}
    webs_by_id = {int(r.native_resid): r for _, r in webs.iterrows()}

    # Materialize file contents as watched .txt/.md (deadline detector)
    content_dir = p / "file contents"
    name_by_id = {}
    for _, r in files.iterrows():
        rid = int(r.native_resid)
        raw_name = str(r["name"] or f"file_{rid}")
        safe = re.sub(r"[^\w.\-\u4e00-\u9fa5]+", "_", raw_name)[:80] or f"file_{rid}"
        src = content_dir / f"{rid}.txt"
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8", errors="ignore")
        if text.strip() in ("", "@|@|@"):
            continue
        # Prefer .md for deadline scanning (detector only reads .md/.txt)
        dest_name = safe if safe.endswith((".txt", ".md")) else (Path(safe).stem + ".md")
        dest = doc_dir / dest_name
        dest.write_text(text, encoding="utf-8")
        name_by_id[rid] = dest_name
        # synthetic file_open + file_save at created time so deadline detector sees them
        created = ms_to_dt(int(r.created)) if pd.notna(r.created) else None
        if created:
            rel = f"文档/{dest_name}"
            # paths relative to LOOKOUT_HOME parent convention used by sim: relative paths in events
            # Our detectors use path as stored; watched_files uses meta user_home.
            # abspath uses SIM which is LOOKOUT_HOME's parent — keep relative like sim: home-relative via meta.
            # Sim paths are like "xiaoyu/文档/...". We'll use "文档/..." and set user_home to home_rlkwic_p1.
            pass

    # Build chronological raw rows
    rows = []
    for _, r in ev.iterrows():
        ts = ms_to_dt(int(r.timestamp_received))
        reporter = str(r.reporter or "")
        cause = str(r.cause or "")
        title = None if pd.isna(r.title) else str(r.title)
        address = None if pd.isna(r.address) else str(r.address)
        app = app_norm(r.active_app)
        if title == "$@|@|@$":
            title = "[redacted]"
        if address == "$@|@|@$":
            address = None
        rows.append({"ts": ts, "reporter": reporter, "cause": cause, "title": title, "address": address, "app": app, "raw": r})

    rows.sort(key=lambda x: x["ts"])

    # Precompute focus timeline for clipboard src/dst inference
    focus_idx = [i for i, x in enumerate(rows) if x["reporter"] in ("window tracker", "cSpaces browser companion") and x["title"]]

    def nearest_focus(i, direction):
        if direction < 0:
            for j in range(i - 1, -1, -1):
                if rows[j]["reporter"] in ("window tracker", "cSpaces browser companion") and rows[j]["title"]:
                    return rows[j]
        else:
            for j in range(i + 1, len(rows)):
                if rows[j]["reporter"] in ("window tracker", "cSpaces browser companion") and rows[j]["title"]:
                    return rows[j]
        return None

    out_evs = []
    # Emit synthetic file events from materialized docs (once each, at created)
    for _, r in files.iterrows():
        rid = int(r.native_resid)
        if rid not in name_by_id:
            continue
        created = ms_to_dt(int(r.created)) if pd.notna(r.created) else rows[0]["ts"]
        rel = f"home_rlkwic_p1/文档/{name_by_id[rid]}"
        out_evs.append({"ts": created.isoformat(), "type": "file_open", "path": rel, "app": "unknown"})
        out_evs.append({"ts": created.isoformat(), "type": "file_save", "path": rel, "app": "unknown"})

    # Also: when window title contains a known filename, emit file_open
    known_names = {str(r["name"]): r for _, r in files.iterrows() if pd.notna(r["name"])}

    last_focus_ts = {}
    pending_focus = None  # to compute dur_s when leaving

    def flush_focus(end_ts):
        nonlocal pending_focus
        if not pending_focus:
            return
        dur = max(1, int((end_ts - pending_focus["ts"]).total_seconds()))
        e = dict(pending_focus)
        e["dur_s"] = min(dur, 4 * 3600)
        e["ts"] = e["ts"].isoformat() if hasattr(e["ts"], "isoformat") else e["ts"]
        out_evs.append(e)
        pending_focus = None

    for i, x in enumerate(rows):
        rep, cause = x["reporter"], x["cause"]
        if rep == "clipboard tracker" and x["title"]:
            src = nearest_focus(i, -1)
            dst = nearest_focus(i, +1)
            text = x["title"]
            # truncate huge pastes for events (keep hash)
            h = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
            clip = {
                "ts": x["ts"].isoformat(),
                "type": "clipboard",
                "src_app": (src or {}).get("app") or "unknown",
                "src_title": (src or {}).get("title") or "",
                "dst_app": (dst or {}).get("app") or "unknown",
                "dst_title": (dst or {}).get("title") or "",
                "len": len(text),
                "hash": h,
                "text": text[:200],
            }
            out_evs.append(clip)
            continue

        if rep == "cSpaces browser companion":
            flush_focus(x["ts"])
            url = x["address"]
            title = x["title"] or (url or "browser")
            # If search page, ensure q= is present for repeated_lookup
            if url and "search?q=" not in url and title and " - Search" in title:
                q = title.replace(" - Search", "").strip()
                url = "https://www.bing.com/search?q=" + q.replace(" ", "+")
            pending_focus = {
                "ts": x["ts"],
                "type": "focus",
                "app": "google-chrome" if x["app"] in ("google-chrome", "default-browser", "unknown") else x["app"],
                "title": title,
            }
            if url:
                pending_focus["url"] = url
            # file_open heuristic from title
            for name in known_names:
                if name and name in (title or ""):
                    rid = int(known_names[name].native_resid)
                    if rid in name_by_id:
                        out_evs.append({"ts": x["ts"].isoformat(), "type": "file_open", "path": f"home_rlkwic_{PARTICIPANT}/文档/{name_by_id[rid]}", "app": pending_focus["app"]})
            continue

        if rep == "window tracker" and cause == "active window changed":
            flush_focus(x["ts"])
            title = x["title"] or x["app"]
            pending_focus = {"ts": x["ts"], "type": "focus", "app": x["app"], "title": title}
            # Document open heuristic
            m = DOC_EXT.search(title or "")
            if m:
                # extract filename-ish
                fname = title.split(" - ")[0].strip()
                # map to materialized if possible
                path = None
                for rid, nm in name_by_id.items():
                    if Path(nm).stem[:20] in fname or fname[:20] in nm:
                        path = f"文档/{nm}"
                        break
                if path is None and fname:
                    # virtual path under 下载 for pattern detectors
                    path = f"home_rlkwic_p1/下载/{fname}"
                if path:
                    out_evs.append({"ts": x["ts"].isoformat(), "type": "file_open", "path": path, "app": x["app"]})
            continue

        # ignore sidebar noise for now

    flush_focus(rows[-1]["ts"] if rows else datetime.now())

    out_evs.sort(key=lambda e: e["ts"])
    with open(out / "events.jsonl", "w", encoding="utf-8") as f:
        for e in out_evs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    now = max(e["ts"] for e in out_evs)
    meta = {
        "now": now[:19],
        "user_home": f"real_data/home_rlkwic_{PARTICIPANT}",
        "watched_dirs": ["文档", "下载"],
        "user_aliases": ["Mahta", "participant1", "p1"],
        "source": {
            "dataset": "RLKWiC",
            "license": "CC-BY-4.0",
            "url": "https://zenodo.org/records/11059573",
            "participant": PARTICIPANT,
            "gaps": [
                "clipboard src/dst inferred from neighboring focus",
                "no form_edit",
                "file contents are text extracts (some redacted as @|@|@)",
                "no native file_save timestamps — synthesized from files.csv created",
            ],
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RLKWiC {PARTICIPANT} → {out}/events.jsonl n={len(out_evs)} docs={len(name_by_id)} span={out_evs[0]['ts']}..{out_evs[-1]['ts']}")
    from collections import Counter
    print("types", Counter(e["type"] for e in out_evs))

if __name__ == "__main__":
    main()
