"""第 10 轮：从本机历史里提炼"去标识的兴趣/角色画像"。
本地完整画像（含域名、查询词计数）只写到 capture 目录下（被 .gitignore 挡住）；
能发到云端/外部检索的只有 abstract：主题词、工具名、课程主题，不含人名、路径、URL、账号。

用法：python3 -m lookout.profile --capture <capture_dir> [--out <dir>]"""
import argparse, json, re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote_plus

# 主题词表：主题 -> 触发关键词（在域名/查询/标题里出现即计数）。这是通用词表，不是为某个人写死的。
TOPICS = {
    "漏洞挖掘/安全研究": ["cve", "vuln", "漏洞", "exploit", "poc", "bughunters", "clusterfuzz", "oss-fuzz", "vulncheck", "fuzz", "sandbox", "cna"],
    "浏览器/V8 安全": ["v8", "chromium", "issues.chromium.org", "sandbox violation", "maglev", "turbofan"],
    "AI 辅助安全审计": ["vuln", "audit", "security review", "security-review", "codex security", "codex-security", "llm security", "red team", "redteam", "pentest"],
    "AI 编程代理/大模型工具": ["opencode", "codex", "claude code", "claude-code", "cursor", "ollama", "deepseek", "langflow", "huggingface", "mcp", "llm", "agent"],
    "密码学课程": ["密码", "crypto", "rsa", "aes", "模幂", "有限域", "置换", "代替", "cipher"],
    "CTF/竞赛": ["ctf", "竞赛", "大赛", "挑战赛", "kaggle", "强网"],
    "独立游戏开发": ["itch.io", "rpg maker", "steam", "gumroad", "godot", "unity"],
    "操作系统/编译课程": ["操作系统", "编译", "程序分析"],
}
# 工具：名字 -> (识别模式, 对应的公开上游，用于拉 release/安全公告)
# 工具关注清单：名字 -> (识别模式, 对应的公开上游，用于拉 release/安全公告)。
# 代码里只放几个常见的本地 AI 工具；个人化的清单放在 <capture>/world/tools_watchlist.json（私有，不进 git），存在就覆盖/追加。
TOOLS = {
    "Langflow Desktop": (r"LangflowDesktop|langflow", {"github": "langflow-ai/langflow", "ghsa_affects": "langflow"}),
    "Ollama": (r"ollama app\.exe|\bollama\b", {"github": "ollama/ollama"}),
    "Codex CLI": (r"\bcodex\b", {"github": "openai/codex"}),
}
def load_tools(cap):
    tools = dict(TOOLS); f = Path(cap) / "world" / "tools_watchlist.json"
    if f.exists():
        for k, v in json.loads(f.read_text(encoding="utf-8")).items(): tools[k] = (v["pattern"], v["upstream"])
    return tools

SEARCH_HOSTS = {"www.bing.com": "q", "cn.bing.com": "q", "www.google.com": "q", "www.baidu.com": "wd", "github.com": "q", "duckduckgo.com": "q"}

def _query(url):
    try:
        u = urlparse(url)
    except Exception:
        return None
    key = SEARCH_HOSTS.get(u.netloc)
    if not key or (u.netloc == "github.com" and not u.path.startswith("/search")):
        return None
    v = parse_qs(u.query).get(key)
    return unquote_plus(v[0]).strip().lower() if v else None

