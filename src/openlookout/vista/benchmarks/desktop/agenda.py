"""Execution metadata for open-ended goals; VISTA owns all semantic memory."""
from __future__ import annotations

import json
import math
import ntpath
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .decision_engine import Candidate, DecisionEngine


STATES = {"ready", "verify", "review", "waiting", "done", "dropped", "running"}
ESTIMATES = {
    "confidence": 0.5, "impact": 0.0, "urgency": 0.0, "blocker_relief": 0.0,
    "information_gain": 0.0, "success_probability": 0.5, "action_cost": 0.1,
    "interruption_cost": 0.0, "risk": 0.0, "reversibility": 0.0,
    "downstream_value": 0.0, "novelty": 0.0,
}


def fingerprint(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class Goal:
    goal_id: str
    goal: str
    lane: str
    evidence: list[str]
    expected: str
    state: str
    estimates: dict[str, float]
    action: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    waiting_on: str = ""
    depends_on: list[str] = field(default_factory=list)
    last_result: dict = field(default_factory=dict)
    attempted: list[str] = field(default_factory=list)
    last_selected: int = 0
    request: dict = field(default_factory=dict)
    action_result: dict = field(default_factory=dict)
    assessment: str = ""


class Agenda:
    """Keep execution state; discovery and strategic judgment belong to VISTA."""

    def __init__(self, engine: DecisionEngine, path: Path | None = None):
        self.engine = engine
        self.path = path
        self.goals: dict[str, Goal] = {}
        self.revision = 0
        self.delivered_revision = -1
        self.sequence = 0

    @classmethod
    def load(cls, engine: DecisionEngine, path: Path) -> "Agenda":
        agenda = cls(engine, path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            agenda.revision = data["revision"]
            agenda.sequence = data["sequence"]
            agenda.goals = {row["goal_id"]: Goal(**row) for row in data["goals"]}
            for goal in agenda.goals.values():
                if goal.state == "running":
                    goal.state = "verify" if goal.verification else "review"
                    goal.last_result = {"interrupted": True, "text": "执行被中断，先核验现场，不重放变更。",
                                        "request": dict(goal.request), "expected": goal.expected}
        return agenda

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "version": 1, "revision": self.revision, "sequence": self.sequence,
            "goals": [asdict(goal) for goal in self.goals.values()],
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def update(self, changes: list[dict], tool_names: set[str]) -> None:
        proposed = dict(self.goals)
        for change in changes:
            goal_id = str(change["goal_id"]).strip()
            if not goal_id:
                raise ValueError("goal_id 不能为空")
            old = proposed.get(goal_id)
            requested_state = change.get("state")
            if old is not None:
                change = {**asdict(old), **change,
                          "estimates": {**old.estimates, **change.get("estimates", {})}}
            required = {"goal", "lane", "evidence", "expected", "state", "estimates"}
            if not required.issubset(change):
                raise ValueError("新目标需要 goal/lane/evidence/expected/state/estimates；已有目标只需提交改变的字段")
            state = change["state"]
            if state not in STATES - {"running", "verify"} and requested_state is not None:
                raise ValueError("只能规划 ready/review/waiting/done/dropped")
            estimates = {**ESTIMATES, **change.get("estimates", {})}
            if any(key not in ESTIMATES or isinstance(value, bool)
                   or not isinstance(value, (float, int)) or not math.isfinite(value)
                   or not 0 <= value <= 1 for key, value in estimates.items()):
                raise ValueError("收益/成本估计必须是 0 到 1 之间的有限数")
            goal = Goal(
                goal_id, change["goal"], change["lane"], change["evidence"],
                change["expected"], state, estimates,
                action=change.get("action", {}), verification=change.get("verification", {}),
                waiting_on=change.get("waiting_on", ""), depends_on=change.get("depends_on", []),
                last_result=old.last_result if old else {},
                attempted=list(old.attempted) if old else [],
                last_selected=old.last_selected if old else 0,
                request=dict(old.request) if old else {},
                action_result=dict(old.action_result) if old else {},
                assessment=str(change.get("assessment", old.assessment if old else "")))
            if goal.lane not in {"help", "maintenance", "investigate", "conversation"}:
                raise ValueError("未知的行动类型")
            if not goal.evidence or not all(isinstance(row, str) and row.strip() for row in goal.evidence):
                raise ValueError("目标需要具体来源证据，不能只报指标或猜测")
            for action in (goal.action, goal.verification):
                if action and (action.get("tool") not in tool_names or
                               not isinstance(action.get("arguments", {}), dict)):
                    raise ValueError("下一步必须使用已提供的实际工具")
            if state == "ready" and not goal.action:
                raise ValueError("ready 需要具体工具和参数")
            if state == "waiting" and not goal.waiting_on.strip():
                raise ValueError("waiting 需要明确外部条件或能力缺口")
            if goal_id in goal.depends_on:
                raise ValueError("目标不能依赖自身")
            if state == "done" and (old is None or old.state != "done"):
                result = goal.last_result
                verified = result.get("phase") == "verify" or result.get("mutation") is False
                if (not result.get("success") or not verified
                        or change.get("result_id") != result.get("id")
                        or not str(change.get("assessment", "")).strip()):
                    raise ValueError("完成需要本目标的结果 result_id 与 assessment 说明预期是否满足；变更必须单独核验")
            if state == "ready" and self._attempt_key(goal) in goal.attempted:
                raise ValueError("这项动作在同一证据下已尝试；换方案或等待具体新证据")
            proposed[goal_id] = goal
        for goal in proposed.values():
            visiting: set[str] = set()

            def visit(goal_id: str) -> None:
                if goal_id in visiting:
                    raise ValueError("目标依赖存在循环")
                visiting.add(goal_id)
                for dependency in proposed.get(goal_id, goal).depends_on:
                    if dependency in proposed:
                        visit(dependency)
                visiting.remove(goal_id)

            visit(goal.goal_id)
        if proposed == self.goals:
            return
        previous = self.goals
        self.goals = proposed
        self.revision += 1
        self.save()
        for goal_id, goal in proposed.items():
            if goal.state == "done" and (goal_id not in previous or previous[goal_id].state != "done"):
                self.engine.record_outcome(goal_id, "success", event_id=goal.last_result["id"])

    @staticmethod
    def _attempt_key(goal: Goal) -> str:
        return fingerprint({"action": goal.action, "evidence": goal.evidence})

    def selected(self) -> Goal | None:
        eligible = [goal for goal in self.goals.values()
                    if goal.state in {"ready", "verify"}
                    and all(self.goals.get(dependency) and self.goals[dependency].state == "done"
                            for dependency in goal.depends_on)]
        eligible.sort(key=lambda goal: goal.last_selected)
        candidates = [Candidate(
            candidate_id=goal.goal_id, goal_id=goal.goal_id, lane=goal.lane,
            evidence=1.0, **goal.estimates) for goal in eligible]
        ranked = self.engine.rank(candidates)
        return self.goals[ranked[0][0].goal_id] if ranked and ranked[0][1].value > 0 else None

    def action_for(self, goal: Goal) -> dict:
        return goal.verification if goal.state == "verify" else goal.action

    def continuation_steps(self) -> list[dict]:
        goals = [goal for goal in self.goals.values()
                 if goal.state in {"verify", "ready"} and self.action_for(goal)
                 and all(self.goals.get(dep) and self.goals[dep].state == "done"
                         for dep in goal.depends_on)]
        goals.sort(key=lambda goal: (0 if goal.state == "verify" else 1, goal.last_selected, goal.goal_id))
        return [{"goal_id": goal.goal_id, "status": "ready", "goal": goal.goal,
                 "action": f"调用 {self.action_for(goal).get('tool', '')} 完成该步骤",
                 "evidence": "; ".join(goal.evidence), "tool": self.action_for(goal).get("tool"),
                 "arguments": self.action_for(goal).get("arguments", {}),
                 "result_version": goal.last_result.get("id"),
                 "phase": "verify" if goal.state == "verify" else "action"}
                for goal in goals]

    def continuation_step(self) -> dict | None:
        steps = self.continuation_steps()
        return steps[0] if steps else None

    def matches(self, goal: Goal, name: str, arguments: dict) -> bool:
        expected = self.action_for(goal)
        if expected.get("tool") != name:
            return False
        planned = expected.get("arguments", {})
        if goal.state == "ready" and name == "desktop_write_deliverable":
            return (bool(planned.get("name")) and planned.get("name") == arguments.get("name")
                    and bool(planned.get("sources"))
                    and sorted(planned.get("sources", [])) == sorted(arguments.get("sources", [])))
        if goal.state == "verify" and name == "desktop_read_local":
            return (bool(planned.get("path"))
                    and ntpath.normcase(ntpath.normpath(planned["path"]))
                    == ntpath.normcase(ntpath.normpath(arguments.get("path", "")))
                    and planned.get("offset", 0) == arguments.get("offset", 0)
                    and ("limit" not in planned or planned["limit"] == arguments.get("limit", 5000))
                    and not (arguments.keys() - {"path", "offset", "limit"}))
        return planned == arguments

    def claim(self, name: str, arguments: dict, *, mutation: bool) -> tuple[str, str] | None:
        if any(goal.state == "running" and goal.request.get("tool") == name
               and goal.request.get("arguments", {}) == arguments for goal in self.goals.values()):
            raise ValueError("这项工具正在执行中，先接收实际结果，不重复调用")
        matches = [goal for goal in self.goals.values()
                   if goal.state in {"ready", "verify"}
                   and self.matches(goal, name, arguments)
                   and all(self.goals.get(dependency) and self.goals[dependency].state == "done"
                           for dependency in goal.depends_on)]
        if len(matches) > 1:
            raise ValueError("多个目标登记了同一动作，先合并共同步骤或修订计划，避免错误归因")
        if not matches:
            if mutation:
                registered = [{"goal_id": goal.goal_id, "state": goal.state,
                               "expected": self.action_for(goal)}
                              for goal in self.goals.values()
                              if goal.state in {"ready", "verify"}
                              and self.action_for(goal).get("tool") == name]
                if registered:
                    raise ValueError("已有该工具计划，但实际目标参数不匹配。只修改不一致字段后重试；"
                                     "来源使用同一组真实路径，不要在相对路径和绝对路径间切换："
                                     + json.dumps(registered, ensure_ascii=False))
                raise ValueError("先用 desktop_plan 记录这项变更的目标、证据、预期与核验；只读探索无需先登记目标")
            return None
        goal = matches[0]
        phase = "verify" if goal.state == "verify" else "action"
        if mutation and not goal.verification:
            raise ValueError("变更必须先规划独立的结果核验工具")
        self.sequence += 1
        goal.last_selected = self.sequence
        goal.request = {"tool": name, "arguments": dict(arguments), "expected": goal.expected,
                        "phase": "verify" if goal.state == "verify" else "action",
                        "mutation": mutation, "t": time.time()}
        if phase == "action":
            goal.attempted.append(self._attempt_key(goal))
        goal.state = "running"
        self.revision += 1
        self.save()
        return goal.goal_id, phase

    def record(self, claim: tuple[str, str], name: str, text: str, *, success: bool,
               mutation: bool) -> str:
        goal_id, phase = claim
        goal = self.goals[goal_id]
        event_id = uuid.uuid4().hex
        goal.last_result = {"id": event_id, "tool": name, "phase": phase,
                            "success": success, "mutation": mutation,
                            "text": text[:2000], "t": time.time(),
                            "request": dict(goal.request), "expected": goal.expected}
        if phase == "action":
            goal.action_result = dict(goal.last_result)
        elif goal.action_result:
            goal.last_result["action_result_id"] = goal.action_result["id"]
        if goal.request:
            goal.request["result_id"] = event_id
        goal.state = "verify" if phase == "action" and goal.verification and (mutation or success) else "review"
        self.revision += 1
        self.save()
        if not success:
            self.engine.record_outcome(goal_id, "failure", event_id=event_id)
        return event_id

    def due(self) -> bool:
        return self.revision != self.delivered_revision and (
            any(goal.state in {"ready", "verify", "review"} for goal in self.goals.values()))

    def mark_delivered(self, revision: int | None = None) -> None:
        self.delivered_revision = self.revision if revision is None else revision

    def context(self) -> str:
        selected = self.selected()
        rows = [{
            "goal_id": goal.goal_id, "goal": goal.goal, "state": goal.state,
            "expected": goal.expected,
            "waiting_on": goal.waiting_on, "depends_on": goal.depends_on,
            "next": self.action_for(goal) if goal.state in {"ready", "verify"} else None,
            "last_result": goal.last_result,
            "action_result": goal.action_result if goal.state in {"verify", "review"} else None,
        } for goal in self.goals.values() if goal.state in {"ready", "verify", "review"}]
        return "【执行进度，不是探索方向】" + json.dumps({
            "suggested": selected.goal_id if selected else None, "goals": rows,
        }, ensure_ascii=False) + (
            "\n这里仅防止进度丢失，suggested 是未经校准的局部评分建议，不是命令。"
            "可以自由只读取证、发现新问题、撤销旧假设、拆分或重定目标，不需要先有完整计划。"
            "WORKING 保留解释、反证与下一探查；调查应说明答案怎样改变行动，不为新颖而搜资料。"
            "有结果先对照预期修订方案；waiting 只阻塞自身，不代表其他方向也要等。"
            "变更前登记证据和核验；done 引用本目标 result_id 并用 assessment 说明改善是否成立。"
            "\n注意：waiting（在等他本人或外部条件）的目标不列在这里——已经告知过、"
            "只能由他落笔的事，每轮再注入只会被翻成换措辞的重复催促（真实轨迹里同一件"
            "事 3 分钟一句连播三次）。那些事没有消失，仍在 agenda 里，状态变化会自己回来；"
            "他回到那件事上（打开对应文件或问起）之前，不重提、不换说法重提。")
