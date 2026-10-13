"""活的情境模型：从行为流里算出“用户现在大概在做什么、进展如何、我怎么看”，并把所有外部意见当作证据而不是命令。

行为事件（behavior.jsonl）种类：work / outcome / abandon / alt / switch(应用来回切换) / action(精灵自己做的事) / opinion(用户或外部的看法)
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from .fork import _d, load_events, load_goals, WINDOW_DAYS

CLAIMS = {   # 简易中文解析：把一句话变成“主张”
    "going_well": ["很顺利", "进展顺利", "很有前景", "有前景", "没问题", "越来越好", "快成了", "稳了"],
    "stuck": ["卡住", "不顺", "没进展", "做不下去"],
    "not_important": ["不重要", "无所谓", "不用管"],
    "important": ["很重要", "最重要", "核心"],
}


def parse_claim(text: str):
    for c, ws in CLAIMS.items():
        if any(w in text for w in ws): return c
    return None


@dataclass
class Judgment:
    project: str
    verdict: str            # progressing | stalling | unclear
    confidence: float
    evidence: list
    fp: str                 # 证据指纹：证据没变，判断就不该变


def judge(events, now, project) -> Judgment:
    from .fork import _half
    w1, w2 = _half(events, now, project, "work"); o1, o2 = _half(events, now, project, "outcome", None)
    ab1, ab2 = _half(events, now, project, "abandon", None)
    ev = []
    total = w1 + w2
    if total < 300:
        return Judgment(project, "unclear", 0.2, ["投入还太少，看不出来"], "thin")
    first = min((_d(e['ts']) for e in events if e.get('project') == project and e['kind'] == 'work'), default=now)
    span = (now - first).days
    r1 = o1 / max(w1 / 60, 1); r2 = o2 / max(w2 / 60, 1)
    ev.append(f"后两周投入 {w2/60:.0f} 小时（前两周 {w1/60:.0f}）")
    ev.append(f"成果 前两周 {int(o1)} → 后两周 {int(o2)}")
    if ab1 + ab2: ev.append(f"放弃/重开 {int(ab1+ab2)} 次")
    conf_base = min(1.0, total / 1500)
    if span >= 7 and (o2 > o1 or (o2 >= 2 and r2 >= 0.7 * r1)):
        v, c = "progressing", 0.5 + 0.4 * conf_base
    elif span < 14:
        v, c = "unclear", 0.25
        ev.append("历史还不到两周")
    elif w2 >= 600 and (o2 == 0 or (o2 < o1 and r2 <= 0.5 * r1)):
        v, c = "stalling", 0.45 + 0.4 * conf_base + 0.05 * min(ab1 + ab2, 3)
    else:
        v, c = "unclear", 0.3
    return Judgment(project, v, round(min(c, 0.95), 2), ev, v)


@dataclass
class Situation:
    now: datetime
    focus: str | None
    in_flow: bool
    present: bool
    active_today_min: float
    switches_2h: int
    abandons_2d: int
    uncertainty: float
    judgments: dict
    goals: list
    opinions: list
    actions: list           # 精灵自己做过的事（事件）
    stalled: float = 0.0


def build(home: Path, now: datetime) -> Situation:
    ev = [e for e in load_events(Path(home) / "behavior.jsonl") if _d(e["ts"]) <= now]
    goals = load_goals(Path(home) / "goals.txt")
    work = [e for e in ev if e["kind"] == "work"]
    last_act = max((_d(e["ts"]) for e in ev if e["kind"] in ("work", "switch", "outcome", "abandon")), default=None)
    recent = [e for e in work if now - _d(e["ts"]) <= timedelta(hours=3)]
    mins = {}
    for e in recent: mins[e["project"]] = mins.get(e["project"], 0) + e.get("minutes", 10)
    focus = max(mins, key=mins.get) if mins else None
    today = sum(e.get("minutes", 10) for e in work if _d(e["ts"]).date() == now.date())
    sw = sum(1 for e in ev if e["kind"] == "switch" and now - _d(e["ts"]) <= timedelta(hours=2))
    ab2d = sum(1 for e in ev if e["kind"] == "abandon" and e.get("project") == focus and now - _d(e["ts"]) <= timedelta(days=2))
    # 不确定性：没有焦点 / 焦点和目标对不上 / 今天换了好几个项目
    projs_today = {e["project"] for e in work if _d(e["ts"]).date() == now.date()}
    kw = {w for g in goals for w in g}
    unc = 0.0
    if focus is None: unc += 0.5
    elif goals and not any(w in focus for w in kw): unc += 0.4
    unc += min(0.4, 0.15 * max(0, len(projs_today) - 1))
    if not goals: unc += 0.15
    judgments = {p: judge(ev, now, p) for p in sorted({e["project"] for e in ev if e.get("project") and e["kind"] != "opinion"})}
    stalled = min(1.0, 0.12 * sw + 0.3 * ab2d)
    return Situation(now, focus, last_act is not None and now - last_act <= timedelta(minutes=4),
                     last_act is not None and now - last_act <= timedelta(minutes=25), today, sw, ab2d,
                     min(unc, 1.0), judgments, goals, [e for e in ev if e["kind"] == "opinion"],
                     [e for e in ev if e["kind"] == "action"], stalled)
