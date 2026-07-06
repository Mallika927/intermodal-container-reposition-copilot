"""API routes exposing the synthetic network state, scoring engine, and agent."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agent.loop import run_analysis_cycle
from app.agent.replay import build_replay_cycle
from app.agent.schemas import CycleResult
from app.agent.store import (
    get_recommendation,
    latest_cycle,
    next_decision_seq,
    save_cycle,
    save_decision,
    update_recommendation_status,
)
from app.data.loader import get_network_state
from app.data.models import (
    CandidateOption,
    DecisionAction,
    ImbalanceReport,
    NetworkState,
    PlannerDecision,
    RecommendationStatus,
)
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import get_scoring_params

router = APIRouter()


class _AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    use_replay_mode: bool = False


class DecisionRequest(BaseModel):
    action: DecisionAction
    modified_units: int | None = None
    reason: str | None = None


@router.get("/network/state", response_model=NetworkState)
def read_network_state(
    seed: int | None = Query(default=None, description="Override SYNTHETIC_DATA_SEED"),
) -> NetworkState:
    return get_network_state(seed=seed)


@router.get("/scoring/imbalance", response_model=ImbalanceReport)
def read_imbalance(
    seed: int | None = Query(default=None, description="Override SYNTHETIC_DATA_SEED"),
) -> ImbalanceReport:
    state = get_network_state(seed=seed)
    return compute_imbalance(state, get_scoring_params())


@router.get("/scoring/candidates", response_model=list[CandidateOption])
def read_candidates(
    seed: int | None = Query(default=None, description="Override SYNTHETIC_DATA_SEED"),
) -> list[CandidateOption]:
    state = get_network_state(seed=seed)
    params = get_scoring_params()
    report = compute_imbalance(state, params)
    return generate_candidates(state, report, params)


@router.post("/agent/run", response_model=CycleResult)
async def run_agent_cycle(
    seed: int | None = Query(default=None, description="Override SYNTHETIC_DATA_SEED"),
) -> CycleResult:
    if _AgentSettings().use_replay_mode:
        cycle = build_replay_cycle(seed)
    else:
        cycle = await run_analysis_cycle(seed=seed)
    save_cycle(cycle)
    return cycle


@router.get("/agent/cycles/latest", response_model=CycleResult)
def read_latest_cycle() -> CycleResult:
    cycle = latest_cycle()
    if cycle is None:
        raise HTTPException(status_code=404, detail="No cycles have run yet.")
    return cycle


@router.post("/recommendations/{rec_id}/decision", response_model=PlannerDecision)
def submit_decision(rec_id: str, body: DecisionRequest) -> PlannerDecision:
    recommendation = get_recommendation(rec_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail=f"Recommendation '{rec_id}' not found.")

    if body.action == DecisionAction.MODIFIED and body.modified_units is None:
        raise HTTPException(
            status_code=422, detail="modified_units is required when action is 'modified'."
        )
    if body.action == DecisionAction.REJECTED and not body.reason:
        raise HTTPException(status_code=422, detail="reason is required when action is 'rejected'.")

    now = datetime.now(timezone.utc)
    decision = PlannerDecision(
        id=f"DEC-{now.year}-{now:%m%d}-{next_decision_seq():03d}",
        recommendation_id=rec_id,
        action=body.action,
        modified_units=body.modified_units,
        reason=body.reason,
        decided_ts=now,
    )
    save_decision(decision)
    update_recommendation_status(rec_id, RecommendationStatus(body.action.value))
    return decision
