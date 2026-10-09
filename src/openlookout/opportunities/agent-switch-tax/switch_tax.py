"""agent-switch-tax: measure the durable-knowledge cost of cold-starting another coding agent.

You keep installing / switching agents (OpenCode, Codex, CC Switch, …) as if the scarce
resource is model IQ. This tool shows the other cost: how many project facts a cold agent
cannot see from README alone, and how many tokens it takes to re-carry them.

Stdlib only. No network. Does not read capture_*/ raw events.

Usage:
  python3 switch_tax.py --project /path/to/repo --out /path/to/out
  python3 switch_tax.py --project /path/to/repo --profile profile.json --out /path/to/out
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# --- coding-agent / local-AI tool families (generic; profile strings are matched case-insensitively)
AGENT_RX = re.compile(
    r"opencode|codex|claude\s*code|cursor|cc\s*switch|windsurf|aider|continue\.dev|"
    r"copilot|tabbit|doubao|豆包|ollama|langflow|lm\s*studio|openai\s*cli",
    re.I,
)
CODING_RX = re.compile(
    r"opencode|codex|claude\s*code|cursor|cc\s*switch|windsurf|aider|continue|copilot|tabbit",
    re.I,
)

SKIP_DIR = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "runs", "capture",
    "capture_userbf", "demo_private", "sim_home", "real_data", ".mypy_cache",
}


def _read(p: Path, limit: int = 400_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _approx_tokens(text: str) -> int:
    """Rough token estimate: CJK chars ≈ 1 tok, latin words ≈ 1.3 chars/tok — keep it honest & simple."""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    rest = len(text) - cjk
    return int(cjk + rest / 3.5)


def extract_changelog_facts(text: str, source: str = "CHANGELOG.md") -> list[dict]:
    facts = []
    # Split on ## headers (round titles)
    parts = re.split(r"(?m)^(## .+)$", text)
    # parts: [preamble, h2, body, h2, body, ...]
    i = 1
    while i + 1 < len(parts):
        title = parts[i].strip().lstrip("# ").strip()
        body = parts[i + 1]
        i += 2
        # first 3 non-empty bullet-ish lines as decisions
        bullets = []
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("- ") or s.startswith("* "):
                bullets.append(re.sub(r"^[-*]\s+", "", s))
            if len(bullets) >= 4:
                break
        if not bullets:
            # take first non-empty paragraph sentence
            para = " ".join(x.strip() for x in body.splitlines() if x.strip() and not x.strip().startswith("#"))
            if para:
                bullets = [para[:180]]
        for b in bullets[:3]:
            if len(b) < 12:
                continue
            facts.append({
                "id": f"decision:{len(facts)+1}",
                "kind": "decision",
                "round": title[:80],
                "text": b[:240],
                "source": source,
                "keys": _keys(title + " " + b),
            })
    return facts


def extract_module_facts(root: Path) -> list[dict]:
    facts = []
    # Prefer lookout/ if present, else top-level packages
    candidates = []
    lookout = root / "lookout"
    if lookout.is_dir():
        candidates = sorted(lookout.glob("*.py"))
    else:
        for p in sorted(root.rglob("*.py")):
            if any(s in p.parts for s in SKIP_DIR):
                continue
            if p.name.startswith("test_"):
                continue
            candidates.append(p)
            if len(candidates) >= 40:
                break
    for p in candidates:
        if p.name == "__init__.py":
            continue
        text = _read(p, 8000)
        doc = ""
        m = re.match(r'\s*("""|\'\'\')(.*?)\1', text, re.S)
        if m:
            doc = re.sub(r"\s+", " ", m.group(2).strip())[:200]
        else:
            # first substantive comment / assignment-free line
            for line in text.splitlines()[:15]:
                s = line.strip()
                if s.startswith("#") and len(s) > 8:
                    doc = s.lstrip("# ").strip()[:200]
                    break
        rel = str(p.relative_to(root))
        summary = doc or f"Python module {rel} (no docstring)"
        facts.append({
            "id": f"module:{rel}",
            "kind": "architecture",
            "text": f"{rel}: {summary}",
            "source": rel,
            "keys": _keys(rel + " " + summary),
        })
    return facts


