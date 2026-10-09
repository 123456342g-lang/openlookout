"""V1 外部趋势层：行为定位卡点，趋势打开「现在能做的新事」。

不是新闻摘要。每条趋势必须有 url + date + fact + opens（新打开的能力），
并与行为 finding 的标签对齐后才能上卡。
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "trends" / "catalog.json"

KIND_TAGS = {
    "numbered_series": ["course-crypto", "crypto", "pqc"],
    "manual_summary": ["chores"],
    "version_sprawl": ["doc-workflow"],
    "repeated_download": ["chores"],
    "tool_stack_churn": ["ai-agent", "tool-churn", "codex", "dev-workflow"],
    "openlookout_build": ["ai-agent", "pqc", "crypto", "dev-workflow"],
}

PATH_TAG_HINTS = [
    (re.compile(r"密码|crypto|cryptography|公钥|有限域|模幂", re.I), ["course-crypto", "crypto", "pqc"]),
    (re.compile(r"opencode|codex|ollama|langflow|cc.?switch|claude", re.I), ["ai-agent", "tool-churn", "codex"]),
    (re.compile(r"openlookout|瞭望", re.I), ["ai-agent", "dev-workflow"]),
]


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or CATALOG).read_text(encoding="utf-8"))


def behavior_tags(f: dict) -> set[str]:
    tags = set(KIND_TAGS.get(f.get("kind"), []))
    blob = json.dumps(f.get("local") or {}, ensure_ascii=False) + json.dumps(f.get("facts") or {}, ensure_ascii=False)
    for rx, ts in PATH_TAG_HINTS:
        if rx.search(blob):
            tags.update(ts)
    return tags


def match_trends(f: dict, catalog: dict | None = None, limit: int = 2) -> list[dict]:
    cat = catalog or load_catalog()
    tags = behavior_tags(f)
    if not tags or tags <= {"chores", "doc-workflow"}:
        return []
    scored = []
    for t in cat.get("trends") or []:
        if not (t.get("verified") or {}).get("ok"):
            continue
        overlap = tags & set(t.get("tags") or [])
        if not overlap or overlap <= {"chores"}:
            continue
        date = t.get("date") or ""
        scored.append((len(overlap), date, {**t, "overlap_tags": sorted(overlap)}))
    # 重叠多优先；同重叠时日期新优先
    def key(item):
        n, date, _ = item
        parts = tuple(int(p) for p in date.split("-") if p.isdigit()) or (0,)
        return (-n, tuple(-p for p in parts))
    scored.sort(key=key)
    return [s[2] for s in scored[:limit]]


def verify_url(url: str, timeout: float = 8.0) -> dict:
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "OpenLookoutV1/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = int(getattr(resp, "status", 200) or 200)
            return {"ok": 200 <= code < 400, "status": code, "url": url}
    except Exception as ex:
        return {"ok": False, "error": repr(ex)[:160], "url": url}


def cite(trend: dict) -> dict:
    return {
        "id": trend["id"],
        "date": trend["date"],
        "url": trend["url"],
        "fact": trend["fact"],
        "opens": trend.get("opens", ""),
        "overlap_tags": trend.get("overlap_tags") or [],
        "verified": trend.get("verified") or {},
    }
