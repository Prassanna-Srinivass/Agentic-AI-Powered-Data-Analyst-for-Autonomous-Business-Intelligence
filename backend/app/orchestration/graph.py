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

from typing import Any

# from langgraph.graph import StateGraph, END
# from app.orchestration.state import AnalysisState

# ---------------------------------------------------------------------------
# Approved tool registry
# ---------------------------------------------------------------------------
APPROVED_TOOLS = [
    "profile_dataset",
    "compare_periods",
    "group_metric_change",
    "test_data_quality",
    "detect_anomalies",
    "validate_reconciliation",
    "create_chart",
]

MAX_TOOL_CALLS = 5
MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Graph nodes (to be implemented on Day 3)
# ---------------------------------------------------------------------------

async def profile_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run dataset profiling and update state with schema/quality info."""
    # TODO: Call app.analytics.profiling.profile_dataset()
    return state


async def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """Use LLM to interpret the question and produce a structured plan."""
    # TODO: Call LLM with structured output to select tools and parameters
    return state


async def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the planned deterministic analytics tool."""
    # TODO: Route to the approved tool and capture results
    return state


async def evaluate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Decide whether findings justify another analysis or whether to stop."""
    # TODO: Implement follow-up decision logic (Day 4)
    return state


async def verify_node(state: dict[str, Any]) -> dict[str, Any]:
    """Recalculate totals, check reconciliation, attach evidence references."""
    # TODO: Call app.verification.reconciliation
    return state


async def present_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate final answer with chart specs, assumptions, and limitations."""
    # TODO: Compose the response and mark the job as completed
    return state


# ---------------------------------------------------------------------------
# Graph construction (to be wired on Day 3)
# ---------------------------------------------------------------------------

def build_analysis_graph():
    """
    Build and return the compiled LangGraph state machine.

    Workflow:
        profile → plan → execute → evaluate → [follow-up or verify] → present
    """
    # TODO: Construct the StateGraph with conditional edges
    #
    # graph = StateGraph(AnalysisState)
    # graph.add_node("profile", profile_node)
    # graph.add_node("plan", plan_node)
    # graph.add_node("execute", execute_node)
    # graph.add_node("evaluate", evaluate_node)
    # graph.add_node("verify", verify_node)
    # graph.add_node("present", present_node)
    #
    # graph.set_entry_point("profile")
    # graph.add_edge("profile", "plan")
    # graph.add_edge("plan", "execute")
    # graph.add_edge("execute", "evaluate")
    # graph.add_conditional_edges("evaluate", should_follow_up, ...)
    # graph.add_edge("verify", "present")
    # graph.add_edge("present", END)
    #
    # return graph.compile()
    pass


async def run_analysis(job_id: str, dataset_id: str, question: str):
    """Entry point: run the full analysis workflow for a given job."""
    # TODO: Build graph, initialize state, and invoke
    pass
