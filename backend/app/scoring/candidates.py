"""Deterministic candidate-option generation for empty repositioning moves.

Pure function: given a NetworkState and its ImbalanceReport, propose
origin (surplus) -> destination (deficit) repositioning options bounded
by lane existence, train window feasibility, train slot capacity, and
each origin's safety floor.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.data.models import (
    BookingForecast,
    CandidateOption,
    ImbalanceEntry,
    ImbalanceReport,
    InventorySnapshot,
    Lane,
    NetworkState,
    Severity,
    TrainCapacity,
)
from app.scoring.params import ScoringParams

_DEFICIT_SEVERITIES = (Severity.CRITICAL, Severity.WARNING)


def _feasible_trains(
    trains: list[TrainCapacity], lane: Lane, window_end: datetime
) -> list[TrainCapacity]:
    feasible = [
        train
        for train in trains
        if train.lane_id == lane.id
        and train.departs_ts + timedelta(hours=lane.transit_hrs) <= window_end
    ]
    feasible.sort(key=lambda train: train.departs_ts)
    return feasible


def _build_note(*, floor_breach: bool, flips_negative: bool, variant: str) -> str | None:
    if not floor_breach and not flips_negative:
        return None
    prefix = "Aggressive variant" if variant == "aggressive" else "This move"
    if flips_negative:
        return f"{prefix} would drop origin on-hand below zero — treat as a capacity ceiling, not a feasible plan."
    return f"{prefix} breaches the origin safety floor."


def generate_candidates(
    state: NetworkState, report: ImbalanceReport, params: ScoringParams
) -> list[CandidateOption]:
    deficits = [entry for entry in report.entries if entry.severity in _DEFICIT_SEVERITIES]
    if not deficits:
        return []

    worst_deficit = min(entry.projected_balance for entry in deficits)
    if worst_deficit > -params.no_action_min_deficit:
        return []

    origins = [entry for entry in report.entries if entry.severity == Severity.SURPLUS]
    if not origins:
        return []

    lanes_by_od: dict[tuple[str, str], Lane] = {
        (lane.origin_code, lane.dest_code): lane for lane in state.lanes
    }
    bookings_by_terminal: dict[str, BookingForecast] = {
        booking.terminal_code: booking for booking in state.bookings
    }
    inventory_by_terminal: dict[str, InventorySnapshot] = {
        inv.terminal_code: inv for inv in state.inventory
    }

    options: list[CandidateOption] = []

    for deficit in deficits:
        deficit_size = abs(deficit.projected_balance)
        deficit_booking = bookings_by_terminal[deficit.terminal]

        for origin in origins:
            lane = lanes_by_od.get((origin.terminal, deficit.terminal))
            if lane is None:
                continue

            feasible = _feasible_trains(state.trains, lane, deficit_booking.window_end)
            confirmed_slots = sum(train.available_slots for train in feasible if not train.is_projected)
            projected_slots = sum(train.available_slots for train in feasible if train.is_projected)
            total_slots = confirmed_slots + projected_slots

            floor = round(params.safety_floor_ratio * origin.demand_72h)
            transferable = origin.on_hand - floor
            origin_dwell_days = inventory_by_terminal[origin.terminal].dwell_avg_days

            variants: list[tuple[str, int]] = [
                ("cover", min(deficit_size, transferable, total_slots)),
                ("confirmed", min(deficit_size, transferable, confirmed_slots)),
                (
                    "aggressive",
                    min(round(deficit_size * params.aggressive_multiplier), total_slots),
                ),
            ]

            seen_units: set[int] = set()
            for variant, units in variants:
                if units <= 0 or units in seen_units:
                    continue
                seen_units.add(units)

                origin_floor_breach = units > transferable
                flips_negative = origin.on_hand - units < 0
                slots_needing_projection = max(0, units - confirmed_slots)
                cost_usd = units * lane.cost_per_move_usd
                revenue_protected_usd = min(units, deficit_size) * params.revenue_per_load_usd
                storage_savings_usd = (
                    units
                    * params.storage_cost_per_unit_day_usd
                    * min(int(origin_dwell_days), params.storage_savings_max_days)
                )
                net_usd = revenue_protected_usd + storage_savings_usd - cost_usd
                if net_usd <= 0:
                    continue

                options.append(
                    CandidateOption(
                        option_id=f"OPT-{origin.terminal}-{deficit.terminal}-{variant}",
                        origin=origin.terminal,
                        dest=deficit.terminal,
                        equipment_type=deficit.equipment_type,
                        units=units,
                        feasible_slots_72h=confirmed_slots,
                        slots_needing_projection=slots_needing_projection,
                        cost_usd=cost_usd,
                        revenue_protected_usd=revenue_protected_usd,
                        storage_savings_usd=storage_savings_usd,
                        net_usd=net_usd,
                        origin_floor_breach=origin_floor_breach,
                        note=_build_note(
                            floor_breach=origin_floor_breach,
                            flips_negative=flips_negative,
                            variant=variant,
                        ),
                    )
                )

    options.sort(key=lambda option: option.net_usd, reverse=True)
    return options
