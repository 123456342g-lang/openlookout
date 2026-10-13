"""Legacy conversation experiment, retained for reference only.

The live brain does not import this planner, its quotas or its templates.
VISTA now makes conversational decisions in the continuous visual session.

This is a small contextual bandit for the chat lane. It generates a handful
of human conversation intents, scores them against the current idle/work
context, and learns from shown/accepted/dismissed outcomes. It never reads or
stores screenshots; VISTA supplies the semantic context separately.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ChatCandidate:
    topic: str
    prompt: str
    value: float
    interruption: float
    novelty: float
    requires_idle: bool = True


class ChatPlanner:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.attempts: dict[str, int] = {}
        self.accepted: dict[str, int] = {}
        self.dismissed: dict[str, int] = {}
        self.last_shown: dict[str, float] = {}
        self.day = ""
        self.day_count = 0
        self._load()

    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.attempts = {str(k): int(v) for k, v in (d.get("attempts") or {}).items()}
            self.accepted = {str(k): int(v) for k, v in (d.get("accepted") or {}).items()}
            self.dismissed = {str(k): int(v) for k, v in (d.get("dismissed") or {}).items()}
            self.last_shown = {str(k): float(v) for k, v in (d.get("last_shown") or {}).items()}
            self.day, self.day_count = str(d.get("day") or ""), int(d.get("day_count") or 0)
        except (OSError, ValueError, TypeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"attempts": self.attempts, "accepted": self.accepted,
                                   "dismissed": self.dismissed, "last_shown": self.last_shown,
                                   "day": self.day, "day_count": self.day_count}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def sync(self, rows: list[dict]) -> None:
        """Update priors from explicit conversational outcomes only."""
        for row in rows:
            topic = str(row.get("topic") or "").strip()
            result = row.get("result")
            if not topic or result not in {"accepted", "dismissed", "auto_completed"}:
                continue
            key = f"{topic}:{row.get('t_answer', row.get('t'))}"
            if self.attempts.get(key):
                continue
            self.attempts[key] = 1
            if result in {"accepted", "auto_completed"}:
                self.accepted[topic] = self.accepted.get(topic, 0) + 1
            elif result == "dismissed":
                self.dismissed[topic] = self.dismissed.get(topic, 0) + 1

    def _prior(self, topic: str) -> float:
        a = self.accepted.get(topic, 0)
        d = self.dismissed.get(topic, 0)
        return (1.0 + a) / (2.0 + a + d)

    def candidates(self, *, idle_s: float, has_active_work: bool, now: float | None = None,
                   weather_text: str = "", facts: dict | None = None) -> list[ChatCandidate]:
        now = now if now is not None else time.time()
        if idle_s >= 300 or has_active_work:
            return []
        hour = datetime.fromtimestamp(now).hour
        if hour < 11:
            time_prompt = "早上先问一句轻松的近况，顺带问今天最想推进的一个结果。"
        elif hour < 18:
            time_prompt = "下午用朋友口吻问一句节奏是否顺利，必要时帮他把下一步说清楚。"
        else:
            time_prompt = "晚上用朋友口吻问一句今天是否收尾，提醒只在能减轻明天负担时出现。"
        facts = facts or {}
        candidates = [
            ChatCandidate("check_in", time_prompt, .34, .18, .10),
            ChatCandidate("next_step", "根据连续操作证据，聊一句可能的下一步，但不要复述当前窗口。", .56, .22, .35),
        ]
        if facts.get("recent_win"):
            candidates.append(ChatCandidate("small_win", str(facts["recent_win"]), .62, .16, .58))
        if facts.get("public_fact"):
            candidates.append(ChatCandidate("curiosity", str(facts["public_fact"]), .55, .18, .72))
        if weather_text:
            candidates.append(ChatCandidate("weather_time", weather_text, .36, .20, .15))
        return candidates

    def choose(self, *, idle_s: float, has_active_work: bool, now: float | None = None,
               weather_text: str = "", facts: dict | None = None) -> ChatCandidate | None:
        now = now if now is not None else time.time()
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if day != self.day:
            self.day, self.day_count = day, 0
        if self.day_count >= 2 or any(now - t < 900 for t in self.last_shown.values()):
            return None
        rows = []
        total = max(1, sum(self.accepted.values()) + sum(self.dismissed.values()))
        for candidate in self.candidates(idle_s=idle_s, has_active_work=has_active_work,
                                         now=now, weather_text=weather_text, facts=facts):
            age = now - self.last_shown.get(candidate.topic, 0.0)
            if age < 3600:
                continue
            uncertainty = math.sqrt(math.log(total + 2) / (1 + self.accepted.get(candidate.topic, 0) + self.dismissed.get(candidate.topic, 0)))
            score = candidate.value * self._prior(candidate.topic) + .10 * candidate.novelty * uncertainty - candidate.interruption
            rows.append((score, candidate))
        return max(rows, key=lambda row: row[0])[1] if rows else None

    def mark_shown(self, topic: str, now: float | None = None) -> None:
        self.last_shown[topic] = now if now is not None else time.time()
        self.day_count += 1
        self.save()

    @staticmethod
    def render(candidate: ChatCandidate, now: float | None = None) -> str:
        if candidate.topic == "check_in":
            return "今天节奏还顺吗？我在旁边，想把下一步理清时直接叫我。"
        if candidate.topic == "next_step":
            return "我刚发现你这条流程里有一点重复等待，先不打断；再积累几次，我帮你找更省时间的做法。"
        if candidate.topic == "small_win":
            variants = (
                "刚才那件事已经有结果了：{fact}。这种小进展我先替你记着，别让它悄悄过去。",
                "我刚回看了一下，发现你已经把这件事推进到这里：{fact}。接下来不用急，我陪你把它收好。",
                "顺手说一句，刚才的进展是：{fact}。这种时候歇半分钟也不亏。",
            )
            return variants[int((now or time.time()) // 3600) % len(variants)].format(fact=candidate.prompt)
        if candidate.topic == "curiosity":
            variants = (
                "我刚顺手查到一个今天的小谈资：{fact}。突然觉得，人的专注力和这种故事还挺像，都会在意想不到的地方拐个弯。",
                "刚才空下来我查了点东西：{fact}。这个挺有意思的，你平时会对这种事感兴趣吗？",
                "给你带一句我刚发现的：{fact}。不急着回答，我只是觉得它值得放在今天的聊天里。",
            )
            return variants[int((now or time.time()) // 3600) % len(variants)].format(fact=candidate.prompt)
        if candidate.topic == "weather_time" and candidate.prompt.startswith("今天"):
            return "我刚看了一眼外面：" + candidate.prompt + "。今天如果要出门，记得给自己留点余量。"
        now = now if now is not None else time.time()
        return f"现在是 {datetime.fromtimestamp(now):%H:%M}。今天还有出门或安排的话，我可以顺手帮你看时间和天气。"

