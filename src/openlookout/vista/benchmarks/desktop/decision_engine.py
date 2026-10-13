"""Model independent decision policy for the desktop companion.

The visual model supplies observations and candidate actions.  This module
decides which candidate deserves the next unit of attention.  It is a small
belief-and-outcome controller rather than a scene list or a chat timer.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


LANES = ("help", "maintenance", "investigate", "conversation", "wait")


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class Candidate:
    """A proposed next step with values supplied by evidence, not a rule."""

    candidate_id: str
    lane: str
    goal_id: str
    evidence: float
    confidence: float
    impact: float
    urgency: float
    blocker_relief: float
    information_gain: float
    success_probability: float
    action_cost: float
    interruption_cost: float
    risk: float
    reversibility: float
    downstream_value: float = 0.0
    novelty: float = 0.0
    executable: bool = True
    requires_user: bool = False


@dataclass
class OutcomeStats:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    dismissals: int = 0

    @property
    def success_rate(self) -> float:
        return (1.0 + self.successes) / (2.0 + self.attempts)

    @property
    def uncertainty(self) -> float:
        return 1.0 / math.sqrt(self.attempts + 1.0)


@dataclass
class Score:
    candidate_id: str
    value: float
    expected_gain: float
    information_value: float
    cost: float
    uncertainty_bonus: float
    reason: str


@dataclass
class Decision:
    status: str
    selected: Candidate | None
    score: Score | None
    alternatives: list[Score] = field(default_factory=list)
    reason: str = ""


class DecisionEngine:
    """Rank candidate actions and learn only from explicit outcomes.

    The score is an expected one-step value:

    ``P(success) * impact * (urgency + blocker relief)``
    ``+ information gain * downstream value``
    ``+ decision-relevant uncertainty exploration``
    ``- action/attention/risk costs``

    All inputs are normalized evidence claims.  The engine never invents a
    goal, promotes a metric to a goal, or treats silence as rejection.
    """

    def __init__(self, path: Path | None = None, *, now=time.time):
        self.path = Path(path) if path else None
        self.now = now
        self.stats: dict[str, OutcomeStats] = {}
        self.seen_outcomes: set[str] = set()
        self.total_decisions = 0

    @classmethod
    def load(cls, path: Path, *, now=time.time) -> "DecisionEngine":
        engine = cls(path, now=now)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            engine.total_decisions = int(data.get("total_decisions", 0))
            engine.seen_outcomes = set(data.get("seen_outcomes", []))
            for key, row in (data.get("stats") or {}).items():
                engine.stats[str(key)] = OutcomeStats(
                    attempts=int(row.get("attempts", 0)),
                    successes=int(row.get("successes", 0)),
                    failures=int(row.get("failures", 0)),
                    dismissals=int(row.get("dismissals", 0)),
                )
        except (OSError, TypeError, ValueError):
            pass
        return engine

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "total_decisions": self.total_decisions,
            "stats": {key: asdict(value) for key, value in self.stats.items()},
            "seen_outcomes": sorted(self.seen_outcomes)[-1000:],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def _score(self, candidate: Candidate) -> Score | None:
        if candidate.lane not in LANES or not candidate.executable:
            return None
        evidence = _unit(candidate.evidence) * _unit(candidate.confidence)
        stats = self.stats.setdefault(candidate.candidate_id, OutcomeStats())
        learned_success = stats.success_rate
        success = 0.5 * _unit(candidate.success_probability) + 0.5 * learned_success
        expected_gain = success * (
            0.45 * _unit(candidate.impact)
            + 0.30 * _unit(candidate.urgency)
            + 0.25 * _unit(candidate.blocker_relief)
        )
        information_value = _unit(candidate.information_gain) * _unit(candidate.downstream_value)
        uncertainty_bonus = 0.12 * information_value * stats.uncertainty
        attention_cost = _unit(candidate.interruption_cost) * (
            0.5 + 0.5 * _unit(candidate.urgency)
        )
        risk_cost = _unit(candidate.risk) * (1.0 - _unit(candidate.reversibility))
        cost = (
            0.25 * _unit(candidate.action_cost)
            + 0.35 * attention_cost
            + 0.40 * risk_cost
        )
        if risk_cost >= 0.8:
            cost += risk_cost
        value = evidence * (expected_gain + information_value + uncertainty_bonus) - cost
        reason = (
            f"evidence={evidence:.2f}; gain={expected_gain:.2f}; "
            f"info={information_value:.2f}; cost={cost:.2f}; "
            f"learned_success={learned_success:.2f}"
        )
        return Score(candidate.candidate_id, round(value, 6), round(expected_gain, 6),
                     round(information_value, 6), round(cost, 6),
                     round(uncertainty_bonus, 6), reason)

    def rank(self, candidates: list[Candidate]) -> list[tuple[Candidate, Score]]:
        ranked = []
        for candidate in candidates:
            score = self._score(candidate)
            if score is not None:
                ranked.append((candidate, score))
        ranked.sort(key=lambda item: item[1].value, reverse=True)
        return ranked

    def choose(self, candidates: list[Candidate]) -> Decision:
        ranked = self.rank(candidates)
        if not ranked:
            return Decision("wait", None, None, reason="没有证据充分且可执行的候选")
        selected, score = ranked[0]
        if score.value <= 0.0:
            return Decision(
                "wait", None, score,
                alternatives=[row[1] for row in ranked[1:]],
                reason="候选的预期改善不足以覆盖行动、风险和打扰成本",
            )
        self.total_decisions += 1
        return Decision(
            "act" if selected.lane in {"help", "maintenance"} else selected.lane,
            selected,
            score,
            alternatives=[row[1] for row in ranked[1:]],
            reason=score.reason,
        )

    def record_outcome(self, candidate_id: str, outcome: str, *, event_id: str) -> bool:
        """Update priors from an explicit result; duplicate events are ignored."""
        if event_id in self.seen_outcomes:
            return False
        if outcome not in {"success", "failure", "dismissed", "undone"}:
            raise ValueError(f"unknown outcome: {outcome}")
        stats = self.stats.setdefault(candidate_id, OutcomeStats())
        stats.attempts += 1
        if outcome == "success":
            stats.successes += 1
        elif outcome == "failure":
            stats.failures += 1
        elif outcome == "dismissed":
            stats.dismissals += 1
        elif outcome == "undone":
            stats.failures += 1
        self.seen_outcomes.add(event_id)
        self.save()
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_decisions": self.total_decisions,
            "stats": {key: asdict(value) for key, value in self.stats.items()},
        }
