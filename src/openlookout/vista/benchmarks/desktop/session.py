"""One desktop task: the live screen is the evidence; the tools act on this computer."""
from __future__ import annotations

import hashlib, io, json, os, time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab
from jsonschema import Draft202012Validator

from vista.core.contracts import (
    EvidenceKind, Effect, Observation, ObservationBundle, PublicTask, SubmissionSpec, ToolBinding, ToolReply, Visual,
)
from . import actions
from . import permissions
from .agenda import Agenda
from sprite.config import sprite_home
from sprite.proactive.public_speech import leaks_internal
from vista.core.json import thaw

SHOT_WIDTH, SHOT_QUALITY = 1280, 75
CURRENT = sprite_home() / "perceive" / "current.json"


def screen_visual() -> Visual:
    try:
        img = ImageGrab.grab().convert("RGB")
    except OSError:
        # Headless CI and a display that is not ready must not crash the
        # session. A blank frame is not a screen change by itself once the
        # brain has a thumbnail baseline.
        img = Image.new("RGB", (SHOT_WIDTH, 720), (0, 0, 0))
    h = int(img.height * SHOT_WIDTH / img.width)
    img = img.resize((SHOT_WIDTH, h))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=SHOT_QUALITY)
    return Visual("screen", f"screen-{time.time_ns()}", buf.getvalue(), SHOT_WIDTH, h, mime_type="image/jpeg")


