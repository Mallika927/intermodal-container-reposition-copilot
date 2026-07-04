"""Domain models for the Intermodal Container Reposition Copilot.

These pydantic models serve double duty:
1. Typed contracts for the synthetic data generator and scoring engine.
2. API response schemas for FastAPI (auto-documented at /docs).

Design principle: the LLM agent never computes economics. Every numeric
field on Recommendation must be traceable to a scoring-tool output.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TerminalProfile(str, Enum):
    """Structural imbalance personality. Used ONLY by the generator —
    the scoring engine must detect imbalance from the numbers, never
    read this label."""

    SURPLUS = "surplus"
    DEFICIT = "deficit"
    BALANCED = "balanced"


class EquipmentType(str, Enum):
    DRY_53 = "53FT-DRY"
    DRY_40 = "40FT-DRY"
    REEFER_53 = "53FT-REEFER"


class Severity(str, Enum):
    CRITICAL = "critical"  # projected deficit breaches service commitments
    WARNING = "warning"    # projected deficit within buffer tolerance
    OK = "ok"              # roughly balanced
    SURPLUS = "surplus"    # excess inventory incurring storage cost


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RecommendationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DecisionAction(str, Enum):
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# World entities (what real systems — EMS, TMS — would provide)
# ---------------------------------------------------------------------------


class Terminal(BaseModel):
    code: str = Field(..., examples=["CHI-G4"], description="Short terminal code")
    name: str = Field(..., examples=["Chicago Global IV"])
    profile: TerminalProfile = Field(
        ..., description="Generator-only imbalance personality; hidden from scoring"
    )
    daily_load_base: int = Field(..., ge=0, description="Baseline outbound loads/day")
    lot_capacity: int = Field(..., ge=0, description="Max units the lot can hold")


class Lane(BaseModel):
    id: str = Field(..., examples=["CHI-G4_DAL-ITD"])
    origin_code: str
    dest_code: str
    transit_hrs: int = Field(..., gt=0)
    cost_per_move_usd: int = Field(..., gt=0, description="Cost to reposition one empty")


class InventorySnapshot(BaseModel):
    id: str
    terminal_code: str
    equipment_type: EquipmentType
    snapshot_ts: datetime
    on_hand_empty: int = Field(..., ge=0)
    dwell_avg_days: float = Field(..., ge=0, description="Avg empty dwell in days")
    lot_utilization_pct: int = Field(..., ge=0, le=100)


class BookingForecast(BaseModel):
    id: str
    terminal_code: str
    equipment_type: EquipmentType
    window_start: datetime
    window_end: datetime
    booked_loads: int = Field(..., ge=0, description="Confirmed customer bookings")
    forecast_loads: int = Field(..., ge=0, description="Statistical demand beyond bookings")


class TrainCapacity(BaseModel):
    train_id: str = Field(..., examples=["ZCHDA-03"])
    lane_id: str
    departs_ts: datetime
    available_slots: int = Field(..., ge=0)
    is_projected: bool = Field(
        default=False,
        description="True if this consist is forecast, not yet confirmed",
    )


class NetworkState(BaseModel):
    """Complete synthetic world at one point in time. Same seed + ts
    must always produce an identical NetworkState."""

    snapshot_ts: datetime
    seed: int
    terminals: list[Terminal]
    lanes: list[Lane]
    inventory: list[InventorySnapshot]
    bookings: list[BookingForecast]
    trains: list[TrainCapacity]


# ---------------------------------------------------------------------------
# Scoring artifacts (deterministic — output of scoring.py, input to agent)
# ---------------------------------------------------------------------------


class ImbalanceEntry(BaseModel):
    terminal: str
    equipment_type: EquipmentType
    on_hand: int
    inbound_empties_72h: int
    demand_72h: int = Field(
        ..., description="booked * (1 - no_show_rate) + forecast"
    )
    projected_balance: int = Field(
        ..., description="Negative = deficit, positive = surplus"
    )
    severity: Severity


class ImbalanceReport(BaseModel):
    computed_at: datetime
    no_show_rate: float = Field(..., ge=0, le=1)
    entries: list[ImbalanceEntry]


class CandidateOption(BaseModel):
    option_id: str
    origin: str
    dest: str
    equipment_type: EquipmentType
    units: int = Field(..., gt=0)
    feasible_slots_72h: int = Field(..., ge=0, description="Confirmed train slots")
    slots_needing_projection: int = Field(
        ..., ge=0, description="Units relying on projected (unconfirmed) consists"
    )
    cost_usd: int
    revenue_protected_usd: int
    storage_savings_usd: int = 0
    net_usd: int
    origin_floor_breach: bool = Field(
        ..., description="True if this move drops origin below its safety floor"
    )
    note: str | None = None


# ---------------------------------------------------------------------------
# Agent artifacts (LLM-synthesized, every number traceable to scoring)
# ---------------------------------------------------------------------------


class ExecutionLeg(BaseModel):
    train_id: str
    units: int = Field(..., gt=0)
    confidence: float = Field(default=1.0, ge=0, le=1)


class Recommendation(BaseModel):
    id: str = Field(..., examples=["REC-2026-0703-114"])
    created_ts: datetime
    lane_id: str
    equipment_type: EquipmentType
    units: int = Field(..., gt=0)
    priority: Priority
    execution_legs: list[ExecutionLeg]
    cost_usd: int
    revenue_protected_usd: int
    net_benefit_usd: int
    reasoning_summary: str
    risks: list[str] = Field(default_factory=list)
    alternatives_considered: list[RejectedAlternative] = Field(default_factory=list)
    source_option_id: str = Field(
        ..., description="CandidateOption this recommendation is based on — audit trail"
    )
    status: RecommendationStatus = RecommendationStatus.PENDING
    expires_at: datetime


class RejectedAlternative(BaseModel):
    option_id: str
    summary: str = Field(..., examples=["Move 120 units CHI-G4 -> DAL-ITD"])
    rejected_because: str


# ---------------------------------------------------------------------------
# Human artifacts (the feedback loop)
# ---------------------------------------------------------------------------


class PlannerDecision(BaseModel):
    id: str = Field(..., examples=["DEC-2026-0703-088"])
    recommendation_id: str
    action: DecisionAction
    modified_units: int | None = Field(
        default=None, description="Only set when action == modified"
    )
    reason: str | None = Field(
        default=None,
        description="Planner's stated rationale — tacit knowledge capture",
    )
    decided_ts: datetime


# Resolve forward reference (RejectedAlternative defined after Recommendation)
Recommendation.model_rebuild()