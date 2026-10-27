"""
Data Quality — checks for missing, duplicate, and inconsistent records.

Approved tools:
    test_data_quality   Flag missing, duplicate, or inconsistent records.
    detect_anomalies    Apply a simple, documented statistical rule.

Anomaly rules (documented, deliberately simple):
    iqr     A value is anomalous if it is below ``Q1 - k * IQR`` or above ``Q3 + k * IQR``
            (default ``k = 1.5``; quartiles use linear interpolation).
    zscore  A value is anomalous if ``|(x - mean) / std| > k`` (default ``k = 3``; sample
            standard deviation, ``ddof = 1``).
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.analytics.utils import coerce_numeric, safe_round, to_jsonable, try_parse_datetime


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

MISSING_HIGH_PCT = 50.0
MISSING_MEDIUM_PCT = 20.0
DUPLICATE_MEDIUM_PCT = 1.0
DUPLICATE_HIGH_PCT = 10.0
MAX_CATEGORY_CARDINALITY = 5000
MAX_LISTED_GAPS = 10
MAX_LISTED_EXAMPLES = 3

# Column-name hints for measures that should not normally be negative.
_NON_NEGATIVE_HINT = re.compile(
    r"revenue|sales|price|amount|quantity|qty|units|cost|orders|count|total", re.IGNORECASE
)

DEFAULT_THRESHOLDS = {"iqr": 1.5, "zscore": 3.0}
SUPPORTED_ANOMALY_METHODS = tuple(DEFAULT_THRESHOLDS)
MIN_VALUES_FOR_ANOMALIES = 4


# ---------------------------------------------------------------------------
# test_data_quality
# ---------------------------------------------------------------------------

def test_data_quality(
    df: pd.DataFrame,
    date_column: str | None = None,
) -> dict[str, Any]:
    """
    Run data quality checks on a DataFrame.

    Checks performed
    ----------------
    * duplicate rows (fully identical records)
    * missing values per column, and entirely empty columns
    * constant (single-value) columns
    * inconsistent category spellings (``"North"`` / ``"north "``) and stray whitespace
    * numbers stored as text, with or without unparseable entries
    * negative values in columns whose names suggest non-negative measures
    * when ``date_column`` is given: unparseable dates, future dates, row ordering, and gaps
      in the date sequence

    Parameters
    ----------
    df : pd.DataFrame
        The dataset to check.
    date_column : str | None
        Optional date column to check for temporal consistency.

    Returns
    -------
    dict
        Quality report. ``issues`` is a list of structured findings
        (``severity``, ``check``, ``column``, ``message``, ``count``); ``flags`` holds the
        same messages as plain strings, and ``passed`` is ``False`` if any high/medium
        severity issue exists.
    """
    if date_column is not None and date_column not in df.columns:
        raise ValueError(f"Date column '{date_column}' not found in dataset.")

    issues: list[dict[str, Any]] = []

    def add(severity: str, check: str, message: str, column: str | None = None, count: int | None = None) -> None:
        issues.append({
            "severity": severity,
            "check": check,
            "column": column,
            "message": message,
            "count": count,
        })

    row_count = len(df)

    if row_count == 0:
        add("high", "empty_dataset", "Dataset has no rows.")
        return _assemble(df, issues, 0, 0.0, {}, [], [], {}, [], None)

    # --- Duplicates -----------------------------------------------------------------
    duplicate_rows = int(df.duplicated().sum())
    duplicate_percent = round(duplicate_rows / row_count * 100, 2)
    if duplicate_rows:
        severity = (
            "high" if duplicate_percent > DUPLICATE_HIGH_PCT
            else "medium" if duplicate_percent >= DUPLICATE_MEDIUM_PCT
            else "low"
        )
        add(
            severity, "duplicate_rows",
            f"{duplicate_rows} fully duplicated row(s) ({duplicate_percent}% of rows). "
            "Totals may be double-counted.",
            count=duplicate_rows,
        )

    # --- Missing values ----------------------------------------------------------------
    missing_counts = df.isna().sum()
    missing_summary: dict[str, dict[str, Any]] = {}
    empty_columns: list[str] = []
    for col in df.columns:
        count = int(missing_counts[col])
        if count == 0:
            continue
        pct = round(count / row_count * 100, 2)
        missing_summary[str(col)] = {"count": count, "percent": pct}
        if count == row_count:
            empty_columns.append(str(col))
            add("high", "empty_column", f"Column '{col}' is completely empty.", str(col), count)
        else:
            severity = "high" if pct >= MISSING_HIGH_PCT else "medium" if pct >= MISSING_MEDIUM_PCT else "low"
            add(severity, "missing_values", f"Column '{col}' has {count} missing value(s) ({pct}%).", str(col), count)

    # --- Constant columns -------------------------------------------------------------------
    constant_columns: list[str] = []
    if row_count > 1:
        for col in df.columns:
            if str(col) in empty_columns:
                continue
            if df[col].nunique(dropna=True) == 1:
                constant_columns.append(str(col))
                add(
                    "low", "constant_column",
                    f"Column '{col}' contains a single repeated value; it cannot explain any change.",
                    str(col),
                )

    # --- Text consistency & type problems ---------------------------------------------------
    inconsistent_categories: dict[str, list[dict[str, Any]]] = {}
    type_issues: list[dict[str, Any]] = []

    text_columns = [
        col for col in df.columns
        if str(col) not in empty_columns
        and (
            pd.api.types.is_object_dtype(df[col])
            or pd.api.types.is_string_dtype(df[col])
            or isinstance(df[col].dtype, pd.CategoricalDtype)
        )
    ]
    for col in text_columns:
        series = df[col].dropna()
        if series.empty:
            continue
        text = series.astype(str)

        _, invalid = coerce_numeric(series)
        numeric_share = 1 - invalid / len(series)
        if numeric_share >= 0.8 and not _looks_like_dates(series):
            if invalid == 0:
                type_issues.append({"column": str(col), "type": "numeric_stored_as_text", "count": 0})
                add("info", "numeric_stored_as_text", f"Column '{col}' holds numbers stored as text.", str(col))
            else:
                type_issues.append({"column": str(col), "type": "mixed_types", "count": invalid})
                add(
                    "medium", "mixed_types",
                    f"Column '{col}' is mostly numeric but has {invalid} non-numeric value(s); "
                    "those cells are excluded from calculations.",
                    str(col), invalid,
                )
            continue

        padded = int((text != text.str.strip()).sum())
        if padded:
            add("low", "whitespace", f"Column '{col}' has {padded} value(s) with leading/trailing spaces.", str(col), padded)

        if text.nunique() <= MAX_CATEGORY_CARDINALITY:
            groups = _spelling_variants(text)
            if groups:
                inconsistent_categories[str(col)] = groups
                variant_total = sum(len(g["variants"]) for g in groups)
                add(
                    "medium", "inconsistent_categories",
                    f"Column '{col}' has {len(groups)} category(ies) spelled inconsistently "
                    f"(e.g. {', '.join(repr(v) for v in groups[0]['variants'][:MAX_LISTED_EXAMPLES])}); "
                    "grouped results will split them.",
                    str(col), variant_total,
                )

    # --- Negative values in non-negative-looking measures ---------------------------------------
    for col in df.select_dtypes(include="number").columns:
        if _NON_NEGATIVE_HINT.search(str(col)):
            negatives = int((df[col] < 0).sum())
            if negatives:
                add(
                    "low", "negative_values",
                    f"Column '{col}' has {negatives} negative value(s); confirm these are refunds/returns, not errors.",
                    str(col), negatives,
                )

    # --- Date consistency -----------------------------------------------------------------------
    date_consistency = _check_dates(df, date_column, add) if date_column is not None else None

    return _assemble(
        df, issues, duplicate_rows, duplicate_percent, missing_summary, empty_columns,
        constant_columns, inconsistent_categories, type_issues, date_consistency,
    )


# Prevent pytest from collecting this tool as a test when it is imported into a test module.
test_data_quality.__test__ = False  # type: ignore[attr-defined]


def _assemble(
    df: pd.DataFrame,
    issues: list[dict[str, Any]],
    duplicate_rows: int,
    duplicate_percent: float,
    missing_summary: dict[str, dict[str, Any]],
    empty_columns: list[str],
    constant_columns: list[str],
    inconsistent_categories: dict[str, list[dict[str, Any]]],
    type_issues: list[dict[str, Any]],
    date_consistency: dict[str, Any] | None,
) -> dict[str, Any]:
    issues = sorted(issues, key=lambda i: SEVERITY_ORDER[i["severity"]])
    severity_counts = {level: 0 for level in SEVERITY_ORDER}
    for issue in issues:
        severity_counts[issue["severity"]] += 1
    return to_jsonable({
        "row_count": len(df),
        "column_count": len(df.columns),
        "duplicate_rows": duplicate_rows,
        "duplicate_percent": duplicate_percent,
        "missing_summary": missing_summary,
        "empty_columns": empty_columns,
        "constant_columns": constant_columns,
        "inconsistent_categories": inconsistent_categories,
        "type_issues": type_issues,
        "date_consistency": date_consistency,
        "issues": issues,
        "flags": [i["message"] for i in issues if i["severity"] != "info"],
        "severity_counts": severity_counts,
        "passed": severity_counts["high"] == 0 and severity_counts["medium"] == 0,
    })


def _looks_like_dates(series: pd.Series) -> bool:
    return try_parse_datetime(series.head(1000)) is not None


def _spelling_variants(text: pd.Series) -> list[dict[str, Any]]:
    """Groups of distinct raw values that normalise to the same key (case/whitespace)."""
    normalised = text.str.strip().str.replace(r"\s+", " ", regex=True).str.casefold()
    frame = pd.DataFrame({"raw": text, "key": normalised})
    unique = frame.drop_duplicates()
    counts = unique.groupby("key")["raw"].nunique()
    groups = []
    for key in counts[counts > 1].index:
        variants = sorted(unique.loc[unique["key"] == key, "raw"].tolist())
        groups.append({"normalized": key, "variants": variants})
    return sorted(groups, key=lambda g: g["normalized"])


def _check_dates(df: pd.DataFrame, date_column: str, add) -> dict[str, Any]:
    series = df[date_column]
    result: dict[str, Any] = {"column": date_column, "is_date_like": False}

    parsed = try_parse_datetime(series, min_ratio=0.5)
    if parsed is None:
        add(
            "info", "date_not_parsed",
            f"Column '{date_column}' is not date-like (period labels?); date ordering and gap checks were skipped.",
            date_column,
        )
        return result

    non_missing = int(series.notna().sum())
    valid = parsed.dropna()
    unparseable = non_missing - len(valid)
    result.update({
        "is_date_like": True,
        "missing_count": int(series.isna().sum()),
        "unparseable_count": int(unparseable),
        "parsed_ratio": round(len(valid) / non_missing, 4) if non_missing else None,
    })

    if unparseable:
        pct = unparseable / non_missing * 100
        add(
            "high" if pct > 20 else "medium", "unparseable_dates",
            f"Column '{date_column}' has {unparseable} value(s) that are not valid dates.",
            date_column, int(unparseable),
        )
    if valid.empty:
        return result

    result["min"] = valid.min().isoformat()
    result["max"] = valid.max().isoformat()
    result["span_days"] = int((valid.max() - valid.min()).days)

    if valid.is_monotonic_increasing:
        result["row_order"] = "ascending"
    elif valid.is_monotonic_decreasing:
        result["row_order"] = "descending"
    else:
        result["row_order"] = "unordered"

    future = int((valid > pd.Timestamp.now().normalize() + pd.Timedelta(days=1)).sum())
    result["future_dates"] = future
    if future:
        add("medium", "future_dates", f"Column '{date_column}' has {future} date(s) in the future.", date_column, future)

    days = valid.dt.normalize().drop_duplicates().sort_values()
    result["distinct_dates"] = len(days)
    frequency, step = "unknown", None
    gaps: list[dict[str, Any]] = []
    gap_count = 0
    if len(days) >= 3:
        diffs = days.diff().dropna().dt.days.to_numpy()
        median = float(np.median(diffs))
        if median <= 1:
            frequency, step = "daily", 1.0
        elif 6 <= median <= 8:
            frequency, step = "weekly", 7.0
        elif 27 <= median <= 31:
            frequency, step = "monthly", 30.44
        else:
            frequency = "irregular"
        if step is not None:
            starts = days.to_numpy()[:-1]
            ends = days.to_numpy()[1:]
            for start, end, diff in zip(starts, ends, diffs):
                if diff > step * 1.5:
                    gap_count += 1
                    if len(gaps) < MAX_LISTED_GAPS:
                        gaps.append({
                            "after": pd.Timestamp(start).date().isoformat(),
                            "before": pd.Timestamp(end).date().isoformat(),
                            "missing_periods": round(diff / step) - 1,
                        })
    result.update({"inferred_frequency": frequency, "gap_count": gap_count, "gaps": gaps})
    if gap_count:
        add(
            "medium", "date_gaps",
            f"Column '{date_column}' ({frequency}) has {gap_count} gap(s) in its date sequence; "
            "period totals may be understated.",
            date_column, gap_count,
        )
    return result


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------

def detect_anomalies(
    df: pd.DataFrame,
    metric_column: str,
    method: str = "iqr",
    threshold: float | None = None,
    max_anomalies: int = 50,
) -> dict[str, Any]:
    """
    Detect anomalies in a numeric column using a simple statistical rule.

    Parameters
    ----------
    df : pd.DataFrame
        The dataset.
    metric_column : str
        Numeric column to check for anomalies.
    method : str
        Detection method. Supported: "iqr" (interquartile range), "zscore".
    threshold : float | None
        Multiplier ``k`` of the rule. Defaults to 1.5 for IQR and 3.0 for z-score.
    max_anomalies : int
        Maximum number of anomalous rows listed (the count is always the full total).

    Returns
    -------
    dict
        ``anomaly_count`` (all anomalies), ``anomalies`` (largest deviation first, capped at
        ``max_anomalies``), ``summary`` with the statistics and bounds used, and ``warnings``.
        Anomalies are statistical outliers only; they are not necessarily errors.
    """
    if metric_column not in df.columns:
        raise ValueError(f"Metric column '{metric_column}' not found in dataset.")

    method_key = str(method).strip().lower().replace("-", "").replace("_", "")
    if method_key not in SUPPORTED_ANOMALY_METHODS:
        raise ValueError(f"Unsupported method '{method}'. Supported: {', '.join(SUPPORTED_ANOMALY_METHODS)}.")
    k = DEFAULT_THRESHOLDS[method_key] if threshold is None else float(threshold)
    if not np.isfinite(k) or k <= 0:
        raise ValueError("threshold must be a positive number.")
    if max_anomalies < 0:
        raise ValueError("max_anomalies must not be negative.")

    raw = df[metric_column]
    values, invalid = coerce_numeric(raw)
    values = values.replace([np.inf, -np.inf], np.nan)
    if raw.notna().sum() == 0 or invalid > 0.5 * raw.notna().sum():
        raise ValueError(f"Metric column '{metric_column}' is not numeric.")

    valid = values.dropna()
    warnings_: list[str] = []
    if invalid:
        warnings_.append(f"{invalid} non-numeric value(s) in '{metric_column}' were excluded.")

    summary: dict[str, Any] = {
        "rule": _describe_rule(method_key, k),
        "threshold": k,
        "n_values": len(valid),
        "n_missing": int(raw.isna().sum()),
        "n_non_numeric": int(invalid),
    }

    if len(valid) < MIN_VALUES_FOR_ANOMALIES:
        warnings_.append(
            f"At least {MIN_VALUES_FOR_ANOMALIES} numeric values are required; no anomalies were evaluated."
        )
        return _anomaly_result(metric_column, method_key, 0, [], summary, warnings_, False)

    q1, q3 = float(valid.quantile(0.25)), float(valid.quantile(0.75))
    mean, std = float(valid.mean()), float(valid.std(ddof=1))
    summary.update({
        "mean": safe_round(mean), "std": safe_round(std),
        "min": safe_round(valid.min()), "max": safe_round(valid.max()),
        "q1": safe_round(q1), "median": safe_round(valid.median()), "q3": safe_round(q3),
        "iqr": safe_round(q3 - q1),
    })

    score = pd.Series(np.nan, index=values.index)
    if method_key == "iqr":
        iqr = q3 - q1
        lower, upper = q1 - k * iqr, q3 + k * iqr
        flagged = (values < lower) | (values > upper)
        summary.update({"lower_bound": safe_round(lower), "upper_bound": safe_round(upper)})
        if iqr == 0:
            warnings_.append(
                "The interquartile range is zero, so every value different from the median is flagged; "
                "interpret with care."
            )
        else:
            score = np.where(values > upper, (values - upper) / iqr, np.where(values < lower, (lower - values) / iqr, 0.0))
            score = pd.Series(score, index=values.index)
    else:
        if not np.isfinite(std) or std == 0:
            flagged = pd.Series(False, index=values.index)
            warnings_.append("The column has zero variance; no z-score anomalies are possible.")
        else:
            score = (values - mean) / std
            flagged = score.abs() > k
            max_possible = (len(valid) - 1) / np.sqrt(len(valid))
            if max_possible <= k:
                warnings_.append(
                    f"With only {len(valid)} values a z-score above {k:g} is mathematically impossible; "
                    "consider the 'iqr' method."
                )
        summary.update({
            "lower_bound": safe_round(mean - k * std) if np.isfinite(std) else None,
            "upper_bound": safe_round(mean + k * std) if np.isfinite(std) else None,
        })

    flagged = flagged.fillna(False)
    anomaly_count = int(flagged.sum())
    summary["anomaly_percent"] = round(anomaly_count / len(valid) * 100, 2)

    positions = np.flatnonzero(flagged.to_numpy())
    flagged_values = values.iloc[positions]
    flagged_scores = score.iloc[positions]
    median = float(valid.median())
    records = [
        {
            "row_index": int(pos),
            "index_label": to_jsonable(values.index[pos]),
            "value": safe_round(val),
            "direction": "high" if val > median else "low",
            "score": safe_round(sc, 4),
        }
        for pos, val, sc in zip(positions, flagged_values, flagged_scores)
    ]
    records.sort(key=lambda r: (-(abs(r["score"]) if r["score"] is not None else abs(r["value"] - median)), r["row_index"]))

    truncated = len(records) > max_anomalies
    return _anomaly_result(metric_column, method_key, anomaly_count, records[:max_anomalies], summary, warnings_, truncated)


def _describe_rule(method: str, k: float) -> str:
    if method == "iqr":
        return f"Flag values below Q1 - {k:g} x IQR or above Q3 + {k:g} x IQR."
    return f"Flag values whose absolute z-score (sample std) exceeds {k:g}."


def _anomaly_result(
    metric: str,
    method: str,
    count: int,
    anomalies: list[dict[str, Any]],
    summary: dict[str, Any],
    warnings_: list[str],
    truncated: bool,
) -> dict[str, Any]:
    return to_jsonable({
        "metric": metric,
        "method": method,
        "anomaly_count": count,
        "anomalies": anomalies,
        "truncated": truncated,
        "summary": summary,
        "warnings": warnings_,
    })
