"""[V1 已隔离] 机会引擎 / 创业赛道发现 不是 OpenLookout V1 的默认入口。
V1 核心见 lookout/v1.py 与 V1.md。本模块不进入 `python3 -m lookout.v1`。
保留仅供研究回放。
"""
import argparse, itertools, json, os, re, sys
from collections import defaultdict
from pathlib import Path

# 通用词表：把画像里的自然语言落到资产标签上（不含任何个人信息）
LEXICON = [
    (r"密码|crypto|加密|公钥|有限域|模幂|模运算|RSA|ElGamal|DH", ["crypto", "public-key"]),
    (r"有限域|finite field|模运算|模幂", ["finite-field"]),
    (r"国密|SM2|SM3|SM4|商用密码", ["gm-crypto"]),
    (r"中国|Chinese|国内|中文|大陆|Doubao|豆包", ["china"]),
    (r"编译|compiler|AST|语法分析|LLVM", ["compiler", "static-analysis"]),
    (r"操作系统|OS 课|kernel|operating system", ["systems"]),
    (r"游戏|game|Unity|Godot|RPG Maker|Unreal", ["gamedev"]),
    (r"Ollama|本地模型|local model|llama\.cpp|LM Studio|本地优先|local-first", ["local-llm"]),
    (r"8 ?GB|显卡|GPU|显存|VRAM", ["consumer-gpu"]),
    (r"Codex|OpenCode|Claude Code|Cursor|AI 编程|coding agent|编程代理|Copilot", ["coding-agent"]),
    (r"Langflow|LangChain|Dify|n8n|工作流", ["llm-workflow"]),
    (r"开源|open[- ]source|GitHub|star", ["open-source"]),
    (r"CC Switch|多模型|provider|模型切换", ["multi-provider"]),
    (r"Windows", ["windows"]),
]
# 外部世界的标签 → 哪些资产在这件事上占优（“这条趋势奖励什么样的人”）
ADVANTAGE = {
    "pqc": ["crypto", "public-key", "finite-field"], "crypto-migration": ["crypto", "public-key", "static-analysis"],
    "public-key": ["public-key", "crypto"], "gm-crypto": ["crypto", "china"], "china": ["china"],
    "cbom": ["static-analysis", "crypto", "compiler"], "static-analysis": ["static-analysis", "compiler"],
    "zk": ["finite-field", "crypto", "compiler"], "finite-field": ["finite-field"], "compiler": ["compiler"],
    "digital-identity": ["crypto"], "consumer-gpu": ["consumer-gpu"], "gamedev": ["gamedev"],
    "local-llm": ["local-llm"], "genai": ["coding-agent", "local-llm"], "open-source": ["open-source"],
    "python": ["open-source"], "javascript": [], "standards": [], "regulation": [], "gap": [],
}
# 资产“家族”：同一来源的近义标签（比如同一门密码课带来的 crypto/public-key/finite-field）只算一类
FAMILY = {"crypto": "crypto", "public-key": "crypto", "finite-field": "crypto", "gm-crypto": "crypto",
          "compiler": "compiler", "static-analysis": "compiler", "systems": "systems", "gamedev": "gamedev",
          "local-llm": "local-ai", "consumer-gpu": "hardware", "coding-agent": "ai-tools", "llm-workflow": "ai-tools",
          "multi-provider": "ai-tools", "china": "locale", "open-source": "builder", "windows": "hardware"}
GENERIC = {"locale", "builder", "ai-tools"}  # 很多人都有的家族：可以参与组合，权重减半
KIND_W = {"deadline": 1.5, "gap": 2.0, "trend": 1.0, "adoption": 0.8, "existing": 0.5}

def _text(x):
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)

