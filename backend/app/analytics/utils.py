"""
Shared helpers for the deterministic analytics tools.

- ``load_dataframe``     Safe CSV/Excel loading with row limits.
- ``to_jsonable``        Convert pandas/numpy values into strict-JSON-safe Python values.
- ``try_parse_datetime`` Best-effort date detection that never executes anything dynamic.
"""

from __future__ import annotations

import math
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Hard cap on rows processed per dataset (plan: "limit rows, processing time ...").
MAX_ROWS = 1_000_000

# Cell text is untrusted; never pass unbounded strings downstream (e.g. into an LLM prompt).
MAX_CELL_TEXT_LENGTH = 200

_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_NUMERIC_TEXT = r"^\s*[-+]?\d+(?:\.\d+)?\s*$"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class DatasetLoadError(ValueError):
    """A file could not be loaded; the message is safe to show to users (no cell contents)."""

def load_dataframe(file_path: str | Path, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """
    Load a CSV or Excel file into a DataFrame.

    Raises
    ------
    ValueError
        For unsupported file types, unreadable/malformed/empty files, or
        files exceeding ``max_rows`` (we refuse rather than silently truncate,
        because truncated data would produce wrong totals).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    if not path.exists():
        raise ValueError(f"File not found: {path.name}")

    try:
        if suffix == ".csv":
            df = _read_csv(path, max_rows)
        else:
            df = pd.read_excel(path)
    except DatasetLoadError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise DatasetLoadError("The file is empty or has no columns.") from exc
    except Exception as exc:  # malformed workbook / parser failure — sanitised message
        raise DatasetLoadError(f"Could not parse '{path.name}': {type(exc).__name__}") from exc

    if len(df) > max_rows:
        raise ValueError(f"Dataset has more than the supported maximum of {max_rows:,} rows.")
    if len(df.columns) == 0:
        raise ValueError("The file is empty or has no columns.")

    # Normalise headers so tool arguments match reliably (Excel headers may be numbers/padded).
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _read_csv(path: Path, max_rows: int) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            # Read one extra row so oversized files can be detected without loading everything.
            return pd.read_csv(path, encoding=encoding, nrows=max_rows + 1)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise DatasetLoadError("Could not decode the CSV file with a supported encoding.") from last_error


# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------

def to_jsonable(value: Any, max_text_length: int | None = MAX_CELL_TEXT_LENGTH) -> Any:
    """
    Recursively convert values to strict-JSON-safe Python objects.

    NaN / ±inf / NaT become ``None``; numpy scalars become Python scalars;
    timestamps become ISO-8601 strings; strings longer than ``max_text_length`` are truncated
    (pass ``None`` to keep them intact, e.g. when persisting generated answers).
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, max_text_length) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v, max_text_length) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v, max_text_length) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, np.timedelta64)):
        return str(value)
    text = str(value)
    if max_text_length is not None and len(text) > max_text_length:
        text = text[:max_text_length] + "…"
    return text


def coerce_numeric(series: pd.Series) -> tuple[pd.Series, int]:
    """
    Convert a column to floats, tolerating text such as ``"$1,200.50"``, ``"(35)"`` or ``"12%"``.

    Returns ``(values, invalid_count)`` where ``invalid_count`` is the number of non-null cells
    that could not be interpreted as numbers (they become NaN in ``values``).
    """
    if pd.api.types.is_bool_dtype(series):
        return series.astype(float), 0
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float), 0

    text = series.astype(object).where(series.notna()).astype(str).str.strip()
    text = text.where(series.notna())
    stripped = text.str.replace(r"[$€£¥,%\s]", "", regex=True)
    negative = stripped.str.fullmatch(r"\(.*\)", na=False)
    cleaned = stripped.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    values = pd.to_numeric(cleaned, errors="coerce")
    values = values.where(~negative, -values)
    invalid = int((values.isna() & series.notna()).sum())
    return values.astype(float), invalid


def safe_round(value: Any, digits: int = 4) -> float | None:
    """Round a numeric value; return ``None`` for missing / non-finite values."""
    if value is None:
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Date detection
# ---------------------------------------------------------------------------

def try_parse_datetime(series: pd.Series, min_ratio: float = 0.8) -> pd.Series | None:
    """
    Parse a column as datetimes if (at least ``min_ratio`` of) its non-null values look like dates.

    Returns a tz-naive ``datetime64`` Series aligned with ``series`` (unparseable cells are
    ``NaT``), or ``None`` when the column is not date-like. Numeric columns and pure month-name
    labels (e.g. "August") are deliberately *not* treated as dates.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            return series.dt.tz_convert("UTC").dt.tz_localize(None)
        return series
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return None

    present = series.notna().to_numpy()
    if not present.any():
        return None

    texts = series[present].astype(str).str.strip()
    if texts.str.fullmatch(_NUMERIC_TEXT).all():
        return None

    # Month names alone parse as "this year" dates in dateutil; require a digit to count as a date.
    candidates = texts.where(texts.str.contains(r"\d"))
    parsed = _parse_dates(candidates)
    if parsed.notna().sum() < min_ratio * len(texts):
        # Fast path failed (often because formats are mixed); retry element-wise.
        mixed = _parse_dates(candidates, mixed=True)
        if mixed.notna().sum() > parsed.notna().sum():
            parsed = mixed

    values = np.full(len(series), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    values[present] = parsed.to_numpy(dtype="datetime64[ns]")
    result = pd.Series(values, index=series.index, name=series.name)

    ratio = float(result.notna().sum()) / float(present.sum())
    return result if ratio >= min_ratio else None


def _parse_dates(texts: pd.Series, mixed: bool = False) -> pd.Series:
    """Parse text to tz-naive datetimes (UTC-normalised); failures become NaT."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if mixed:
            parsed = pd.to_datetime(texts, errors="coerce", utc=True, format="mixed")
        else:
            parsed = pd.to_datetime(texts, errors="coerce", utc=True)
    return parsed.dt.tz_localize(None)


def value_label(value: Any) -> str | None:
    """Stable string label for a cell value (``2024.0`` -> ``"2024"``; missing -> ``None``)."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return str(int(value))
    return str(value).strip()
