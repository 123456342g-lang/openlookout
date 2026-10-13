"""岔路口检测器：只在真正需要用户重新想一想的时候才开口。

输入（behavior.jsonl，每行一个事件，本地）:
  {"ts": ISO, "project": "名字", "kind": "work", "minutes": 45}          投入
  {"ts": ..., "project": "名字", "kind": "outcome", "what": "..."}        成果证据（发布/跑通/用户反馈/交付…）
  {"ts": ..., "project": "名字", "kind": "abandon"}                       放弃的尝试（弃坑/回滚/重开）
  {"ts": ..., "project": "名字", "kind": "alt", "alt": "另一条路", "minutes": 40, "outcomes": 3}
                                                                          在自己的历史里出现过的、更便宜的路径（投入分钟 + 产出）
目标文件 goals.txt：每行一个目标，用空格/逗号分隔关键词，项目名含任一关键词即视为与目标相关。

信号（都带数字）：投入上升、成果持平/下降、反复放弃、更便宜的路径、偏离目标、沉没成本。
规则：至少 2 个独立信号才开口；每 cooldown_days 天最多 1 次；用户选“继续”后，同一岔路 14 天内不再提。
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

WINDOW_DAYS = 28


@dataclass
class Fork:
    key: str
    project: str
    kind: str                 # sunk_cost | better_path | drift
    text: str                 # 自然语言：判断 + 证据 + 问题
    evidence: list = field(default_factory=list)
    counter: str = ""
    options: list = field(default_factory=list)   # 2~3 个选项


def _d(ts: str) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=None)


def load_events(path: Path) -> list:
    if not Path(path).exists(): return []
    return [json.loads(l) for l in Path(path).read_text("utf-8").splitlines() if l.strip()]


def load_goals(path: Path) -> list:
    if not Path(path).exists(): return []
    return [[w for w in re.split(r"[\s,，、;；]+", l.strip()) if w] for l in Path(path).read_text("utf-8").splitlines() if l.strip() and not l.startswith("#")]


def _half(events, now, project, kind, field_="minutes"):
    """返回 (前半窗口, 后半窗口) 的合计（minutes 或计数）。"""
    a = now - timedelta(days=WINDOW_DAYS); mid = now - timedelta(days=WINDOW_DAYS // 2)
    first = second = 0.0
    for e in events:
        if e.get("project") != project or e["kind"] != kind: continue
        t = _d(e["ts"])
        if t < a or t > now: continue
        v = e.get(field_, 1) if field_ else 1
        if t < mid: first += v
        else: second += v
    return first, second


def analyse(events, now: datetime, goals) -> list:
    """对每个项目算信号，返回候选 Fork（未做冷却/去重）。"""
    projects = sorted({e["project"] for e in events if e.get("project")})
    out = []
    mine = {}
    for p in projects:
        w1, w2 = _half(events, now, p, "work")
        o1, o2 = _half(events, now, p, "outcome", None)
        ab1, ab2 = _half(events, now, p, "abandon", None)
        mine[p] = dict(w1=w1, w2=w2, o1=o1, o2=o2, ab=ab1 + ab2)
    for p, s in mine.items():
        total = s["w1"] + s["w2"]
        if total < 600: continue                                   # 投入太少，不值得打扰
        sig = []
        if s["w2"] >= 1.3 * max(s["w1"], 1):
            sig.append(("rising", f"投入在涨：前两周 {s['w1']/60:.0f} 小时 → 后两周 {s['w2']/60:.0f} 小时"))
        if s["o2"] <= s["o1"] and s["o1"] + s["o2"] <= 2:
            sig.append(("flat", f"成果证据没跟上：前两周 {int(s['o1'])} 个、后两周 {int(s['o2'])} 个"))
        if s["ab"] >= 3:
            sig.append(("abandon", f"这个方向已经放弃/重开 {int(s['ab'])} 次"))
        # 更便宜的路径
        alts = [e for e in events if e.get("project") == p and e["kind"] == "alt" and now - timedelta(days=WINDOW_DAYS) <= _d(e["ts"]) <= now]
        best = None
        if alts and total > 0:
            my_rate = (s["o1"] + s["o2"]) / (total / 60)            # 成果/小时
            for a in alts:
                if a.get("minutes", 0) <= 0: continue
                r = a.get("outcomes", 0) / (a["minutes"] / 60)
                if r >= max(3 * my_rate, 0.5) and (best is None or r > best[0]): best = (r, a, my_rate)
        if best:
            r, a, mr = best
            sig.append(("alt", f"你自己试过的「{a['alt']}」：{a['minutes']} 分钟出了 {a.get('outcomes',0)} 个成果（{r:.1f}/小时），"
                               f"而这条路是 {mr:.2f}/小时"))
        # 偏离目标
        if goals:
            kw = {w for g in goals for w in g}
            if not any(w and w in p for w in kw):
                sig.append(("drift", f"目标文件里的关键词（{'、'.join(sorted(kw))[:30]}）和这个项目对不上，它占了你近四周 {total/60:.0f} 小时"))
        kinds = {k for k, _ in sig}
        ev = [t for _, t in sig]
        if {"rising", "flat"} <= kinds and ("abandon" in kinds or "alt" in kinds or "drift" in kinds) and "alt" not in kinds:
            out.append(Fork(f"sunk:{p}", p, "sunk_cost",
                f"我得先说一句不太好听的：「{p}」你已经投了 {total/60:.0f} 小时，而且还在加码，可成果没怎么长。{ev[0]}；{ev[1]}；{ev[2]}。"
                f"继续投的理由是已经投了这么多，还是接下来真有新证据？",
                ev, "反方观点：这类东西常常要熬到某个点才有回报，现在的平台期不一定说明方向错。",
                ["再给它 2 周，设个检查点", "砍到最小版本", "先放下"]))
        elif "alt" in kinds and "flat" in kinds:
            out.append(Fork(f"better:{p}", p, "better_path",
                f"我注意到一件事：{ev[-1] if sig[-1][0]=='alt' else [t for k,t in sig if k=='alt'][0]}。"
                f"{[t for k,t in sig if k=='flat'][0]}。有没有可能那条更省力的路才是你真正该走的？",
                ev, "反方观点：那条路的样本只有一次，可能是运气，也可能和你要的目标不是一回事。",
                ["再认真试一轮那条路", "两条并行但设上限", "继续原来的"]))
        elif "drift" in kinds and "rising" in kinds:
            d = [t for k, t in sig if k == "drift"][0]
            out.append(Fork(f"drift:{p}", p, "drift",
                f"你写下的目标和最近的时间对不上：{d}；而且投入还在涨（{[t for k,t in sig if k=='rising'][0]}）。这是有意的转向，还是被带偏了？",
                ev, "反方观点：目标文件可能已经过时，真正的重心也许就是现在这个。",
                ["更新目标，认可转向", "拉回原目标", "先不管"]))
    return out


class ForkDetector:
    def __init__(self, home: Path, cooldown_days: int = 4, snooze_days: int = 14):
        self.home, self.cd, self.snooze = Path(home), cooldown_days, snooze_days
        self.f = self.home / "fork_state.json"
        self.st = json.loads(self.f.read_text("utf-8")) if self.f.exists() else {"last": None, "keys": {}}

    def _save(self): self.f.write_text(json.dumps(self.st, ensure_ascii=False), "utf-8")

    def check(self, now: datetime):
        """返回至多一个 Fork，或 None。"""
        if self.st["last"] and now - _d(self.st["last"]) < timedelta(days=self.cd): return None
        events = load_events(self.home / "behavior.jsonl")
        cands = analyse(events, now, load_goals(self.home / "goals.txt"))
        for c in cands:
            until = self.st["keys"].get(c.key)
            if until and now < _d(until): continue
            self.st["last"] = now.isoformat(timespec="seconds"); self._save()
            return c
        return None

    def answer(self, fork_key: str, choice_idx: int, now: datetime):
        """用户点了某个选项；第 0 项视作“继续/认可”，该岔路 snooze 期内不再提。其余选项也静音一周，避免追问。"""
        days = self.snooze if choice_idx == 0 else 7
        self.st["keys"][fork_key] = (now + timedelta(days=days)).isoformat(timespec="seconds"); self._save()
