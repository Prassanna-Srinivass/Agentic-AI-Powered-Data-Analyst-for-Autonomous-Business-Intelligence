"""
Dataset Profiling — schema inference, missing values, duplicates, and summary statistics.

Approved tool: profile_dataset
    Infer column types, missing values, duplicates, ranges, and useful metrics.
    Returns: profile dict + quality flags.

The profile is strictly JSON-safe (no NaN/inf/Timestamp objects), so it can be returned
directly from the API and handed to the planner as the list of "known columns".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.analytics.utils import coerce_numeric, load_dataframe, to_jsonable, try_parse_datetime

# Semantic column types reported in ``column_types`` / ``columns``.
NUMERIC = "numeric"
CATEGORICAL = "categorical"
DATETIME = "datetime"
BOOLEAN = "boolean"
TEXT = "text"
IDENTIFIER = "identifier"
DATE_PART = "date_part"
EMPTY = "empty"

HIGH_MISSING_PERCENT = 20.0
MAX_DIMENSION_CARDINALITY = 50
CATEGORICAL_UNIQUE_RATIO = 0.5
TYPE_SAMPLE_SIZE = 2000
NUMERIC_TEXT_MIN_RATIO = 0.9
SAMPLE_ROW_COUNT = 5
EXAMPLE_VALUE_COUNT = 3

_ID_NAME_STRICT = re.compile(r"(^|[_\s\-])(id|uuid|guid|key|index)$|[a-z0-9](ID|Id)$")
_DATE_PART_NAME = re.compile(
    r"^(year|yr|month|mo|quarter|qtr|week|day|fiscal[_\s]?year|fy|period)$", re.IGNORECASE
)
_PERIOD_LABEL = re.compile(
    r"^(q[1-4]([\s\-_]*(fy)?\d{2,4})?|(fy)?\d{4}[\s\-_]*q[1-4]|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|"
    r"oct(ober)?|nov(ember)?|dec(ember)?)(\s+\d{4})?$",
    re.IGNORECASE,
)
_BOOL_WORDS = {"true", "false", "yes", "no", "y", "n", "t", "f"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def profile_dataset(file_path: str) -> dict[str, Any]:
    """
    Profile an uploaded dataset.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the CSV or Excel file.

    Returns
    -------
    dict
        A dictionary containing:
        - schema: column names with pandas dtype strings
        - column_types: column names with semantic types
          (numeric, categorical, datetime, boolean, text, identifier, date_part, empty)
        - columns: per-column details (type, missing, unique count, example values)
        - row_count / column_count
        - missing_values: per-column null counts and percentages (columns with nulls only)
        - duplicate_count: number of duplicate rows
        - numeric_summary: describe() output for numeric columns
        - sample_rows: first few rows for preview
        - candidate_metrics / candidate_dimensions / date_columns / period_columns /
          identifier_columns: column suggestions for the planner
        - date_ranges: min/max/span for each datetime column
        - quality_flags: list of potential data quality issues

    Raises
    ------
    ValueError
        For unsupported, unreadable, or empty files.
    """
    df = load_dataframe(Path(file_path))
    return profile_dataframe(df)


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Profile an already-loaded DataFrame (see :func:`profile_dataset`)."""
    df = df.rename(columns=str)
    row_count = len(df)

    # --- Schema & semantic types --------------------------------------------------
    schema = {str(col): str(dtype) for col, dtype in df.dtypes.items()}
    column_infos = [_profile_column(df[col], str(col), row_count) for col in df.columns]
    column_types = {info["name"]: info["type"] for info in column_infos}

    # --- Missing values -------------------------------------------------------------------
    missing_values = {
        info["name"]: {"count": info["missing_count"], "percent": info["missing_percent"]}
        for info in column_infos
        if info["missing_count"] > 0
    }

    # --- Duplicates ---------------------------------------------------------------------
    duplicate_count = int(df.duplicated().sum()) if row_count else 0

    # --- Numeric summary ----------------------------------------------------------
    numeric_summary: dict[str, dict[str, Any]] = {}
    for info in column_infos:
        if info["type"] not in (NUMERIC, DATE_PART) or info["name"] not in df.columns:
            continue
        values, _ = coerce_numeric(df[info["name"]])
        values = values.replace([np.inf, -np.inf], np.nan)
        if values.notna().any():
            numeric_summary[info["name"]] = to_jsonable(
                {k: round(float(v), 4) if pd.notna(v) else None for k, v in values.describe().items()}
            )

    # --- Candidate columns for the planner ------------------------------------------------
    candidate_metrics = [
        i["name"] for i in column_infos if i["type"] == NUMERIC and i["unique_count"] > 1
    ]
    candidate_dimensions = [
        i["name"] for i in column_infos
        if i["type"] in (CATEGORICAL, BOOLEAN) and 2 <= i["unique_count"] <= MAX_DIMENSION_CARDINALITY
    ]
    date_columns = [i["name"] for i in column_infos if i["type"] == DATETIME]
    period_columns = date_columns + [
        i["name"] for i in column_infos
        if i["type"] == DATE_PART or i.get("is_period_label")
    ]
    identifier_columns = [i["name"] for i in column_infos if i["type"] == IDENTIFIER]

    date_ranges: dict[str, dict[str, Any]] = {}
    for name in date_columns:
        parsed = try_parse_datetime(df[name])
        if parsed is not None and parsed.notna().any():
            low, high = parsed.min(), parsed.max()
            date_ranges[name] = {
                "min": low.isoformat(),
                "max": high.isoformat(),
                "span_days": int((high - low).days),
            }

    # --- Sample rows ---------------------------------------------------------------------
    sample_rows = to_jsonable(df.head(SAMPLE_ROW_COUNT).to_dict(orient="records"))

    # --- Quality flags ----------------------------------------------------------------
    quality_flags = _quality_flags(
        row_count, duplicate_count, missing_values, column_infos, candidate_metrics, period_columns
    )

    return to_jsonable({
        "schema": schema,
        "column_types": column_types,
        "columns": column_infos,
        "row_count": row_count,
        "column_count": len(df.columns),
        "missing_values": missing_values,
        "duplicate_count": duplicate_count,
        "numeric_summary": numeric_summary,
        "sample_rows": sample_rows,
        "candidate_metrics": candidate_metrics,
        "candidate_dimensions": candidate_dimensions,
        "date_columns": date_columns,
        "period_columns": period_columns,
        "identifier_columns": identifier_columns,
        "date_ranges": date_ranges,
        "quality_flags": quality_flags,
    })


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

