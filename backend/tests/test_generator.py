"""Tests for the seeded synthetic network generator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.data.generator import generate_network_state

FIXED_SNAPSHOT_TS = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

GENERATOR_SOURCE = Path(__file__).resolve().parents[1] / "app" / "data" / "generator.py"


def test_same_seed_identical() -> None:
    first = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    second = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    assert first.model_dump() == second.model_dump()


def test_different_seed_differs() -> None:
    seed_42 = generate_network_state(seed=42, snapshot_ts=FIXED_SNAPSHOT_TS)
    seed_43 = generate_network_state(seed=43, snapshot_ts=FIXED_SNAPSHOT_TS)
    assert seed_42.model_dump() != seed_43.model_dump()


def test_structural_invariant() -> None:
    for seed in range(1, 201):
        state = generate_network_state(seed=seed, snapshot_ts=FIXED_SNAPSHOT_TS)

        demand_72h: dict[str, int] = {}
        for booking in state.bookings:
            demand_72h[booking.terminal_code] = (
                demand_72h.get(booking.terminal_code, 0)
                + booking.booked_loads
                + booking.forecast_loads
            )

        balances = [
            inv.on_hand_empty - demand_72h.get(inv.terminal_code, 0)
            for inv in state.inventory
        ]

        assert any(balance < -50 for balance in balances), f"seed {seed}: no clear deficit terminal"
        assert any(balance > 100 for balance in balances), f"seed {seed}: no clear surplus terminal"


def test_no_global_random() -> None:
    source = GENERATOR_SOURCE.read_text(encoding="utf-8")
    assert "random.seed" not in source
    assert "import random\n" not in source