class DesktopSession:
    """Every screen is given to the harness once as CURRENT; the harness keeps all of them in visual memory."""

    def __init__(self, objective: str, context: dict[str, Any], *, visual: Visual | None = None) -> None:
        visual = visual or screen_visual()
        self.task = PublicTask("desktop/this-computer", objective, context, self._bundle(visual))
        self.submission = SubmissionSpec(Effect.SUBMISSION)
        self.tools = tuple(ToolBinding(spec, self._handler(name, fn)) for name, (fn, spec) in actions.SPECS.items()) + (
            ToolBinding(actions.PLAN_SPEC, self._plan),
            ToolBinding(actions.COMPANION_SPEC, self._companion),)
        self.decisions: list[dict[str, Any]] = []
        self.suppressed = 0                 # 因「刚说过/他拒绝过」被压掉的次数（时机质量的数据）
        self.final: str | None = None
        self.actions = 0
        self.action_results: list[dict[str, Any]] = []
        self.reports: list[str] = []
        self._turn_mutations: list[dict[str, Any]] = []
        self.policy_context: dict[str, Any] | None = None
        self.agenda: Agenda | None = None
        self.closed = False
        self.evidence_revision = 0
        self._evidence_seen: set[str] = set()
        self._gate: permissions.Gate | None = None

    @property
    def gate(self) -> permissions.Gate:
        """风险闸门：每 session 一份，这样「同一轮攒一批」才有确定边界。

        故意做成惰性属性而不是 ``__init__`` 里赋值：不少测试用
        ``DesktopSession.__new__`` 造裸对象（不起模型、不截图），那条路径
        不会跑 ``__init__``。闸门缺了会让这些用例在 ``_flush_risk_batches``
        上炸 AttributeError，而不是安静地拿到一个默认闸门。
        """
        if getattr(self, "_gate", None) is None:
            self._gate = permissions.Gate(policy=permissions.load_policy())
        return self._gate

    @gate.setter
    def gate(self, value: permissions.Gate) -> None:
        self._gate = value

    def _bundle(self, visual: Visual) -> ObservationBundle:
        """One new CURRENT observation with a unique identity. VISTA itself keeps every earlier
        observation in visual memory (history / inspect), so history is never re-supplied here."""
        self.count = getattr(self, "count", 0) + 1
        self.current_visual = visual
        return ObservationBundle((Observation(f"screen-{self.count}", (visual,), EvidenceKind.CURRENT),))

    def observe(self, visual: Visual) -> ObservationBundle:
        """A new screen arrived: hand it to the harness as the next CURRENT observation."""
        return self._bundle(visual)

    def _plan(self, arguments: Any) -> ToolReply:
        if self.agenda is None:
            return ToolReply("该任务没有启用常驻目标调度。", success=False)
        try:
            changes = (arguments or {}).get("changes", [])
            for change in changes:
                verification = change.get("verification")
                if verification and actions.SPECS.get(verification.get("tool"), (None, None))[1] is not None:
                    if actions.SPECS[verification["tool"]][1].effect not in {Effect.NONE, Effect.ANNOTATION}:
                        raise ValueError("结果核验必须是独立的只读或证据核验工具")
            self.agenda.update(changes, set(actions.SPECS))
        except (KeyError, TypeError, ValueError) as exc:
            return ToolReply(str(exc), success=False)
        return ToolReply(self.agenda.context())

    def _companion(self, arguments: Any) -> ToolReply:
        """The per-turn decision. Ends the turn; the harness then waits for the next screen."""
        d = dict(arguments or {}, t=time.time())
        # ``opportunity`` is an optional, model-authored report.  Keep its
        # contract strict at the runtime boundary so malformed claims cannot
        # leak into the decision log or user-facing speech.  The report is
        # evidence, not a scheduler or a scene label.
        opportunity = d.get("opportunity")
        if opportunity is not None:
            required = ("hypothesis", "evidence", "impact_if_ignored",
                        "next_investigation", "expected_result")
            if not isinstance(opportunity, dict) or any(
                    not isinstance(opportunity.get(key), str)
                    or not opportunity[key].strip() for key in required):
                return ToolReply(
                    "opportunity 必须包含 hypothesis/evidence/impact_if_ignored/"
                    "next_investigation/expected_result 五个非空事实字段。",
                    success=False)
            if set(opportunity) - set(required):
                return ToolReply("opportunity 只能包含约定的五个字段。", success=False)
            # Avoid silently accepting unbounded model payloads.
            if any(len(opportunity[key]) > 600 for key in required):
                return ToolReply("opportunity 字段过长，请压缩为可核验的一句话。", success=False)
        if self.agenda is not None:
            d["agenda"] = {"revision": self.agenda.revision,
                           "suggested": self.agenda.selected().goal_id if self.agenda.selected() else None,
                           "states": {goal_id: goal.state for goal_id, goal in self.agenda.goals.items()}}
        if self.policy_context is not None:
            d["policy"] = dict(self.policy_context)
            self.policy_context = None
        kind, say, topic = d.get("kind"), (d.get("say") or "").strip(), (d.get("topic") or "").strip()
        step = d.get("next_step") or {}
        if self.agenda is not None and step.get("status") == "ready":
            next_tool = step.get("tool")
            if not next_tool:
                suggested = self.agenda.selected()
                if suggested is not None:
                    planned = self.agenda.action_for(suggested)
                    step = dict(step, tool=planned.get("tool"), arguments=planned.get("arguments", {}))
                    d["next_step"] = step
                    next_tool = step.get("tool")
            available = {binding.spec.name for binding in self.tools} | {
                "inspect", "history", "read_pixels", "read_guide", "write_guide", "read_working", "write_working"}
            if next_tool not in available:
                return ToolReply("ready 必须填写现在能调用的 tool 与 arguments，不能把用户同意后或未提供的编辑能力写成可执行下一步。"
                                 "已交付且核验的目标写 done；外部能力缺口写 waiting，并自行比较其他可推进线索。", success=False)
            spec = next((binding.spec for binding in self.tools if binding.spec.name == next_tool), None)
            if spec is not None:
                error = next(Draft202012Validator(thaw(spec.input_schema)).iter_errors(step.get("arguments", {})), None)
                if error is not None:
                    return ToolReply("ready 的实际工具参数不能执行：" + error.message
                                     + "。补全可调用参数；未核验目标先核验，能力缺口写 waiting。", success=False)
        if kind in ("companion", "offer") and not say:
            return ToolReply("开口需要 say 正文；请表达一个清楚想法，或明确选择 quiet。", success=False)
        if not d.get("next_step"):
            work_step = self.agenda.continuation_step() if self.agenda is not None else None
            if work_step is not None:
                d["next_step"] = work_step
            elif kind == "quiet":
                d["next_step"] = {
                    "status": "waiting",
                    "goal": "当前没有已核实的高价值动作",
                    "action": "等待与当前目标有关的新画面、消息或证据，不重复检查",
                    "evidence": "本轮没有安全且高价值的下一步",
                }
            elif kind == "companion":
                d["next_step"] = {
                    "status": "waiting",
                    "goal": "继续理解这段交流",
                    "action": "等待用户回应或出现新的相关线索",
                    "evidence": "当前贡献已送达",
                }
        mutations = list(self._turn_mutations)
        self._turn_mutations.clear()
        # Memory trimming is background hygiene. It can still run and is
        # recorded in action_results, but it must not turn into a recurring
        # user-facing notification when it is the only thing accomplished.
        # A real task blocker should be expressed through a different action
        # or a later, evidence-backed report.
        if (mutations and all(row.get("tool") == "desktop_trim" for row in mutations)
                and d.get("intent") != "conversation"):
            kind, say = "quiet", ""
            d["kind"], d["say"] = kind, say
        if kind in ("companion", "offer") and say and leaks_internal(say):
            # The model tried to narrate our own machinery. End the turn quietly
            # instead of putting that sentence on the bubble.
            d["leak_suppressed"] = True
            kind, say = "quiet", ""
            d["kind"], d["say"] = kind, say
        self.decisions.append(d)
        activity = (d.get("activity") or "").strip() or say or "我在持续观察当前画面"
        if leaks_internal(activity):
            activity = "我在安静陪着"
        CURRENT.parent.mkdir(parents=True, exist_ok=True)
        tmp = CURRENT.with_suffix(".tmp")
        work = self.work_summary()
        d["speech"] = {"kind": kind, "say": say}
        if opportunity is not None:
            d["opportunity"] = opportunity
        d["work"] = work
        tmp.write_text(json.dumps({"t": d["t"], "activity": activity, "topic": topic,
                                   "confidence": float(d.get("confidence", 0.8)),
                                   "speech": d["speech"],
                                   "work": work,
                                   "next_step": self.public_next_step(d.get("next_step")),
                                   "source": "vista"}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CURRENT)
        with (CURRENT.parent / "decisions.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(dict(d, actions=mutations), ensure_ascii=False) + "\n")
        if kind in ("companion", "offer") and say and (kind == "companion" or float(d.get("confidence", 0.8)) >= 0.7):
            from sprite.proactive.help import (OFFER_OPTIONS, conversation_worth_saying,
                                               publish, record, worth_saying)
            allowed = conversation_worth_saying(say) if kind == "companion" else worth_saying(topic, kind, say)
            if not allowed:
                self.suppressed += 1
                return ToolReply("这一句刚说过、他还没回应，先不重复打扰。",
                                 boundary="decision_complete", event_text="decision:suppressed")
            offer = dict(id=f"{time.time_ns()}", t=d["t"], text=say, topic=topic,
                         kind=kind, action="none", confidence=float(d.get("confidence", 0.8)))
            # offer 要动手改电脑，所以必须先问过。选项写进 offer 记录本身（不只是画在气泡上），
            # 这样 offers.jsonl 才留得住「摆过什么选项」，正负样本才统计得出来。
            if kind == "offer":
                offer["options"] = list(OFFER_OPTIONS)
            if d.get("reply_to"):
                offer["reply_to"] = d["reply_to"]
            publish(offer); record(dict(offer, result="shown"))
            self.reports.append(say)
        self._flush_risk_batches()
        if d.get("leak_suppressed"):
            return ToolReply(
                "这句话没有发给用户：里面有内部用语。下一轮只讲他正在做的事，用人话；没有就 quiet。",
                boundary="decision_complete", event_text="decision:quiet")
        return ToolReply("已记录这一轮的决定。", boundary="decision_complete", event_text=f"decision:{d.get('kind')}")

    def _flush_risk_batches(self) -> None:
        """回合边界：把这一轮攒下的中风险批次变成**一条**提议。

        放在 ``_companion`` 末尾是因为 companion 每轮必调（它决定开口说什么），
        所以它就是「这一轮结束」的可靠边界。高风险不进 batches，因此这里发出的
        每条提议都只含同档操作，不会把一次点头的范围悄悄放大。
        """
        for proposal in self.gate.flush():
            items = proposal.get("items") or []
            from sprite.proactive.help import OFFER_OPTIONS, publish, record
            offer = {"id": f"risk-{time.time_ns()}", "t": time.time(),
                     "text": proposal["text"], "topic": f"risk:{proposal.get('risk')}",
                     "kind": "offer", "risk": proposal.get("risk"),
                     "items": items, "options": list(OFFER_OPTIONS)}
            publish(offer); record(dict(offer, result="shown"))
            permissions.append_pending(proposal)

    def work_summary(self) -> dict:
        agenda = self.agenda
        if agenda is None:
            return {"status": "idle"}
        step = agenda.continuation_step()
        counts = {state: sum(goal.state == state for goal in agenda.goals.values())
                  for state in sorted({goal.state for goal in agenda.goals.values()})}
        if step is not None:
            return {"status": "verify" if step["phase"] == "verify" else "ready",
                    "tool": step["tool"], "counts": counts}
        status = "review" if counts.get("review") else "waiting" if counts.get("waiting") else "idle"
        return {"status": status, "counts": counts}

    @staticmethod
    def public_next_step(step: dict | None) -> dict | None:
        if step is None:
            return None
        if step.get("goal_id"):
            return {"status": step.get("status"), "tool": step.get("tool"),
                    "goal": "推进已登记工作", "action": "核验实际结果" if step.get("phase") == "verify" else "执行具体下一步",
                    "evidence": "已有工作记录"}
        return {key: value for key, value in step.items() if key not in {"arguments", "goal_id", "phase"}}

    def _handler(self, name, fn):
        def run(arguments: Any) -> ToolReply:
            spec = actions.SPECS.get(name, (None, None))[1]
            read_only = spec is not None and spec.effect in {Effect.NONE, Effect.ANNOTATION}
            agenda = getattr(self, "agenda", None)
            if not read_only and name != "desktop_capture_evidence":
                if agenda is None and self.actions >= actions.MAX_ACTIONS:
                    return ToolReply(f"本次任务的操作次数已达上限（{actions.MAX_ACTIONS}）。", success=False)
                # 预算在闸门**之前**扣：被闸门拦下的尝试同样占用一次机会，
                # 否则模型可以对同一个高风险操作无限重试，闸门反倒成了漏洞。
                self.actions += 1
            # 风险闸门（2026-10-13）：只读与低风险直接做，中风险攒批，高风险每次单问。
            # 放在分发处而不是提示词里 —— 上一轮 basic_shell 就是靠这里拦下的，
            # 「请不要做」在模型面前没有强制力。
            #
            # 必须排在 agenda.claim **之前**：被闸门拦下的调用根本没发生，
            # 如果先 claim 就留下一个永远不会 record 的悬空目标，
            # 下一次 continuation_step 会一直重复追一个不存在的执行。
            if not read_only:
                verdict = self.gate.admit(name, arguments or {}, spec)
                if not verdict.allow:
                    # 拦下的调用不算成功改动，不进 action_results（那是给用户看的
                    # 「到底动没动过机器」的账），但证据指纹要更新，模型才知道
                    # 现场没变。
                    self._record_evidence(name, ToolReply(verdict.reason, success=False))
                    return ToolReply(verdict.reason, success=False)
            claim = None
            if agenda is not None and name != "desktop_undo":
                try:
                    claim = agenda.claim(name, arguments or {}, mutation=not read_only)
                except ValueError as exc:
                    return ToolReply(str(exc), success=False)
            try:
                if name == "desktop_capture_evidence":
                    reply = fn(arguments or {}, visual=self.current_visual)
                    if reply.success:
                        self.reviewable_evidence = getattr(self, "reviewable_evidence", set())
                        self.reviewable_evidence.add(json.loads(reply.text)["id"])
                elif name == "desktop_review_evidence":
                    if (arguments or {}).get("id") not in getattr(self, "reviewable_evidence", set()):
                        reply = ToolReply("只能核验本会话中已经返回给你的截图。", success=False)
                    else:
                        reply = fn(arguments or {})
                else:
                    reply = fn(arguments or {})
            except Exception as exc:
                reply = ToolReply(f"工具执行异常（{type(exc).__name__}），结果未确认；先核验现场，不宣称没有改动。",
                                  success=False)
            self._record_evidence(name, reply)
            if claim is not None:
                result_id = agenda.record(claim, name, reply.text, success=reply.success,
                                          mutation=not read_only)
                reply = replace(reply, text=reply.text + "\n目标结果 result_id=" + result_id
                                + "；对照预期判断改善或反证，再修订下一步，不能把调用成功当目标完成。")
            if not read_only:
                row = {
                    "tool": name,
                    "success": bool(getattr(reply, "success", False)),
                    "text": str(getattr(reply, "text", "")),
                }
                self.action_results.append(row)
                self._turn_mutations.append(row)
            return reply
        return run

    def _record_evidence(self, name: str, reply: ToolReply) -> None:
        if name in {"basic_time", "desktop_processes"} or not isinstance(getattr(reply, "text", None), str):
            return
        try:
            value = json.loads(reply.text)
            if isinstance(value, dict):
                value = {key: item for key, item in value.items() if key not in {"snapshot", "captured_at"}}
                if name == "basic_search":
                    value = {key: value.get(key) for key in ("ok", "root", "matches", "truncated", "error")}
            content = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (ValueError, TypeError):
            content = reply.text
        fingerprint = hashlib.sha256((name + ":" + content).encode()).hexdigest()
        seen = getattr(self, "_evidence_seen", set())
        if fingerprint not in seen:
            seen.add(fingerprint)
            self._evidence_seen = seen
            self.evidence_revision = getattr(self, "evidence_revision", 0) + 1

    @property
    def answered(self) -> bool:
        return self.final is not None

    def submit(self, answer: str) -> ToolReply:
        if self.answered: return ToolReply("已经提交过结论。", success=False)
        self.final = answer
        return ToolReply("结论已记录，任务结束。", finished=True, event_text="结论已记录")

    def result(self) -> dict[str, Any]:
        return {
            "objective": self.task.objective,
            "answered": self.answered,
            "final": self.final,
            "report": self.reports[-1] if self.reports else None,
            "actions": self.actions,
            "action_results": list(self.action_results),
        }

    def close(self) -> None:
        self.closed = True
