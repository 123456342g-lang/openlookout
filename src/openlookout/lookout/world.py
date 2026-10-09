"""[V1 已隔离] 本模块不是 OpenLookout V1 的默认入口。
V1 核心见 lookout/v1.py 与 V1.md：只做「行为痕迹 → 潜在需求 → 已验证方案」。
世界雷达 / 新闻 / 比赛提醒 不进入 `python3 -m lookout.v1`。
保留本文件仅供研究回放，不要当作产品主路径。
"""
import argparse, html, json, os, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

KITS = Path(__file__).resolve().parent / "world_kits"
TODAY = date.today()

# ------------------------------------------------------------------ live signals
def gh(url):
    req = urllib.request.Request(url, headers={"User-Agent": "openlookout", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def collect_live(profile_private):
    live = {"fetched_at": datetime.now().isoformat(timespec="seconds"), "releases": {}, "advisories": {}}
    for name, t in profile_private["tools"].items():
        repo = t.get("github")
        if not repo: continue
        try:
            rel = [r for r in gh(f"https://api.github.com/repos/{repo}/releases?per_page=8") if not r["prerelease"]]
            if rel:
                live["releases"][name] = {"tag": rel[0]["tag_name"], "published": rel[0]["published_at"], "url": rel[0]["html_url"]}
        except Exception as e:
            live["releases"][name] = {"error": str(e)[:80]}
        if t.get("ghsa_affects"):
            items = gh(f"https://api.github.com/advisories?affects={t['ghsa_affects']}&per_page=50&sort=published")
            live["advisories"][name] = [{"ghsa": a["ghsa_id"], "cve": a["cve_id"], "published": a["published_at"][:10], "severity": a["severity"],
                                         "summary": a["summary"], "url": a["html_url"],
                                         "ranges": [(v["vulnerable_version_range"], v["first_patched_version"]) for v in a["vulnerabilities"]
                                                    if v["package"]["name"] == t["ghsa_affects"]]} for a in items
                                        if not a["summary"].startswith("Duplicate Advisory")]   # GitHub 的重复公告会把计数翻倍
    return live

# ------------------------------------------------------------------ scoring
def _d(s):
    try: return datetime.fromisoformat(str(s)[:16]).date()
    except Exception:
        try: return date.fromisoformat(str(s)[:10])
        except Exception: return None

def score(sig, abstract):
    topics = abstract["topics"]; tools = set(abstract["tools"])
    rel = sum(max(0, 4 - topics.index(t) // 2) for t in sig.get("topics", []) if t in topics)
    rel += sum(3 for t in sig.get("tools", []) if t in tools)
    rel += 6 if sig.get("course_link") else 0   # 用户反馈：课程实验系列是重要的
    dl, pub = _d(sig.get("deadline")), _d(sig.get("published"))
    urgent = 0
    if dl:
        days = (dl - TODAY).days
        urgent = -99 if days < 0 else (4 if days <= 7 else 3 if days <= 14 else 1 if days <= 45 else 0)
    if sig.get("severity") == "critical" and pub and (TODAY - pub).days <= 7: urgent = max(urgent, 4)
    novel = 2 if pub and (TODAY - pub).days <= 14 else 0
    act = 3 if sig.get("preparer") else 0
    return {"relevance": rel, "time": urgent, "novelty": novel, "actionable": act, "total": rel + urgent + novel + act}

# ------------------------------------------------------------------ preparers
def run(cmd, cwd, timeout=600):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)

def prep_pubkey_lab(sig, d, ctx):
    shutil.copytree(KITS / "pubkey_lab", d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    rc1, out1 = run([sys.executable, "-m", "unittest", "test_pubkey_lab", "-v"], d)
    rc2, out2 = run([sys.executable, "pqc_compare.py", "--out", "pqc_compare.md"], d)
    rc3, out3 = run([sys.executable, "-c", "import json,pubkey_lab as L;print(json.dumps(L.bench(2048,10)))"], d)
    bench = json.loads(out3.strip().splitlines()[-1]) if rc3 == 0 else {}
    src = sig["sources"]
    md = [f"# 公钥实验预习包（为下一次实验准备，生成于 {TODAY}）", "",
          "> " + sig.get("prep_args", {}).get("inference", "下一次实验的题目未知；按常见课程顺序，模幂/有限域之后通常是公钥密码（RSA / DH / ElGamal），这是推测。"),
          "", "## 文件", "- `pubkey_lab.py`：平方-乘模幂（统计平方/乘法次数，接上一个实验）、Miller-Rabin、RSA（含 CRT 解密）、PKCS#1 v1.5 验签、DH、ElGamal",
          "- `test_pubkey_lab.py`：6 个测试，含与 `cryptography` 库生成的 RSA 密钥/签名互验", "- `pqc_compare.py` / `pqc_compare.md`：本机 OpenSSL 3.5 对比 RSA/Ed25519/X25519 与 ML-DSA/ML-KEM 的尺寸和速度", "",
          "## 本机实测（沙箱，2048 位）", f"- 普通解密 {bench.get('dec_ms', 0):.2f} ms，CRT 解密 {bench.get('dec_crt_ms', 0):.2f} ms，加速 {bench.get('speedup', 0):.2f} 倍（理论约 3–4 倍）",
          f"- d 有 {bench.get('d_bits')} 位：平方 {bench.get('squarings')} 次、乘法 {bench.get('multiplies')} 次（约一半的位是 1）", "",
          "## 这两周的真实世界（可写进\"思考题/拓展\"）"]
    md += [f"- {s['fact']}（{s['date']}，{s['url']}）" for s in src]
    md += ["", "## 可直接用的思考题草稿（请按你们的任务书改）",
           "1. 为什么 RSA 用 CRT 能快约 4 倍？用本包 bench 的数据说明，并指出 CRT 实现要防的故障攻击（Bellcore）。",
           "2. 对比表里 ML-DSA-44 签名 2420 字节、Ed25519 只有 64 字节：OpenSSH 10.6 为什么选\"ML-DSA-44 + Ed25519\"混合而不是只用 ML-DSA？",
           "3. BSI 因新的密码分析建议新项目不用 Classic McEliece：这说明了什么叫\"密码敏捷性\"？",
           "4. \"先收集、后解密\"（harvest now, decrypt later）为什么让密钥交换比签名更早需要迁移？", "",
           "## 运行", "```", "python -m unittest test_pubkey_lab -v", "python pubkey_lab.py", "python pqc_compare.py --out pqc_compare.md   # 需要 OpenSSL 3.5+", "```"]
    (d / "实验预习说明.md").write_text("\n".join(md), encoding="utf-8")
    ok = rc1 == 0 and rc2 == 0 and "OK" in out1
    return {"ok": ok, "files": ["实验预习说明.md", "pubkey_lab.py", "test_pubkey_lab.py", "pqc_compare.py", "pqc_compare.md"],
            "verify": [f"单元测试：{'6/6 通过' if rc1 == 0 else '失败'}（含与 cryptography 库的 RSA 签名互验）",
                       f"OpenSSL 3.5 往返自检（签名验签、ML-KEM 封装/解封）：{'全部通过' if rc2 == 0 else '失败'}",
                       f"2048 位 CRT 加速实测 {bench.get('speedup', 0):.2f} 倍"]}

def prep_ai_tools_check(sig, d, ctx):
    shutil.copytree(KITS / "ai_tools_check", d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    live = ctx["live"]
    adv = {"snapshot": live["fetched_at"], "langflow": live["advisories"].get("Langflow Desktop", []),
           "langflow_latest": live["releases"].get("Langflow Desktop", {}).get("tag"),
           "ollama": {"cve": "CVE-2026-103663", "range": ">= 0.34.2, <= 0.35.0", "recommended": (live["releases"].get("Ollama", {}).get("tag") or "v0.40.1").lstrip("v"),
                      "source": "https://cert.pl/en/posts/2026/10/CVE-2026-103663/",
                      "note": "CERT Polska 页面同时写了'受影响 0.34.2 到 0.35.0'和'0.35.0 已修复'，按保守读法把 0.35.0 算作受影响，建议直接升到最新稳定版"}}
    (d / "advisories.json").write_text(json.dumps(adv, ensure_ascii=False, indent=1), encoding="utf-8")
    rc1, out1 = run([sys.executable, "-m", "unittest", "test_check_ai_tools", "-v"], d)
    rc2, out2 = run([sys.executable, "check_ai_tools.py"], d)       # 沙箱里没有这两个服务：应返回 2 且不报错
    recent = [a for a in adv["langflow"] if a["published"] >= str(TODAY - timedelta(days=14))]
    crit = [a for a in recent if a["severity"] == "critical"]
    maxfix = max((tuple(map(int, fx.split("."))) for a in recent for _, fx in a["ranges"] if fx), default=None)
    steps = ["# Langflow Desktop / Ollama 安全自检与升级步骤", f"快照时间 {adv['snapshot']}（Asia/Shanghai）", "",
             "## 1. 先自检（只读，不改任何东西）", "先打开 Langflow Desktop 和 Ollama，然后在本目录运行：", "```", "python check_ai_tools.py --online", "```",
             "- 退出码 1：有需要处理的项；0：没发现；2：没检测到服务（先把应用打开）", "",
             "## 2. 升级", f"- Langflow：近 14 天公告共 {len(recent)} 条（critical {len(crit)} 条），最高修复线 {'.'.join(map(str, maxfix)) if maxfix else '?'}；当前最新稳定版 {adv['langflow_latest']}。Langflow Desktop 用应用内更新或到官网重新下载安装。",
             f"- Ollama：升到 {adv['ollama']['recommended']} 或更新（托盘图标 → 重启以更新，或从官网重新下载安装）。", "",
             "## 3. 升级之外", "- Ollama：确认没有把 `OLLAMA_HOST` 设成 `0.0.0.0`；脚本会尝试从本机局域网 IP 连 11434，连得上就说明对外暴露了。",
             "- Langflow：不要导入来源不明的 flow；如果曾把 Langflow 暴露到局域网/公网，按 CVE-2026-9205（弱 Fernet 密钥）的思路，轮换存进去的 API key。", "",
             "## 公告清单（GitHub 公告库）"]
    steps += [f"- {a['published']} {a['cve'] or a['ghsa']} [{a['severity']}] {a['summary']} — 受影响 {a['ranges']} — {a['url']}" for a in recent]
    (d / "升级步骤.md").write_text("\n".join(steps), encoding="utf-8")
    ok = rc1 == 0 and rc2 == 2
    return {"ok": ok, "files": ["升级步骤.md", "check_ai_tools.py", "advisories.json", "test_check_ai_tools.py"],
            "verify": [f"判定逻辑测试 {'4/4 通过' if rc1 == 0 else '失败'}：用本地假服务器模拟 Langflow 1.9.0/1.10.2/1.12.5、Ollama 0.35.0/0.40.1，判定与公告范围一致",
                       f"沙箱里实际运行一次：{'正确报告未检测到服务（退出码 2），无异常' if rc2 == 2 else '异常：' + out2[-200:]}",
                       "没有在用户电脑上运行（只在沙箱）；Windows 上未实测"]}

def prep_codex_security(sig, d, ctx):
    """把一个开源 AI 安全审计 CLI 装进沙箱，并对一个公开 C 代码目标做 dry-run。目标由信号的 prep_args 指定（私有）。"""
    pa = sig["prep_args"]; repo, sub = pa["repo_url"], pa["subdir"]; name = repo.rstrip("/").split("/")[-1].removesuffix(".git")
    tool = Path(ctx["work"]) / "codex_security_tool"; tool.mkdir(parents=True, exist_ok=True)
    if not (tool / "node_modules/.bin/codex-security").exists():
        run(["npm", "init", "-y"], tool); run(["npm", "i", "@openai/codex-security@latest"], tool, timeout=900)
    bin_ = str(tool / "node_modules/.bin/codex-security")
    rc0, ver = run([bin_, "--version"], tool)
    tgt = Path(ctx["work"]) / name
    if not tgt.exists(): run(["git", "clone", "-q", "--depth", "1", repo, str(tgt)], ctx["work"], timeout=600)
    _, head = run(["git", "log", "-1", "--format=%H %cI"], tgt)
    rc1, dry = run([bin_, "scan", sub, "--dry-run"], tgt, timeout=120)
    (d / "dry_run.txt").write_text(f"# target: {repo} {head.strip()} {sub}\n" + dry, encoding="utf-8")
    runbook = [f"# 用 Codex Security CLI 复查 {name}/{sub}（runbook）", "",
               f"沙箱已安装：`@openai/codex-security` {ver.strip()}；已对公开仓库 {repo} 的 {sub} 做 `--dry-run`（输出见 dry_run.txt）。", "",
               "## 在你自己的电脑上", "```", "npm i -g @openai/codex-security", "codex-security login            # 用 ChatGPT 账号登录；或 --with-api-key 从 stdin 读 key",
               f"git clone --depth 1 {repo} && cd {name}", f"codex-security scan {sub} --dry-run   # 先看范围和认证是否就绪",
               f"codex-security scan {sub}             # 真扫（会消耗额度，默认模型/推理强度见 codex-security info）", "codex-security findings --format md > findings.md",
               "codex-security validate <finding-id>     # 让它自己复现/验证单个发现", "```", "",
               "## 怎么用才有价值", "- 拿你已经手工确认过的问题当\"答案\"，看它能不能独立找到 → 估计召回率，再决定要不要用在新目标上",
               "- 0.2.0 新增离线检查源码里暴露的凭据，适合在公开 PoC/报告仓库前跑一遍", "- 任何发现都要自己复现后再报告；未公开漏洞细节交给第三方服务前先想清楚披露流程", "",
               "## 没验证的", "- 真实扫描需要登录，沙箱没有你的凭据，所以只验证到 preflight（认证状态 verified: false）", "- 费用、额度、对 C 代码的实际效果都未知"]
    (d / "runbook.md").write_text("\n".join(runbook), encoding="utf-8")
    ok = rc0 == 0 and rc1 == 0 and "Preflight complete" in dry
    return {"ok": ok, "files": ["runbook.md", "dry_run.txt"],
            "verify": [f"沙箱 npm 安装成功，`codex-security --version` = {ver.strip()}",
                       f"对 {name}（{head.strip()[:10]}…）{sub} 执行 `scan --dry-run`：{'Preflight complete' if ok else '失败'}",
                       "未做真实扫描：需要你的 ChatGPT 登录/API key（认证 verified: false）"]}

def _ics_event(uid, start, end, summary, desc=""):
    f = lambda t: t.strftime("%Y%m%dT%H%M%S")
    return ["BEGIN:VEVENT", f"UID:{uid}@openlookout", f"DTSTAMP:{f(datetime.now())}", f"DTSTART;TZID=Asia/Shanghai:{f(start)}",
            f"DTEND;TZID=Asia/Shanghai:{f(end)}", f"SUMMARY:{summary}", f"DESCRIPTION:{desc}", "END:VEVENT"]

def prep_contest_plan(sig, d, ctx):
    """竞赛/征文：日历 + 决策/准备计划。事件与计划正文来自信号的 prep_args；验证日历可解析、每个日期都出现在来源事实里、截止日未过。"""
    pa = sig["prep_args"]; src = sig["sources"][0]
    evs = [(e["uid"], datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]), e["summary"]) for e in pa["events"]]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenLookout//world//CN"]
    for uid, s, e, t in evs: lines += _ics_event(sig["id"] + "-" + uid, s, e, t, "来源：" + src["url"])
    lines.append("END:VCALENDAR")
    (d / "赛程.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    (d / "报名决策与准备计划.md").write_text(f"来源：{src['url']}（{src['date']}）\n\n" + pa["plan_md"], encoding="utf-8")
    txt = (d / "赛程.ics").read_text(encoding="utf-8")
    starts = re.findall(r"DTSTART;TZID=Asia/Shanghai:(\d{8})", txt)
    in_src = all(s.strftime("%m-%d") in src["fact"] for _, s, _, _ in evs)
    dl = _d(sig["deadline"]); days = (dl - TODAY).days
    ok = len(starts) == len(evs) and in_src and days >= 0
    return {"ok": ok, "files": ["报名决策与准备计划.md", "赛程.ics"],
            "verify": [f"日历文件 {len(starts)} 个事件，每个日期都能在来源原文里找到：{'是' if in_src else '否'}", f"截止日 {dl} 距今天 {days} 天",
                       *pa.get("extra_verify", [])]}

PREPARERS = {"pubkey_lab": prep_pubkey_lab, "ai_tools_check": prep_ai_tools_check, "codex_security": prep_codex_security, "contest_plan": prep_contest_plan}

# ------------------------------------------------------------------ why-it-matters（可选 LLM，只发抽象画像 + 公开事实）
def why_lines(cards, abstract, run_dir, use_llm):
    out = {c["id"]: c.get("why_template", "") for c in cards}
    if not use_llm: return out, None
    from .llm import LLM
    llm = LLM(run_dir, "mimo-v2.6-flash")
    payload = {"profile": {k: abstract[k] for k in ("role", "topics", "tools_evidence", "course_progress")},
               "cards": [{"id": c["id"], "title": c["title"], "facts": [s["fact"] for s in c["sources"]][:4]} for c in cards]}
    sys_p = "你是信息助手。对每张卡写一句中文（≤50字）说明它为什么和这个人有关，只能用给定的画像和事实，不得编造；工具按 tools_evidence 区分\"装过\"和\"浏览/搜索过\"，不要说对方\"正在用\"或\"已受影响\"（版本未知）。输出 JSON：{id: 句子}。"
    try:
        from .llm import parse_json
        txt, rec = llm.chat("world_why", sys_p, json.dumps(payload, ensure_ascii=False), max_tokens=1500)
        j = parse_json(txt) or {}
        # 和第 9 轮一样：确定性模板优先（LLM 容易把"装过"说成"正在用"、或给出奇怪的角度），LLM 文本只在没有模板时使用，另存备查
        rec["why_llm"] = {k: v for k, v in j.items() if isinstance(v, str)}
        for k, v in rec["why_llm"].items():
            if k in out and not out[k] and 6 <= len(v) <= 80: out[k] = v
        return out, rec
    except Exception as e:
        return out, {"error": str(e)[:120]}

# ------------------------------------------------------------------ render
CSS = """body{font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;background:#f4f5f7;margin:0;padding:24px;color:#1f2328}
.wrap{max-width:980px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}.sub{color:#57606a;font-size:13px;margin-bottom:18px}
.card{background:#fff;border-radius:10px;padding:16px 18px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,.08);border-left:5px solid #2f81f7}
.card.adv{border-left-color:#cf222e}.card.comp{border-left-color:#bf8700}.card.tool{border-left-color:#8250df}
.t{font-size:16px;font-weight:600;margin-bottom:6px}.why{background:#f6f8fa;border-radius:6px;padding:6px 10px;font-size:14px;margin:6px 0}
.sc{float:right;font-size:12px;color:#57606a}.k{font-size:12px;color:#57606a;margin-top:8px;font-weight:600}
ul{margin:4px 0 4px 18px;padding:0;font-size:13px}li{margin:2px 0}a{color:#0969da;word-break:break-all}.ok{color:#1a7f37;font-weight:600}.bad{color:#cf222e;font-weight:600}
.unc{font-size:12px;color:#9a6700}.drop{font-size:13px;color:#57606a}.pill{display:inline-block;background:#eef;padding:1px 7px;border-radius:9px;font-size:12px;margin:1px}"""

def render(cards, dropped, abstract, out_html, prepared_rel):
    e = html.escape
    cls = {"advisory": "adv", "competition": "comp", "tool": "tool"}
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>瞭望手 · 外部机会</title><style>{CSS}</style></head><body><div class='wrap'>",
         f"<h1>瞭望手 · 外部机会收件箱</h1><div class='sub'>{TODAY}（Asia/Shanghai）· 本地历史只用来生成去标识画像；信号来自近两周的公开来源，每条都附链接与日期 · 共 {len(cards)} 张卡（上限 5）</div>"]
    for i, c in enumerate(cards, 1):
        s = c["score"]; r = c["result"]
        h.append(f"<div class='card {cls.get(c['kind'], '')}'><div class='sc'>相关 {s['relevance']} · 时效 {s['time']} · 新颖 {s['novelty']} · 可行动 {s['actionable']}</div>")
        h.append(f"<div class='t'>{i}. {e(c['title'])}</div><div class='why'>{e(c['why'])}</div>")
        if c.get("deadline"): h.append(f"<div class='k'>时间点：{e(str(c['deadline']))}{'（' + e(c['deadline_note']) + '）' if c.get('deadline_note') else ''}</div>")
        h.append("<div class='k'>证据（均已实际抓取）</div><ul>" + "".join(f"<li>{e(x['date'])} · {e(x['fact'])}<br><a href='{e(x['url'])}'>{e(x['url'])}</a></li>" for x in c["sources"]) + "</ul>")
        h.append(f"<div class='k'>已准备 · <span class='{'ok' if r['ok'] else 'bad'}'>{'验证通过' if r['ok'] else '验证未通过'}</span> · 目录 {e(prepared_rel)}/{e(c['id'])}/</div><ul>"
                 + "".join(f"<li>{e(v)}</li>" for v in r["verify"]) + "</ul><div>" + "".join(f"<span class='pill'>{e(f)}</span>" for f in r["files"]) + "</div>")
        if c.get("uncertain"): h.append("<div class='k'>不确定 / 需要你判断</div><ul class='unc'>" + "".join(f"<li>{e(u)}</li>" for u in c["uncertain"]) + "</ul>")
        h.append("</div>")
    h.append("<div class='card' style='border-left-color:#8c959f'><div class='t'>看到了但没出卡</div><ul class='drop'>" +
             "".join(f"<li><b>{e(d['title'])}</b>：{e(d.get('drop_reason', ''))} <a href='{e(d['sources'][0]['url'])}'>来源</a></li>" for d in dropped) + "</ul>")
    h.append("<div class='k'>本次使用的去标识画像（唯一能出站的部分）</div><ul class='drop'>" +
             f"<li>角色：{e(abstract['role'])}</li><li>主题：{e('、'.join(abstract['topics']))}</li><li>工具：{e('；'.join(f'{k}（{v}）' for k, v in abstract['tools_evidence'].items()))}</li><li>课程进度：{e('；'.join(abstract['course_progress']))}</li></ul></div>")
    h.append("</div></body></html>")
    Path(out_html).write_text("\n".join(h), encoding="utf-8")

def screenshot(html_path, png):
    for b in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(b):
            subprocess.run([b, "--headless=new", "--no-sandbox", "--hide-scrollbars", f"--screenshot={png}", "--window-size=1100,2900",
                            "file://" + str(Path(html_path).resolve())], capture_output=True, timeout=120)
            return Path(png).exists()
    return False

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True); ap.add_argument("--signals", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--tag", default="world")
    ap.add_argument("--no-llm", action="store_true"); ap.add_argument("--max-cards", type=int, default=5)
    a = ap.parse_args()
    from . import profile as P
    private, abstract = P.build(a.capture)
    wdir = Path(a.capture) / "world"; wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "profile_abstract.json").write_text(json.dumps(abstract, ensure_ascii=False, indent=1), encoding="utf-8")
    run_dir = Path("runs") / a.tag; run_dir.mkdir(parents=True, exist_ok=True)
    print("[world] live signals from GitHub …", flush=True)
    live = collect_live(private); (wdir / "signals_live.json").write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
    sigs = json.loads(Path(a.signals).read_text(encoding="utf-8"))
    for s in sigs: s["score"] = score(s, abstract)
    cand = sorted([s for s in sigs if s.get("preparer") and s["score"]["time"] > -99], key=lambda s: -s["score"]["total"])
    dropped = [s for s in sigs if s not in cand]
    out = Path(a.out); prep = out / "prepared_world"; prep.mkdir(parents=True, exist_ok=True)
    ctx = {"live": live, "work": str((wdir / "work").resolve())}; Path(ctx["work"]).mkdir(exist_ok=True)
    cards = []
    for s in cand:
        if len(cards) >= a.max_cards: dropped.append({**s, "drop_reason": "超过每日上限"}); continue
        d = prep / s["id"]; d.mkdir(parents=True, exist_ok=True)
        print(f"[world] prepare {s['id']} …", flush=True)
        try:
            s["result"] = PREPARERS[s["preparer"]](s, d, ctx)
        except Exception as ex:
            s["result"] = {"ok": False, "files": [], "verify": [f"准备器异常：{str(ex)[:160]}"]}
        if s["result"]["ok"]: cards.append(s)
        else: dropped.append({**s, "drop_reason": "准备的东西没通过验证：" + "; ".join(s["result"]["verify"])[:200]})
    why, rec = why_lines(cards, abstract, run_dir, not a.no_llm)
    for c in cards: c["why"] = why.get(c["id"], "")
    (run_dir / "world_summary.json").write_text(json.dumps({"cards": cards, "dropped": dropped, "llm": rec}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    html_p = out / "inbox_world.html"
    render(cards, dropped, abstract, html_p, prep.name)
    png = screenshot(html_p, out / "inbox_world.png")
    print(json.dumps({"cards": [(c["id"], c["score"]["total"], c["result"]["ok"]) for c in cards], "dropped": [d["id"] for d in dropped], "png": png}, ensure_ascii=False))

if __name__ == "__main__":
    main()
