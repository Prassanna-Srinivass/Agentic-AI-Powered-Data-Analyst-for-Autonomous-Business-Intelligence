"""
Independent verification of investigation results.

The analytics tools produce the numbers; this module *recomputes* the key ones straight from
the DataFrame with a separate code path and compares them, then checks internal consistency
(segment totals, contribution percentages, cross-step agreement). Every check is returned as
``{"name", "passed", "detail", "step"}`` so the presenter can attach evidence to claims and
refuse to chart or assert numbers that failed verification.

Inputs are plain dicts (``{"step", "tool", "params", "result"}``) so this module does not
depend on the orchestration layer.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

from app.analytics.periods import PeriodResolver
from app.analytics.utils import coerce_numeric

REL_TOL = 1e-9
ABS_TOL = 1e-3          # results are rounded to 4 decimals
PERCENT_ABS_TOL = 1e-3  # percentages rounded to 4 (periods) / 2 (segments) decimals
CONTRIBUTION_SLACK_PER_SEGMENT = 0.005


def _close(a: float | None, b: float | None, abs_tol: float = ABS_TOL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=abs_tol)


def _check(name: str, passed: bool, detail: str, step: int | None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail, "step": step}


def verify_investigation(df: pd.DataFrame, executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run every applicable check for the successful tool results in ``executed``."""
    checks: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for item in executed:
        tool, result, step = item["tool"], item.get("result"), item["step"]
        if not result:
            continue
        try:
            if tool == "compare_periods":
                comparisons.append(item)
                checks += _verify_comparison(df, item)
            elif tool == "group_metric_change":
                checks += _verify_segments(item)
            elif tool == "detect_anomalies":
                checks += _verify_anomalies(df, item)
            elif tool == "test_data_quality":
                checks += _verify_quality(df, item)
        except Exception as exc:  # a verifier bug must never pass silently
            checks.append(_check(f"{tool}: verification could not run", False, type(exc).__name__, step))

    for item in executed:
        if item["tool"] == "group_metric_change" and item.get("result"):
            checks += _cross_check_totals(item, comparisons)
    return checks


# ---------------------------------------------------------------------------
# Individual verifiers
# ---------------------------------------------------------------------------

def _verify_comparison(df: pd.DataFrame, item: dict[str, Any]) -> list[dict[str, Any]]:
    result, params, step = item["result"], item["params"], item["step"]
    metric_col, date_col = params["metric"], params["date_column"]
    agg = result.get("aggregation", "sum")

    values, _ = coerce_numeric(df[metric_col])
    resolver = PeriodResolver(df[date_col])
    totals: dict[str, float | None] = {}
    for label, key in (("a", "period_a"), ("b", "period_b")):
        mask = resolver.resolve(result[key]).mask
        selected = values[mask]
        if agg == "count":
            totals[label] = float(selected.notna().sum())
        elif agg == "sum":
            totals[label] = float(np.nansum(selected.to_numpy()))
        else:
            totals[label] = float(getattr(selected, agg)()) if selected.notna().any() else None

    checks = [
        _check(
            "period totals recomputed",
            _close(totals["a"], result["period_a_total"]) and _close(totals["b"], result["period_b_total"]),
            f"{result['period_a']}: recomputed {totals['a']} vs reported {result['period_a_total']}; "
            f"{result['period_b']}: recomputed {totals['b']} vs reported {result['period_b_total']}",
            step,
        )
    ]

    if totals["a"] is not None and totals["b"] is not None:
        change = totals["b"] - totals["a"]
        pct = None if totals["a"] == 0 else change / abs(totals["a"]) * 100
        passed = _close(change, result["absolute_change"]) and (
            (pct is None and result["percent_change"] is None)
            or (pct is not None and result["percent_change"] is not None
                and _close(pct, result["percent_change"], PERCENT_ABS_TOL))
        )
        checks.append(_check(
            "change and percentage recomputed",
            passed,
            f"recomputed change {round(change, 4)} / {None if pct is None else round(pct, 4)}% vs reported "
            f"{result['absolute_change']} / {result['percent_change']}%",
            step,
        ))
    return checks