def build(capture):
    cap = Path(capture)
    evs = [json.loads(l) for l in open(cap / "events.jsonl", encoding="utf-8")]
    try:
        from .history import filter_noise
        evs, _ = filter_noise(evs)
    except Exception:
        pass
    doms, queries, titles, files = Counter(), Counter(), Counter(), Counter()
    for e in evs:
        url = e.get("url") or ""
        if url.startswith("http"):
            doms[urlparse(url).netloc.lower()] += 1
            q = _query(url)
            if q: queries[q] += 1
        if e.get("title"): titles[e["title"]] += 1
        if e.get("path"): files[Path(str(e["path"]).replace("\\", "/")).name] += 1
    log = (cap / "backfill_log.txt").read_text(encoding="utf-8", errors="ignore") if (cap / "backfill_log.txt").exists() else ""
    blob = "\n".join(list(doms) + list(queries) + list(titles) + list(files) + [log]).lower()
    topics = {}
    for t, kws in TOPICS.items():
        hits = sum(blob.count(k) for k in kws)
        if hits: topics[t] = hits
    tools = {}
    for name, (pat, up) in load_tools(cap).items():
        n = len(re.findall(pat, blob, re.I))
        if n: tools[name] = {"signal_count": n, **up, "installed_hint": bool(re.search(pat, log, re.I))}
    # 课程主题：编号系列文件名里的"实验N_主题"，只取主题词（不含路径/组号/人名）
    course = {}
    for f in files:
        m = re.search(r"实验\s*([0-9一二三四五六七八九十]+)[_\s]*([\u4e00-\u9fa5A-Za-z与和的]{4,30})", f)
        if m and not re.search(r"组|模板|截图|操作系统", m.group(2)):
            if m.group(2) not in course.values(): course.setdefault(m.group(1), m.group(2))
    private = {"domains": doms.most_common(60), "queries": queries.most_common(80),
               "files_sample": [f for f, _ in files.most_common(40)], "topics": topics, "tools": tools, "course_series": course}
    abstract = {
        "role": "中国高校本科生，网络空间安全方向；做漏洞研究/披露；同时在修应用密码学（每周实验）",
        "topics": sorted(topics, key=lambda k: -topics[k]),
        "tools": sorted(tools, key=lambda k: -tools[k]["signal_count"]),
        "tools_evidence": {k: ("装过（本机有该应用的数据目录）" if v["installed_hint"] else "浏览/搜索过") for k, v in tools.items()},
        "course_progress": [f"实验{k}:{v}" for k, v in sorted(course.items(), key=lambda kv: kv[0])],
        # 只保留能落到某个主题/工具上的查询（导航型、闲聊型查询不出站）
        "interests_queries": sorted({q for q, _ in queries.most_common(200) if _safe_query(q) and _on_topic(q)})[:40],
    }
    return private, abstract

def _on_topic(q):
    return any(k in q for kws in TOPICS.values() for k in kws if len(k) >= 3) or any(re.search(p, q, re.I) for p, _ in TOOLS.values()) \
        or re.search(r"vuln|fuzz|security|audit|cve|ctf|agent|game", q)

def _safe_query(q):
    """只保留像"主题/工具名"的查询：短、无数字串、无 @ / 路径 / 中文人名风险较低。"""
    return 2 <= len(q) <= 40 and not re.search(r"[@/\\:]|\d{5,}", q)

def audit(abstract, forbidden):
    s = json.dumps(abstract, ensure_ascii=False)
    bad = [w for w in forbidden if w and w in s]
    if re.search(r"https?://|[A-Za-z]:[\\/]|\\Users\\", s): bad.append("<url/path>")
    return bad

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True); ap.add_argument("--out")
    a = ap.parse_args()
    out = Path(a.out or Path(a.capture) / "world"); out.mkdir(parents=True, exist_ok=True)
    private, abstract = build(a.capture)
    meta = json.loads((Path(a.capture) / "meta.json").read_text(encoding="utf-8"))
    forbidden = [meta.get("user_home", "")] if len(meta.get("user_home", "")) > 2 else []
    try:
        from .deid import collect_names
        import lookout.common as common
        common.CAP = Path(a.capture)
        forbidden += collect_names(meta)
    except Exception:
        pass
    bad = audit(abstract, forbidden)
    if bad:
        raise SystemExit(f"abstract profile failed audit: {len(bad)} hits")
    (out / "profile_private.json").write_text(json.dumps(private, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "profile_abstract.json").write_text(json.dumps(abstract, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(abstract, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
