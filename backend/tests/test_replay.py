"""Tests for deterministic replay-mode cycles (no API calls)."""

from __future__ import annotations

from app.agent.loop import _audit_submission
from app.agent.replay import build_replay_cycle
from app.agent.schemas import CycleResult
from app.data.loader import get_network_state
from app.scoring.params import get_scoring_params


def test_replay_cycle_passes_audit_gate_and_validates() -> None:
    cycle = build_replay_cycle(42)

    assert cycle.replay is True
    assert isinstance(cycle, CycleResult)
    CycleResult.model_validate(cycle.model_dump())

    submit_call = next(
        entry
        for entry in cycle.trace
        if entry["type"] == "tool_call" and entry["name"] == "submit_recommendations"
    )

    state = get_network_state(seed=42)
    params = get_scoring_params()
    error = _audit_submission(submit_call["input"], state, params)
    assert error is None