def _profile_column(series: pd.Series, name: str, row_count: int) -> dict[str, Any]:
    missing = int(series.isna().sum())
    non_null = series.dropna()
    unique_count = int(non_null.nunique()) if len(non_null) else 0

    info: dict[str, Any] = {
        "name": name,
        "dtype": str(series.dtype),
        "type": EMPTY,
        "missing_count": missing,
        "missing_percent": round(missing / row_count * 100, 2) if row_count else 0.0,
        "unique_count": unique_count,
        "examples": [],
    }
    if non_null.empty:
        return info

    semantic, extras = _semantic_type(series, non_null, name, unique_count)
    info["type"] = semantic
    info.update(extras)
    info["examples"] = to_jsonable(non_null.drop_duplicates().head(EXAMPLE_VALUE_COUNT).tolist())
    return info


def _semantic_type(
    series: pd.Series, non_null: pd.Series, name: str, unique_count: int
) -> tuple[str, dict[str, Any]]:
    n = len(non_null)
    unique_ratio = unique_count / n

    if pd.api.types.is_bool_dtype(series):
        return BOOLEAN, {}
    if pd.api.types.is_datetime64_any_dtype(series):
        return DATETIME, {}

    if pd.api.types.is_numeric_dtype(series):
        return _numeric_kind(non_null, name, unique_count, unique_ratio), {}

    # Text-like column: sample large columns so type detection stays cheap.
    sample = non_null.head(TYPE_SAMPLE_SIZE)

    lowered = sample.astype(str).str.strip().str.casefold()
    if lowered.nunique() <= 2 and set(lowered.unique()) <= _BOOL_WORDS:
        return BOOLEAN, {}

    if try_parse_datetime(sample) is not None:
        return DATETIME, {}

    values, invalid = coerce_numeric(sample)
    if 1 - invalid / len(sample) >= NUMERIC_TEXT_MIN_RATIO:
        kind = _numeric_kind(values.dropna(), name, unique_count, unique_ratio)
        return kind, {"stored_as_text": True}

    if _ID_NAME_STRICT.search(name) and unique_ratio >= 0.9:
        return IDENTIFIER, {}

    if unique_count <= MAX_DIMENSION_CARDINALITY or unique_ratio <= CATEGORICAL_UNIQUE_RATIO:
        is_period = bool(lowered.str.fullmatch(_PERIOD_LABEL).mean() >= 0.8)
        extras = {"is_period_label": True} if is_period else {}
        return CATEGORICAL, extras

    return TEXT, {}


def _numeric_kind(values: pd.Series, name: str, unique_count: int, unique_ratio: float) -> str:
    """Distinguish measures from identifiers and year/month-style date parts."""
    finite = values[np.isfinite(values.astype(float))] if len(values) else values
    integer_valued = bool(len(finite)) and bool((finite == finite.round()).all())

    if integer_valued and _DATE_PART_NAME.match(name) and unique_count <= 366:
        return DATE_PART
    if integer_valued and _ID_NAME_STRICT.search(name) and unique_ratio >= 0.9:
        return IDENTIFIER
    if integer_valued and len(finite) > 1 and unique_count == len(finite):
        ordered = finite.sort_values()
        is_row_index = name.lower().startswith("unnamed") or _ID_NAME_STRICT.search(name)
        if (ordered.diff().dropna() == 1).all() and is_row_index:
            return IDENTIFIER
    return NUMERIC


# ---------------------------------------------------------------------------
# Quality flags
# ---------------------------------------------------------------------------

def _quality_flags(
    row_count: int,
    duplicate_count: int,
    missing_values: dict[str, dict[str, Any]],
    column_infos: list[dict[str, Any]],
    candidate_metrics: list[str],
    period_columns: list[str],
) -> list[str]:
    flags: list[str] = []
    if row_count == 0:
        return ["Dataset is empty."]

    if duplicate_count > 0:
        flags.append(f"{duplicate_count} duplicate rows detected.")

    empty = [i["name"] for i in column_infos if i["type"] == EMPTY]
    if empty:
        flags.append(f"Completely empty columns: {', '.join(empty)}")

    high_missing = [
        col for col, info in missing_values.items()
        if info["percent"] > HIGH_MISSING_PERCENT and col not in empty
    ]
    if high_missing:
        flags.append(f"High missing values (>20%): {', '.join(high_missing)}")

    constant = [
        i["name"] for i in column_infos
        if i["type"] != EMPTY and i["unique_count"] == 1 and row_count > 1 and i["missing_count"] == 0
    ]
    if constant:
        flags.append(f"Constant columns (single value): {', '.join(constant)}")

    as_text = [i["name"] for i in column_infos if i.get("stored_as_text")]
    if as_text:
        flags.append(f"Numbers stored as text: {', '.join(as_text)}")

    if not candidate_metrics:
        flags.append("No numeric metric columns were found; quantitative analysis is limited.")
    if not period_columns:
        flags.append("No date or period column was found; period comparisons are not possible.")
    return flags