def sanitize(profile):
    """去掉排除主题；返回 (可出站画像, 被去掉的条目数)。只保留白名单字段。"""
    ex = [e for e in profile.get("exclude_topics", []) if e]
    rx = re.compile("|".join(re.escape(e) for e in ex), re.I) if ex else None
    out, dropped = {}, 0
    for k in ("role", "topics", "tools", "courses", "assets", "hardware", "constraints", "goals"):
        v = profile.get(k)
        if v is None: continue
        if isinstance(v, list):
            keep = [x for x in v if not (rx and rx.search(_text(x)))]
            dropped += len(v) - len(keep); out[k] = keep
        else:
            s = _text(v)
            if rx: s2 = rx.sub("", s); dropped += int(s2 != s); s = re.sub(r"[；;，,、]\s*[；;，,、]", "；", s2)
            out[k] = s
    out["exclude_topics"] = ex
    return out, dropped

def audit_outbound(obj):
    """出站前审计：不许出现 URL、盘符/家目录路径、邮箱、长数字串（与 lookout.profile.audit 同口径再加两项）。"""
    s = json.dumps(obj, ensure_ascii=False)
    bad = []
    if re.search(r"https?://", s): bad.append("url")
    if re.search(r"[A-Za-z]:[\\/]|\\Users\\|/home/\w+", s): bad.append("path")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", s): bad.append("email")
    if re.search(r"\d{9,}", s): bad.append("long-number")
    return bad

def asset_tags(profile):
    tags = defaultdict(list)  # tag -> 证据（画像原文片段）
    for k in ("role", "topics", "tools", "courses", "assets", "hardware", "constraints"):
        v = profile.get(k)
        for item in (v if isinstance(v, list) else [v] if v else []):
            s = _text(item)
            for rx, ts in LEXICON:
                if re.search(rx, s, re.I):
                    for t in ts:
                        if s not in tags[t]: tags[t].append(s[:60])
    return dict(tags)

def advantaged(signal, at):
    """这条信号奖励的、而画像里正好有的资产标签。"""
    return {a for t in signal["tags"] for a in ADVANTAGE.get(t, [])} & set(at)

def _weight(combo):
    fams = {FAMILY.get(t, t) for t in combo}
    return sum(0.5 if f in GENERIC else 1.0 for f in fams), fams

def cross_match(profile, signals, top=5):
    """主题 = 2~4 个资产标签的组合，至少跨两个“家族”（加权 ≥1.5，大众家族记 0.5）。
    必须有信号**单条**同时奖励组合里的全部资产才算命中——不会把两条不相关的信号硬拼成一个主题。
    分数 = 信号强度 × 家族数^1.5 ×（有空白信号 1.3）×（有截止日 1.2）。同一家族组合只保留最高分。"""
    at = asset_tags(profile)
    adv = {s["id"]: advantaged(s, at) for s in signals}
    tags = sorted(at)
    best = {}
    for r in (2, 3, 4):
        for combo in itertools.combinations(tags, r):
            w, fams = _weight(combo)
            if w < 1.5 or len(fams) < r - 1: continue
            hits = [s for s in signals if set(combo) <= adv[s["id"]]]
            if not hits: continue
            hit_tags = set().union(*[set(h["tags"]) for h in hits]) - {"open-source", "standards", "regulation", "python", "javascript"}
            related = [s for s in signals if s not in hits and s["kind"] in ("gap", "existing") and set(s["tags"]) & hit_tags]
            kinds = {s["kind"] for s in hits + related}
            strength = sum(KIND_W[s["kind"]] for s in hits) + 0.5 * sum(KIND_W[s["kind"]] for s in related)
            score = round(strength * w ** 1.5 * (1.3 if "gap" in kinds else 1.0) * (1.2 if "deadline" in kinds else 1.0), 2)
            key = frozenset(fams)
            th = {"assets": list(combo), "families": sorted(fams), "score": score, "signals": [s["id"] for s in hits],
                  "related": [s["id"] for s in related], "kinds": sorted(kinds), "evidence": {t: at[t][:2] for t in combo}}
            if key not in best or score > best[key]["score"]: best[key] = th
    themes = sorted(best.values(), key=lambda x: -x["score"])
    out = []
    for th in themes:  # 再去冗余：信号集合几乎被更高分主题覆盖的跳过
        if any(len(set(th["signals"]) - set(o["signals"] + o["related"])) == 0 and set(th["families"]) <= set(o["families"]) for o in out):
            continue
        out.append(th)
        if len(out) >= top: break
    return out, at