CONSTRAINT_PATTERNS = [
    (r"ground_truth", "Must not tune detectors against ground_truth/"),
    (r"gitignore|不进 git|\.gitignore", "Private capture/demo paths stay out of git"),
    (r"出站|outbound|脱敏|deid|audit", "Outbound content must pass de-identification / audit"),
    (r"bubblewrap|bwrap|沙箱|sandbox", "Solver actions run inside a sandbox; no send/pay/delete"),
    (r"verified|不打扰|reminder_only|去打扰", "Only verified (or artifact-bearing draft) cards surface"),
    (r"exclude_topics|排除主题", "Excluded topics are stripped before outbound / opportunity matching"),
    (r"标准库|stdlib|zero.?depend", "Prefer stdlib / zero-dependency tooling where claimed"),
    (r"本地优先|local-first|不联网", "Local-first: prefer offline / no-network paths"),
]


def extract_constraint_facts(root: Path) -> list[dict]:
    facts = []
    blobs = []
    for name in ("README.md", "CHANGELOG.md", ".gitignore"):
        p = root / name
        if p.exists():
            blobs.append((name, _read(p, 120_000)))
    # also lookout/deid.py / schema short headers
    for rel in ("lookout/deid.py", "lookout/sandbox.py", "lookout/opportunity_engine.py"):
        p = root / rel
        if p.exists():
            blobs.append((rel, _read(p, 6000)))
    seen = set()
    for source, text in blobs:
        for rx, label in CONSTRAINT_PATTERNS:
            if re.search(rx, text, re.I) and label not in seen:
                seen.add(label)
                facts.append({
                    "id": f"constraint:{len(facts)+1}",
                    "kind": "constraint",
                    "text": label,
                    "source": source,
                    "keys": _keys(label + " " + rx),
                })
    return facts


def extract_invariant_facts(root: Path) -> list[dict]:
    """Hard product invariants visible in code strings (privacy / action limits)."""
    facts = []
    probes = [
        ("lookout/opportunity_engine.py", r"audit_outbound|long-number|exclude_topics",
         "Opportunity engine audits outbound for URL/path/email/long-number and drops exclude_topics"),
        ("lookout/sandbox.py", r"bwrap|network|ro-bind",
         "Sandbox blocks network and keeps user files read-only"),
        ("lookout/blocks.py", r"send|submit|pay|delete",
         "Block library must not include send/submit/pay/delete actions"),
        ("lookout/history.py", r"filter_noise|appshell|automation",
         "Backfill noise filter drops appshell/automation browser sources"),
        ("lookout/profile.py", r"audit|tools_evidence|装过",
         "Profile distinguishes installed vs searched tools; outbound is abstract-only"),
    ]
    for rel, rx, label in probes:
        p = root / rel
        if p.exists() and re.search(rx, _read(p, 50_000), re.I):
            facts.append({
                "id": f"invariant:{len(facts)+1}",
                "kind": "invariant",
                "text": label,
                "source": rel,
                "keys": _keys(label),
            })
    return facts


def _keys(s: str) -> list[str]:
    # tokens useful for coverage matching: identifiers + CJK bigrams-ish words length>=2
    keys = set()
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", s):
        keys.add(w.lower() if w.isascii() else w)
    return sorted(keys)[:24]


def build_ledger(root: Path) -> dict:
    facts = []
    facts.extend(extract_module_facts(root))
    cl = root / "CHANGELOG.md"
    if cl.exists():
        facts.extend(extract_changelog_facts(_read(cl)))
    facts.extend(extract_constraint_facts(root))
    facts.extend(extract_invariant_facts(root))
    # stable ids already set; ensure uniqueness
    by_id = {}
    for f in facts:
        by_id[f["id"]] = f
    facts = list(by_id.values())
    kinds = Counter(f["kind"] for f in facts)
    return {
        "project": str(root.resolve()),
        "n_facts": len(facts),
        "kinds": dict(kinds),
        "facts": facts,
    }


def pack_texts(root: Path, ledger: dict) -> dict:
    readme = _read(root / "README.md") if (root / "README.md").exists() else ""
    changelog = _read(root / "CHANGELOG.md") if (root / "CHANGELOG.md").exists() else ""
    # last 2 round sections only
    last_rounds = ""
    parts = re.split(r"(?m)^(## .+)$", changelog)
    if len(parts) > 1:
        # take first two ## blocks (changelog is newest-first in this repo)
        chunks = []
        i = 1
        while i + 1 < len(parts) and len(chunks) < 2:
            chunks.append(parts[i] + "\n" + parts[i + 1][:3000])
            i += 2
        last_rounds = "\n".join(chunks)
    ledger_md = render_ledger_md(ledger)
    return {
        "readme": readme,
        "readme_plus_2rounds": readme + "\n\n" + last_rounds,
        "full_ledger": ledger_md,
    }


