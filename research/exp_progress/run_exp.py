"""Micro-experiment: synthetic activity traces (progress|stuck|error) → evidence pack →
FakeNovelClient (real cloud only if OPENLOOKOUT_NOVEL=1 + key). Metrics: needs_help P/R/F1 + confusion.

No anomaly-taxonomy detector: gold labels come with traces; judge sees only packed evidence.
"""
from __future__ import annotations
import json, os, sys
from collections import Counter
from pathlib import Path

def _resolve_root() -> Path:
    here = Path(__file__).resolve().parent
    cands = [
        here.parents[1] / "sync",                 # research/microexp → openlookout/sync
        here.parents[1],                          # sync/research/microexp → sync (=sprite root)
        here.parents[1] / "src" / "openlookout",
    ]
    for c in cands:
        if (c / "sprite" / "novel.py").is_file() and (c / "sprite" / "investigate.py").is_file():
            return c
    raise SystemExit("cannot find sprite.novel")

ROOT = _resolve_root()
sys.path.insert(0, str(ROOT))

from sprite.investigate import Candidate, Understanding
from sprite.novel import (
    FakeNovelClient, NovelUnderstander, build_evidence_pack, needs_novel, make_env_cloud_client, env_novel_enabled,
)

OUT = Path(__file__).resolve().parent
LABELS = ("progress", "stuck", "error")  # gold activity classes
# needs_help gold: progress=0, stuck=1, error=1
HELP = {"progress": 0, "stuck": 1, "error": 1}


def synth_traces():
    """Synthetic UI/activity traces — labels only for eval, not fed as taxonomy to the judge."""
    rows = []
    # progress: title changes / short dwell / advancing steps
    for i in range(8):
        rows.append(dict(
            id=f"p{i}", gold="progress",
            events=[
                {"type": "focus", "app": "Code", "title": f"main.py — step {i}", "dur_s": 12 + i},
                {"type": "focus", "app": "Code", "title": f"main.py — step {i+1}", "dur_s": 8},
                {"type": "file_save", "path": "main.py"},
            ],
            summary=f"title advanced step {i}→{i+1}; short dwell; file saved",
        ))
    # stuck: long dwell same title, flicker, no save
    for i in range(8):
        rows.append(dict(
            id=f"s{i}", gold="stuck",
            events=[
                {"type": "focus", "app": "WeirdCAD", "title": "参数面板 ???", "dur_s": 180 + 20 * i},
                {"type": "focus", "app": "WeirdCAD", "title": "参数面板 ???", "dur_s": 40},
                {"type": "focus", "app": "WeirdCAD", "title": "参数面板 ???", "dur_s": 35},
            ],
            summary=f"same title dwell {180+20*i}s+; flicker; no progress signal",
        ))
    # error: browser_error / dialog text in evidence
    for i in range(8):
        rows.append(dict(
            id=f"e{i}", gold="error",
            events=[
                {"type": "focus", "app": "chrome", "title": "172.16.170.169", "dur_s": 25},
                {"type": "browser_error", "url": f"http://172.16.170.169/x{i}", "error": "ERR_EMPTY_RESPONSE"},
            ],
            summary="browser_error ERR_EMPTY_RESPONSE on LAN URL; empty response",
        ))
    return rows


def judge_fn(system: str, user: str):
    """Fake cloud: read evidence pack text only — no gold label field.
    Heuristic stands in for LLM: act if long dwell / same-title / browser_error / ERR_."""
    pack = json.loads(user)
    blob = json.dumps(pack, ensure_ascii=False).lower()
    evidence = " ".join(pack.get("evidence") or []).lower()
    facts = pack.get("facts") or {}
    summary = str(facts.get("summary") or "").lower()
    text = blob + " " + evidence + " " + summary
    needs = any(k in text for k in (
        "browser_error", "err_empty", "err_", "dwell 1", "dwell 2", "same title",
        "flicker", "no progress", "参数面板", "empty response",
    ))
    # progress cues without error/stuck cues → no help
    if ("file saved" in text or "title advanced" in text or "short dwell" in text) and not needs:
        needs = False
    if needs:
        payload = dict(
            what="用户可能受阻（僵局或错误）", why="证据包含久停/闪烁或浏览失败",
            state="unknown", confidence=0.82, act=True,
            candidate_actions=[dict(kind="archive_note", args={}, reason="记下待跟进", risk="safe", reversible="full")],
        )
    else:
        payload = dict(
            what="用户在推进中", why="标题推进/短停留/有存盘",
            state="in_use", confidence=0.85, act=False,
            candidate_actions=[dict(kind="skip", args={}, reason="无需插手", risk="safe", reversible="full")],
        )
    return json.dumps(payload, ensure_ascii=False), 110, 60


def run():
    traces = synth_traces()
    use_real = env_novel_enabled() and make_env_cloud_client() is not None
    if use_real:
        client = make_env_cloud_client()
        client_name = "env_cloud"
    else:
        client = FakeNovelClient(fn=judge_fn)
        client_name = "FakeNovelClient"

    home = OUT / "_run_home"
    home.mkdir(exist_ok=True)
    clock = lambda: 1_800_000_000.0
    novel = NovelUnderstander(home, clock=clock, client=client, enabled=True, prefer_novel=True)

    y_true, y_pred = [], []
    rows_out = []
    for t in traces:
        gold = t["gold"]
        cand = Candidate("activity", f"act:{t['id']}", f"trace {t['id']}",
                         signals=dict(need=1.0 if HELP[gold] else 0.0, severity=0.4), ctx={})
        facts = dict(summary=t["summary"], n_events=len(t["events"]),
                     event_types=[e["type"] for e in t["events"]])
        evidence = [t["summary"]] + [
            f"{e.get('type')} {e.get('title', e.get('error', e.get('path', '')))}" for e in t["events"]
        ]
        # local prior intentionally weak (not taxonomy brain)
        prior = Understanding(cand.key, cand.kind, cand.title, state="unknown",
                              confidence=0.2, act=False, why="本地不定性")
        assert needs_novel(prior, prefer_novel=True) is True
        u = novel.understand(cand, facts, evidence, prior=prior, force=True)
        pred_help = 1 if (u is not None and u.act) else 0
        y_true.append(HELP[gold])
        y_pred.append(pred_help)
        rows_out.append(dict(id=t["id"], gold=gold, gold_help=HELP[gold], pred_help=pred_help,
                             what=(u.what if u else None), act=(u.act if u else None)))

    # metrics for needs_help (binary)
    tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    # confusion: rows=gold_help 0/1, cols=pred 0/1
    cm = [[tn, fp], [fn, tp]]

    # also gold-label × pred_help counts
    by_label = Counter()
    for r in rows_out:
        by_label[(r["gold"], r["pred_help"])] += 1

    result = dict(
        experiment="exp_progress",
        client=client_name,
        n=len(traces),
        labels=list(LABELS),
        needs_help=dict(precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
                        tp=tp, tn=tn, fp=fp, fn=fn),
        confusion_matrix=dict(order="[[tn,fp],[fn,tp]] rows=gold_help cols=pred_help", matrix=cm),
        by_gold_label={f"{g}|pred_help={p}": c for (g, p), c in sorted(by_label.items())},
        prefer_novel_default=True,
        network_discoverer_used=False,
    )
    (OUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "predictions.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    r = run()
    ok = r["needs_help"]["f1"] >= 0.85 and r["needs_help"]["fp"] == 0
    raise SystemExit(0 if ok else 1)
