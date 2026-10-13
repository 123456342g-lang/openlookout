"""统一的“要不要开口、说什么、什么语气”决策。汇报、关心、提议帮忙、挑战、不同意、改口，都是同一套打分的输出。

每个候选话题有 价值 v（对用户此刻有多大用处）；开口要付 代价 cost（打断心流、静默时段、刚说过话）；
关系预算 budget（0..1）：用户接话上升，被忽略/关掉就下降，随时间缓慢恢复。净收益 = v*(0.5+0.5*budget) - cost，超过门槛才开口。
所有候选的分数和理由都写进 decisions.jsonl。
"""
from __future__ import annotations
import json, math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from . import fork as F
from .situation import Situation, build, _d

THRESH = 0.3


@dataclass
class Cand:
    topic: str
    v: float
    why: str
    project: str | None = None
    facts: dict = field(default_factory=dict)
    options: list = field(default_factory=list)


@dataclass
class Decision:
    speak: bool
    cand: Cand | None
    net: float
    cost: float
    budget: float
    rationale: str
    all: list


class Brain:
    def __init__(self, home: Path, quiet=("23:00", "08:00")):
        self.home = Path(home); self.home.mkdir(parents=True, exist_ok=True)
        self.quiet = quiet
        f = self.home / "brain_state.json"
        self.f = f
        self.st = json.loads(f.read_text("utf-8")) if f.exists() else {
            "budget": 0.8, "t_budget": None, "last_say": None, "last_contact": None, "reported": [],
            "stated": {}, "last_challenge": None, "snooze": {}, "open": None}
        self.log = self.home / "decisions.jsonl"

    def save(self): self.f.write_text(json.dumps(self.st, ensure_ascii=False), "utf-8")

    # ---- 预算
    def _recover(self, now):
        t = self.st["t_budget"]
        if t:
            h = max(0, (now - _d(t)).total_seconds() / 3600)
            self.st["budget"] = min(1.0, self.st["budget"] + 0.002 * h)
        self.st["t_budget"] = now.isoformat(timespec="seconds")

    def feedback(self, kind: str, now: datetime, key=None, choice=None):
        self._recover(now)
        b = self.st["budget"]
        if kind == "engage": b += 0.2; self.st["last_contact"] = now.isoformat(timespec="seconds")
        elif kind == "dismiss": b -= 0.3
        elif kind == "ignore": b -= 0.12
        self.st["budget"] = max(0.0, min(1.0, b))
        if key:
            days = 10 if kind == "dismiss" else (14 if choice == 0 else 7)
            self.st["snooze"][key] = (now + timedelta(days=days)).isoformat(timespec="seconds")
        self.st["open"] = None; self.save()

    # ---- 候选
    def candidates(self, S: Situation) -> list:
        now = S.now; out = []
        # 1) 汇报自己做过的事：越近、越和当前焦点相关，越值得说
        for a in S.actions:
            if a.get("id") in self.st["reported"]: continue
            age_h = (now - _d(a["ts"])).total_seconds() / 3600
            rel = 1.0 if (S.focus and a.get("project") == S.focus) else 0.5
            v = (0.95 * math.exp(-age_h / 3)) if a.get("urgent") else 0.75 * rel * math.exp(-age_h / 10)
            out.append(Cand("report", v, f"做过的事 {age_h:.1f}h 前，与焦点相关度 {rel}", a.get("project"),
                            dict(what=a["what"], detail=a.get("detail"), age_h=round(age_h, 1), id=a.get("id"))))
        # 2) 关心：我不确定你在做什么 + 很久没交流
        last = max([x for x in (self.st["last_contact"], self.st["last_say"]) if x], default=None)
        hrs = 99 if not last else (now - _d(last)).total_seconds() / 3600
        v = 0.95 * S.uncertainty * (1 - math.exp(-hrs / 40))
        out.append(Cand("check_in", v, f"不确定度 {S.uncertainty:.2f}，距上次交流 {min(hrs,99):.0f}h", S.focus,
                        dict(focus=S.focus, today_min=S.active_today_min, goals=[g[0] for g in S.goals][:2])))
        # 3) 卡住了就提议帮忙
        if S.focus and S.stalled > 0.3:
            out.append(Cand("offer_help", 0.85 * S.stalled, f"来回切换 {S.switches_2h} 次、近两天放弃 {S.abandons_2d} 次", S.focus,
                            dict(focus=S.focus, switches=S.switches_2h, abandons=S.abandons_2d),
                            ["帮我整理一下", "我自己来"]))
        # 4) 自己的判断 vs 用户/外部意见
        for p, j in S.judgments.items():
            ops = [o for o in S.opinions if o.get("project") == p]
            if not ops: continue
            mine = j.verdict
            stated = self.st["stated"].get(p)          # {"fp","verdict","n_ops"}
            for o in ops[-1:]:
                claim = o["claim"]; src = o.get("source", "user")
                conflict = (claim == "going_well" and mine == "stalling") or (claim == "stuck" and mine == "progressing") \
                    or (claim == "not_important" and mine == "progressing" and p == S.focus)
                if conflict:
                    w = 1.0 if src == "user" else 0.8           # 外部意见同样只是证据
                    adj = max(0.0, j.confidence - 0.05)        # 对方有不同看法，自己略谨慎，但不据此改判断
                    if stated is None or stated["fp"] != j.fp:
                        out.append(Cand("disagree", 0.45 + 0.5 * adj * w, f"{src} 说 {claim}，我的判断 {mine}（置信 {j.confidence}），证据已变/首次表态", p,
                                        dict(claim=claim, source=src, verdict=mine, conf=j.confidence, evidence=j.evidence),
                                        ["我再想想", "我有你不知道的信息", "维持现状"]))
                    elif stated["n_ops"] < len(ops) and stated.get("repeat", 0) < 1:
                        out.append(Cand("hold", 0.45, "用户重申观点但证据没变：只再表态一次，说明什么会改变我的看法", p,
                                        dict(claim=claim, verdict=mine, conf=j.confidence, evidence=j.evidence)))
                elif stated and stated["verdict"] != mine and ((claim == "going_well" and mine == "progressing") or (claim == "stuck" and mine == "stalling")):
                    out.append(Cand("update", 0.85, f"我之前不同意，现在证据变了：{stated['verdict']} → {mine}", p,
                                    dict(claim=claim, verdict=mine, conf=j.confidence, evidence=j.evidence, before=stated["verdict"])))
        # 5) 岔路口挑战（没有针对同一项目的不同意时才出）
        disagreed = {c.project for c in out if c.topic in ("disagree", "hold")}
        ev = F.load_events(self.home / "behavior.jsonl")
        lc = self.st["last_challenge"]
        gap_d = 99 if not lc else (now - _d(lc)).total_seconds() / 86400
        for fk in F.analyse([e for e in ev if e["kind"] != "opinion" and _d(e["ts"]) <= now], now, S.goals):
            if fk.project in disagreed: continue
            until = self.st["snooze"].get(fk.key)
            if until and now < _d(until): continue
            out.append(Cand("challenge", (0.45 + 0.12 * len(fk.evidence)) * (1 - math.exp(-gap_d / 3)),
                            f"{fk.kind}：{len(fk.evidence)} 个信号，距上次挑战 {gap_d:.0f} 天", fk.project,
                            dict(kind=fk.kind, evidence=fk.evidence, counter=fk.counter, key=fk.key), fk.options))
        return out

    # ---- 决策
    def _in_quiet(self, now):
        a, b = [int(x[:2]) * 60 + int(x[3:]) for x in self.quiet]; t = now.hour * 60 + now.minute
        if a == b: return False
        return (a <= t < b) if a < b else (t >= a or t < b)

    def decide(self, now: datetime, S: Situation | None = None) -> Decision:
        self._recover(now)
        S = S or build(self.home, now)
        cands = self.candidates(S)
        cost = 0.0; why = []
        if not S.present: cost += 1.0; why.append("你不在电脑前")
        if S.in_flow: cost += 0.5; why.append("你正在心流中")
        if self._in_quiet(now): cost += 1.0; why.append("静默时段")
        if self.st["open"]: cost += 1.0; why.append("上一句还没得到回应")
        if self.st["last_say"]:
            gap = (now - _d(self.st["last_say"])).total_seconds() / 60
            c = max(0.0, 1 - gap / 90) ; cost += c
            if c > 0.05: why.append(f"刚说过话（{gap:.0f} 分钟前）")
        bf = 0.5 + 0.5 * self.st["budget"]
        best = None
        for c in cands:
            net = c.v * bf - cost
            c.facts["_net"] = round(net, 2)
            if best is None or net > best[0]: best = (net, c)
        speak = bool(best and best[0] > THRESH)
        r = (f"最佳 {best[1].topic} v={best[1].v:.2f} 预算={self.st['budget']:.2f} 代价={cost:.2f}（{'、'.join(why) or '无'}）→ 净={best[0]:.2f} "
             f"{'>' if speak else '≤'} {THRESH}") if best else "没有候选"
        d = Decision(speak, best[1] if speak else None, best[0] if best else 0, cost, self.st["budget"], r,
                     [(c.topic, round(c.v, 2), c.why) for c in cands])
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=now.isoformat(timespec="seconds"), speak=speak, topic=d.cand.topic if d.cand else None,
                                    net=round(d.net, 2), cost=round(cost, 2), budget=round(self.st["budget"], 2),
                                    rationale=r, cands=d.all), ensure_ascii=False) + "\n")
        return d

    def mark_spoken(self, d: Decision, now: datetime, text: str):
        c = d.cand; ts = now.isoformat(timespec="seconds")
        self.st["last_say"] = ts; self.st["open"] = {"topic": c.topic, "project": c.project, "ts": ts}
        self.st["budget"] = max(0.0, self.st["budget"] - 0.12)
        if c.topic == "report" and c.facts.get("id"): self.st["reported"].append(c.facts["id"])
        if c.topic == "challenge": self.st["last_challenge"] = ts; self.st["open"]["key"] = c.facts["key"]
        if c.topic in ("disagree", "hold", "update"):
            j = build(self.home, now).judgments.get(c.project)
            n = len([o for o in build(self.home, now).opinions if o.get("project") == c.project])
            prev = self.st["stated"].get(c.project) or {}
            self.st["stated"][c.project] = dict(fp=j.fp, verdict=j.verdict, n_ops=n,
                                                repeat=(prev.get("repeat", 0) + 1) if c.topic == "hold" else 0)
            with (self.home / "judgments.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(dict(ts=ts, project=c.project, topic=c.topic, user_claim=c.facts.get("claim"),
                                        my_verdict=j.verdict, confidence=j.confidence, evidence=j.evidence,
                                        agrees=(c.topic == "update"), text=text), ensure_ascii=False) + "\n")
        self.save()
