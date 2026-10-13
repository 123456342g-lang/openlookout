"""多日模拟：脚本化的用户历史 -> 精灵每 30 分钟“看一眼”情境并决定说不说。输出对话记录和决策理由。
python -m sprite.sim [--llm] [--out DIR]"""
from __future__ import annotations
import argparse, json, shutil, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from .decide import Brain
from .situation import build
from . import voice

T0 = datetime(2026, 8, 1, 0, 0)


def iso(t): return t.isoformat(timespec="seconds")


class Script:
    def __init__(self): self.ev = []
    def day(self, d, proj, minutes, outcomes=0, abandons=0, switches=0, start=9, end=17):
        slots = max(1, minutes // 10); t = T0 + timedelta(days=d, hours=start)
        step = max(10, int((end - start) * 60 / slots))
        for i in range(slots):
            self.ev.append(dict(ts=iso(t + timedelta(minutes=i * step)), project=proj, kind="work", minutes=10))
        for k in range(outcomes): self.ev.append(dict(ts=iso(t + timedelta(hours=3 + k)), project=proj, kind="outcome", what="交付"))
        for k in range(abandons): self.ev.append(dict(ts=iso(t + timedelta(hours=4 + k)), project=proj, kind="abandon"))
        for k in range(switches): self.ev.append(dict(ts=iso(t + timedelta(hours=6, minutes=5 * k)), project=proj, kind="switch"))
    def say(self, d, hour, proj, text, source="user"):
        from .situation import parse_claim
        self.ev.append(dict(ts=iso(T0 + timedelta(days=d, hours=hour)), project=proj, kind="opinion", claim=parse_claim(text), source=source, text=text))
    def alt(self, d, proj, alt, minutes, outcomes):
        self.ev.append(dict(ts=iso(T0 + timedelta(days=d, hours=15)), project=proj, kind="alt", alt=alt, minutes=minutes, outcomes=outcomes))
    def action(self, d, hour, proj, what, i):
        self.ev.append(dict(ts=iso(T0 + timedelta(days=d, hours=hour)), project=proj, kind="action", what=what, id=f"a{i}"))


def sc_sunk():
    s = Script(); P = "语音助手"
    for d in range(0, 14): s.day(d, P, 60, outcomes=1 if d in (3, 8) else 0)
    for d in range(14, 36): s.day(d, P, 130, abandons=1 if d in (18, 24, 30) else 0)
    s.say(21, 12, P, "语音助手 很有前景，我觉得没问题")
    s.say(28, 12, P, "我还是觉得语音助手 很有前景")           # 重申，证据没变
    for d in (36, 37, 38, 39): s.day(d, P, 130, outcomes=2)     # 新证据
    s.say(39, 20, P, "你看，语音助手 进展顺利")
    return s, 42, "user_optimistic_but_stalling→new_evidence"


def sc_better():
    s = Script(); P = "实验报告"
    for d in range(0, 30): s.day(d, P, 120 if d > 10 else 70)
    s.alt(12, P, "直接脚本生成", 40, 3)
    return s, 32, "better_path_seen"


def sc_control_productive():
    s = Script(); P = "论文写作"
    for d in range(0, 34): s.day(d, P, 100, outcomes=1 if d % 4 == 0 else 0)
    s.say(20, 12, P, "论文写作 进展顺利")
    return s, 34, "control:productive+user_agrees"


def sc_control_scattered():
    s = Script()
    import random; r = random.Random(3)
    for d in range(0, 34):
        for p in r.sample(["杂事", "邮件", "资料", "课程"], 2): s.day(d, p, r.choice([20, 30, 40]), outcomes=r.choice([0, 0, 1]))
    return s, 34, "control:scattered_low_effort"


def sc_outside_conflict():
    s = Script(); P = "产品原型"
    for d in range(0, 34): s.day(d, P, 90, outcomes=1 if d % 3 == 0 else 0)
    s.say(25, 12, P, "（导师）产品原型 不重要，别做了", source="outside")
    return s, 34, "outside_opinion_conflicts_with_progress"


def sc_helper():
    s = Script(); P = "lab"
    for d in range(0, 20): s.day(d, P, 90, outcomes=1 if d % 5 == 0 else 0)
    s.action(15, 10, P, "给 lab7 建好了子文件夹和说明", 1)
    s.action(17, 11, "下载", "把 3 个重复下载移进了 _dupes（没删）", 2)
    return s, 20, "helper_actions_reported_in_context"


def sc_dismiss():
    s, n, _ = sc_sunk(); return s, n, "user_dismisses_everything"


def react(name, d, now):
    t = d.cand.topic
    if name.startswith("user_dismisses"): return "dismiss", None
    if t in ("disagree", "challenge"): return "engage", 1 if t == "disagree" else 0
    return ("engage", None) if hash(iso(now)) % 2 == 0 else ("ignore", None)


def run(make, use_llm, outdir, seed_name):
    s, ndays, name = make()
    home = Path(tempfile.mkdtemp(prefix="sprite_sim_"))
    (home / "behavior.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in sorted(s.ev, key=lambda e: e["ts"])) + "\n", "utf-8")
    (home / "goals.txt").write_text("论文 实验 产品 lab\n", "utf-8") if "control" in name or "lab" in seed_name else None
    brain = Brain(home); say = []; st = {}
    import hashlib
    for day in range(ndays):
        for h2 in range(16, 46):                    # 08:00 - 22:30
            now = T0 + timedelta(days=day, minutes=h2 * 30)
            d = brain.decide(now)
            if not d.speak: continue
            c = d.cand
            text = voice.compose(c.topic, c.facts, c.project, iso(now), use_llm, st)
            brain.mark_spoken(d, now, text)
            kind, ch = react(name, d, now)
            brain.feedback(kind, now + timedelta(minutes=2), key=c.facts.get("key") if c.topic == "challenge" else None, choice=ch)
            say.append(dict(day=day, time=now.strftime("%H:%M"), topic=c.topic, project=c.project, text=text, reaction=kind, net=round(d.net, 2), why=d.rationale))
    return name, say, st, home


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--llm", action="store_true"); ap.add_argument("--out", default="/workspace/openlookout/demo_private")
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    md = ["# 小精灵多日模拟\n"]; summary = {}
    for mk in (sc_sunk, sc_better, sc_control_productive, sc_control_scattered, sc_outside_conflict, sc_helper, sc_dismiss):
        name, say, st, home = run(mk, a.llm, out, mk.__name__)
        topics = {}
        for x in say: topics[x["topic"]] = topics.get(x["topic"], 0) + 1
        summary[mk.__name__] = dict(name=name, n=len(say), topics=topics, voice=st)
        md.append(f"\n## {mk.__name__}：{name}\n共开口 {len(say)} 次 {topics} 声音统计 {st}\n")
        for x in say: md.append(f"- 第{x['day']}天 {x['time']} [{x['topic']}] {x['text']}  （用户：{x['reaction']}；{x['why']}）")
        shutil.copy(home / "decisions.jsonl", out / f"sim_decisions_{mk.__name__}.jsonl")
        if (home / "judgments.jsonl").exists(): shutil.copy(home / "judgments.jsonl", out / f"sim_judgments_{mk.__name__}.jsonl")
    (out / "sprite_sim.md").write_text("\n".join(md), "utf-8"); (out / "sprite_sim_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
