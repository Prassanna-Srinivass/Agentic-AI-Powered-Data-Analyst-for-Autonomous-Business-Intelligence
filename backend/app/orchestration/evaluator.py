"""
Evaluator — Decides whether findings justify another approved analysis or whether to stop.

This module implements the adaptive investigation logic from the project plan:
- Compare → Group → Secondary dimension → Quality → Companion metric
- Maximum 5 tool calls per question
- Retry limit of 2
"""

from __future__ import annotations

from typing import Any

from app.orchestration.state import AnalysisState, PlanStep
from app.orchestration.tools import ANALYTIC_TOOLS

logger = __import__("logging").getLogger(__name__)

MAX_TOOL_CALLS = 5
MAX_RETRIES = 2

# Debug counter
_evaluation_count = 0


def _has_comparison_result(executed: list[dict[str, Any]]) -> bool:
    """Check if we have a compare_periods result."""
    return any(
        item["tool"] == "compare_periods" and item.get("result")
        for item in executed
    )


def _has_decomposition_result(executed: list[dict[str, Any]]) -> bool:
    """Check if we have a group_metric_change result."""
    return any(
        item["tool"] == "group_metric_change" and item.get("result")
        for item in executed
    )


def _has_quality_result(executed: list[dict[str, Any]]) -> bool:
    """Check if we have a test_data_quality result."""
    return any(
        item["tool"] == "test_data_quality" and item.get("result")
        for item in executed
    )


def _has_anomaly_result(executed: list[dict[str, Any]]) -> bool:
    """Check if we have a detect_anomalies result."""
    return any(
        item["tool"] == "detect_anomalies" and item.get("result")
        for item in executed
    )


