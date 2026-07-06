"""Deterministic replay mode: builds a CycleResult without any LLM calls.

Used when USE_REPLAY_MODE is enabled (e.g. demos, offline dev, CI) so the
UI has something to stream. The recommendation-picking logic here is a
simple deterministic stand-in for the model's judgment — every number is
still copied exactly from a CandidateOption, same as the audited live path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agent.schemas import CycleResult
from app.agent.tools import execute_tool
from app.data.loader import get_network_state
from app.data.models import (
    CandidateOption,
    ExecutionLeg,
    ImbalanceEntry,
    Lane,
    NetworkState,
    Priority,
    Recommendation,
    RecommendationStatus,
    RejectedAlternative,
    Severity,
)
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import get_scoring_params


def _execution_legs(
    option: CandidateOption, lane: Lane, state: NetworkState, window_end: datetime
) -> list[ExecutionLeg]:
    feasible = [
        train
        for train in state.trains
        if train.lane_id == lane.id
        and train.departs_ts + timedelta(hours=lane.transit_hrs) <= window_end
    ]
    feasible.sort(key=lambda train: train.departs_ts)
    confirmed = [train for train in feasible if not train.is_projected]
    projected = [train for train in feasible if train.is_projected]

    legs: list[ExecutionLeg] = []
    remaining = option.units
    for train in confirmed + projected:
        if remaining <= 0:
            break
        take = min(train.available_slots, remaining)
        if take <= 0:
            continue
        confidence = 0.75 if train.is_projected else 1.0
        legs.append(ExecutionLeg(train_id=train.train_id, units=take, confidence=confidence))
        remaining -= take
    return legs


def _rejected_because(chosen: CandidateOption, runner_up: CandidateOption) -> str:
    if runner_up.origin_floor_breach:
        return f"Breaches {runner_up.origin}'s safety floor despite a higher headline net value."
    return f"Lower net value (${runner_up.net_usd:,} vs ${chosen.net_usd:,} for the chosen option)."


def _reasoning_summary(
    deficit: ImbalanceEntry, chosen: CandidateOption, lane: Lane, coverage_gap: int
) -> str:
    coverage_clause = (
        f"even with this move, {coverage_gap} units of the gap remain uncovered within the "
        "72h window."
        if coverage_gap > 0
        else "this move fully covers the projected gap within the 72h window."
    )
    return (
        f"{deficit.terminal} is projected {abs(deficit.projected_balance)} units short of "
        f"72h demand (balance {deficit.projected_balance}). Repositioning {chosen.units} "
        f"units from {chosen.origin} via {lane.id} is the strongest available option by net "
        f"value; {coverage_clause}"
    )


def _risks_for(legs: list[ExecutionLeg], deficit: ImbalanceEntry, coverage_gap: int) -> list[str]:
    risks = [
        f"{leg.units} units on train {leg.train_id} rely on a projected (unconfirmed) consist."
        for leg in legs
        if leg.confidence < 1.0
    ]
    if coverage_gap > 0:
        risks.append(
            f"{coverage_gap} units of {deficit.terminal}'s deficit remain uncovered in-window "
            "even after this move."
        )
    return risks


def build_replay_cycle(seed: int | None) -> CycleResult:
    """Deterministically build a CycleResult for `seed`, with zero API calls."""
    started_ts = datetime.now(timezone.utc)
    state = get_network_state(seed=seed)
    params = get_scoring_params()

    report = compute_imbalance(state, params)
    options = generate_candidates(state, report, params)

    trace: list[dict[str, Any]] = []
    trace.append(
        {"type": "text", "text": "Let me start by pulling the current imbalance report for the network."}
    )
    imbalance_output = execute_tool("get_imbalance_report", {}, state, params)
    trace.append({"type": "tool_call", "name": "get_imbalance_report", "input": {}})
    trace.append({"type": "tool_result", "name": "get_imbalance_report", "output": imbalance_output})

    critical_entries = [entry for entry in report.entries if entry.severity == Severity.CRITICAL]
    trace.append(
        {
            "type": "text",
            "text": (
                f"{len(critical_entries)} terminal(s) at critical severity. Checking candidate "
                "repositioning options."
            ),
        }
    )
    candidates_output = execute_tool("get_candidate_options", {}, state, params)
    trace.append({"type": "tool_call", "name": "get_candidate_options", "input": {}})
    trace.append({"type": "tool_result", "name": "get_candidate_options", "output": candidates_output})

    lanes_by_od: dict[tuple[str, str], Lane] = {
        (lane.origin_code, lane.dest_code): lane for lane in state.lanes
    }
    options_by_dest: dict[str, list[CandidateOption]] = {}
    for option in options:
        options_by_dest.setdefault(option.dest, []).append(option)

    used_lanes: set[str] = set()
    raw_recommendations: list[dict[str, Any]] = []
    recommendations: list[Recommendation] = []
    expires_at = state.snapshot_ts + timedelta(hours=12)

    for deficit in critical_entries:
        candidates_for_dest = options_by_dest.get(deficit.terminal, [])
        eligible = [
            option
            for option in candidates_for_dest
            if not option.origin_floor_breach
            and lanes_by_od[(option.origin, option.dest)].id not in used_lanes
        ]
        if not eligible:
            continue

        chosen = eligible[0]
        lane = lanes_by_od[(chosen.origin, chosen.dest)]
        used_lanes.add(lane.id)

        runner_up = next(
            (option for option in candidates_for_dest if option.option_id != chosen.option_id),
            None,
        )

        deficit_booking_window_end = next(
            booking.window_end for booking in state.bookings if booking.terminal_code == deficit.terminal
        )
        legs = _execution_legs(chosen, lane, state, deficit_booking_window_end)
        coverage_gap = max(0, abs(deficit.projected_balance) - chosen.units)

        alternatives_considered = (
            [
                RejectedAlternative(
                    option_id=runner_up.option_id,
                    summary=f"Move {runner_up.units} units {runner_up.origin} -> {runner_up.dest}",
                    rejected_because=_rejected_because(chosen, runner_up),
                )
            ]
            if runner_up is not None
            else []
        )

        raw = {
            "lane_id": lane.id,
            "equipment_type": chosen.equipment_type.value,
            "units": chosen.units,
            "priority": Priority.HIGH.value,
            "execution_legs": [leg.model_dump(mode="json") for leg in legs],
            "cost_usd": chosen.cost_usd,
            "revenue_protected_usd": chosen.revenue_protected_usd,
            "net_benefit_usd": chosen.net_usd,
            "reasoning_summary": _reasoning_summary(deficit, chosen, lane, coverage_gap),
            "risks": _risks_for(legs, deficit, coverage_gap),
            "alternatives_considered": [alt.model_dump(mode="json") for alt in alternatives_considered],
            "source_option_id": chosen.option_id,
        }
        raw_recommendations.append(raw)

        rec_id = f"REC-{started_ts.year}-{started_ts:%m%d}-{len(recommendations) + 1:03d}"
        recommendations.append(
            Recommendation(
                id=rec_id,
                created_ts=started_ts,
                status=RecommendationStatus.PENDING,
                expires_at=expires_at,
                **raw,
            )
        )

    no_action_rationale = None
    if not recommendations:
        no_action_rationale = (
            "No critical-severity deficit terminal has a non-floor-breaching candidate "
            "option available this cycle; no repositioning action is warranted."
            if critical_entries
            else "No terminals are at critical severity this cycle; no repositioning action is warranted."
        )

    trace.append(
        {
            "type": "tool_call",
            "name": "submit_recommendations",
            "input": {
                "recommendations": raw_recommendations,
                "no_action_rationale": no_action_rationale,
            },
        }
    )

    return CycleResult(
        cycle_id=f"CYCLE-{uuid.uuid4().hex[:12]}",
        started_ts=started_ts,
        completed_ts=datetime.now(timezone.utc),
        recommendations=recommendations,
        no_action_rationale=no_action_rationale,
        trace=trace,
        replay=True,
    )
