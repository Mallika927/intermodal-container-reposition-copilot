"""Tests for the deterministic scoring engine (imbalance + candidates)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_imbalance_seed_42() -> None:
    state = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    params = get_scoring_params()
    report = compute_imbalance(state, params)

    severities = {entry.terminal: entry.severity.value for entry in report.entries}
    assert severities["KCS-IC"] == "critical"
    assert severities["HOU-BAR"] == "critical"
    assert severities["DEN-RG"] == "critical"
    assert severities["DAL-ITD"] == "warning"
    assert severities["CHI-G4"] == "surplus"
    assert severities["LAX-ICTF"] == "surplus"
    assert severities["SEA-SIG"] == "surplus"

    kcs_ic = next(entry for entry in report.entries if entry.terminal == "KCS-IC")
    assert kcs_ic.demand_72h == 251
    assert kcs_ic.projected_balance == -202


def test_candidates_window_feasibility() -> None:
    state = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    params = get_scoring_params()
    report = compute_imbalance(state, params)
    options = generate_candidates(state, report, params)

    lane = next(l for l in state.lanes if l.id == "LAX-ICTF_KCS-IC")
    kcs_booking = next(b for b in state.bookings if b.terminal_code == "KCS-IC")
    lane_trains = [t for t in state.trains if t.lane_id == lane.id]

    zlakc_02 = next(t for t in lane_trains if t.train_id == "ZLAKC-02")
    zlakc_02_arrival = zlakc_02.departs_ts + timedelta(hours=lane.transit_hrs)
    assert zlakc_02_arrival > kcs_booking.window_end, "test assumption: ZLAKC-02 must miss the window"

    feasible = [
        t for t in lane_trains
        if t.departs_ts + timedelta(hours=lane.transit_hrs) <= kcs_booking.window_end
    ]
    assert zlakc_02 not in feasible
    for option in options:
        if option.dest == "KCS-IC":
            assert option.slots_needing_projection == 0 or "ZLAKC-02" not in option.option_id

    confirmed_slots = sum(t.available_slots for t in feasible if not t.is_projected)
    projected_slots = sum(t.available_slots for t in feasible if t.is_projected)

    origin_entry = next(e for e in report.entries if e.terminal == "LAX-ICTF")
    deficit_entry = next(e for e in report.entries if e.terminal == "KCS-IC")
    floor = round(params.safety_floor_ratio * origin_entry.demand_72h)
    transferable = origin_entry.on_hand - floor
    deficit_size = abs(deficit_entry.projected_balance)

    expected_cover_units = min(deficit_size, transferable, confirmed_slots + projected_slots)

    cover_option = next(
        option
        for option in options
        if option.origin == "LAX-ICTF" and option.dest == "KCS-IC" and option.option_id.endswith("-cover")
    )
    assert cover_option.units == expected_cover_units
    assert cover_option.units <= 48


def test_floor_never_breached_except_aggressive() -> None:
    params = get_scoring_params()
    for seed in range(1, 51):
        state = generate_network_state(seed=seed, snapshot_ts=FIXED_SNAPSHOT_TS)
        report = compute_imbalance(state, params)
        options = generate_candidates(state, report, params)
        for option in options:
            variant = option.option_id.rsplit("-", 1)[-1]
            if variant != "aggressive":
                assert not option.origin_floor_breach, (
                    f"seed {seed}: {option.option_id} breached the floor outside the aggressive variant"
                )


def test_no_action_possible() -> None:
    params = get_scoring_params()

    for seed in range(1, 501):
        state = generate_network_state(seed=seed, snapshot_ts=FIXED_SNAPSHOT_TS)
        report = compute_imbalance(state, params)
        if not generate_candidates(state, report, params):
            return  # found a naturally-occurring no-action seed; branch proven

    # No such seed in 1-500: prove the branch with a hand-built, all-balanced state.
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
    state = NetworkState(
        snapshot_ts=FIXED_SNAPSHOT_TS,
        seed=0,
        terminals=[terminal],
        lanes=[],
        inventory=[inventory],
        bookings=[booking],
        trains=[],
    )
    report = compute_imbalance(state, params)
    assert all(entry.severity.value not in ("critical", "warning") for entry in report.entries)
    assert generate_candidates(state, report, params) == []


def test_purity() -> None:
    state = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    params = get_scoring_params()
    first = compute_imbalance(state, params)
    second = compute_imbalance(state, params)
    assert first.model_dump() == second.model_dump()
