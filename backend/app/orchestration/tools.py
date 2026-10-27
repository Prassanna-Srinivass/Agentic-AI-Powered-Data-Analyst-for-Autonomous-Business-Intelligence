"""
Approved tool registry — the only code the orchestrator is allowed to run.

Every analytical step goes through :func:`run_tool`, which checks the tool name against an
allow-list and the parameters against a fixed schema. Neither the planner nor the language
model can introduce new tools, new parameters, or executable code.

Also provides the human-readable input/output summaries shown as investigation steps, and the
number formatting shared by the presenter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.analytics.comparisons import compare_periods, group_metric_change
from app.analytics.data_quality import detect_anomalies, test_data_quality
from app.analytics.profiling import profile_dataframe

#: Tools that perform analysis on the data. Each call counts against the per-question budget.
ANALYTIC_TOOLS = (
    "compare_periods",
    "group_metric_change",
    "test_data_quality",
    "detect_anomalies",
)

#: All tools named in the project plan (profiling, verification and charting are separate stages).
APPROVED_TOOLS = (
    "profile_dataset",
    *ANALYTIC_TOOLS,
    "validate_reconciliation",
    "create_chart",
)

MAX_SUMMARY_CHARS = 300


@dataclass(frozen=True)
class ToolSpec:
    run: Callable[[pd.DataFrame, dict[str, Any]], dict[str, Any]]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


TOOLS: dict[str, ToolSpec] = {
    "profile_dataset": ToolSpec(
        run=lambda df, p: profile_dataframe(df),
        required=(),
        optional=(),
    ),
    "compare_periods": ToolSpec(
        run=lambda df, p: compare_periods(
            df, p["metric"], p["date_column"], p["period_a"], p["period_b"], p.get("aggregation", "sum")
        ),
        required=("metric", "date_column", "period_a", "period_b"),
        optional=("aggregation",),
    ),
    "group_metric_change": ToolSpec(
        run=lambda df, p: group_metric_change(
            df, p["metric"], p["date_column"], p["group_column"], p["period_a"], p["period_b"],
            p.get("aggregation", "sum"),
        ),
        required=("metric", "date_column", "group_column", "period_a", "period_b"),
        optional=("aggregation",),
    ),
    "test_data_quality": ToolSpec(
        run=lambda df, p: test_data_quality(df, p.get("date_column")),
        required=(),
        optional=("date_column",),
    ),
    "detect_anomalies": ToolSpec(
        run=lambda df, p: detect_anomalies(df, p["metric"], p.get("method", "iqr")),
        required=("metric",),
        optional=("method",),
    ),
}


def run_tool(name: str, df: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    """
    Run an approved analytics tool.

    Raises ``ValueError`` for an unapproved tool, missing/unknown parameters, or any error the
    tool itself reports (unknown column, unmatched period, non-numeric metric, ...).
    """
    spec = TOOLS.get(name)
    if spec is None:
        raise ValueError(f"'{name}' is not an approved analytics tool.")
    missing = [key for key in spec.required if not params.get(key)]
    if missing:
        raise ValueError(f"Missing parameter(s) for {name}: {', '.join(missing)}.")
    unknown = set(params) - set(spec.required) - set(spec.optional)
    if unknown:
        raise ValueError(f"Unsupported parameter(s) for {name}: {', '.join(sorted(unknown))}.")
    return spec.run(df, params)


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def fmt_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    number = float(value)
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def fmt_signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    text = fmt_number(abs(value))
    return f"+{text}" if value > 0 else f"-{text}" if value < 0 else text


def fmt_pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%" if signed else f"{abs(value):.1f}%"


# ---------------------------------------------------------------------------
# Step summaries
# ---------------------------------------------------------------------------

def describe_input(tool: str, params: dict[str, Any]) -> str:
    if tool == "profile_dataset":
        return "dataset profile (schema, missing values, duplicates, summaries)"
    if tool == "compare_periods":
        return f"{params['metric']}: {params['period_a']} vs {params['period_b']} (by {params['date_column']})"
    if tool == "group_metric_change":
        return (
            f"{params['metric']} change by {params['group_column']}: "
            f"{params['period_a']} vs {params['period_b']}"
        )
    if tool == "test_data_quality":
        date = params.get("date_column")
        return f"dataset-wide checks{f' incl. dates in {date}' if date else ''}"
    if tool == "detect_anomalies":
        return f"{params['metric']} ({params.get('method', 'iqr')} rule)"
    return ""


def summarize_output(tool: str, result: dict[str, Any]) -> str:
    if tool == "profile_dataset":
        rows = result.get("row_count", 0)
        cols = result.get("column_count", 0)
        metrics = len(result.get("candidate_metrics", []))
        dims = len(result.get("candidate_dimensions", []))
        return f"{rows} rows, {cols} cols, {metrics} metrics, {dims} dimensions"
    if tool == "compare_periods":
        text = (
            f"{result['period_a']} {fmt_number(result['period_a_total'])} → "
            f"{result['period_b']} {fmt_number(result['period_b_total'])} "
            f"({fmt_signed(result['absolute_change'])}, {fmt_pct(result['percent_change'])})"
        )
    elif tool == "group_metric_change":
        top = result.get("largest_contributor")
        text = (
            f"{result['segment_count']} segment(s); net change {fmt_signed(result['total_change'])}"
            + (f"; largest contributor {top['group']} ({fmt_signed(top['absolute_change'])})" if top else "")
        )
    elif tool == "test_data_quality":
        counts = result["severity_counts"]
        text = (
            f"{counts['high']} high, {counts['medium']} medium, {counts['low']} low issue(s) "
            f"in {result['row_count']} rows"
        )
    elif tool == "detect_anomalies":
        text = f"{result['anomaly_count']} anomalous value(s) of {result['summary'].get('n_values', 0)} ({result['method']})"
    else:
        text = ""
    return text[:MAX_SUMMARY_CHARS]