def _verify_segments(item: dict[str, Any]) -> list[dict[str, Any]]:
    result, step = item["result"], item["step"]
    segments = result["segments"]
    n = max(len(segments), 1)
    # Each of the n values is rounded to 4 decimals, so the sums can differ by n * 5e-5.
    tol = ABS_TOL + n * 5e-5

    sum_a = math.fsum(s["period_a_value"] or 0.0 for s in segments)
    sum_b = math.fsum(s["period_b_value"] or 0.0 for s in segments)
    checks = [_check(
        "segment values add up to period totals",
        _close(sum_a, result["period_a_total"], tol) and _close(sum_b, result["period_b_total"], tol),
        f"segments sum to {round(sum_a, 4)} / {round(sum_b, 4)}; "
        f"period totals are {result['period_a_total']} / {result['period_b_total']}",
        step,
    )]

    total_change = result["total_change"]
    if total_change:
        contributions = [s["contribution_pct"] for s in segments if s["contribution_pct"] is not None]
        total_pct = math.fsum(contributions)
        slack = 0.1 + CONTRIBUTION_SLACK_PER_SEGMENT * n
        checks.append(_check(
            "contributions sum to 100%",
            abs(total_pct - 100.0) <= slack,
            f"contributions sum to {round(total_pct, 2)}%",
            step,
        ))
    return checks


def reconciliation_check(step: int, reconciliation: dict[str, Any]) -> dict[str, Any]:
    """Format a ``validate_reconciliation`` result as a verification check."""
    return _check(
        "segment changes reconcile with overall change",
        reconciliation["reconciled"],
        f"segments sum to {reconciliation['segment_sum']}, overall change is "
        f"{reconciliation['overall_change']} (difference {reconciliation['difference']}, "
        f"allowed {reconciliation['allowed_difference']})",
        step,
    )


def _cross_check_totals(group_item: dict[str, Any], comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = group_item["result"]
    for comparison in comparisons:
        other = comparison["result"]
        if (
            other["metric"] == result["metric"]
            and other["period_a"] == result["period_a"]
            and other["period_b"] == result["period_b"]
            and other.get("aggregation", "sum") == result.get("aggregation", "sum")
        ):
            return [_check(
                "segment decomposition matches period comparison",
                _close(other["absolute_change"], result["total_change"], ABS_TOL + len(result["segments"]) * 5e-5),
                f"comparison (step {comparison['step']}) change {other['absolute_change']} vs "
                f"decomposition total {result['total_change']}",
                group_item["step"],
            )]
    return []


def _verify_anomalies(df: pd.DataFrame, item: dict[str, Any]) -> list[dict[str, Any]]:
    result, params, step = item["result"], item["params"], item["step"]
    summary = result["summary"]
    if summary.get("n_values", 0) < 4:
        return []
    values, _ = coerce_numeric(df[params["metric"]])
    valid = values.replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    k = summary["threshold"]
    if result["method"] == "iqr":
        q1, q3 = np.percentile(valid, [25, 75])
        low, high = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        expected = int(((valid < low) | (valid > high)).sum())
    else:
        std = float(np.std(valid, ddof=1))
        expected = 0 if std == 0 else int((np.abs((valid - valid.mean()) / std) > k).sum())
    return [_check(
        "anomaly count recomputed",
        expected == result["anomaly_count"],
        f"recomputed {expected} vs reported {result['anomaly_count']} ({result['method']} rule)",
        step,
    )]


def _verify_quality(df: pd.DataFrame, item: dict[str, Any]) -> list[dict[str, Any]]:
    result, step = item["result"], item["step"]
    duplicates = int(df.duplicated().sum())
    return [_check(
        "row and duplicate counts recomputed",
        result["row_count"] == len(df) and result["duplicate_rows"] == duplicates,
        f"rows {len(df)} vs {result['row_count']}; duplicates {duplicates} vs {result['duplicate_rows']}",
        step,
    )]


# ---------------------------------------------------------------------------
# Evidence references
# ---------------------------------------------------------------------------

def evidence_check(findings: list[dict[str, Any]], verified_steps: set[int]) -> dict[str, Any]:
    """Every finding must cite a step that exists and succeeded."""
    missing = [
        f["claim"][:60] for f in findings
        if not _cites_known_step(f.get("evidence_reference", ""), verified_steps)
    ]
    return _check(
        "every finding cites a calculation",
        not missing,
        "all findings reference a completed step" if not missing else f"no valid evidence for: {missing}",
        None,
    )


def _cites_known_step(reference: str, steps: set[int]) -> bool:
    numbers = {int(n) for n in re.findall(r"step (\d+)", reference)}
    return bool(numbers) and numbers <= steps


def summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap checks into the job's ``verification`` payload."""
    return {"all_passed": all(c["passed"] for c in checks), "checks": checks}
