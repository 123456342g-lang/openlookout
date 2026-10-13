"""分层成本架构：
 tier0 纯本地代码/统计，随时开着，几乎零 token，由状态变化触发（本项目绝大多数判断都在这一层）；
 tier1 可选的本地小模型（如 Ollama），用来分类/润色，不花云端 token（只记本地用量）；
 tier2 云端大模型：只在“新颖且有价值”的情形用，并把结论蒸馏成可缓存的规则（以后同类问题 0 token）。
有每日 token/美元硬预算，超了就优雅降级到 tier0/1；每次调用都记账，可出报表。
安全：模型给的分类只能把“不认识(high)”升到“问(ask)”，永远不能直接升到“自动做(safe)”；要变成 safe 只能靠你多次点同意（见 promote）。"""
from __future__ import annotations
import json, os, re, time, urllib.request
from datetime import datetime
from pathlib import Path

PRICE = dict(in_per_m=0.10, out_per_m=0.40)        # 假设价（美元/百万 token），可在 config 里改；本地模型按 0 计


class Meter:
    def __init__(self, path: Path, clock=time.time): self.f = Path(path); self.clock = clock
    def record(self, tier: int, purpose: str, tin: int = 0, tout: int = 0, cached=False, decision=None, usd=None):
        usd = (0.0 if tier < 2 else (tin * PRICE["in_per_m"] + tout * PRICE["out_per_m"]) / 1e6) if usd is None else usd
        e = dict(ts=self.clock(), day=datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d"), tier=tier, purpose=purpose, tin=tin, tout=tout, usd=usd, cached=cached, decision=decision)
        with self.f.open("a", encoding="utf-8") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e
    def rows(self): return [json.loads(l) for l in self.f.read_text("utf-8").splitlines() if l.strip()] if self.f.exists() else []
    def today(self):
        d = datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d"); r = [x for x in self.rows() if x["day"] == d and x["tier"] == 2]
        return dict(tokens=sum(x["tin"] + x["tout"] for x in r), usd=sum(x["usd"] for x in r))
    def report(self):
        days = {}
        for x in self.rows():
            d = days.setdefault(x["day"], dict(tier0=0, tier1=0, tier2=0, tokens2=0, usd=0.0, cache_hits=0))
            d["tier%d" % x["tier"]] += 1; d["tokens2"] += (x["tin"] + x["tout"]) if x["tier"] == 2 else 0; d["usd"] += x["usd"]; d["cache_hits"] += 1 if x["cached"] else 0
        return days


class Budget:
    def __init__(self, meter: Meter, daily_tokens=20000, daily_usd=0.05): self.m, self.tok, self.usd = meter, daily_tokens, daily_usd
    def allow(self, est_tokens: int) -> bool:
        t = self.m.today(); return t["tokens"] + est_tokens <= self.tok and t["usd"] + est_tokens * PRICE["out_per_m"] / 1e6 <= self.usd


class DistilledRules:
    """LLM 结论蒸馏出的规则缓存：签名 -> 判定。以后同类直接命中，0 token。"""
    def __init__(self, path: Path): self.f = Path(path); self.d = json.loads(self.f.read_text("utf-8")) if self.f.exists() else {}
    def _save(self): self.f.write_text(json.dumps(self.d, ensure_ascii=False), "utf-8")
    def get(self, sig): 
        r = self.d.get(sig)
        if r: r["hits"] = r.get("hits", 0) + 1; self._save()
        return r
    def put(self, sig, verdict, reason, source): self.d[sig] = dict(verdict=verdict, reason=reason, source=source, hits=0, approvals=0, ts=time.time()); self._save()
    def approve(self, sig):
        r = self.d.get(sig)
        if r: r["approvals"] += 1; self._save()
    def promoted(self, sig, need=3): r = self.d.get(sig); return bool(r and r["approvals"] >= need and r["verdict"] == "ask")      # 用户同意够多次才可当作 safe 的候选


SYSTEM_CLASSIFY = ("你是电脑清理助手的分类器。给你一类文件/进程的抽象签名与脱敏上下文，只回答 JSON：{\"verdict\":\"ask\"|\"high\",\"reason\":\"<=20字\"}。"
                   "ask=可能是可再生的缓存/临时产物，值得问用户；high=可能是用户的东西或不确定。拿不准就 high。不要输出别的。")


def sig_of(path: Path, size: int) -> str:
    """抽象签名：扩展名 + 上级目录名模式 + 文件名模式 + 大小量级（不含用户名/具体路径）。"""
    name = re.sub(r"[0-9a-f]{6,}", "<hex>", re.sub(r"\d+", "<n>", path.stem.lower()))
    par = re.sub(r"\d+", "<n>", path.parent.name.lower())
    return f"{path.suffix.lower()}|{par}|{name}|1e{len(str(max(size, 1)))}"


class Router:
    def __init__(self, home: Path, clock=time.time, local_model=None, cloud=None, daily_tokens=20000, daily_usd=0.05, min_value_s=120.0):
        self.home = Path(home); self.clock = clock
        self.meter = Meter(self.home / "tokens.jsonl", clock); self.budget = Budget(self.meter, daily_tokens, daily_usd)
        self.rules = DistilledRules(self.home / "distilled_rules.json"); self.local, self.cloud, self.min_value_s = local_model, cloud, min_value_s

    def classify_unknown(self, sig: str, context: str, value_s: float) -> tuple[str, str]:
        r = self.rules.get(sig)
        if r: self.meter.record(0, "classify_cache", cached=True, decision=sig); return r["verdict"], r["reason"] + "（已学会的规则）"
        if value_s < self.min_value_s:
            self.meter.record(0, "classify_skip_lowvalue", decision=sig); return "high", "价值不够，不值得问模型，保守不动"
        for tier, fn in ((1, self.local), (2, self.cloud)):
            if fn is None: continue
            est = 600
            if tier == 2 and not self.budget.allow(est):
                self.meter.record(0, "classify_degraded_budget", decision=sig); return "high", "今天云端预算用完，降级为保守"
            try: text, tin, tout = fn(SYSTEM_CLASSIFY, f"签名：{sig}\\n上下文：{context}")
            except Exception: continue
            self.meter.record(tier, "classify_novel", tin, tout, decision=sig)
            try: j = json.loads(re.search(r"\{.*\}", text, re.S).group(0)); v = j.get("verdict"); why = str(j.get("reason", ""))[:30]
            except Exception: v, why = "high", "解析失败"
            v = v if v in ("ask", "high") else "high"                 # 模型永远不能给出 safe
            self.rules.put(sig, v, why, f"tier{tier}"); return v, why
        self.meter.record(0, "classify_no_model", decision=sig); return "high", "没有可用模型，保守不动"

    def phrase(self, topic: str, facts: dict, project, seed: str, value_s: float, local_compose, llm_compose=None):
        """话术：高价值话题且预算够才用云端；否则本地措辞（tier0）。"""
        if llm_compose and topic in ("challenge", "disagree", "update", "hold") and value_s >= self.min_value_s and self.budget.allow(600):
            try:
                text, tin, tout = llm_compose(topic, facts, project, seed)
                self.meter.record(2, "phrase_" + topic, tin, tout); return text
            except Exception: pass
        elif llm_compose and topic in ("challenge", "disagree", "update", "hold"): self.meter.record(0, "phrase_degraded", decision=topic)
        self.meter.record(0, "phrase_local", decision=topic); return local_compose(topic, facts, project, seed)


def mimo_cloud(model="mimo-v2.6-flash"):
    """真实云端调用（MiMo，密钥只读 ~/.config/ai-butler/mimo.env，不打印）；返回 (text, tokens_in, tokens_out)。"""
    env = {}
    for l in Path(os.path.expanduser("~/.config/ai-butler/mimo.env")).read_text("utf-8").splitlines():
        if "=" in l and not l.startswith("#"): k, v = l.split("=", 1); env[k.strip()] = v.strip().strip("\"'")
    def call(system, user):
        body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": 300, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(env["MIMO_BASE_URL"].rstrip("/") + "/chat/completions", body, {"Authorization": "Bearer " + env["MIMO_API_KEY"], "Content-Type": "application/json"})
        j = json.loads(urllib.request.urlopen(req, timeout=60).read()); u = j.get("usage", {})
        return (j["choices"][0]["message"].get("content") or ""), u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    return call
