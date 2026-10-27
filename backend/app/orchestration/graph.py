"""
LangGraph Workflow — Orchestration graph for the Agentic Data Analyst.

This module defines the bounded multi-step investigation workflow:
    1. Profile  → understand the dataset
    2. Plan     → interpret the question and select approved tools
    3. Execute  → run deterministic calculations
    4. Evaluate → decide whether to follow up or stop
    5. Verify   → reconcile values and attach evidence
    6. Present  → generate answer with chart specs and limitations

Constraints:
    - Maximum 3–5 analytical tool calls per question
    - Small retry limit with clear stop conditions
    - Only approved deterministic functions; no arbitrary code execution
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.analytics.profiling import profile_dataset
from app.orchestration.evaluator import (
    decide_followups,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
    should_continue,
)
from app.orchestration.planner import create_plan, get_next_step
from app.orchestration.state import AnalysisState
from app.orchestration.tools import run_tool, APPROVED_TOOLS, describe_input, summarize_output
from app.reporting.charts import create_chart
from app.verification.checks import evidence_check, reconciliation_check, summarize as verification_summarize, verify_investigation
from app.verification.reconciliation import validate_reconciliation

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 5
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------

async def profile_node(state: AnalysisState) -> AnalysisState:
    """Run dataset profiling and update state with schema/quality info."""
    logger.info("Starting profile_node for job %s", state.job_id)
    state.status = "profiling"

    try:
        # Load and profile the dataset
        profile = profile_dataset(state.file_path)
        state.schema = profile.get("schema", {})
        state.profile = profile
        state.quality_flags = profile.get("quality_flags", [])

        logger.info(
            "Profile complete: %d rows, %d columns, metrics=%s, dims=%s, dates=%s",
            profile.get("row_count", 0),
            profile.get("column_count", 0),
            profile.get("candidate_metrics", []),
            profile.get("candidate_dimensions", []),
            profile.get("date_columns", []),
        )
    except Exception as exc:
        logger.error("Profiling failed: %s", exc)
        state.errors.append(f"Profiling failed: {exc}")
        state.status = "failed"

    return state


async def plan_node(state: AnalysisState) -> AnalysisState:
    """Use LLM to interpret the question and produce a structured plan."""
    logger.info("Starting plan_node for job %s", state.job_id)
    state.status = "planning"

    try:
        state = await create_plan(state)
        logger.info("Plan created with %d steps, intent=%s", len(state.plan), state.intent)
    except Exception as exc:
        logger.error("Planning failed: %s", exc)
        state.errors.append(f"Planning failed: {exc}")
        state.status = "failed"

    return state


async def execute_node(state: AnalysisState) -> AnalysisState:
    """Execute the next planned deterministic analytics tool."""
    logger.info("Starting execute_node for job %s", state.job_id)
    state.status = "executing"

    # Get next step from queue
    next_step = get_next_step(state)
    if not next_step:
        logger.info("No pending steps to execute")
        return state

    logger.info("Executing step %d: %s", state.current_step + 1, next_step.tool)

    # Mark step as running
    state = mark_step_running(state, next_step)

    # Load DataFrame for tool execution
    import pandas as pd
    from app.analytics.utils import load_dataframe
    from pathlib import Path

    try:
        df = load_dataframe(Path(state.file_path))
    except Exception as exc:
        logger.error("Failed to load dataframe: %s", exc)
        state = mark_step_failed(state, next_step, f"Failed to load data: {exc}", describe_input(next_step.tool, next_step.params))
        return state

    # Run the approved tool
    try:
        result = run_tool(next_step.tool, df, next_step.params)
        input_summary = describe_input(next_step.tool, next_step.params)
        output_summary = summarize_output(next_step.tool, result)

        state = mark_step_completed(
            state,
            next_step,
            result,
            input_summary,
            output_summary,
        )
        logger.info("Step completed: %s", output_summary)

    except Exception as exc:
        logger.error("Tool execution failed: %s", exc)
        input_summary = describe_input(next_step.tool, next_step.params)
        state = mark_step_failed(state, next_step, str(exc), input_summary)

    return state


async def evaluate_node(state: AnalysisState) -> AnalysisState:
    """Decide whether findings justify another analysis or whether to stop."""
    logger.info("Starting evaluate_node for job %s", state.job_id)
    state.status = "evaluating"

    try:
        state = decide_followups(state)
        logger.info("Evaluation complete: budget_exhausted=%s, clarification=%s", state.budget_exhausted, state.clarification)
    except Exception as exc:
        logger.error("Evaluation failed: %s", exc)
        state.errors.append(f"Evaluation failed: {exc}")

    return state


async def verify_node(state: AnalysisState) -> AnalysisState:
    """Recalculate totals, check reconciliation, attach evidence references."""
    logger.info("Starting verify_node for job %s", state.job_id)
    state.status = "verifying"

    try:
        # Load DataFrame for verification
        import pandas as pd
        from app.analytics.utils import load_dataframe
        from pathlib import Path

        df = load_dataframe(Path(state.file_path))

        # Run independent verification checks
        checks = verify_investigation(df, state.executed)

        # If we have a decomposition, run reconciliation
        for item in state.executed:
            if item["tool"] == "group_metric_change" and item.get("result"):
                result = item["result"]
                segments = result.get("segments", [])
                segment_changes = {s["group"]: s["absolute_change"] for s in segments if s.get("absolute_change") is not None}
                overall_change = result.get("total_change", 0)

                if segment_changes:
                    reconciliation = validate_reconciliation(overall_change, segment_changes)
                    checks.append(reconciliation_check(item["step"], reconciliation))

        # Evidence check
        verified_steps = {item["step"] for item in state.executed if item.get("result")}
        findings_for_check = [
            {
                "claim": f.claim,
                "evidence_reference": f.evidence_reference,
            }
            for f in state.findings
        ]
        checks.append(evidence_check(findings_for_check, verified_steps))

        # Summarize verification
        verification = verification_summarize(checks)
        state.verification = verification

        logger.info("Verification complete: all_passed=%s, checks=%d", verification.get("all_passed"), len(checks))

    except Exception as exc:
        logger.error("Verification failed: %s", exc)
        state.errors.append(f"Verification failed: {exc}")
        state.verification = {"all_passed": False, "checks": []}

    return state


async def present_node(state: AnalysisState) -> AnalysisState:
    """Generate final answer with chart specs, assumptions, and limitations."""
    logger.info("Starting present_node for job %s", state.job_id)
    state.status = "presenting"

    try:
        # Build findings from executed steps
        state.findings = _build_findings(state)

        # Generate charts from verified results
        state.charts = _build_charts(state)

        # Compose final answer
        state.answer = _compose_answer(state)

        # Add standard limitations
        if not state.limitations:
            state.limitations = [
                "Observed contribution does not prove causation.",
                "Analysis based on available data; missing periods or segments may affect conclusions.",
            ]

        # Add quality flags as limitations
        for flag in state.quality_flags:
            if "missing" in flag.lower() or "duplicate" in flag.lower():
                state.limitations.append(f"Data quality: {flag}")

        # Add verification status
        if state.verification and not state.verification.get("all_passed", True):
            state.limitations.append("Some verification checks did not pass; see details in verification output.")

        state.status = "completed"
        logger.info("Presentation complete: answer length=%d, findings=%d, charts=%d",
                    len(state.answer), len(state.findings), len(state.charts))

    except Exception as exc:
        logger.error("Presentation failed: %s", exc)
        state.errors.append(f"Presentation failed: {exc}")
        state.status = "failed"

    return state


# ---------------------------------------------------------------------------
# Helper functions for presentation
# ---------------------------------------------------------------------------

def _build_findings(state: AnalysisState) -> list:
    """Build findings from executed steps."""
    from app.orchestration.state import Finding
    findings = []

    for item in state.executed:
        tool = item["tool"]
        result = item.get("result")
        step = item["step"]

        if not result:
            continue

        if tool == "compare_periods":
            findings.append(Finding(
                claim=f"{result['metric']} changed by {result['absolute_change']:,.2f} ({result['percent_change']:+.1f}%) from {result['period_a']} to {result['period_b']}.",
                metric=result["metric"],
                value=result["absolute_change"],
                evidence_reference=f"step {step}",
                confidence="high" if state.verification.get("all_passed") else "medium",
                limitation="Comparison only; does not explain root cause.",
            ))

        elif tool == "group_metric_change":
            top = result.get("largest_contributor")
            if top:
                findings.append(Finding(
                    claim=f"The largest measured contributor to the {result['metric']} change was {top['group']} ({top['absolute_change']:+,.2f}, {top['contribution_pct']:+.1f}% of total change).",
                    metric=result["metric"],
                    value=top["absolute_change"],
                    evidence_reference=f"step {step}",
                    confidence="high" if state.verification.get("all_passed") else "medium",
                    limitation="Observed contribution does not prove causation.",
                ))

        elif tool == "test_data_quality":
            counts = result.get("severity_counts", {})
            if counts.get("high", 0) > 0 or counts.get("medium", 0) > 0:
                findings.append(Finding(
                    claim=f"Data quality check found {counts.get('high', 0)} high and {counts.get('medium', 0)} medium severity issues.",
                    metric="data_quality",
                    value=counts,
                    evidence_reference=f"step {step}",
                    confidence="high",
                    limitation="Quality issues may affect the reliability of other findings.",
                ))

        elif tool == "detect_anomalies":
            if result.get("anomaly_count", 0) > 0:
                findings.append(Finding(
                    claim=f"Detected {result['anomaly_count']} anomalous value(s) in {result['metric']} using {result['method']} method.",
                    metric=result["metric"],
                    value=result["anomaly_count"],
                    evidence_reference=f"step {step}",
                    confidence="medium",
                    limitation="Anomalies are statistical outliers; business context needed to interpret.",
                ))

    return findings


def _build_charts(state: AnalysisState) -> list[dict[str, Any]]:
    """Build chart specifications from verified results."""
    charts = []

    if not state.verification.get("all_passed", True):
        logger.warning("Skipping charts because verification did not pass")
        return charts

    for item in state.executed:
        tool = item["tool"]
        result = item.get("result")
        step = item["step"]

        if not result:
            continue

        evidence_ref = f"step {step}"

        try:
            if tool == "compare_periods":
                chart = create_chart("period_comparison", result, evidence_ref)
                charts.append(chart)

            elif tool == "group_metric_change":
                chart = create_chart("segment_change", result, evidence_ref)
                charts.append(chart)

        except Exception as exc:
            logger.warning("Failed to create chart for step %d: %s", step, exc)

    return charts


def _compose_answer(state: AnalysisState) -> str:
    """Compose the final natural language answer."""
    parts = []

    # Start with the main finding
    if state.findings:
        parts.append(state.findings[0].claim)

    # Add decomposition findings
    for finding in state.findings[1:]:
        if "largest measured contributor" in finding.claim:
            parts.append(finding.claim)

    # Add quality/anomaly findings
    for finding in state.findings:
        if finding.metric in ("data_quality", "anomaly_count") and finding.value:
            if finding.metric == "data_quality":
                counts = finding.value
                if counts.get("high", 0) > 0:
                    parts.append(f"Data quality check revealed {counts['high']} high-severity issues that may affect results.")
            elif finding.metric == "anomaly_count":
                parts.append(f"Anomaly detection found {finding.value} unusual value(s) in the data.")

    # Add limitations summary
    if state.limitations:
        parts.append("Limitations: " + "; ".join(state.limitations[:3]))

    return " ".join(parts) if parts else "Analysis completed but no findings were generated."


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------

def _should_continue_execution(state: AnalysisState) -> str:
    """Conditional edge: decide whether to continue executing or move to verification."""
    if state.status == "failed":
        return "present"  # Go to present to generate error response

    if should_continue(state):
        return "execute"

    return "verify"


def build_analysis_graph():
    """
    Build and return the compiled LangGraph state machine.

    Workflow:
        profile → plan → execute → evaluate → [follow-up or verify] → present
    """
    graph = StateGraph(AnalysisState)

    # Add nodes
    graph.add_node("profile", profile_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("verify", verify_node)
    graph.add_node("present", present_node)

    # Set entry point
    graph.set_entry_point("profile")

    # Linear edges
    graph.add_edge("profile", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "evaluate")

    # Conditional edge from evaluate
    graph.add_conditional_edges(
        "evaluate",
        _should_continue_execution,
        {
            "execute": "execute",  # Loop back for follow-up
            "verify": "verify",
            "present": "present",
        },
    )

    # Final edges
    graph.add_edge("verify", "present")
    graph.add_edge("present", END)

    return graph.compile()


async def run_analysis(job_id: str, dataset_id: str, question: str):
    """
    Entry point: run the full analysis workflow for a given job.

    This function:
    1. Loads the dataset file path from storage
    2. Initializes the AnalysisState
    3. Runs the LangGraph workflow
    4. Updates the job status in storage
    """
    from app.storage import get_store

    store = get_store()

    # Get dataset info
    dataset = store.get_dataset(dataset_id)
    if not dataset:
        raise ValueError(f"Dataset {dataset_id} not found")

    file_path = dataset.get("file_path")
    if not file_path:
        raise ValueError(f"Dataset {dataset_id} has no file path")

    # Initialize state
    initial_state = AnalysisState(
        job_id=job_id,
        dataset_id=dataset_id,
        question=question,
        file_path=file_path,
    )

    # Build and run graph
    graph = build_analysis_graph()

    try:
        # Update job status to profiling
        store.update_job(job_id, status="profiling")

        # Run the graph
        final_state = await graph.ainvoke(initial_state)

        # Update job with final results
        _save_final_state(store, job_id, final_state)

    except Exception as exc:
        logger.error("Workflow failed for job %s: %s", job_id, exc)
        store.fail_job(job_id, f"The analysis failed: {type(exc).__name__}")


def _save_final_state(store, job_id: str, state: AnalysisState) -> None:
    """Save the final state to the job store."""
    # Convert findings to serializable format
    findings_out = []
    for f in state.findings:
        findings_out.append({
            "claim": f.claim,
            "metric": f.metric,
            "value": f.value,
            "evidence_reference": f.evidence_reference,
            "confidence": f.confidence,
            "limitation": f.limitation,
        })

    # Convert steps
    steps_out = []
    for s in state.steps:
        steps_out.append({
            "step_number": s.step_number,
            "tool_name": s.tool_name,
            "input_summary": s.input_summary,
            "output_summary": s.output_summary,
            "status": s.status,
            "result": s.result,
        })

    # Determine final status
    final_status = state.status
    if final_status not in ("completed", "failed"):
        final_status = "completed" if state.answer else "failed"

    store.update_job(
        job_id,
        status=final_status,
        steps=steps_out,
        findings=findings_out,
        answer=state.answer,
        chart_specs=state.charts,
        limitations=state.limitations,
        assumptions=state.assumptions,
        intent=state.intent,
        verification=state.verification,
        error=state.errors[0] if state.errors else None,
    )