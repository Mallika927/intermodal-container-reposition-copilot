"""API routes exposing the synthetic network state and scoring engine."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.data.loader import get_network_state
from app.data.models import CandidateOption, ImbalanceReport, NetworkState
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import get_scoring_params

router = APIRouter()


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
