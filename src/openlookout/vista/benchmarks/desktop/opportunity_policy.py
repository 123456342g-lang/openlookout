"""Online opportunity scheduler for the always-on companion.

The visual model supplies semantic evidence. This module supplies the part a
prompt cannot reliably do: compare heterogeneous opportunities, account for
interruption cost, reserve some budget for information gathering, and learn
which lanes actually help this user.

It is intentionally small and deterministic. The policy is a contextual-UCB
style ranker, not a scene whitelist:

    utility = evidence * confidence * expected_benefit
              + exploration * uncertainty
              - interruption_cost - irreversibility_risk

The persisted state contains only lane/topic outcomes and timestamps, never
screenshots or raw user text.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path


LANES = ("help", "maintenance", "chat")


@dataclass(frozen=True)
class Opportunity:
    lane: str
    topic: str
    evidence: float
    confidence: float
    impact: float
    urgency: float
    blocker: float
    information_gain: float
    action_cost: float
    interruption_cost: float
    reversibility: float
    novelty: float = 0.0

    def score(self, prior: float = 0.5, uncertainty: float = 0.0) -> float:
        evidence = max(0.0, min(1.0, self.evidence)) * max(0.0, min(1.0, self.confidence))
        benefit = (0.34 * self.impact + 0.24 * self.urgency + 0.28 * self.blocker
                   + 0.14 * self.novelty)
        exploration = 0.12 * max(0.0, min(1.0, self.information_gain)) * uncertainty
        costs = 0.18 * self.action_cost + 0.22 * self.interruption_cost + 0.20 * (1.0 - self.reversibility)
        return round(evidence * benefit * (0.75 + 0.25 * prior) + exploration - costs, 4)


@dataclass
class LaneStats:
    attempts: int = 0
    successes: int = 0
    dismissed: int = 0
    last_t: float = 0.0

    def prior(self) -> float:
        # Laplace smoothing keeps a new lane eligible without making it win by
        # default. Dismissals count as weak negative evidence.
        return (1.0 + self.successes) / (2.0 + self.attempts + 0.5 * self.dismissed)

    def uncertainty(self, total_attempts: int) -> float:
        n = max(1, self.attempts)
        return math.sqrt(math.log(max(2, total_attempts + 1)) / n)


class OpportunityPolicy:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.lanes = {lane: LaneStats() for lane in LANES}
        self.seen_outcomes: set[str] = set()
        self.last_topic: dict[str, float] = {}

    @classmethod
    def load(cls, path: Path) -> "OpportunityPolicy":
        p = cls(path)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for lane, row in (data.get("lanes") or {}).items():
                if lane in p.lanes:
                    p.lanes[lane] = LaneStats(**{k: row.get(k, 0) for k in ("attempts", "successes", "dismissed", "last_t")})
            p.seen_outcomes = set(data.get("seen_outcomes") or [])
            p.last_topic = {str(k): float(v) for k, v in (data.get("last_topic") or {}).items()}
        except (OSError, ValueError, TypeError):
            pass
        return p

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"lanes": {k: asdict(v) for k, v in self.lanes.items()},
                                   "seen_outcomes": sorted(self.seen_outcomes)[-500:],
                                   "last_topic": self.last_topic}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def sync_outcomes(self, rows: list[dict]) -> None:
        """Learn only from explicit offer outcomes, once per event."""
        now = time.time()
        for row in rows:
            event_id = f"{row.get('id')}:{row.get('result')}:{row.get('t_answer', row.get('t'))}"
            if event_id in self.seen_outcomes:
                continue
            result = row.get("result")
            lane = "help" if row.get("kind") == "offer" else "chat"
            if result not in {"accepted", "dismissed", "auto_completed", "auto_failed", "undone"}:
                continue
            stats = self.lanes[lane]
            stats.attempts += 1
            stats.last_t = now
            if result in {"accepted", "auto_completed"}:
                stats.successes += 1
            elif result == "dismissed":
                stats.dismissed += 1
            self.seen_outcomes.add(event_id)

    def rank(self, candidates: list[Opportunity], now: float | None = None) -> list[dict]:
        now = now if now is not None else time.time()
        total = sum(s.attempts for s in self.lanes.values())
        ranked = []
        for candidate in candidates:
            if candidate.lane not in self.lanes:
                continue
            score = candidate.score(self.lanes[candidate.lane].prior(),
                                    self.lanes[candidate.lane].uncertainty(total))
            age = now - self.last_topic.get(candidate.topic, 0.0) if candidate.topic else now
            # Topic recency is a continuous decay, not a fixed “do not speak” rule.
            if age < 300:
                score -= 0.25 * (1.0 - age / 300.0)
            ranked.append({"candidate": candidate, "score": round(score, 4),
                           "prior": round(self.lanes[candidate.lane].prior(), 3),
                           "uncertainty": round(self.lanes[candidate.lane].uncertainty(total), 3)})
        ranked.sort(key=lambda row: row["score"], reverse=True)
        return ranked

    def recommendation(self, *, stuck: bool, pattern: bool, system_critical: bool,
                       idle: bool, feedback: bool) -> str:
        candidates = []
        if stuck or pattern or feedback:
            candidates.append(Opportunity("help", "当前工作阻塞", .8 if stuck else .6, .65,
                                          .9, .7 if stuck else .45, .85 if stuck else .55,
                                          .65, .35, .3, .8, .5))
        if system_critical:
            candidates.append(Opportunity("maintenance", "后台环境维护", .9, .8, .25, .55, .15,
                                          .2, .2, .08, .95, .05))
        if idle and not stuck:
            candidates.append(Opportunity("chat", "朋友式寒暄或有用发现", .45 if not pattern else .7, .55,
                                          .3 if not pattern else .55, .15, .15,
                                          .7, .05, .12, .98, .25 if pattern else .05))
        ranked = self.rank(candidates)
        if not ranked:
            return "【调度器】当前没有足够证据的候选；继续观察，不制造动作。"
        top = ranked[0]
        c = top["candidate"]
        return (f"【调度器】优先线={c.lane}，候选={c.topic}，分数={top['score']}，"
                f"成功先验={top['prior']}，不确定性={top['uncertainty']}。"
                "模型仍需用视觉上下文核验；维护可静默，帮助需有结果，聊天需有内容。")

