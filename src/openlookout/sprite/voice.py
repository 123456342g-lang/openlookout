"""“嗓子”：把决策（话题、语气、证据）变成一句短话。优先用 MiMo（只发脱敏后的事实，项目名换成代号，密钥只在内存里）；
不可用/输出不合格时退回本地措辞（按上下文哈希挑选，不是固定模板，但仍是有限的措辞库）。"""
from __future__ import annotations
import hashlib, json, os, re, urllib.request
from pathlib import Path

ENV = Path(os.path.expanduser("~/.config/ai-butler/mimo.env"))
MODEL = "mimo-v2.6-flash"

SYSTEM = ("你是创业搭档型的桌面小精灵，和用户平等说话。只根据给定事实说一句中文，最多 60 字，不用客套话和表情，不要说“作为AI”。"
          "话题含义：report=告诉对方你刚做了什么；check_in=问问对方在忙什么，并表示愿意帮忙；offer_help=发现对方卡住了，提议帮忙；"
          "challenge=在岔路口提出有证据的质疑并给出一个问题；disagree=你不同意对方的看法：说出你的判断、置信度和关键证据，然后把决定留给对方；"
          "hold=对方重申了看法但证据没变：礼貌地说你仍这么看，并说什么新证据会让你改口；update=证据变了，承认之前判断需要修正。"
          "不要盲目附和，不要命令对方，不要编造事实里没有的数字。")


def _pick(seed: str, xs):
    return xs[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(xs)]


def local(topic: str, f: dict, project: str | None, seed: str) -> str:
    p = project or "手头这件事"
    if topic == "report":
        return _pick(seed, [f"刚才{f['what']}。", f"{f['what']}，已弄好。", f"顺手{f['what']}。"])
    if topic == "check_in":
        if f.get("focus"):
            return _pick(seed, [f"你这会儿主要在忙{p}吗？有要我搭手的随时说。", f"看你今天在{p}上花了 {f['today_min']/60:.1f} 小时，是在冲什么吗？"])
        return _pick(seed, ["今天在忙什么？有能帮上的我就接。", "这阵子在推进哪件事？我好知道往哪儿使劲。"])
    if topic == "offer_help":
        return _pick(seed, [f"{p}好像有点磕绊（来回切了 {f['switches']} 次、放弃过 {f['abandons']} 次），要我先整理一下吗？",
                            f"{p}这两小时一直在来回切，我可以先帮你把重复的步骤理出来。"])
    if topic == "challenge":
        ev = list(f["evidence"]); k = f.get("kind")
        alt = [e for e in ev if e.startswith("你自己试过")]; flat = [e for e in ev if e.startswith("成果")]; rise = [e for e in ev if e.startswith("投入")]
        cn = f["counter"].split("：", 1)[-1] if f.get("counter") else ""
        if k == "better_path" and alt:
            return _pick(seed, [f"{p}有件事我想问：{alt[0]}。{flat[0] if flat else ''}。要不要认真考虑那条路？",
                                f"回头看你自己的记录：{alt[0]}。{cn}但值得想想。"])
        if k == "sunk_cost":
            return _pick(seed, [f"说句直的：{p}{rise[0] if rise else ''}，{flat[0] if flat else ''}。是有新证据支撑继续，还是已经投进去了不想停？",
                                f"{p}我有点担心：{rise[0] if rise else ''}；{flat[0] if flat else ''}。你有没有想过设个检查点？"])
        return f"{p}：{'；'.join(ev[:2])}。你怎么看？"
    if topic == "disagree":
        j = {"stalling": "我看它其实在原地打转", "progressing": "我看它其实在往前走"}[f["verdict"]]
        return _pick(seed, [f"这点我和你看法不太一样：{p}{j}（把握约 {f['conf']:.0%}），依据是{f['evidence'][1]}。当然你定。",
                            f"我不太同意：{j.replace('我看它','数据上它')}，{f['evidence'][1]}，把握 {f['conf']:.0%}。决定在你。"])
    if topic == "hold":
        return f"我还是这么看（把握约 {f['conf']:.0%}）。如果接下来两周{p}出现新的成果，我会马上改口。"
    if topic == "update":
        return f"这次是你对：{p}后来有成果了（{f['evidence'][1]}），我之前的判断得修正。"
    return ""


def _llm(topic, facts, project, seed):
    env = {}
    for l in ENV.read_text("utf-8").splitlines():
        if "=" in l and not l.startswith("#"): k, v = l.split("=", 1); env[k.strip()] = v.strip().strip("\"'")
    code = "项目A"
    clean = json.loads(json.dumps(facts, ensure_ascii=False).replace(project, code)) if project else facts
    clean = {k: v for k, v in clean.items() if not k.startswith("_") and k != "id"}
    body = json.dumps({"model": MODEL, "temperature": 0.7, "max_tokens": 400,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": json.dumps(dict(topic=topic, project=code if project else None, facts=clean), ensure_ascii=False)}]}).encode()
    req = urllib.request.Request(env["MIMO_BASE_URL"].rstrip("/") + "/chat/completions", body,
                                 {"Authorization": "Bearer " + env["MIMO_API_KEY"], "Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=40).read())["choices"][0]["message"].get("content") or ""
    out = out.strip().replace(code, project or "")
    return out


def compose(topic, facts, project, seed, use_llm=False, stats=None):
    if use_llm and ENV.exists():
        try:
            t = _llm(topic, facts, project, seed)
            if 4 <= len(t) <= 110 and "\n" not in t.strip():
                if stats is not None: stats["llm"] = stats.get("llm", 0) + 1
                return t.strip()
        except Exception:
            pass
        if stats is not None: stats["fallback"] = stats.get("fallback", 0) + 1
    return local(topic, facts, project, seed)


def detail(topic: str, f: dict) -> str | None:
    """点“详情”后展开的长版本。"""
    if topic == "report" and f.get("detail"): return f["detail"]
    if topic in ("disagree", "challenge", "hold", "update") and f.get("evidence"): return "证据：" + "；".join(f["evidence"])
    return None