def render_ledger_md(ledger: dict) -> str:
    lines = [f"# Context ledger ({ledger['n_facts']} facts)", ""]
    for kind in ("constraint", "invariant", "architecture", "decision"):
        group = [f for f in ledger["facts"] if f["kind"] == kind]
        if not group:
            continue
        lines.append(f"## {kind} ({len(group)})")
        for f in group:
            extra = f" — {f['round']}" if f.get("round") else ""
            lines.append(f"- [{f['source']}{extra}] {f['text']}")
        lines.append("")
    return "\n".join(lines)


def coverage(pack_text: str, facts: list[dict]) -> dict:
    """A fact is covered if ≥2 of its keys appear in the pack (or 1 key if it only has 1)."""
    low = pack_text.lower()
    # also keep original for CJK
    covered, missed = [], []
    for f in facts:
        keys = f.get("keys") or _keys(f["text"])
        if not keys:
            missed.append(f["id"])
            continue
        hits = 0
        for k in keys:
            if k.isascii():
                if k.lower() in low:
                    hits += 1
            else:
                if k in pack_text:
                    hits += 1
        need = 1 if len(keys) == 1 else min(2, len(keys))
        # also accept near-full text snippet
        snippet = f["text"][:40]
        if snippet and snippet in pack_text:
            hits = need
        if hits >= need:
            covered.append(f["id"])
        else:
            missed.append(f["id"])
    n = len(facts) or 1
    return {
        "n": len(facts),
        "covered": len(covered),
        "missed": len(missed),
        "coverage": round(len(covered) / n, 4),
        "missed_ids": missed,
        "covered_ids": covered,
    }


def profile_agent_counts(profile: dict | None) -> dict:
    if not profile:
        return {"tools_listed": 0, "ai_stacks": 0, "coding_agents": 0, "names": []}
    tools = list(profile.get("tools") or [])
    # tools_evidence keys may add more
    te = profile.get("tools_evidence") or {}
    for k in te:
        if k not in tools:
            tools.append(k)
    names = []
    coding = []
    for t in tools:
        if AGENT_RX.search(str(t)):
            names.append(str(t))
            if CODING_RX.search(str(t)):
                coding.append(str(t))
    return {
        "tools_listed": len(tools),
        "ai_stacks": len(names),
        "coding_agents": len(coding),
        "names": names,
        "coding_names": coding,
    }


def measure(root: Path, profile: dict | None = None) -> dict:
    ledger = build_ledger(root)
    packs = pack_texts(root, ledger)
    cov = {name: coverage(text, ledger["facts"]) for name, text in packs.items()}
    # strip large id lists from summary view but keep in detail
    pack_stats = {}
    for name, text in packs.items():
        c = cov[name]
        pack_stats[name] = {
            "chars": len(text),
            "approx_tokens": _approx_tokens(text),
            "coverage": c["coverage"],
            "covered": c["covered"],
            "missed": c["missed"],
        }
    agents = profile_agent_counts(profile)
    # Tax = facts missed by README-only cold start
    readme_miss = cov["readme"]["missed_ids"]
    tax_n = cov["readme"]["missed"]
    ledger_tokens = pack_stats["full_ledger"]["approx_tokens"]
    # Each additional coding agent beyond the first theoretically re-pays the ledger once on cold start
    extra_agents = max(0, agents["coding_agents"] - 1)
    multi_switch_fact_tax = tax_n * max(1, agents["coding_agents"])  # total facts×agent exposures if all cold
    result = {
        "project": str(root.resolve()),
        "ledger_summary": {"n_facts": ledger["n_facts"], "kinds": ledger["kinds"]},
        "packs": pack_stats,
        "switch_tax": {
            "definition": "facts invisible to a cold agent that only receives README.md",
            "tax_facts_n": tax_n,
            "tax_fact_ratio": round(tax_n / (ledger["n_facts"] or 1), 4),
            "ledger_approx_tokens": ledger_tokens,
            "readme_approx_tokens": pack_stats["readme"]["approx_tokens"],
            "delta_tokens_to_carry_ledger": max(0, ledger_tokens - pack_stats["readme"]["approx_tokens"]),
            "coverage_readme": pack_stats["readme"]["coverage"],
            "coverage_readme_plus_2rounds": pack_stats["readme_plus_2rounds"]["coverage"],
            "coverage_full_ledger": pack_stats["full_ledger"]["coverage"],
        },
        "agents_from_profile": agents,
        "multi_agent_exposure": {
            "coding_agents": agents["coding_agents"],
            "extra_coding_agents_beyond_first": extra_agents,
            "if_each_coding_agent_cold_starts_once_fact_exposures": multi_switch_fact_tax,
            "note": "Install evidence ≠ daily switches; this is an upper-bound exposure model, not measured switch frequency.",
        },
        "missed_by_readme": [
            {"id": f["id"], "kind": f["kind"], "text": f["text"][:160]}
            for f in ledger["facts"] if f["id"] in set(readme_miss)
        ],
        "honest_limits": [
            "Coverage matching is keyword/heuristic, not an LLM judge of understanding.",
            "Profile tool lists show installed/searched stacks, not switch counts per day.",
            "CHANGELOG newest-first assumed when taking 'last 2 rounds'.",
            "Token estimate is approximate (CJK=1, other≈len/3.5).",
        ],
    }
    return {"result": result, "ledger": ledger, "coverage_detail": {
        k: {"missed_ids": v["missed_ids"], "covered_ids": v["covered_ids"]} for k, v in cov.items()
    }}


