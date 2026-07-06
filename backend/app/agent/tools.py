"""Anthropic tool definitions and dispatch for the repositioning agent.

The agent never computes economics itself — every tool here either
returns deterministic, pre-computed scoring output (read-only) or is
the terminal action of a cycle (submit_recommendations, handled by the
loop's audit gate rather than here).
"""

from __future__ import annotations

import json
from typing import Any

from app.data.models import NetworkState, Recommendation
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import ScoringParams


def _recommendation_input_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive the per-recommendation schema from Recommendation, excluding
    server-stamped fields the agent must never invent."""
    schema = Recommendation.model_json_schema()
    excluded = {"id", "created_ts", "status", "expires_at"}
    properties = {key: value for key, value in schema["properties"].items() if key not in excluded}
    required = [field for field in schema.get("required", []) if field not in excluded]
    item_schema = {"type": "object", "properties": properties, "required": required}
    return item_schema, schema.get("$defs", {})


_RECOMMENDATION_ITEM_SCHEMA, _RECOMMENDATION_DEFS = _recommendation_input_schema()

SUBMIT_RECOMMENDATIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "items": _RECOMMENDATION_ITEM_SCHEMA,
            "description": "Zero or more repositioning recommendations for this cycle.",
        },
        "no_action_rationale": {
            "type": ["string", "null"],
            "description": (
                "Required (non-null) when recommendations is empty: explain "
                "clearly why no repositioning action is warranted this cycle."
            ),
        },
    },
    "required": ["recommendations", "no_action_rationale"],
    "$defs": _RECOMMENDATION_DEFS,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_imbalance_report",
        "description": (
            "Call this FIRST every cycle. Returns the current deterministic "
            "imbalance report: on-hand empties, 72h demand, projected balance, "
            "and severity for every terminal in the network. Takes no inputs."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_candidate_options",
        "description": (
            "Returns pre-computed repositioning candidate options (origin -> "
            "deficit moves), each with units, cost, revenue protected, and net "
            "value already calculated. These numbers are pre-computed and "
            "authoritative — NEVER recalculate or adjust them. An empty list "
            "means no action is warranted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "deficit_terminal": {
                    "type": "string",
                    "description": (
                        "Optional terminal code to filter options to a single "
                        "deficit destination, e.g. 'KCS-IC'."
                    ),
                }
            },
            "required": [],
        },
    },
    {
        "name": "submit_recommendations",
        "description": (
            "Submit your final recommendations for this cycle. This ends the "
            "cycle — call it exactly once, after reviewing the imbalance "
            "report and candidate options. Every recommendation must cite the "
            "source_option_id of the CandidateOption it is based on, and "
            "every dollar figure and unit count must be copied exactly from "
            "that option."
        ),
        "input_schema": SUBMIT_RECOMMENDATIONS_SCHEMA,
    },
]


def execute_tool(
    name: str, tool_input: dict[str, Any], state: NetworkState, params: ScoringParams
) -> str:
    """Dispatch a read-only tool call to the deterministic scoring engine.

    submit_recommendations is not dispatched here — its return value isn't
    used because the agent loop handles it directly via the audit gate.
    """
    if name == "get_imbalance_report":
        report = compute_imbalance(state, params)
        return json.dumps(report.model_dump(mode="json"), separators=(",", ":"))

    if name == "get_candidate_options":
        report = compute_imbalance(state, params)
        options = generate_candidates(state, report, params)
        deficit_terminal = tool_input.get("deficit_terminal")
        if deficit_terminal:
            options = [option for option in options if option.dest == deficit_terminal]
        return json.dumps(
            [option.model_dump(mode="json") for option in options], separators=(",", ":")
        )

    if name == "submit_recommendations":
        return ""

    raise ValueError(f"Unknown tool: {name}")
