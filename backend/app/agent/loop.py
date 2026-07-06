"""The agent's analysis-cycle loop: orchestrates the LLM against the
deterministic scoring tools and audits its final submission before it is
ever treated as trustworthy output.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schemas import CycleResult
from app.agent.tools import TOOL_DEFINITIONS, execute_tool
from app.data.loader import get_network_state
from app.data.models import NetworkState, Recommendation, RecommendationStatus
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import ScoringParams, get_scoring_params

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOOL_ITERATIONS = 8
MAX_AUDIT_FAILURES = 2

_INITIAL_USER_MESSAGE = "Run the repositioning analysis cycle for the current network state."
_FINISH_PROMPT = "You must finish by calling submit_recommendations."


class AgentAuditError(RuntimeError):
    """Raised when submit_recommendations fails the audit gate too many times."""


class AgentIncompleteError(RuntimeError):
    """Raised when the model never calls submit_recommendations."""


def _build_client() -> AsyncAnthropic:
    # Reads ANTHROPIC_API_KEY via the SDK's default env handling; never logged.
    return AsyncAnthropic()


def _model_name() -> str:
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)


def _content_block_to_dict(block: Any) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    raise ValueError(f"Unsupported content block type: {block.type!r}")


def _audit_submission(
    tool_input: dict[str, Any], state: NetworkState, params: ScoringParams
) -> str | None:
    """Return None if the submission passes the audit gate, else a
    human-readable description of the first mismatch found."""
    recommendations = tool_input.get("recommendations") or []
    no_action_rationale = tool_input.get("no_action_rationale")

    if not recommendations:
        if not isinstance(no_action_rationale, str) or not no_action_rationale.strip():
            return "recommendations is empty but no_action_rationale is missing or empty."
        return None
    if no_action_rationale is not None:
        return "no_action_rationale must be null when recommendations is non-empty."

    report = compute_imbalance(state, params)
    options_by_id = {
        option.option_id: option for option in generate_candidates(state, report, params)
    }
    lanes_by_od = {(lane.origin_code, lane.dest_code): lane for lane in state.lanes}

    seen_lane_ids: set[str] = set()
    for rec in recommendations:
        source_option_id = rec.get("source_option_id")
        option = options_by_id.get(source_option_id)
        if option is None:
            return (
                f"source_option_id '{source_option_id}' does not exist in this "
                "cycle's candidate list."
            )

        for field, expected in (
            ("units", option.units),
            ("cost_usd", option.cost_usd),
            ("revenue_protected_usd", option.revenue_protected_usd),
            ("net_benefit_usd", option.net_usd),
        ):
            actual = rec.get(field)
            if actual != expected:
                return (
                    f"{field} mismatch for {source_option_id}: expected {expected}, "
                    f"got {actual}."
                )

        execution_legs = rec.get("execution_legs") or []
        legs_total = sum(leg.get("units", 0) for leg in execution_legs)
        if legs_total != rec.get("units"):
            return (
                f"execution_legs total units ({legs_total}) does not equal units "
                f"({rec.get('units')}) for {source_option_id}."
            )

        expected_lane = lanes_by_od.get((option.origin, option.dest))
        expected_lane_id = expected_lane.id if expected_lane else None
        lane_id = rec.get("lane_id")
        if lane_id != expected_lane_id:
            return (
                f"lane_id mismatch for {source_option_id}: expected "
                f"'{expected_lane_id}', got {lane_id}."
            )

        if lane_id in seen_lane_ids:
            return (
                f"multiple recommendations target lane '{lane_id}'; at most one "
                "recommendation per lane is allowed per cycle."
            )
        seen_lane_ids.add(lane_id)

    return None


def _finalize_cycle(
    tool_input: dict[str, Any],
    state: NetworkState,
    started_ts: datetime,
    trace: list[dict[str, Any]],
) -> CycleResult:
    raw_recommendations = tool_input.get("recommendations") or []
    no_action_rationale = tool_input.get("no_action_rationale")
    expires_at = state.snapshot_ts + timedelta(hours=12)

    recommendations: list[Recommendation] = []
    for i, raw in enumerate(raw_recommendations, start=1):
        rec_id = f"REC-{started_ts.year}-{started_ts:%m%d}-{i:03d}"
        recommendations.append(
            Recommendation(
                id=rec_id,
                created_ts=started_ts,
                status=RecommendationStatus.PENDING,
                expires_at=expires_at,
                **raw,
            )
        )

    return CycleResult(
        cycle_id=f"CYCLE-{uuid.uuid4().hex[:12]}",
        started_ts=started_ts,
        completed_ts=datetime.now(timezone.utc),
        recommendations=recommendations,
        no_action_rationale=no_action_rationale,
        trace=trace,
    )


async def run_analysis_cycle(seed: int | None = None) -> CycleResult:
    started_ts = datetime.now(timezone.utc)
    state = get_network_state(seed=seed)
    params = get_scoring_params()

    client = _build_client()
    model = _model_name()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _INITIAL_USER_MESSAGE},
    ]
    trace: list[dict[str, Any]] = []
    audit_failures = 0
    reprompted = False

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        assistant_content = [_content_block_to_dict(block) for block in response.content]
        messages.append({"role": "assistant", "content": assistant_content})

        for block in assistant_content:
            if block["type"] == "text":
                trace.append({"type": "text", "text": block["text"]})

        if response.stop_reason != "tool_use":
            if reprompted:
                raise AgentIncompleteError(
                    "Model ended its turn without calling submit_recommendations."
                )
            reprompted = True
            messages.append({"role": "user", "content": _FINISH_PROMPT})
            continue

        tool_results: list[dict[str, Any]] = []
        submitted: CycleResult | None = None

        for block in assistant_content:
            if block["type"] != "tool_use":
                continue
            name = block["name"]
            tool_input = block["input"]
            trace.append({"type": "tool_call", "name": name, "input": tool_input})

            if name == "submit_recommendations":
                error = _audit_submission(tool_input, state, params)
                if error is not None:
                    audit_failures += 1
                    trace.append(
                        {"type": "tool_result", "name": name, "output": error, "is_error": True}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": error,
                            "is_error": True,
                        }
                    )
                    if audit_failures >= MAX_AUDIT_FAILURES:
                        raise AgentAuditError(
                            f"submit_recommendations failed the audit gate "
                            f"{audit_failures} times: {error}"
                        )
                    continue

                submitted = _finalize_cycle(tool_input, state, started_ts, trace)
                continue

            output = execute_tool(name, tool_input, state, params)
            trace.append({"type": "tool_result", "name": name, "output": output})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": output}
            )

        if submitted is not None:
            return submitted

        messages.append({"role": "user", "content": tool_results})

    raise AgentIncompleteError("Exceeded max tool iterations without submit_recommendations.")
