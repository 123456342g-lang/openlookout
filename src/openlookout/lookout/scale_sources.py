"""行为痕迹缩放：更多来源 → 统一事件 schema → 消融（少源 vs 全源）。

把行为数据当“语言”看：来源越多，潜在需求发现是否更好——用同一套
检测器+惊喜门控，只改变可用事件子集，量化对比。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

# 统一 schema 字段（所有来源最终都归一到这些）
SCHEMA = ("ts", "type", "source", "app", "path", "url", "title", "size", "dur_s")

# 来源族：消融用
SOURCE_FAMILIES = {
    "browser": re.compile(r"^backfill:(chrome|edge|brave|tabbit|firefox|doubao|ima|default)(-|$)"),
    "downloads": re.compile(r"downloads"),
    "recent": re.compile(r"^backfill:recent"),
    "office": re.compile(r"^backfill:office"),
    "files": re.compile(r"^backfill:fs"),
    "search": re.compile(r"^derived:search"),
    "git": re.compile(r"^derived:git"),
    "editor": re.compile(r"^derived:editor|^backfill:vscode|^backfill:cursor"),
    "realtime": re.compile(r"^(?!backfill:|derived:)"),  # recorder 实时
}

# 预设消融配置
ABLATIONS = {
    "few": ["browser"],                          # 只有浏览器访问
    "mid": ["browser", "downloads", "recent"],   # 浏览器+下载+最近
    "files_heavy": ["files", "recent", "office"],
    "all_raw": ["browser", "downloads", "recent", "office", "files"],
    "all_plus": ["browser", "downloads", "recent", "office", "files", "search", "git", "editor"],
}


def family_of(source: str) -> str:
    s = str(source or "")
    for name, rx in SOURCE_FAMILIES.items():
        if name == "downloads":
            if "downloads" in s:
                return "downloads"
            continue
        if rx.search(s):
            return name
    return "other"


def filter_by_families(evs: list[dict], families: list[str]) -> list[dict]:
    allow = set(families)
    return [e for e in evs if family_of(e.get("source", "")) in allow]


def derive_search_queries(evs: list[dict]) -> list[dict]:
    """从浏览器 URL 抽出搜索词 → derived:search 事件（不改原事件）。"""
    out = []
    seen = set()
    for e in evs:
        if e.get("type") != "focus" or not e.get("url"):
            continue
        u = urlparse(e["url"])
        q = (parse_qs(u.query).get("wd") or parse_qs(u.query).get("q") or parse_qs(u.query).get("query") or [None])[0]
        if not q or len(q) < 2:
            continue
        key = (e.get("ts", "")[:16], q.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "ts": e["ts"], "type": "search_query", "source": "derived:search",
            "app": e.get("app"), "url": e.get("url"), "title": q, "query": q,
            "dt": e.get("dt"),
        })
    return out


def derive_git_activity(roots: list[Path], now_iso: str | None = None, max_repos: int = 8, max_commits: int = 80) -> list[dict]:
    """只读扫描 roots 下 .git，导出近期 commit 为 derived:git（本机盒内可用）。"""
    import subprocess
    out = []
    found = []
    for root in roots:
        if not root or not Path(root).exists():
            continue
        for gitdir in Path(root).rglob(".git"):
            if len(found) >= max_repos:
                break
            repo = gitdir.parent if gitdir.is_dir() else gitdir.parent
            # skip nested huge trees
            if "node_modules" in str(repo) or ".venv" in str(repo):
                continue
            found.append(repo)
        if len(found) >= max_repos:
            break
    for repo in found:
        try:
            r = subprocess.run(
                ["git", "-C", str(repo), "log", f"-n{max_commits}",
                 "--pretty=format:%H\t%aI\t%s"],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode != 0:
                continue
            for line in r.stdout.splitlines():
                if "\t" not in line:
                    continue
                parts = line.split("\t", 2)
                if len(parts) < 3:
                    continue
                sha, ts, subj = parts
                out.append({
                    "ts": ts.replace("Z", "+00:00")[:19] if "T" in ts else ts,
                    "type": "git_commit",
                    "source": "derived:git",
                    "app": "git",
                    "path": str(repo),
                    "title": subj[:200],
                    "sha": sha[:12],
                })
        except Exception:
            continue
    return out


def derive_editor_recents(home_hints: list[Path]) -> list[dict]:
    """尝试读 VS Code / Cursor 的 storage.json recent（跨平台路径提示）。"""
    out = []
    candidates = []
    for h in home_hints:
        h = Path(h)
        for rel in (
            "AppData/Roaming/Code/User/globalStorage/storage.json",
            "AppData/Roaming/Cursor/User/globalStorage/storage.json",
            ".config/Code/User/globalStorage/storage.json",
            ".config/Cursor/User/globalStorage/storage.json",
        ):
            p = h / rel
            if p.exists():
                candidates.append(p)
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # best-effort keys
        blobs = []
        for k, v in (data.items() if isinstance(data, dict) else []):
            if "recent" in k.lower() or "history" in k.lower():
                blobs.append(v)
        text = json.dumps(blobs, ensure_ascii=False)
        for m in re.finditer(r'"(?:file|folder|path)(?:Uri)?":\s*"([^"]+)"', text):
            path = m.group(1).replace("file:///", "").replace("%3A", ":")
            out.append({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "type": "file_open",
                "source": "derived:editor",
                "app": "code" if "Code" in str(p) else "cursor",
                "path": path[:300],
            })
    return out


def enrich(evs: list[dict], meta: dict, extra_roots: list[Path] | None = None) -> tuple[list[dict], dict]:
    """在已有 capture 上派生 search/git/editor，返回合并事件 + 统计。"""
    derived = []
    derived += derive_search_queries(evs)
    roots = list(extra_roots or [])
    uh = meta.get("user_home")
    if uh:
        roots.append(Path(uh))
    # 只扫用户树 / 显式 extra_roots；不要把运行环境里的 OpenLookout 仓库算进用户行为
    git_ev = derive_git_activity(roots)
    derived += git_ev
    editor_ev = derive_editor_recents([Path(uh)] if uh else [])
    # also try Windows-style under capture content
    derived += editor_ev
    # attach dt
    for e in derived:
        if "dt" not in e and e.get("ts"):
            try:
                e["dt"] = datetime.fromisoformat(e["ts"][:19].replace("Z", "")).replace(tzinfo=None)
            except Exception:
                e["dt"] = meta.get("now_dt") or datetime.now()
    stats = {
        "base_events": len(evs),
        "derived_search": sum(1 for e in derived if e["source"] == "derived:search"),
        "derived_git": sum(1 for e in derived if e["source"] == "derived:git"),
        "derived_editor": sum(1 for e in derived if e["source"] == "derived:editor"),
        "by_family_base": dict(Counter(family_of(e.get("source")) for e in evs)),
    }
    return evs + derived, stats


def ablation_report(rows: list[dict]) -> str:
    lines = ["# 行为来源缩放消融\n",
             "| 配置 | 事件数 | 发现数 | 过门控 | 有趋势卡 | 种类 |\n",
             "|---|---:|---:|---:|---:|---|\n"]
    for r in rows:
        kinds = ",".join(r.get("passed_kinds") or []) or "—"
        lines.append(
            f"| {r['name']} | {r['n_events']} | {r['n_findings']} | {r['n_passed']} | {r['n_with_trend']} | {kinds} |\n"
        )
    lines.append("\n判定标准：过门控张数、是否覆盖 crypto/AI/OpenLookout 交叉、惊喜分总和。\n")
    return "".join(lines)