SYSTEM = """你是一个只说有证据的话的创业顾问。任务：根据用户的去标识画像和一组已核实的公开信号，找出用户位置异常有利、而且价值会随技术和市场发展而增长的机会。
硬性规则：
1. 只能引用给定信号里的事实。每个依据都写信号 id，不许编造数字、日期、产品或来源。
2. 不要写新闻、提醒、待办，也不要写“学习某技术”这类泛泛建议。必须是把用户已有的 ≥2 类资产组合起来、别人不容易复制的位置。
3. 不得涉及画像 exclude_topics 中的主题。
4. 第一步必须能在 1~2 周内做完、能测量，并写出验收标准（数字或可复现的检查）。
只输出 JSON：{"opportunities":[{"title":"","insight":"一句话","why_you":{"assets":["资产标签"],"text":""},
"why_now":{"signals":["id"],"text":""},"existing_and_gap":{"signals":["id"],"text":""},
"first_step":{"build":"","success_metric":""},"risks":""}]}"""

def llm_opportunities(profile_out, themes, signals, run_dir, model="mimo-v2.6-pro", n=3):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lookout.llm import LLM, parse_json
    sig = [{k: s[k] for k in ("id", "kind", "date", "fact", "tags")} for s in signals]  # 不发 URL：模型只按 id 引用
    payload = {"profile": profile_out, "candidate_themes": themes, "signals": sig, "n": n}
    bad = audit_outbound(payload)
    if bad: raise SystemExit(f"outbound audit failed: {bad}")
    llm = LLM(run_dir, model=model)
    text, rec = llm.chat("opportunities", SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=6000, temperature=0.4)
    return parse_lenient(text).get("opportunities", []), rec

