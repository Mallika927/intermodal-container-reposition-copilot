"""Pydantic schemas for agent-loop outputs not part of the core domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.data.models import Recommendation


class CycleResult(BaseModel):
    """Everything produced by one run of the analysis cycle, including the
    full reasoning/tool-call trace for the UI to replay."""

    cycle_id: str
    started_ts: datetime
    completed_ts: datetime
    recommendations: list[Recommendation]
    no_action_rationale: str | None
    trace: list[dict[str, Any]]
