"""Static topology of the synthetic rail network: terminals and lanes.

These definitions are fixed inputs to the generator — they never change
across seeds or snapshots. Only inventory, bookings, and train capacity
are randomized per (seed, snapshot_ts).
"""

from __future__ import annotations

from app.data.models import Lane, Terminal, TerminalProfile

TERMINALS: list[Terminal] = [
    Terminal(
        code="CHI-G4",
        name="Chicago Global IV",
        profile=TerminalProfile.SURPLUS,
        daily_load_base=180,
        lot_capacity=520,
    ),
    Terminal(
        code="LAX-ICTF",
        name="Los Angeles ICTF",
        profile=TerminalProfile.SURPLUS,
        daily_load_base=220,
        lot_capacity=600,
    ),
    Terminal(
        code="DAL-ITD",
        name="Dallas Intermodal",
        profile=TerminalProfile.DEFICIT,
        daily_load_base=95,
        lot_capacity=300,
    ),
    Terminal(
        code="MEM-IMX",
        name="Memphis Intermodal",
        profile=TerminalProfile.BALANCED,
        daily_load_base=110,
        lot_capacity=350,
    ),
    Terminal(
        code="KCS-IC",
        name="Kansas City",
        profile=TerminalProfile.DEFICIT,
        daily_load_base=70,
        lot_capacity=250,
    ),
    Terminal(
        code="HOU-BAR",
        name="Houston Barbours Cut",
        profile=TerminalProfile.BALANCED,
        daily_load_base=130,
        lot_capacity=400,
    ),
    Terminal(
        code="DEN-RG",
        name="Denver Rail Gateway",
        profile=TerminalProfile.DEFICIT,
        daily_load_base=55,
        lot_capacity=200,
    ),
    Terminal(
        code="SEA-SIG",
        name="Seattle South IG",
        profile=TerminalProfile.SURPLUS,
        daily_load_base=90,
        lot_capacity=320,
    ),
]

# Directed lanes: surplus -> (deficit | balanced), plus a few
# balanced -> deficit short-haul lanes. transit_hrs and cost_per_move_usd
# scale roughly together with distance.
LANES: list[Lane] = [
    # Chicago (surplus) -> deficit / balanced
    Lane(id="CHI-G4_DAL-ITD", origin_code="CHI-G4", dest_code="DAL-ITD", transit_hrs=38, cost_per_move_usd=282),
    Lane(id="CHI-G4_KCS-IC", origin_code="CHI-G4", dest_code="KCS-IC", transit_hrs=14, cost_per_move_usd=218),
    Lane(id="CHI-G4_DEN-RG", origin_code="CHI-G4", dest_code="DEN-RG", transit_hrs=26, cost_per_move_usd=250),
    Lane(id="CHI-G4_MEM-IMX", origin_code="CHI-G4", dest_code="MEM-IMX", transit_hrs=16, cost_per_move_usd=223),
    Lane(id="CHI-G4_HOU-BAR", origin_code="CHI-G4", dest_code="HOU-BAR", transit_hrs=30, cost_per_move_usd=261),
    # Los Angeles (surplus) -> deficit / balanced
    Lane(id="LAX-ICTF_DAL-ITD", origin_code="LAX-ICTF", dest_code="DAL-ITD", transit_hrs=42, cost_per_move_usd=293),
    Lane(id="LAX-ICTF_KCS-IC", origin_code="LAX-ICTF", dest_code="KCS-IC", transit_hrs=36, cost_per_move_usd=277),
    Lane(id="LAX-ICTF_DEN-RG", origin_code="LAX-ICTF", dest_code="DEN-RG", transit_hrs=24, cost_per_move_usd=245),
    Lane(id="LAX-ICTF_HOU-BAR", origin_code="LAX-ICTF", dest_code="HOU-BAR", transit_hrs=40, cost_per_move_usd=288),
    # Seattle (surplus) -> deficit
    Lane(id="SEA-SIG_DEN-RG", origin_code="SEA-SIG", dest_code="DEN-RG", transit_hrs=46, cost_per_move_usd=304),
    Lane(id="SEA-SIG_DAL-ITD", origin_code="SEA-SIG", dest_code="DAL-ITD", transit_hrs=52, cost_per_move_usd=320),
    Lane(id="SEA-SIG_KCS-IC", origin_code="SEA-SIG", dest_code="KCS-IC", transit_hrs=44, cost_per_move_usd=298),
    # Balanced -> deficit short-haul
    Lane(id="MEM-IMX_DAL-ITD", origin_code="MEM-IMX", dest_code="DAL-ITD", transit_hrs=14, cost_per_move_usd=218),
    Lane(id="MEM-IMX_KCS-IC", origin_code="MEM-IMX", dest_code="KCS-IC", transit_hrs=10, cost_per_move_usd=207),
    Lane(id="HOU-BAR_DAL-ITD", origin_code="HOU-BAR", dest_code="DAL-ITD", transit_hrs=10, cost_per_move_usd=207),
]
