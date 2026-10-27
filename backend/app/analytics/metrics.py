"""
Metrics — deterministic metric aggregation and trend series.

Helpers used for follow-up investigation steps (units sold, order counts, average order
value) and as the verified numeric source for chart specifications:

    aggregate_metric   Aggregate a metric overall or by a categorical dimension.
    metric_trend       Aggregate a metric over time (day / week / month / quarter / year).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.comparisons import MISSING_LABEL, OTHER_LABEL, SUPPORTED_AGGREGATIONS
from app.analytics.utils import coerce_numeric, safe_round, to_jsonable, try_parse_datetime, value_label

MAX_TREND_POINTS = 500
_FREQUENCIES = {"d": "D", "w": "W", "m": "M", "q": "Q", "y": "Y"}
_ADDITIVE = ("sum", "count")


def _metric_values(df: pd.DataFrame, metric_column: str) -> tuple[pd.Series, int]:
    if metric_column not in df.columns:
        raise ValueError(f"Metric column '{metric_column}' not found in dataset.")
    values, invalid = coerce_numeric(df[metric_column])
    non_null = int(df[metric_column].notna().sum())
    if non_null == 0 or invalid > 0.5 * non_null:
        raise ValueError(f"Metric column '{metric_column}' is not numeric.")
    return values, invalid


def _check_aggregation(aggregation: str) -> str:
    agg = str(aggregation).strip().lower()
    if agg not in SUPPORTED_AGGREGATIONS:
        raise ValueError(f"Unsupported aggregation '{aggregation}'. Supported: {', '.join(SUPPORTED_AGGREGATIONS)}.")
    return agg


def _reduce(values: pd.Series, agg: str) -> float | None:
    if agg == "count":
        return float(values.notna().sum())
    if values.notna().sum() == 0:
        return 0.0 if agg == "sum" else None
    return float(getattr(values, agg)())


def aggregate_metric(
    df: pd.DataFrame,
    metric_column: str,
    aggregation: str = "sum",
    group_column: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Aggregate a metric over the whole dataset, optionally broken down by a dimension.

    Parameters
    ----------
    metric_column : str
        Numeric column to aggregate.
    aggregation : str
        One of ``sum`` (default), ``mean``, ``median``, ``min``, ``max``, ``count``.
    group_column : str | None
        Optional categorical column. Groups are returned largest first; groups beyond
        ``top_n`` are merged into ``"(other)"`` (only for ``sum``/``count``, where merging is exact).
    top_n : int
        Number of groups to list individually.

    Returns
    -------
    dict
        ``value`` (overall aggregate), ``row_count`` and, when grouped, ``groups`` with
        ``share_pct`` of the overall value for additive aggregations.
    """
    agg = _check_aggregation(aggregation)
    if top_n < 1:
        raise ValueError("top_n must be at least 1.")
    values, invalid = _metric_values(df, metric_column)
    overall = _reduce(values, agg)

    warnings_: list[str] = []
    if invalid:
        warnings_.append(f"{invalid} non-numeric value(s) in '{metric_column}' were excluded.")

    result: dict[str, Any] = {
        "metric": metric_column,
        "aggregation": agg,
        "value": safe_round(overall),
        "row_count": len(df),
        "valid_value_count": int(values.notna().sum()),
        "group_by": group_column,
        "groups": [],
        "warnings": warnings_,
    }
    if group_column is None:
        return to_jsonable(result)

    if group_column not in df.columns:
        raise ValueError(f"Group column '{group_column}' not found in dataset.")
    if group_column == metric_column:
        raise ValueError("group_column must differ from the metric column.")

    labels = df[group_column].map(value_label).fillna(MISSING_LABEL)
    grouped = values.groupby(labels)
    table = getattr(grouped, "count" if agg == "count" else agg)().dropna()
    counts = labels.groupby(labels).size()
    # Largest value first; alphabetical tie-break keeps the output deterministic.
    ordered = sorted(table.items(), key=lambda item: (-item[1], str(item[0])))

    additive = agg in _ADDITIVE
    rows = [(str(g), float(v), int(counts[g])) for g, v in ordered]
    if len(rows) > top_n and additive:
        kept, rest = rows[:top_n], rows[top_n:]
        rows = kept + [(OTHER_LABEL, sum(r[1] for r in rest), sum(r[2] for r in rest))]
    elif len(rows) > top_n:
        rows = rows[:top_n]
        warnings_.append(f"Only the top {top_n} groups are shown; '{agg}' cannot be merged into '{OTHER_LABEL}'.")

    result["group_count"] = len(table)
    result["groups"] = [
        {
            "group": g,
            "value": safe_round(v),
            "row_count": n,
            "share_pct": round(v / overall * 100, 2) if additive and overall else None,
        }
        for g, v, n in rows
    ]
    return to_jsonable(result)


def metric_trend(
    df: pd.DataFrame,
    metric_column: str,
    date_column: str,
    freq: str = "month",
    aggregation: str = "sum",
) -> dict[str, Any]:
    """
    Aggregate a metric over time.

    Parameters
    ----------
    date_column : str
        A date-like column (rows with unparseable dates are excluded and counted).
    freq : str
        ``day``, ``week``, ``month`` (default), ``quarter`` or ``year`` (first letter suffices).
    aggregation : str
        One of ``sum`` (default), ``mean``, ``median``, ``min``, ``max``, ``count``.

    Returns
    -------
    dict
        ``points`` — chronologically ordered ``{period, value, row_count}`` records (only
        periods that contain data; the latest ``500`` are kept) — plus exclusion counts.
    """
    agg = _check_aggregation(aggregation)
    key = str(freq).strip().lower()[:1]
    if key not in _FREQUENCIES:
        raise ValueError("Unsupported freq. Use one of: day, week, month, quarter, year.")
    if date_column not in df.columns:
        raise ValueError(f"Date column '{date_column}' not found in dataset.")
    values, invalid = _metric_values(df, metric_column)

    parsed = try_parse_datetime(df[date_column])
    if parsed is None:
        raise ValueError(f"Column '{date_column}' is not a date column.")

    valid_dates = parsed.notna()
    unparseable = int((~valid_dates & df[date_column].notna()).sum())
    periods = parsed[valid_dates].dt.to_period(_FREQUENCIES[key])
    grouped = values[valid_dates].groupby(periods)

    points = []
    for period, group in grouped:
        points.append({
            "period": str(period),
            "value": safe_round(_reduce(group, agg)),
            "row_count": len(group),
        })
    points.sort(key=lambda p: p["period"])

    warnings_: list[str] = []
    if unparseable:
        warnings_.append(f"{unparseable} row(s) with unparseable dates were excluded.")
    if invalid:
        warnings_.append(f"{invalid} non-numeric value(s) in '{metric_column}' were excluded.")
    if len(points) > MAX_TREND_POINTS:
        warnings_.append(f"Only the latest {MAX_TREND_POINTS} periods are returned.")
        points = points[-MAX_TREND_POINTS:]

    return to_jsonable({
        "metric": metric_column,
        "date_column": date_column,
        "aggregation": agg,
        "frequency": key,
        "points": points,
        "excluded_unparseable_dates": unparseable,
        "excluded_non_numeric_rows": invalid,
        "warnings": warnings_,
    })