def parse_lenient(text):
    """lookout.llm.parse_json 会补少掉的右括号；这里再处理多出来的：在报错位置删掉多余的 } 或 ]，最多删 5 次（只动结构）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lookout.llm import parse_json
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    s = m.group(1) if m else text[text.find("{"):]
    for _ in range(6):
        try:
            return parse_json(s)
        except json.JSONDecodeError as e:
            pos = e.pos
            j = max(i for i in (s.rfind("}", 0, pos + 1), s.rfind("]", 0, pos + 1)))
            if j < 0: raise
            s = s[:j] + s[j + 1:]
    return parse_json(s)

def validate(opps, profile_out, signals, asset_tag_map):
    ids = {s["id"] for s in signals}
    ex = [e for e in profile_out.get("exclude_topics", []) if e]
    kept, rejected = [], []
    for o in opps:
        why = []
        cited = set((o.get("why_now") or {}).get("signals", [])) | set((o.get("existing_and_gap") or {}).get("signals", []))
        if not cited: why.append("没有引用任何信号")
        if cited - ids: why.append(f"引用了不存在的信号 {sorted(cited - ids)}")
        assets = (o.get("why_you") or {}).get("assets", [])
        fams = set()
        for a in assets:  # 资产可以写标签，也可以照抄画像原文；都映射回资产家族
            if a in asset_tag_map: fams.add(FAMILY.get(a, a)); continue
            if any(a[:12] in ev or ev[:12] in a for evs in asset_tag_map.values() for ev in evs):
                fams |= {FAMILY.get(t, t) for t, evs in asset_tag_map.items() if any(a[:12] in ev or ev[:12] in a for ev in evs)}
        if len(fams - GENERIC) < 2 and not (len(fams - GENERIC) == 1 and fams & GENERIC):
            why.append(f"why_you 里能在画像中找到的资产家族不足 2 类（{sorted(fams)}）")
        blob = json.dumps(o, ensure_ascii=False)
        hit = [e for e in ex if e.lower() in blob.lower()]
        if hit: why.append(f"含排除主题 {hit}")
        fs = o.get("first_step") or {}
        if not fs.get("build") or not re.search(r"\d|通过|复现|测|校验", fs.get("success_metric", "")): why.append("第一步缺少可测量的验收标准")
        # 文中出现的数字必须能在被引用信号的原文里找到（防止模型自己编数字）
        facts = " ".join(s["fact"] + " " + s["date"] for s in signals if s["id"] in cited)
        nums = set(re.findall(r"\d[\d,.]*\d|\d", " ".join(_text(o.get(k, "")) for k in ("why_now", "existing_and_gap"))))
        made_up = [x for x in nums if x.replace(",", "") not in facts.replace(",", "") and len(x.replace(",", "")) >= 3]
        if made_up: why.append(f"依据里的数字在所引信号原文中找不到 {made_up[:3]}")
        (rejected if why else kept).append({**o, "_rejected": why} if why else o)
    return kept, rejected

def render_md(themes, kept, rejected, signals):
    url = {s["id"]: s for s in signals}
    L = ["# 机会发现引擎输出", "", "## 确定性交叉匹配（主题打分）", ""]
    for t in themes:
        L.append(f"- **{' × '.join(t['assets'])}**　分数 {t['score']}　信号 {', '.join(t['signals'])}")
    L += ["", "## 机会卡（已过校验）", ""]
    for i, o in enumerate(kept, 1):
        L += [f"### {i}. {o.get('title', '')}", "", f"**洞察**：{o.get('insight', '')}", "",
              f"**为什么是你**（{', '.join(o['why_you'].get('assets', []))}）：{o['why_you'].get('text', '')}", "",
              f"**为什么是现在**：{o['why_now'].get('text', '')}", ""]
        for sid in o["why_now"].get("signals", []) + o["existing_and_gap"].get("signals", []):
            if sid in url: L.append(f"  - [{sid}] {url[sid]['date']}：{url[sid]['fact']}（{url[sid]['url']}）")
        L += ["", f"**已有什么、空白在哪**：{o['existing_and_gap'].get('text', '')}", "",
              f"**第一步**：{o['first_step'].get('build', '')}；验收：{o['first_step'].get('success_metric', '')}", "",
              f"**风险**：{o.get('risks', '')}", ""]
    if rejected:
        L += ["## 被校验拒掉的卡", ""] + [f"- {o.get('title', '?')}：{'；'.join(o['_rejected'])}" for o in rejected]
    return "\n".join(L) + "\n"

def run(profile, signals, out_dir, use_llm=False, model="mimo-v2.6-pro", n=3, from_response=None):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    prof_out, dropped = sanitize(profile)
    themes, at = cross_match(prof_out, signals)
    res = {"dropped_excluded_items": dropped, "asset_tags": at, "themes": themes, "opportunities": [], "rejected": []}
    if from_response:  # 离线重放：不再调模型，只重新解析/校验已存档的回复
        opps, rec = parse_lenient(Path(from_response).read_text(encoding="utf-8")).get("opportunities", []), {"replayed": str(from_response)}
        res["opportunities"], res["rejected"] = validate(opps, prof_out, signals, at); res["llm"] = rec
    elif use_llm:
        opps, rec = llm_opportunities(prof_out, themes, signals, out, model=model, n=n)
        res["opportunities"], res["rejected"] = validate(opps, prof_out, signals, at)
        res["llm"] = rec
    (out / "opportunities.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "opportunities.md").write_text(render_md(themes, res["opportunities"], res["rejected"], signals), encoding="utf-8")
    return res

def main():
    ap = argparse.ArgumentParser(description="机会发现引擎")
    ap.add_argument("--profile", required=True); ap.add_argument("--signals", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--llm", action="store_true"); ap.add_argument("--model", default="mimo-v2.6-pro"); ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--from-response", help="重放已存档的模型回复（不联网）")
    a = ap.parse_args()
    profile = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    signals = json.loads(Path(a.signals).read_text(encoding="utf-8"))["signals"]
    r = run(profile, signals, a.out, a.llm, a.model, a.n, a.from_response)
    print(f"themes={len(r['themes'])} kept={len(r['opportunities'])} rejected={len(r['rejected'])} dropped_excluded={r['dropped_excluded_items']}")
    for t in r["themes"][:5]: print(" ", " × ".join(t["assets"]), t["score"], t["signals"][:4])

if __name__ == "__main__":
    main()
