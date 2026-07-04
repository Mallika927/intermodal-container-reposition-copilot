"""Deterministic synthetic network state generator.

Given a (seed, snapshot_ts) pair this module produces a byte-identical
NetworkState every time. All randomness must flow through a single
`Random(seed)` instance created inside `generate_network_state` — never
through the global `random` module.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from random import Random

from app.data.models import (
    BookingForecast,
    EquipmentType,
    InventorySnapshot,
    Lane,
    NetworkState,
    Terminal,
    TerminalProfile,
    TrainCapacity,
)
from app.data.network import LANES, TERMINALS

BOOKING_WINDOW_HOURS = 72

# dwell_avg_days range per profile — unaffected by the demand-derived
# on-hand math below.
_DWELL_RANGES: dict[TerminalProfile, tuple[float, float]] = {
    TerminalProfile.SURPLUS: (3.0, 5.0),
    TerminalProfile.DEFICIT: (0.5, 1.5),
    TerminalProfile.BALANCED: (1.5, 3.0),
}

# on_hand_empty = round(demand_72h * multiplier). Surplus terminals carry
# 1.7-2.2x their 72h demand in empties; deficit terminals only 0.15-0.35x;
# balanced terminals roughly track demand.
_ON_HAND_MULTIPLIER_RANGES: dict[TerminalProfile, tuple[float, float]] = {
    TerminalProfile.SURPLUS: (1.7, 2.2),
    TerminalProfile.DEFICIT: (0.15, 0.35),
    TerminalProfile.BALANCED: (0.8, 1.15),
}

# Anomaly variants: a deficit terminal generating healthy, or a balanced
# terminal generating mildly short, so imbalance detection isn't trivial.
# Implemented by swapping to an adjacent profile's multiplier/dwell band,
# never by nudging the derived on_hand afterward.
_ANOMALY_CHANCE = 0.10
_DEFICIT_HEALTHY_DWELL_RANGE = (2.0, 3.5)
_BALANCED_SHORT_DWELL_RANGE = (0.8, 1.8)

_LOT_CAPACITY_SAFETY_FACTOR = 0.97

# (min, max) demand factor applied to daily_load_base * 3 for 72h bookings.
_DEMAND_FACTOR_RANGES: dict[TerminalProfile, tuple[float, float]] = {
    TerminalProfile.DEFICIT: (0.9, 1.1),
    TerminalProfile.SURPLUS: (0.5, 0.7),
    TerminalProfile.BALANCED: (0.7, 0.9),
}

_FORECAST_PCT_RANGE = (0.10, 0.25)
_TRAIN_COUNT_RANGE = (2, 3)
_TRAIN_SLOTS_RANGE = (10, 60)


def _abbr(terminal_code: str) -> str:
    return terminal_code.split("-")[0][:2].upper()


def _generate_inventory(
    terminal: Terminal, rng: Random, snapshot_ts: datetime, demand_72h: int
) -> InventorySnapshot:
    anomaly_roll = rng.random()
    if terminal.profile == TerminalProfile.DEFICIT and anomaly_roll < _ANOMALY_CHANCE:
        mult_range = _ON_HAND_MULTIPLIER_RANGES[TerminalProfile.BALANCED]
        dwell_range = _DEFICIT_HEALTHY_DWELL_RANGE
    elif terminal.profile == TerminalProfile.BALANCED and anomaly_roll < _ANOMALY_CHANCE:
        mult_range = _ON_HAND_MULTIPLIER_RANGES[TerminalProfile.DEFICIT]
        dwell_range = _BALANCED_SHORT_DWELL_RANGE
    else:
        mult_range = _ON_HAND_MULTIPLIER_RANGES[terminal.profile]
        dwell_range = _DWELL_RANGES[terminal.profile]

    on_hand_empty = round(demand_72h * rng.uniform(*mult_range))
    if on_hand_empty > terminal.lot_capacity:
        on_hand_empty = round(terminal.lot_capacity * _LOT_CAPACITY_SAFETY_FACTOR)

    dwell_avg_days = round(rng.uniform(*dwell_range), 2)
    lot_utilization_pct = round(on_hand_empty / terminal.lot_capacity * 100)

    return InventorySnapshot(
        id=f"INV-{terminal.code}-{snapshot_ts:%Y%m%d%H}",
        terminal_code=terminal.code,
        equipment_type=EquipmentType.DRY_53,
        snapshot_ts=snapshot_ts,
        on_hand_empty=on_hand_empty,
        dwell_avg_days=dwell_avg_days,
        lot_utilization_pct=lot_utilization_pct,
    )


def _generate_booking(terminal: Terminal, rng: Random, snapshot_ts: datetime) -> BookingForecast:
    factor_lo, factor_hi = _DEMAND_FACTOR_RANGES[terminal.profile]
    factor = rng.uniform(factor_lo, factor_hi)
    booked_loads = round(terminal.daily_load_base * 3 * factor)

    forecast_pct = rng.uniform(*_FORECAST_PCT_RANGE)
    forecast_loads = round(booked_loads * forecast_pct)

    window_start = snapshot_ts
    window_end = snapshot_ts + timedelta(hours=BOOKING_WINDOW_HOURS)

    return BookingForecast(
        id=f"BKG-{terminal.code}-{snapshot_ts:%Y%m%d%H}",
        terminal_code=terminal.code,
        equipment_type=EquipmentType.DRY_53,
        window_start=window_start,
        window_end=window_end,
        booked_loads=booked_loads,
        forecast_loads=forecast_loads,
    )


def _generate_trains_for_lane(lane: Lane, rng: Random, snapshot_ts: datetime) -> list[TrainCapacity]:
    num_trains = rng.randint(*_TRAIN_COUNT_RANGE)
    interval_hrs = BOOKING_WINDOW_HOURS / (num_trains + 1)
    origin_abbr = _abbr(lane.origin_code)
    dest_abbr = _abbr(lane.dest_code)

    trains: list[TrainCapacity] = []
    for i in range(num_trains):
        departs_ts = snapshot_ts + timedelta(hours=interval_hrs * (i + 1))
        available_slots = rng.randint(*_TRAIN_SLOTS_RANGE)
        trains.append(
            TrainCapacity(
                train_id=f"Z{origin_abbr}{dest_abbr}-{i + 1:02d}",
                lane_id=lane.id,
                departs_ts=departs_ts,
                available_slots=available_slots,
                is_projected=(i == num_trains - 1),
            )
        )
    return trains


def generate_network_state(seed: int, snapshot_ts: datetime) -> NetworkState:
    """Deterministically synthesize the network world for (seed, snapshot_ts).

    NOTE: Terminal.profile is consumed here only, to bias the random
    draws below. Nothing downstream (scoring, agent, API consumers) may
    read Terminal.profile — imbalance must be inferred from the numbers.
    """
    rng = Random(seed)

    inventory: list[InventorySnapshot] = []
    bookings: list[BookingForecast] = []
    for terminal in TERMINALS:
        booking = _generate_booking(terminal, rng, snapshot_ts)
        bookings.append(booking)
        demand_72h = booking.booked_loads + booking.forecast_loads
        inventory.append(_generate_inventory(terminal, rng, snapshot_ts, demand_72h))
    trains = [
        train
        for lane in LANES
        for train in _generate_trains_for_lane(lane, rng, snapshot_ts)
    ]

    return NetworkState(
        snapshot_ts=snapshot_ts,
        seed=seed,
        terminals=list(TERMINALS),
        lanes=list(LANES),
        inventory=inventory,
        bookings=bookings,
        trains=trains,
    )