def write_outputs(out: Path, measured: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.json").write_text(json.dumps(measured["ledger"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "ledger.md").write_text(render_ledger_md(measured["ledger"]), encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(measured["result"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "coverage_detail.json").write_text(json.dumps(measured["coverage_detail"], ensure_ascii=False, indent=2), encoding="utf-8")
    r = measured["result"]
    st = r["switch_tax"]
    ag = r["agents_from_profile"]
    lines = [
        "# agent-switch-tax 实测",
        "",
        f"- 项目：`{r['project']}`",
        f"- 账本事实数：{r['ledger_summary']['n_facts']}（{r['ledger_summary']['kinds']}）",
        f"- README 覆盖率：{st['coverage_readme']:.1%}（漏掉 {st['tax_facts_n']} 条 = switch tax）",
        f"- README+近 2 轮 CHANGELOG 覆盖率：{st['coverage_readme_plus_2rounds']:.1%}",
        f"- 完整 ledger 覆盖率：{st['coverage_full_ledger']:.1%}",
        f"- 补齐 ledger 约增 tokens：{st['delta_tokens_to_carry_ledger']}（ledger≈{st['ledger_approx_tokens']}，README≈{st['readme_approx_tokens']}）",
        f"- 画像中的 AI 栈：{ag['ai_stacks']}（编码代理类 {ag['coding_agents']}）：{', '.join(ag['names']) or '（无）'}",
        f"- 若每个编码代理都冷启动一次：事实暴露量 {r['multi_agent_exposure']['if_each_coding_agent_cold_starts_once_fact_exposures']}",
        "",
        "## README 冷启动漏掉的事实（节选）",
    ]
    for item in r["missed_by_readme"][:25]:
        lines.append(f"- ({item['kind']}) {item['text']}")
    if len(r["missed_by_readme"]) > 25:
        lines.append(f"- …共 {len(r['missed_by_readme'])} 条，见 metrics.json")
    lines.append("")
    lines.append("## 诚实边界")
    for h in r["honest_limits"]:
        lines.append(f"- {h}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure coding-agent cold-start switch tax on a project")
    ap.add_argument("--project", required=True, help="Project root to ledgerize")
    ap.add_argument("--profile", help="Optional abstract profile JSON (tools list)")
    ap.add_argument("--out", required=True, help="Output directory")
    args = ap.parse_args(argv)
    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    profile = None
    if args.profile:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    measured = measure(root, profile)
    out = Path(args.out)
    write_outputs(out, measured)
    summary = {
        "n_facts": measured["result"]["ledger_summary"]["n_facts"],
        "coverage_readme": measured["result"]["switch_tax"]["coverage_readme"],
        "tax_facts_n": measured["result"]["switch_tax"]["tax_facts_n"],
        "coding_agents": measured["result"]["agents_from_profile"]["coding_agents"],
        "out": str(out),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
