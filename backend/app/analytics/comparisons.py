"""
Comparisons — period-over-period and segment decomposition analytics.

Approved tools:
    compare_periods       Compare metric values between two periods.
    group_metric_change   Break down a metric change by a categorical dimension.

Both tools are deterministic: they only use pandas aggregation over the supplied DataFrame,
and every figure in the result can be recomputed from the returned row counts and totals.
Wording guidance (project plan): results describe *measured contributors*; they do not
establish causation.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.periods import resolve_period_pair
from app.analytics.utils import coerce_numeric, safe_round, value_label

#: Aggregations supported by ``compare_periods``.
SUPPORTED_AGGREGATIONS = ("sum", "mean", "median", "min", "max", "count")

#: Aggregations that are additive across segments, so contributions reconcile exactly.
ADDITIVE_AGGREGATIONS = ("sum", "count")

MISSING_LABEL = "(missing)"
OTHER_LABEL = "(other)"
DEFAULT_MAX_SEGMENTS = 50

_RECONCILE_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame, *columns: str, kind: str | None = None) -> None:
    for name in columns:
        if name not in df.columns:
            label = f"{kind} column" if kind else "Column"
            raise ValueError(f"{label} '{name}' not found in dataset.")


def _prepare_metric(df: pd.DataFrame, metric_column: str) -> tuple[pd.Series, int]:
    """Return the metric as floats plus the number of unparseable (excluded) cells."""
    values, invalid = coerce_numeric(df[metric_column])
    non_null = int(df[metric_column].notna().sum())
    if non_null == 0:
        raise ValueError(f"Metric column '{metric_column}' contains no values.")
    if invalid > 0.5 * non_null:
        raise ValueError(f"Metric column '{metric_column}' is not numeric.")
    return values, invalid


def _validate_aggregation(aggregation: str, allowed: tuple[str, ...]) -> str:
    agg = str(aggregation).strip().lower()
    if agg not in allowed:
        raise ValueError(f"Unsupported aggregation '{aggregation}'. Supported: {', '.join(allowed)}.")
    return agg


def _aggregate(values: pd.Series, aggregation: str) -> float | None:
    if aggregation == "count":
        return float(values.notna().sum())
    if values.notna().sum() == 0:
        return 0.0 if aggregation == "sum" else None
    return float(getattr(values, aggregation)())


def _pct_change(base: float | None, change: float | None, digits: int = 4) -> float | None:
    """Percent change relative to ``abs(base)``; ``None`` when the base is zero/unknown."""
    if base is None or change is None or base == 0:
        return None
    return round(change / abs(base) * 100, digits)


def _direction(change: float | None) -> str:
    if change is None:
        return "unknown"
    if change > 0:
        return "increase"
    if change < 0:
        return "decrease"
    return "no_change"


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------

def compare_periods(
    df: pd.DataFrame,
    metric_column: str,
    date_column: str,
    period_a: str,
    period_b: str,
    aggregation: str = "sum",
) -> dict[str, Any]:
    """
    Compare a metric between two time periods.

    Parameters
    ----------
    df : pd.DataFrame
        The dataset.
    metric_column : str
        Name of the numeric column to aggregate.
    date_column : str
        Name of the column containing date/period values.
    period_a : str
        Label or value for the baseline period (see ``app.analytics.periods`` for the
        supported formats, e.g. ``"August"``, ``"2024-08"``, ``"Q3 2024"``).
    period_b : str
        Label or value for the comparison period.
    aggregation : str
        One of ``sum`` (default), ``mean``, ``median``, ``min``, ``max``, ``count``.
        The ``period_*_total`` keys hold this aggregate.

    Returns
    -------
    dict
        absolute_change, percent_change (relative to ``abs(period_a_total)``),
        period_a_total, period_b_total, row counts, direction, and any warnings.

    Raises
    ------
    ValueError
        Unknown columns/aggregation, non-numeric metric, identical periods, or a period
        that matches no rows.
    """
    _require_columns(df, metric_column, kind="Metric")
    _require_columns(df, date_column, kind="Date")
    agg = _validate_aggregation(aggregation, SUPPORTED_AGGREGATIONS)

    metric, invalid = _prepare_metric(df, metric_column)
    a, b, warnings_ = resolve_period_pair(df[date_column], period_a, period_b)

    a_total = _aggregate(metric[a.mask], agg)
    b_total = _aggregate(metric[b.mask], agg)

    absolute_change = None if a_total is None or b_total is None else b_total - a_total
    percent_change = _pct_change(a_total, absolute_change)

    if invalid:
        warnings_.append(f"{invalid} non-numeric value(s) in '{metric_column}' were excluded.")
    if a_total is None or b_total is None:
        warnings_.append("One period has no valid metric values, so the change cannot be computed.")

    return {
        "metric": metric_column,
        "date_column": date_column,
        "aggregation": agg,
        "period_a": period_a,
        "period_b": period_b,
        "period_a_total": safe_round(a_total),
        "period_b_total": safe_round(b_total),
        "absolute_change": safe_round(absolute_change),
        "percent_change": percent_change,
        "direction": _direction(absolute_change),
        "period_a_row_count": a.row_count,
        "period_b_row_count": b.row_count,
        "period_a_match": a.method,
        "period_b_match": b.method,
        "excluded_non_numeric_rows": invalid,
        "warnings": warnings_,
    }


# ---------------------------------------------------------------------------
# group_metric_change
# ---------------------------------------------------------------------------

def group_metric_change(
    df: pd.DataFrame,
    metric_column: str,
    date_column: str,
    group_column: str,
    period_a: str,
    period_b: str,
    aggregation: str = "sum",
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> dict[str, Any]:
    """
    Decompose a metric change by a categorical dimension.

    Parameters
    ----------
    df : pd.DataFrame
        The dataset.
    metric_column : str
        Numeric column to aggregate.
    date_column : str
        Column containing date/period values.
    group_column : str
        Categorical column to group by (e.g., region, product).
    period_a : str
        Baseline period label.
    period_b : str
        Comparison period label.
    aggregation : str
        ``sum`` (default) or ``count``. Only additive aggregations are allowed because the
        per-segment changes must add up to the overall change.
    max_segments : int
        Maximum number of segments returned individually. Smaller segments are merged into
        a single ``"(other)"`` row so the decomposition still reconciles.

    Returns
    -------
    dict
        Per-group breakdown (largest absolute change first) with each group's
        ``contribution_pct`` of the overall change, the largest contributor / offset, a
        ``segment_changes`` mapping ready for ``validate_reconciliation`` and a
        ``reconciliation`` self-check. Rows whose group is missing are reported under
        ``"(missing)"`` so nothing is silently dropped.

    Notes
    -----
    ``contribution_pct`` can exceed 100% or be negative when some segments move against the
    overall trend. It is ``None`` when the overall change is exactly zero.
    """
    _require_columns(df, metric_column, kind="Metric")
    _require_columns(df, date_column, kind="Date")
    _require_columns(df, group_column, kind="Group")
    if group_column in (metric_column, date_column):
        raise ValueError("group_column must differ from the metric and date columns.")
    agg = _validate_aggregation(aggregation, ADDITIVE_AGGREGATIONS)
    if max_segments < 1:
        raise ValueError("max_segments must be at least 1.")

    metric, invalid = _prepare_metric(df, metric_column)
    a, b, warnings_ = resolve_period_pair(df[date_column], period_a, period_b)

    labels = df[group_column].map(value_label).fillna(MISSING_LABEL)

    def per_group(mask: pd.Series) -> pd.Series:
        grouped = metric[mask].groupby(labels[mask])
        return grouped.count() if agg == "count" else grouped.sum()

    a_grouped = per_group(a.mask).astype(float)
    b_grouped = per_group(b.mask).astype(float)

    frame = pd.DataFrame({"a": a_grouped, "b": b_grouped}).fillna(0.0)
    frame["change"] = frame["b"] - frame["a"]

    total_a = float(frame["a"].sum())
    total_b = float(frame["b"].sum())
    total_change = total_b - total_a

    # Largest absolute change first; alphabetical tie-break keeps the output deterministic.
    frame = frame.assign(_abs=frame["change"].abs(), _name=frame.index.astype(str))
    frame = frame.sort_values(["_abs", "_name"], ascending=[False, True]).drop(columns=["_abs", "_name"])

    rows: list[tuple[str, float, float]] = [
        (str(name), float(r.a), float(r.b)) for name, r in frame.iterrows()
    ]
    if len(rows) > max_segments:
        kept, rest = rows[: max_segments - 1], rows[max_segments - 1 :]
        rows = kept + [
            (OTHER_LABEL, sum(r[1] for r in rest), sum(r[2] for r in rest))
        ]
        warnings_.append(
            f"{len(rest)} smaller segments were merged into '{OTHER_LABEL}' (max_segments={max_segments})."
        )

    segments: list[dict[str, Any]] = []
    for name, val_a, val_b in rows:
        change = val_b - val_a
        segments.append({
            "group": name,
            "period_a_value": safe_round(val_a),
            "period_b_value": safe_round(val_b),
            "absolute_change": safe_round(change),
            "percent_change": _pct_change(val_a, change, digits=2),
            "contribution_pct": (
                round(change / total_change * 100, 2) if total_change != 0 else None
            ),
        })

    segment_changes = {s["group"]: s["absolute_change"] for s in segments}
    segment_sum = sum(
        (val_b - val_a) for _, val_a, val_b in rows
    )
    difference = abs(total_change - segment_sum)

    direction = _direction(total_change)
    largest_contributor = None
    largest_offset = None
    if direction in ("increase", "decrease"):
        sign = 1 if direction == "increase" else -1
        with_trend = [s for s in segments if s["absolute_change"] * sign > 0]
        against = [s for s in segments if s["absolute_change"] * sign < 0]
        largest_contributor = with_trend[0] if with_trend else None
        largest_offset = against[0] if against else None

    if invalid:
        warnings_.append(f"{invalid} non-numeric value(s) in '{metric_column}' were excluded.")
    if MISSING_LABEL in segment_changes:
        warnings_.append(f"Some rows have no value in '{group_column}' and are reported as '{MISSING_LABEL}'.")

    return {
        "metric": metric_column,
        "aggregation": agg,
        "group_by": group_column,
        "period_a": period_a,
        "period_b": period_b,
        "period_a_total": safe_round(total_a),
        "period_b_total": safe_round(total_b),
        "total_change": safe_round(total_change),
        "direction": direction,
        "segment_count": len(frame),
        "segments": segments,
        "largest_contributor": largest_contributor,
        "largest_offset": largest_offset,
        "segment_changes": segment_changes,
        "reconciliation": {
            "segment_sum": safe_round(segment_sum),
            "total_change": safe_round(total_change),
            "difference": safe_round(difference),
            "reconciled": bool(difference <= _RECONCILE_TOLERANCE * max(1.0, abs(total_change))),
        },
        "excluded_non_numeric_rows": invalid,
        "warnings": warnings_,
    }
