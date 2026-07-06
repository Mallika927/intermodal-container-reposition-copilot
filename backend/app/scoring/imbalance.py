"""Deterministic imbalance computation from a NetworkState snapshot.

MVP limitation: inbound_empties_72h is hardcoded to 0 — no inbound loaded
flows (empties returning from other terminals) are modeled yet, so
projected_balance today reduces to on_hand minus demand. The field is
kept and added into the formula so this stays forward-compatible once
inbound flows are modeled.
"""

from __future__ import annotations

from app.data.models import (
    BookingForecast,
    EquipmentType,
    ImbalanceEntry,
    ImbalanceReport,
    NetworkState,
    Severity,
)
from app.scoring.params import ScoringParams


def _severity(balance: int, params: ScoringParams) -> Severity:
    if balance <= params.critical_threshold:
        return Severity.CRITICAL
    if balance <= params.warning_threshold:
        return Severity.WARNING
    if balance >= params.surplus_threshold:
        return Severity.SURPLUS
    return Severity.OK


def compute_imbalance(state: NetworkState, params: ScoringParams) -> ImbalanceReport:
    bookings_by_key: dict[tuple[str, EquipmentType], BookingForecast] = {
        (booking.terminal_code, booking.equipment_type): booking for booking in state.bookings
    }

    entries: list[ImbalanceEntry] = []
    for inv in state.inventory:
        booking = bookings_by_key[(inv.terminal_code, inv.equipment_type)]
        demand_72h = (
            round(booking.booked_loads * (1 - params.no_show_rate)) + booking.forecast_loads
        )
        inbound_empties_72h = 0  # MVP: no inbound loaded flows modeled yet.
        projected_balance = inv.on_hand_empty + inbound_empties_72h - demand_72h

        entries.append(
            ImbalanceEntry(
                terminal=inv.terminal_code,
                equipment_type=inv.equipment_type,
                on_hand=inv.on_hand_empty,
                inbound_empties_72h=inbound_empties_72h,
                demand_72h=demand_72h,
                projected_balance=projected_balance,
                severity=_severity(projected_balance, params),
            )
        )

    entries.sort(key=lambda entry: entry.projected_balance)

    return ImbalanceReport(
        computed_at=state.snapshot_ts,
        no_show_rate=params.no_show_rate,
        entries=entries,
    )