def _get_latest_comparison(executed: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Get the most recent compare_periods result."""
    for item in reversed(executed):
        if item["tool"] == "compare_periods" and item.get("result"):
            return item["result"]
    return None


def _get_latest_decomposition(executed: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Get the most recent group_metric_change result."""
    for item in reversed(executed):
        if item["tool"] == "group_metric_change" and item.get("result"):
            return item["result"]
    return None


def _get_metric_from_executed(executed: list[dict[str, Any]]) -> str | None:
    """Extract the metric from the first executed step."""
    for item in executed:
        if item.get("params", {}).get("metric"):
            return item["params"]["metric"]
    return None


def _get_date_column_from_executed(executed: list[dict[str, Any]]) -> str | None:
    """Extract the date column from the first executed step."""
    for item in executed:
        if item.get("params", {}).get("date_column"):
            return item["params"]["date_column"]
    return None


def _get_periods_from_executed(executed: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Extract periods from the first executed step."""
    for item in executed:
        params = item.get("params", {})
        if params.get("period_a") and params.get("period_b"):
            return params["period_a"], params["period_b"]
    return None, None


def _get_used_dimensions(executed: list[dict[str, Any]]) -> set[str]:
    """Get the set of dimensions already used for grouping."""
    dims = set()
    for item in executed:
        if item["tool"] == "group_metric_change" and item.get("params", {}).get("group_column"):
            dims.add(item["params"]["group_column"])
    return dims


def _build_followup_step(
    tool: str,
    params: dict[str, Any],
    rationale: str,
    depends_on: list[int] | None = None,
) -> PlanStep:
    """Helper to create a PlanStep for a follow-up."""
    return PlanStep(
        tool=tool,
        params=params,
        rationale=rationale,
        depends_on=depends_on or [],
    )


def decide_followups(state: AnalysisState) -> AnalysisState:
    """
    Decide whether to continue the investigation with another approved analysis.

    Follow-up priority (from project plan):
    1. compare_periods → group_metric_change (decompose by primary dimension)
    2. group_metric_change → group_metric_change (secondary dimension)
    3. → test_data_quality (validate data issues)
    4. → detect_anomalies (check for outliers in the metric)
    5. → compare_periods (companion metric if available)

    Stops when:
    - Budget exhausted (5 tool calls)
    - No meaningful follow-up available
    - All relevant dimensions exhausted
    """
    executed = state.executed
    tool_calls_used = state.tool_calls_used
    retries_used = state.retries_used
    profile = state.profile

    # Budget check
    if tool_calls_used >= MAX_TOOL_CALLS:
        state.budget_exhausted = True
        state.clarification = f"Reached maximum tool calls ({MAX_TOOL_CALLS}). Stopping investigation."
        logger.info("Budget exhausted: %d tool calls used", tool_calls_used)
        return state

    # If we have no results yet, we can't decide on follow-ups
    if not executed:
        return state

    candidate_metrics = profile.get("candidate_metrics", [])
    candidate_dimensions = profile.get("candidate_dimensions", [])
    used_dimensions = _get_used_dimensions(executed)

    has_comparison = _has_comparison_result(executed)
    has_decomposition = _has_decomposition_result(executed)
    has_quality = _has_quality_result(executed)
    has_anomaly = _has_anomaly_result(executed)

    metric = _get_metric_from_executed(executed)
    date_column = _get_date_column_from_executed(executed)
    period_a, period_b = _get_periods_from_executed(executed)

    if not metric or not date_column or not period_a or not period_b:
        logger.debug("Missing key parameters for follow-up")
        return state

    # Get the latest comparison to check if there's significant change
    latest_comparison = _get_latest_comparison(executed)
    latest_decomposition = _get_latest_decomposition(executed)

    # Determine if there's a meaningful change to investigate
    significant_change = False
    if latest_comparison:
        pct_change = abs(latest_comparison.get("percent_change", 0) or 0)
        significant_change = pct_change >= 1.0  # At least 1% change

    followups: list[PlanStep] = []

    # Priority 1: If we have comparison but no decomposition, decompose
    if has_comparison and not has_decomposition and significant_change:
        # Find best dimension to decompose by
        for dim in candidate_dimensions:
            if dim not in used_dimensions:
                followups.append(_build_followup_step(
                    "group_metric_change",
                    {
                        "metric": metric,
                        "date_column": date_column,
                        "group_column": dim,
                        "period_a": period_a,
                        "period_b": period_b,
                        "aggregation": "sum",
                    },
                    f"Decompose {metric} change by {dim} to find contributors",
                    depends_on=[state.current_step],
                ))
                break  # Only add one decomposition at a time

    # Priority 2: If we have decomposition but no quality check, try secondary dimension
    if not followups and has_decomposition and not has_quality:
        available_dims = [d for d in candidate_dimensions if d not in used_dimensions]
        if available_dims:
            # Use the next available dimension
            next_dim = available_dims[0]
            followups.append(_build_followup_step(
                "group_metric_change",
                {
                    "metric": metric,
                    "date_column": date_column,
                    "group_column": next_dim,
                    "period_a": period_a,
                    "period_b": period_b,
                    "aggregation": "sum",
                },
                f"Decompose {metric} change by {next_dim} (secondary dimension)",
                depends_on=[state.current_step],
            ))

    # Priority 3: Check data quality if we haven't yet (fall through if no follow-ups from priority 2)
    if not followups and not has_quality:
        followups.append(_build_followup_step(
            "test_data_quality",
            {"date_column": date_column},
            "Validate data quality to ensure findings are reliable",
            depends_on=[state.current_step],
        ))

    # Priority 4: Check for anomalies in the metric
    if not followups and not has_anomaly:
        followups.append(_build_followup_step(
            "detect_anomalies",
            {"metric": metric, "method": "iqr"},
            f"Check for anomalous values in {metric} that might explain the change",
            depends_on=[state.current_step],
        ))

    # Priority 5: Look at companion metric if available
    if not followups:
        # Find another metric that might be related
        companion_metrics = [m for m in candidate_metrics if m != metric]
        if companion_metrics:
            companion = companion_metrics[0]
            followups.append(_build_followup_step(
                "compare_periods",
                {
                    "metric": companion,
                    "date_column": date_column,
                    "period_a": period_a,
                    "period_b": period_b,
                    "aggregation": "sum",
                },
                f"Check companion metric {companion} for corroborating evidence",
                depends_on=[state.current_step],
            ))

    # Add follow-ups to queue (only if we have budget)
    remaining_budget = MAX_TOOL_CALLS - tool_calls_used
    for followup in followups[:remaining_budget]:
        state.queue.append(followup)

    # Update state
    if followups:
        state.clarification = f"Planned {len(followups[:remaining_budget])} follow-up step(s)"
        logger.info("Planned %d follow-up steps", len(followups[:remaining_budget]))
        for f in followups[:remaining_budget]:
            logger.info("  Follow-up: %s - %s", f.tool, f.rationale)
    else:
        state.clarification = "No further follow-ups planned; investigation complete."
        logger.info("No follow-ups planned")

    return state


def should_continue(state: AnalysisState) -> bool:
    """
    Determine if the workflow should continue to execute another step.

    Returns True if:
    - There are pending steps in the queue
    - Budget not exhausted
    - Retries not exceeded
    """
    # Check budget
    if state.budget_exhausted or state.tool_calls_used >= MAX_TOOL_CALLS:
        return False

    # Check retries
    if state.retries_used >= MAX_RETRIES:
        return False

    # Check for pending steps in queue
    pending_steps = [s for s in state.queue if s.status == "pending"]
    if not pending_steps:
        return False

    return True


def mark_step_running(state: AnalysisState, step: PlanStep) -> AnalysisState:
    """Mark a step as running and increment the step counter."""
    step.status = "running"
    state.current_step += 1
    return state


def mark_step_completed(
    state: AnalysisState,
    step: PlanStep,
    result: dict[str, Any],
    input_summary: str,
    output_summary: str,
) -> AnalysisState:
    """Mark a step as completed and record the result."""
    step.status = "completed"
    state.tool_calls_used += 1

    # Record in executed list
    state.executed.append({
        "step": state.current_step,
        "tool": step.tool,
        "params": step.params,
        "result": result,
        "input_summary": input_summary,
        "output_summary": output_summary,
    })

    # Record in results list
    state.results.append(result)

    # Add to steps for API output
    from app.orchestration.state import AnalysisStep
    state.steps.append(AnalysisStep(
        step_number=state.current_step,
        tool_name=step.tool,
        input_summary=input_summary,
        output_summary=output_summary,
        status="completed",
        result=result,
    ))

    return state


def mark_step_failed(
    state: AnalysisState,
    step: PlanStep,
    error: str,
    input_summary: str,
) -> AnalysisState:
    """Mark a step as failed and handle retry logic."""
    step.status = "failed"
    state.retries_used += 1
    state.errors.append(f"Step {state.current_step} ({step.tool}): {error}")

    # Add to steps for API output
    from app.orchestration.state import AnalysisStep
    state.steps.append(AnalysisStep(
        step_number=state.current_step,
        tool_name=step.tool,
        input_summary=input_summary,
        output_summary=f"Error: {error}",
        status="failed",
        result=None,
    ))

    # If retries not exhausted, re-queue the step
    if state.retries_used < MAX_RETRIES:
        step.status = "pending"
        state.clarification = f"Retrying step {state.current_step} (attempt {state.retries_used + 1}/{MAX_RETRIES})"
        logger.warning("Step failed, will retry: %s", error)
    else:
        state.clarification = f"Step {state.current_step} failed after {MAX_RETRIES} retries"
        logger.error("Step failed after max retries: %s", error)

    return state