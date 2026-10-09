"""OpenLookout V1 主入口。

唯一核心：从可量化行为痕迹（可叠加已验证外部趋势）挖出用户说不出的需求，
并交付已验证成品。行为定位卡点；趋势打开「现在能做的新事」——不是新闻摘要。

用法：
  python3 -m lookout.v1 --capture <dir> --out <dir> [--no-llm] [--max-cards 3]
  python3 -m lookout.v1 --capture <dir> --out <dir> --ablation   # 少源 vs 全源消融
"""
from __future__ import annotations

import argparse, json, shutil, time
from collections import Counter
from datetime import datetime
from pathlib import Path

import lookout.common as common
from . import history as H
from . import surprise as S
from . import inbox
from . import trends as T
from . import feedback as FB
from . import nexus as NX
from . import scale_sources as SS


SKIP_KINDS = {
    "window_thrash", "copy_paste_friction",
    "recurring_doc_focus",
}
QUARANTINED_MODULES = ("lookout.world", "lookout.opportunity_engine")


def _assert_quarantine():
    import sys
    for m in QUARANTINED_MODULES:
        if m in sys.modules:
            raise RuntimeError(f"V1 禁止加载已隔离模块: {m}")


def build_tree(cap: Path):
    tree = cap / "_tree"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir()
    mp = cap / "content_manifest.json"
    n = 0
    if mp.exists():
        for x in json.loads(mp.read_text(encoding="utf-8")):
            dst = tree / x["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            src = (cap / x["stored"]).resolve()
            if src.exists() and not dst.exists():
                try:
                    dst.symlink_to(src)
                except OSError as error:
                    if getattr(error, "winerror", None) != 1314:
                        raise
                    shutil.copy2(src, dst)
                n += 1
    return tree, n


def describe(f, deid=None):
    if f["kind"] in NX.EXTRA_KINDS:
        return NX.describe_extra(f)
    if f["kind"] in H.KIND_CN:
        return H.describe(f)
    from . import run as R
    return R.describe(f, deid) if deid else str(f.get("facts"))


def solve_one(f, env, model, use_llm):
    if f["kind"] in NX.EXTRA_KINDS:
        return NX.solve_extra(f, env)
    if f["kind"] in H.KIND_CN:
        return H.solve(f, env)
    if use_llm:
        from .solvers import SOLVERS
        return SOLVERS[f["kind"]](f, env, model)
    from .solvers import solve_observation
    return solve_observation(f, env, model)


def render_v1_cards(summary, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    findings = {f["id"]: f for f in summary["findings"]}
    cards_out = []
    for cid in summary["gate"]["selected_ids"]:
        f = findings[cid]
        r = summary["results"][cid]
        c = summary["cards"][cid]
        audit = next(a for a in summary["gate"]["audits"] if a["id"] == cid)
        if f["kind"] in NX.EXTRA_KINDS:
            ev = NX.evidence_extra(f)
        elif f["kind"] in H.KIND_CN:
            ev = H.evidence(f)
        else:
            ev = inbox.evidence(f, r)
        arts = []
        for a in r.get("artifacts") or []:
            p = Path(a)
            dest = out_dir / "artifacts" / cid / p.name
            # keep relative structure for trend kits
            try:
                rel = p.relative_to(Path(summary.get("run_dir") or p.parent))
                dest = out_dir / "artifacts" / cid / rel
            except Exception:
                dest = out_dir / "artifacts" / cid / p.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.is_file():
                shutil.copy2(p, dest)
                arts.append({"path": str(dest.relative_to(out_dir)), "name": p.name})
        trends = r.get("trends") or []
        card = {
            "id": cid,
            "kind": f["kind"],
            "kind_cn": (
                {"tool_stack_churn": "AI 代理切换税", "openlookout_build": "正在做 OpenLookout"}.get(f["kind"])
                or H.KIND_CN.get(f["kind"])
                or inbox.KIND_CN.get(f["kind"], f["kind"])
            ),
            "title": inbox.fill(c.get("title"), r.get("slots") or {}),
            "noticed": inbox.fill(c.get("noticed"), r.get("slots") or {}),
            "prepared": inbox.fill(c.get("prepared"), r.get("slots") or {}),
            "verified": inbox.fill(c.get("verified"), r.get("slots") or {}),
            "question": inbox.fill(c.get("question"), r.get("slots") or {}),
            "options": c.get("options") or [],
            "evidence": ev,
            "metric": audit["metric"],
            "surprise": audit["surprise"],
            "ranking": audit.get("ranking", audit["surprise"]),
            "signals": audit["signals"],
            "trends": trends,
            "status": r["status"],
            "artifacts": arts,
            "verify": r.get("verify_deid") or {},
            "facts": f.get("facts") or {},
            "feedback": {"mult": audit.get("feedback_mult"), "hits": audit.get("feedback_hits")},
        }
        cards_out.append(card)

    (out_dir / "v1_cards.json").write_text(
        json.dumps({"generated_at": summary["generated_at"], "gate": {
            "min_surprise": summary["gate"]["min_surprise"],
            "max_cards": summary["gate"]["max_cards"],
            "selected_ids": summary["gate"]["selected_ids"],
            "rejected_ids": summary["gate"]["rejected_ids"],
            "overflow_ids": summary["gate"]["overflow_ids"],
        }, "cards": cards_out, "audits": summary["gate"]["audits"]},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")

    rows = []
    for i, c in enumerate(cards_out, 1):
        m = c["metric"] or {}
        metric_html = (f"<div class='metric'><b>主指标</b>：{m.get('label','')} = "
                       f"<span class='num'>{m.get('value','')}</span> {m.get('unit','')}</div>")
        ev_html = "<ul class='ev'>" + "".join(f"<li>{_esc(x)}</li>" for x in (c["evidence"] or [])[:8]) + "</ul>"
        art_html = "<ul class='art'>" + "".join(
            f"<li><code>{_esc(a['path'])}</code></li>" for a in c["artifacts"][:12]) + "</ul>"
        tr = c.get("trends") or []
        if tr:
            th = "<ul class='tr'>" + "".join(
                f"<li><b>{_esc(t.get('date'))}</b> · {_esc(t.get('fact'))}<br>"
                f"<a href='{_esc(t.get('url'))}'>{_esc(t.get('url'))}</a><br>"
                f"<i>新打开：{_esc(t.get('opens'))}</i></li>" for t in tr) + "</ul>"
        else:
            th = "<p class='muted'>（本卡无外部趋势交叉——仅行为）</p>"
        sig = "、".join(s["name"] for s in c["signals"]) or "—"
        rows.append(
            f"<div class='card'><div class='meta'>V1 · 排序 {c.get('ranking', c['surprise']):.2f} "
            f"(惊喜 {c['surprise']:.2f}) · {_esc(c['kind_cn'])} · {c['status']}</div>"
            f"<h2>{i}. {_esc(c['title'])}</h2>"
            f"{metric_html}"
            f"<p><b>我注意到</b>：{_esc(c['noticed'])}</p>"
            f"<p><b>潜在信号</b>：{_esc(sig)}</p>"
            f"<div class='sec'><b>行为 × 趋势</b>{th}</div>"
            f"<p><b>已准备</b>：{_esc(c['prepared'])}</p>"
            f"<p><b>已验证</b>：{_esc(c['verified'])}</p>"
            f"<div class='sec'><b>行为证据</b>{ev_html}</div>"
            f"<div class='sec'><b>成品</b>{art_html}</div>"
            f"<p class='q'>{_esc(c['question'])}</p>"
            f"</div>"
        )
    empty = not rows
    body = ("<div class='empty'><h2>今天没有通过惊喜门控的卡片</h2>"
            "<p>V1 宁可交白卷，也不出提醒、杂务或空想。</p></div>"
            if empty else "".join(rows))
    html = f"""<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<title>OpenLookout V1 · 已办清单</title>
<style>
body{{font:16px/1.55 system-ui,sans-serif;max-width:820px;margin:32px auto;padding:0 20px;color:#1a1a1a;background:#f6f5f2}}
h1{{font-size:1.4rem;margin:0 0 4px}} .sub{{color:#666;margin-bottom:24px}}
.card{{background:#fff;border:1px solid #e6e2da;border-radius:12px;padding:20px 22px;margin:0 0 18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.meta{{font-size:.8rem;color:#888;margin-bottom:8px}} h2{{font-size:1.15rem;margin:0 0 10px}}
.metric{{background:#f0f7f2;border-radius:8px;padding:8px 12px;margin:0 0 12px}} .num{{font-weight:700;color:#0a7a3e}}
.ev,.art,.tr{{margin:6px 0 0;padding-left:1.2em}} .sec{{margin:10px 0}} .q{{margin-top:14px;color:#333}}
.empty{{background:#fff;border:1px dashed #ccc;border-radius:12px;padding:28px;text-align:center;color:#666}}
code{{font-size:.85em;background:#f3f0ea;padding:1px 6px;border-radius:4px}}
.muted{{color:#888;font-size:.9rem}} a{{color:#0b57d0;word-break:break-all}}
</style></head><body>
<h1>OpenLookout V1 · 已办清单</h1>
<p class="sub">行为证据 × 已验证趋势 × 已验证成品 · 惊喜门控 · 反馈降权 · 每日最多 {summary['gate']['max_cards']} 张 · {summary['generated_at']}</p>
{body}
</body></html>"""
    (out_dir / "v1_inbox.html").write_text(html, encoding="utf-8")

    md = [f"# OpenLookout V1 · 已办清单\n",
          f"生成于 {summary['generated_at']} · 惊喜阈值 {summary['gate']['min_surprise']} · 上限 {summary['gate']['max_cards']} 张\n"]
    if not cards_out:
        md.append("\n**今天没有通过惊喜门控的卡片。**\n")
    for i, c in enumerate(cards_out, 1):
        m = c["metric"] or {}
        md += [f"\n## {i}. {c['title']}\n",
               f"- 排序分：{c.get('ranking', c['surprise']):.2f}（惊喜 {c['surprise']:.2f}）· {c['kind_cn']} · {c['status']}\n",
               f"- 主指标：{m.get('label')} = **{m.get('value')}** {m.get('unit')}\n",
               f"- 潜在信号：{', '.join(s['name'] for s in c['signals'])}\n"]
        if c.get("trends"):
            md.append("- 行为×趋势：\n")
            for t in c["trends"]:
                md.append(f"  - [{t.get('date')}] {t.get('fact')} — {t.get('url')}\n")
                md.append(f"    - 新打开：{t.get('opens')}\n")
        md += [f"- 我注意到：{c['noticed']}\n",
               f"- 已准备：{c['prepared']}\n",
               f"- 已验证：{c['verified']}\n",
               f"- 行为证据：\n"]
        for e in (c["evidence"] or [])[:8]:
            md.append(f"  - {e}\n")
        md.append("- 成品：\n")
        for a in c["artifacts"][:12]:
            md.append(f"  - `{a['path']}`\n")
    (out_dir / "v1_inbox.md").write_text("".join(md), encoding="utf-8")
    return cards_out


def _esc(s):
    import html as Htm
    return Htm.escape("" if s is None else str(s))


def screenshot(html_path: Path, png: Path):
    import subprocess
    for b in ("google-chrome", "chromium", "chromium-browser"):
        try:
            subprocess.run(
                [b, "--headless=new", "--no-sandbox", "--hide-scrollbars",
                 f"--screenshot={png}", "--window-size=1100,2600", str(html_path)],
                check=False, capture_output=True, timeout=60)
            if png.exists() and png.stat().st_size > 1000:
                return png
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _discover(evs, meta):
    from .detectors import run_all
    from .sheet_audit import detect_manual_summary
    allf = run_all(evs, meta)
    skipped = Counter(f["kind"] for f in allf if f["kind"] in SKIP_KINDS)
    fs = [f for f in allf if f["kind"] not in SKIP_KINDS]
    hfs = H.run_history(evs, meta) + detect_manual_summary(evs, meta)
    hfs += NX.detect_tool_stack_churn(evs, meta)
    hfs += NX.detect_openlookout_build(evs, meta)
    rhythm_titles = {f["local"]["title"] for f in hfs if f["kind"] == "site_rhythm"}
    fs = [f for f in fs if not (f["kind"] == "recurring_doc_focus" and any(
        f["local"]["title"] == common.norm_title(t) for t in rhythm_titles))]
    fs = sorted(fs + hfs, key=lambda f: -f["score"])
    for i, f in enumerate(fs, 1):
        f["id"] = f"V{i}"
    return fs, skipped


def run_pipeline(cap: Path, out_dir: Path, tag: str, no_llm: bool, max_cards: int,
                 model: str, do_screenshot: bool, families: list[str] | None = None,
                 enrich: bool = True) -> dict:
    """跑完整 V1；families 非空时只保留这些来源族（消融）。"""
    common.CAP = cap
    tree, n_content = build_tree(cap)
    common.SIM = tree
    run_dir = common.ROOT / "runs" / tag
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    evs, meta = common.load_events(), common.load_meta()
    n_raw = len(evs)
    evs, noise = H.filter_noise(evs)
    enrich_stats = {}
    if enrich:
        evs, enrich_stats = SS.enrich(evs, meta, extra_roots=[tree, common.ROOT])
    if families is not None:
        evs = SS.filter_by_families(evs, families)
    meta["user_home"] = str(tree)
    meta["watched_dirs"] = sorted(p.name for p in tree.iterdir() if p.is_dir()) if tree.exists() else []
    meta["user_aliases"] = meta.get("user_aliases") or []

    from .deid import Deid
    deid = Deid(meta)
    fs, skipped = _discover(evs, meta)

    env = type("Env", (), {})()
    env.evs, env.meta, env.deid, env.run_dir, env.tree = evs, meta, deid, run_dir, tree
    env.recurring, env.dups = [], []
    use_llm = not no_llm
    llm = None
    if use_llm:
        from .llm import LLM
        llm = LLM(run_dir, model)
        llm.deid = deid
        env.llm = llm

    catalog = T.load_catalog()
    results = {}
    for f in fs:
        t = time.time()
        try:
            res = solve_one(f, env, model, use_llm and f["kind"] not in H.KIND_CN and f["kind"] not in NX.EXTRA_KINDS)
            res = NX.enhance(f, res, env, catalog)
        except Exception as ex:
            res = {"status": "failed", "error": repr(ex)[:300], "artifacts": [], "slots": {}, "verify_deid": {}, "trends": []}
        res["solve_s"] = round(time.time() - t, 2)
        results[f["id"]] = res

    rules = FB.load_rules()
    gate = S.gate(fs, results, max_cards=max_cards,
                  feedback_fn=lambda f: FB.multiplier(f, rules))
    show = [f for f in fs if f["id"] in gate["selected_ids"]]
    show.sort(key=lambda f: -next(a.get("ranking", a["surprise"]) for a in gate["audits"] if a["id"] == f["id"]))

    cards = {}
    for f in show:
        if f["kind"] in NX.EXTRA_KINDS:
            cards[f["id"]] = NX.template_extra(f, results[f["id"]])
        elif f["kind"] in H.KIND_CN:
            cards[f["id"]] = H.template_card(f, results[f["id"]])
        else:
            cards[f["id"]] = {
                "title": inbox.KIND_CN.get(f["kind"], f["kind"]),
                "noticed": describe(f, deid),
                "prepared": f"已准备 {len(results[f['id']].get('artifacts') or [])} 个成品。",
                "verified": str(results[f["id"]].get("verify_deid") or {}),
                "question": "这份方案对你有用吗？",
                "options": ["有用", "不重要", "方向不对"],
            }
        # append trend hook into prepared text
        tr = results[f["id"]].get("trends") or []
        if tr and cards[f["id"]].get("prepared"):
            cards[f["id"]]["prepared"] = cards[f["id"]]["prepared"] + f" 对照趋势：{tr[0].get('id')}（{tr[0].get('date')}）。"

    inbox.KIND_CN.update(H.KIND_CN)
    inbox.KIND_CN.update({"tool_stack_churn": "AI 代理切换税", "openlookout_build": "正在做 OpenLookout"})
    summary = {
        "tag": tag,
        "mode": "v1",
        "model": model if llm else "不调用模型（规则+模板）",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "now": meta["now"],
        "run_dir": str(run_dir),
        "timing": {
            "total_s": round(time.time() - t0, 2),
            "events": len(evs), "events_raw": n_raw,
            "noise_dropped": noise, "skipped_kinds": dict(skipped),
            "content_files": n_content, "enrich": enrich_stats,
            "families": families,
        },
        "source": {"dataset": "本机历史回溯（backfill_win）+ derived", "license": "原始数据只在本机"},
        "findings": [{"id": f["id"], "kind": f["kind"], "score": f["score"],
                      "desc": describe(f, deid), "facts": f["facts"],
                      "local": json.loads(json.dumps(f["local"], ensure_ascii=False, default=str))}
                     for f in fs],
        "results": results,
        "cards": cards,
        "gate": gate,
        "quarantined": list(QUARANTINED_MODULES),
    }
    (run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out_dir / "gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    cards_out = render_v1_cards(summary, out_dir)
    (out_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    png = screenshot(out_dir / "v1_inbox.html", out_dir / "v1_inbox.png") if do_screenshot else None

    print(f"V1 done: out={out_dir} findings={len(fs)} passed={len(gate['selected_ids'])} "
          f"cards={len(cards_out)} total={summary['timing']['total_s']}s families={families}")
    for a_ in gate["audits"]:
        flag = "PASS" if a_["passed"] and a_["id"] in gate["selected_ids"] else (
            "OVERFLOW" if a_["id"] in gate["overflow_ids"] else "REJECT")
        why = (a_["reject_reasons"][0] if a_["reject_reasons"] else
               f"rank={a_.get('ranking')} surprise={a_['surprise']} trends={a_.get('n_trends')}")
        print(f"  {flag:8} {a_['id']:<4} {a_['kind']:<20} {why[:100]}")
    if png:
        print(f"screenshot: {png}")
    return summary


def run_ablation(cap: Path, out_root: Path, **kw) -> list[dict]:
    rows = []
    for name, families in SS.ABLATIONS.items():
        sub = out_root / f"ablation_{name}"
        summary = run_pipeline(cap, sub, tag=f"v1_ab_{name}", families=families,
                               enrich=(name == "all_plus"), **kw)
        gate = summary["gate"]
        passed = [a for a in gate["audits"] if a["id"] in gate["selected_ids"]]
        rows.append({
            "name": name,
            "families": families,
            "n_events": summary["timing"]["events"],
            "n_findings": len(summary["findings"]),
            "n_passed": len(passed),
            "n_with_trend": sum(1 for a in passed if a.get("n_trends")),
            "passed_kinds": [a["kind"] for a in passed],
            "surprise_sum": round(sum(a["surprise"] for a in passed), 3),
            "ranking_sum": round(sum(a.get("ranking", 0) for a in passed), 3),
        })
    (out_root / "ablation.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "ablation.md").write_text(SS.ablation_report(rows), encoding="utf-8")
    print(SS.ablation_report(rows))
    return rows


def main(argv=None):
    _assert_quarantine()
    FB.ensure_default_file()
    ap = argparse.ArgumentParser(description="OpenLookout V1：行为×趋势 → 潜在需求 + 已验证方案")
    ap.add_argument("--capture", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--model", default="mimo-v2.6-flash")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--max-cards", type=int, default=S.MAX_CARDS)
    ap.add_argument("--screenshot", action="store_true")
    ap.add_argument("--ablation", action="store_true", help="少源 vs 全源消融实验")
    ap.add_argument("--no-enrich", action="store_true", help="不派生 search/git/editor")
    a = ap.parse_args(argv)
    cap = Path(a.capture).resolve()
    out_dir = Path(a.out).resolve()
    kw = dict(no_llm=a.no_llm, max_cards=a.max_cards, model=a.model, do_screenshot=a.screenshot)
    if a.ablation:
        run_ablation(cap, out_dir, **kw)
        # also produce main inbox with all_plus
        run_pipeline(cap, out_dir, tag=a.tag, families=None, enrich=not a.no_enrich, **kw)
    else:
        run_pipeline(cap, out_dir, tag=a.tag, families=None, enrich=not a.no_enrich, **kw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
