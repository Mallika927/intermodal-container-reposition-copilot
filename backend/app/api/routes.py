"""API routes exposing the synthetic network state."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.data.loader import get_network_state
from app.data.models import NetworkState

router = APIRouter()


@router.get("/network/state", response_model=NetworkState)
def read_network_state(
    seed: int | None = Query(default=None, description="Override SYNTHETIC_DATA_SEED"),
) -> NetworkState:
    return get_network_state(seed=seed)
