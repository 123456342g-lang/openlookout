"""可插拔、可核实的“外部已有能力”查询（通用，不含任何领域类别清单）。
 CapabilityIndex.search(phrase, lang) -> [Candidate]   例：GitHubIndex（真实）、FixtureIndex（离线测试）；也可以接 PyPI/npm/内部知识库
 VerifierPolicy.check(candidate, phrase) -> (ok, why)   对候选的“可核实事实”设阈值：许可证、是否归档、活跃度、采用度、与要做的事是否真相关
"""
from __future__ import annotations
import json, re, urllib.parse, urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Unlicense", "0BSD", "Zlib", "BSL-1.0", "LGPL-3.0", "LGPL-2.1"}
STOP = {"the", "a", "of", "and", "to", "for", "in", "util", "utils", "helper", "helpers", "common", "base", "lib", "my", "new", "test", "tests", "main", "core", "tool", "tools",
        "py", "js", "ts", "go", "rs", "impl", "simple", "custom", "service", "manager", "handler", "wrapper", "module", "script", "data", "file", "files", "app", "project"}


def stem(w: str) -> str:
    w = w.lower()
    for suf in ("ing", "ers", "er", "ed", "es", "s", "ion"):
        if w.endswith(suf) and len(w) - len(suf) >= 3: return w[: -len(suf)]
    return w


def tokens(text: str) -> set:
    parts = re.findall(r"[A-Za-z][A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", text.replace("_", " ").replace("-", " ")))
    return {stem(p) for p in parts if p.lower() not in STOP and len(p) >= 2}


@dataclass
class Candidate:
    name: str
    url: str = ""
    facts: dict = field(default_factory=dict)       # license, archived, pushed_at(ISO), adoption(数值), description, topics(list), fork


class GitHubIndex:
    def __init__(self, token=None, timeout=15): self.token, self.timeout, self.cache = token, timeout, {}
    def search(self, phrase: str, lang: str | None = None, n=8) -> list:
        key = (phrase, lang)
        if key in self.cache: return self.cache[key]
        q = phrase + (f" language:{lang}" if lang else "")
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": n})
        req = urllib.request.Request(url, headers={"User-Agent": "openlookout-sprite", "Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        try: items = json.loads(urllib.request.urlopen(req, timeout=self.timeout).read()).get("items", [])
        except Exception: items = []
        out = [Candidate(i["full_name"], i["html_url"], dict(license=(i.get("license") or {}).get("spdx_id"), archived=i.get("archived", False), pushed_at=i.get("pushed_at"),
                                                           adoption=i.get("stargazers_count", 0), description=i.get("description") or "", topics=i.get("topics", []), fork=i.get("fork", False)))
               for i in items]
        self.cache[key] = out; return out


class FixtureIndex:
    def __init__(self, table: dict): self.table, self.calls = table, []
    def search(self, phrase, lang=None, n=8):
        self.calls.append(phrase); ts = tokens(phrase)
        for k, v in self.table.items():
            if tokens(k) & ts: return v
        return []


@dataclass
class VerifierPolicy:
    licenses: set = field(default_factory=lambda: set(PERMISSIVE))
    max_idle_days: int = 365
    min_adoption: int = 1000
    min_relevance: float = 0.5
    now: datetime | None = None

    def check(self, c: Candidate, phrase: str):
        f = c.facts; now = self.now or datetime.now(timezone.utc)
        if f.get("license") not in self.licenses: return False, f"许可证不合适（{f.get('license')}）"
        if f.get("archived") or f.get("fork"): return False, "已归档或是 fork"
        try: pushed = datetime.fromisoformat(f["pushed_at"].replace("Z", "+00:00"))
        except Exception: return False, "没有活跃度信息"
        if (now - pushed).days > self.max_idle_days: return False, f"{(now - pushed).days} 天没更新"
        if f.get("adoption", 0) < self.min_adoption: return False, f"采用度太低（{f.get('adoption', 0)}）"
        want = tokens(phrase); have = tokens(c.name + " " + f.get("description", "") + " " + " ".join(f.get("topics", [])))
        rel = len(want & have) / max(len(want), 1)
        if rel < self.min_relevance: return False, f"和要做的事相关度太低（{rel:.2f}）"
        return True, f"{f['license']}、{f['adoption']/1000:.1f}k、{pushed.date()} 仍在更新、相关度 {rel:.2f}"
