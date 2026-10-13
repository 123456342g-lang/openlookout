"""场景：长期约定的学习与落地（通用）。证据来自 ① world.instructions（用户的重复提醒/纠正，来自活动流） ② 规则文件本身 ③ 任意“证据提供者”（如 reinvention.ReinventionProvider）。
推断出的约定若足够可信，就以带类型的动作写进工具会读的规则文件（项目级=safe，全局级=medium 要问）。"""
from __future__ import annotations
import json
from pathlib import Path
from ..framework import Problem, Scenario
from ..conventions import ConventionLearner
from .. import persist


def make(learner: ConventionLearner, projects_getter, providers=(), rule_scan=True):
    state = dict(announced=set(), rejected=set(), det=[])
    def rule_texts(projects):
        out = {}
        for p in map(Path, projects):
            t = ""
            for f in persist.TARGETS:
                if (p / f).is_file(): t += (p / f).read_text("utf-8", "ignore") + "\n"
            out[str(p)] = t
        return out
    def detect(w):
        projects = [str(p) for p in projects_getter(w)]
        for pr in providers: state["det"] += pr.events(w)
        events = list(getattr(w, "instructions", [])) + state["det"]
        convs = learner.infer(events, rule_texts(projects) if rule_scan else {}, state["rejected"], active_projects=projects)
        out = []
        for c in convs:
            targets = [c.project] if c.scope == "project" and c.project else c.missing_in
            for t in targets:
                key = (c.id, t)
                if t is None or key in state["announced"]: continue
                state["announced"].add(key)
                out.append(Problem("convention", min(1.0, 0.3 + 0.4 * c.confidence), f"“{c.text[:20]}”出现 {c.n_events} 次，置信度 {c.confidence:.0%}", key=f"{c.id}:{t}", ctx=dict(conv=c, project=t)))
        return out
    def propose(pb, w):
        c, t = pb.ctx["conv"], pb.ctx["project"]
        return [persist.persist_action(w, Path(t), c, rejected_cb=lambda cc: state["rejected"].add((cc.id, t)))]
    sc = Scenario("conventions", detect, propose, group_short=lambda acted, pb: acted[0].done_short([acted[0]]))
    sc.state = state
    return sc
