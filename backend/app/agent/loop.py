"""The agent's analysis-cycle loop: orchestrates the LLM against the
deterministic scoring tools and audits its final submission before it is
ever treated as trustworthy output.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import HTTPException

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schemas import CycleResult
from app.agent.settings import get_agent_settings
from app.agent.store import save_cycle
from app.agent.tools import TOOL_DEFINITIONS, execute_tool
from app.data.loader import get_network_state
from app.data.models import NetworkState, Recommendation, RecommendationStatus
from app.scoring.candidates import generate_candidates
from app.scoring.imbalance import compute_imbalance
from app.scoring.params import ScoringParams, get_scoring_params

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16000
MAX_TOOL_ITERATIONS = 8
MAX_AUDIT_FAILURES = 2
MAX_TRUNCATION_RETRIES = 2

_READ_ONLY_TOOLS = {"get_imbalance_report", "get_candidate_options"}

_INITIAL_USER_MESSAGE = "Run the repositioning analysis cycle for the current network state."
_FINISH_PROMPT = "You must finish by calling submit_recommendations."
_TRUNCATION_RETRY_PROMPT = (
    "Your previous response exceeded the output limit and was truncated "
    "before the tool call completed. Respond again: keep any analysis to a "
    "few sentences and proceed directly to the tool call."
)


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

        expected_legs = sorted((leg.train_id, leg.units) for leg in option.suggested_legs)
        execution_legs = rec.get("execution_legs") or []
        actual_legs = sorted(
            (leg.get("train_id"), leg.get("units")) for leg in execution_legs
        )
        if actual_legs != expected_legs:
            expected_str = ", ".join(f"{train_id}:{units}" for train_id, units in expected_legs)
            return (
                f"execution_legs for {source_option_id} do not match the option's "
                f"suggested_legs (same train_ids and units required); expected "
                f"[{expected_str}]."
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
    cycle_id: str,
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
        cycle_id=cycle_id,
        started_ts=started_ts,
        completed_ts=datetime.now(timezone.utc),
        recommendations=recommendations,
        no_action_rationale=no_action_rationale,
        trace=trace,
    )


def _process_tool_use_blocks(
    tool_use_blocks: list[dict[str, Any]],
    state: NetworkState,
    params: ScoringParams,
    started_ts: datetime,
    cycle_id: str,
    trace: list[dict[str, Any]],
    audit_failures: int,
) -> tuple[list[dict[str, Any]], CycleResult | None, int]:
    """Process every tool_use block from one assistant turn, building exactly
    one tool_result per id (in order) — the API rejects a follow-up request
    that's missing a tool_result for any tool_use id from the prior turn."""
    tool_results: list[dict[str, Any]] = []
    submitted: CycleResult | None = None

    for block in tool_use_blocks:
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

            # Record the tool_result for protocol completeness — even though
            # we return before any follow-up request would use it — before
            # finalizing, since _finalize_cycle snapshots trace into the
            # returned CycleResult.
            trace.append({"type": "tool_result", "name": name, "output": "accepted"})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": "accepted"}
            )
            submitted = _finalize_cycle(tool_input, state, started_ts, trace, cycle_id)
            continue

        if name not in _READ_ONLY_TOOLS:
            error_message = f"Unknown tool: {name!r}"
            trace.append(
                {"type": "tool_result", "name": name, "output": error_message, "is_error": True}
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": error_message,
                    "is_error": True,
                }
            )
            continue

        output = execute_tool(name, tool_input, state, params)
        trace.append({"type": "tool_result", "name": name, "output": output})
        tool_results.append(
            {"type": "tool_result", "tool_use_id": block["id"], "content": output}
        )

    return tool_results, submitted, audit_failures


async def run_analysis_cycle(seed: int | None = None) -> CycleResult:
    started_ts = datetime.now(timezone.utc)
    cycle_id = f"CYCLE-{uuid.uuid4().hex[:12]}"
    state = get_network_state(seed=seed)
    params = get_scoring_params()

    if not get_agent_settings().use_replay_mode and not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail=(
                "ANTHROPIC_API_KEY not configured. Set it in backend/.env or "
                "enable USE_REPLAY_MODE=true."
            ),
        )

    client = _build_client()
    model = _model_name()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _INITIAL_USER_MESSAGE},
    ]
    trace: list[dict[str, Any]] = []
    audit_failures = 0
    truncation_count = 0
    reprompted = False

    try:
        for iteration in range(1, MAX_TOOL_ITERATIONS + 1):
            response = await client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            assistant_content = [_content_block_to_dict(block) for block in response.content]
            tool_use_blocks = [block for block in assistant_content if block["type"] == "tool_use"]
            logger.info(
                "cycle_id=%s iteration=%d/%d stop_reason=%s tools=%s",
                cycle_id,
                iteration,
                MAX_TOOL_ITERATIONS,
                response.stop_reason,
                [block["name"] for block in tool_use_blocks],
            )

            if response.stop_reason == "max_tokens":
                truncation_count += 1
                logger.warning(
                    "cycle_id=%s iteration=%d truncated at max_tokens (attempt %d/%d); "
                    "content_length=%d",
                    cycle_id,
                    iteration,
                    truncation_count,
                    MAX_TRUNCATION_RETRIES,
                    len(json.dumps(assistant_content)),
                )
                if truncation_count >= MAX_TRUNCATION_RETRIES:
                    raise AgentIncompleteError(
                        f"Model's response was truncated at the token limit "
                        f"{truncation_count} times; giving up."
                    )
                # Drop the truncated turn — it may contain a dangling
                # tool_use with incomplete input, and the API rejects a
                # follow-up request missing a tool_result for any tool_use
                # id from the prior turn — so never append it as-is.
                messages.append({"role": "user", "content": _TRUNCATION_RETRY_PROMPT})
                continue

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

            tool_results, submitted, audit_failures = _process_tool_use_blocks(
                tool_use_blocks, state, params, started_ts, cycle_id, trace, audit_failures
            )

            if submitted is not None:
                return submitted

            messages.append({"role": "user", "content": tool_results})

        raise AgentIncompleteError("Exceeded max tool iterations without submit_recommendations.")
    except Exception as exc:
        last_assistant_message = next(
            (message for message in reversed(messages) if message["role"] == "assistant"), None
        )
        logger.error(
            "cycle_id=%s failed: %s; last_assistant_content=%s",
            cycle_id,
            exc,
            last_assistant_message["content"] if last_assistant_message else None,
        )
        save_cycle(
            CycleResult(
                cycle_id=cycle_id,
                started_ts=started_ts,
                completed_ts=datetime.now(timezone.utc),
                recommendations=[],
                no_action_rationale=None,
                trace=trace,
                error=str(exc),
            )
        )
        raise
