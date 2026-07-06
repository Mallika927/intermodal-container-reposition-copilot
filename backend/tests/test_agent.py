"""Tests for the agent loop, audit gate, and agent/decision endpoints.

No network calls are made: the Anthropic client is replaced with a
FakeClient that returns scripted responses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.agent import loop as loop_module
from app.agent.loop import AgentAuditError, run_analysis_cycle
from app.data.generator import generate_network_state
from app.data.models import (
    BookingForecast,
    EquipmentType,
    InventorySnapshot,
    NetworkState,
    Terminal,
    TerminalProfile,
)
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import get_scoring_params

FIXED_SNAPSHOT_TS = datetime(2026, 7, 4, 23, 0, 0, tzinfo=timezone.utc)


@dataclass
class FakeContentBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class FakeMessage:
    stop_reason: str
    content: list[FakeContentBlock]


class FakeMessagesResource:
    def __init__(self, responses: list[FakeMessage]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def create(self, **kwargs: Any) -> FakeMessage:
        self.call_count += 1
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self._responses.pop(0)


@dataclass
class FakeClient:
    responses: list[FakeMessage]
    messages: FakeMessagesResource = field(init=False)

    def __post_init__(self) -> None:
        self.messages = FakeMessagesResource(self.responses)


def _tool_use_message(tool_use_id: str, name: str, tool_input: dict[str, Any]) -> FakeMessage:
    return FakeMessage(
        stop_reason="tool_use",
        content=[FakeContentBlock(type="tool_use", id=tool_use_id, name=name, input=tool_input)],
    )


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list[FakeMessage]) -> FakeClient:
    fake = FakeClient(responses=responses)
    monkeypatch.setattr(loop_module, "_build_client", lambda: fake)
    return fake


def _seed_42_top_option_submission() -> dict[str, Any]:
    """Build a valid submit_recommendations payload for seed 42's top option,
    with every number copied directly from the real candidate list."""
    state = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    params = get_scoring_params()
    report = compute_imbalance(state, params)
    options = generate_candidates(state, report, params)

    top = options[0]
    assert top.option_id == "OPT-LAX-ICTF-DEN-RG-cover"
    runner_up = next(o for o in options if o.option_id == "OPT-CHI-G4-KCS-IC-cover")
    lane = next(l for l in state.lanes if l.origin_code == top.origin and l.dest_code == top.dest)

    confirmed_units = top.feasible_slots_72h
    projected_units = top.units - confirmed_units

    recommendation = {
        "lane_id": lane.id,
        "equipment_type": top.equipment_type.value,
        "units": top.units,
        "priority": "HIGH",
        "execution_legs": [
            {"train_id": "ZLADE-01", "units": confirmed_units, "confidence": 1.0},
            {"train_id": "ZLADE-02", "units": projected_units, "confidence": 0.75},
        ],
        "cost_usd": top.cost_usd,
        "revenue_protected_usd": top.revenue_protected_usd,
        "net_benefit_usd": top.net_usd,
        "reasoning_summary": (
            "DEN-RG is critically short of empties against 72h demand. "
            "LAX-ICTF has surplus capacity and a direct lane; part of the "
            "move relies on a projected train since confirmed slots don't "
            "fully cover the gap."
        ),
        "risks": [
            f"{projected_units} of {top.units} units ride on projected train ZLADE-02, not yet confirmed."
        ],
        "alternatives_considered": [
            {
                "option_id": runner_up.option_id,
                "summary": f"Move {runner_up.units} units {runner_up.origin} -> {runner_up.dest}",
                "rejected_because": "Lower net value and targets a different deficit terminal.",
            }
        ],
        "source_option_id": top.option_id,
    }
    return {"recommendations": [recommendation], "no_action_rationale": None}


def test_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    submission = _seed_42_top_option_submission()
    fake = _install_fake_client(
        monkeypatch,
        [
            _tool_use_message("tu_1", "get_imbalance_report", {}),
            _tool_use_message("tu_2", "get_candidate_options", {}),
            _tool_use_message("tu_3", "submit_recommendations", submission),
        ],
    )

    result = asyncio.run(run_analysis_cycle(seed=42))

    assert result.no_action_rationale is None
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.status.value == "pending"
    assert rec.source_option_id == "OPT-LAX-ICTF-DEN-RG-cover"
    assert fake.messages.call_count == 3
    model_turns = [entry for entry in result.trace if entry["type"] == "tool_call"]
    assert len(model_turns) == 3


def test_audit_gate_catches_altered_number(monkeypatch: pytest.MonkeyPatch) -> None:
    good_submission = _seed_42_top_option_submission()
    bad_submission = {
        "recommendations": [
            {**good_submission["recommendations"][0], "cost_usd": good_submission["recommendations"][0]["cost_usd"] + 1}
        ],
        "no_action_rationale": None,
    }

    fake = _install_fake_client(
        monkeypatch,
        [
            _tool_use_message("tu_1", "get_imbalance_report", {}),
            _tool_use_message("tu_2", "get_candidate_options", {}),
            _tool_use_message("tu_3", "submit_recommendations", bad_submission),
            _tool_use_message("tu_4", "submit_recommendations", good_submission),
        ],
    )

    result = asyncio.run(run_analysis_cycle(seed=42))

    assert result.recommendations[0].cost_usd == good_submission["recommendations"][0]["cost_usd"]
    assert fake.messages.call_count == 4
    error_results = [entry for entry in result.trace if entry.get("is_error")]
    assert len(error_results) == 1
    assert "cost_usd" in error_results[0]["output"]


def test_audit_gate_hard_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    good_submission = _seed_42_top_option_submission()
    bad_submission = {
        "recommendations": [
            {**good_submission["recommendations"][0], "cost_usd": good_submission["recommendations"][0]["cost_usd"] + 1}
        ],
        "no_action_rationale": None,
    }

    _install_fake_client(
        monkeypatch,
        [
            _tool_use_message("tu_1", "get_imbalance_report", {}),
            _tool_use_message("tu_2", "get_candidate_options", {}),
            _tool_use_message("tu_3", "submit_recommendations", bad_submission),
            _tool_use_message("tu_4", "submit_recommendations", bad_submission),
        ],
    )

    with pytest.raises(AgentAuditError):
        asyncio.run(run_analysis_cycle(seed=42))


def _balanced_state() -> NetworkState:
    terminal = Terminal(
        code="AAA",
        name="Test Terminal",
        profile=TerminalProfile.BALANCED,
        daily_load_base=50,
        lot_capacity=200,
    )
    inventory = InventorySnapshot(
        id="INV-AAA-TEST",
        terminal_code="AAA",
        equipment_type=EquipmentType.DRY_53,
        snapshot_ts=FIXED_SNAPSHOT_TS,
        on_hand_empty=100,
        dwell_avg_days=1.0,
        lot_utilization_pct=50,
    )
    booking = BookingForecast(
        id="BKG-AAA-TEST",
        terminal_code="AAA",
        equipment_type=EquipmentType.DRY_53,
        window_start=FIXED_SNAPSHOT_TS,
        window_end=FIXED_SNAPSHOT_TS + timedelta(hours=72),
        booked_loads=50,
        forecast_loads=10,
    )
    return NetworkState(
        snapshot_ts=FIXED_SNAPSHOT_TS,
        seed=0,
        terminals=[terminal],
        lanes=[],
        inventory=[inventory],
        bookings=[booking],
        trains=[],
    )


def test_no_action_path(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _balanced_state()
    monkeypatch.setattr(loop_module, "get_network_state", lambda seed=None: state)

    submission = {
        "recommendations": [],
        "no_action_rationale": "All terminals are within tolerance; no deficit requires action.",
    }
    _install_fake_client(
        monkeypatch,
        [
            _tool_use_message("tu_1", "get_imbalance_report", {}),
            _tool_use_message("tu_2", "get_candidate_options", {}),
            _tool_use_message("tu_3", "submit_recommendations", submission),
        ],
    )

    result = asyncio.run(run_analysis_cycle(seed=None))

    assert result.recommendations == []
    assert result.no_action_rationale == submission["no_action_rationale"]


def test_decision_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    submission = _seed_42_top_option_submission()
    _install_fake_client(
        monkeypatch,
        [
            _tool_use_message("tu_1", "get_imbalance_report", {}),
            _tool_use_message("tu_2", "get_candidate_options", {}),
            _tool_use_message("tu_3", "submit_recommendations", submission),
        ],
    )

    client = TestClient(app)
    run_response = client.post("/api/agent/run", params={"seed": 42})
    assert run_response.status_code == 200
    cycle = run_response.json()
    rec_id = cycle["recommendations"][0]["id"]

    decision_response = client.post(
        f"/api/recommendations/{rec_id}/decision",
        json={"action": "modified", "modified_units": 80, "reason": "Reduced to match yard capacity."},
    )
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["recommendation_id"] == rec_id
    assert decision["action"] == "modified"

    latest = client.get("/api/agent/cycles/latest")
    assert latest.status_code == 200
    updated_rec = next(r for r in latest.json()["recommendations"] if r["id"] == rec_id)
    assert updated_rec["status"] == "modified"
