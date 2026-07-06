"""In-memory MVP persistence for agent cycles and planner decisions.

The public interface (save_cycle, get_cycle, latest_cycle, save_decision)
is kept narrow so swapping this for SQLite later doesn't require touching
callers in routes.py.
"""

from __future__ import annotations

import threading

from app.agent.schemas import CycleResult
from app.data.models import PlannerDecision, Recommendation, RecommendationStatus

_lock = threading.Lock()
_cycles: dict[str, CycleResult] = {}
_cycle_order: list[str] = []
_decisions: dict[str, PlannerDecision] = {}
_decision_seq = 0


def save_cycle(cycle: CycleResult) -> None:
    with _lock:
        _cycles[cycle.cycle_id] = cycle
        _cycle_order.append(cycle.cycle_id)


def get_cycle(cycle_id: str) -> CycleResult | None:
    with _lock:
        return _cycles.get(cycle_id)


def latest_cycle() -> CycleResult | None:
    with _lock:
        if not _cycle_order:
            return None
        return _cycles[_cycle_order[-1]]


def save_decision(decision: PlannerDecision) -> None:
    with _lock:
        _decisions[decision.recommendation_id] = decision


def next_decision_seq() -> int:
    global _decision_seq
    with _lock:
        _decision_seq += 1
        return _decision_seq


def get_recommendation(recommendation_id: str) -> Recommendation | None:
    with _lock:
        for cycle_id in reversed(_cycle_order):
            for recommendation in _cycles[cycle_id].recommendations:
                if recommendation.id == recommendation_id:
                    return recommendation
    return None


def update_recommendation_status(
    recommendation_id: str, status: RecommendationStatus
) -> Recommendation | None:
    with _lock:
        for cycle_id in reversed(_cycle_order):
            for recommendation in _cycles[cycle_id].recommendations:
                if recommendation.id == recommendation_id:
                    recommendation.status = status
                    return recommendation
    return None
