"""
Tests for the dataset profiling tool.

Verifies schema inference, missing-value counts, duplicate detection,
and numeric summary statistics against known sample data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.analytics.profiling import profile_dataframe, profile_dataset


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a small sample CSV for testing (row 3 duplicates row 4; one missing 'units')."""
    df = pd.DataFrame({
        "date": ["2024-08-01", "2024-08-02", "2024-08-03", "2024-08-03"],
        "region": ["North", "South", "North", "North"],
        "revenue": [1000.0, 1500.0, 1200.0, 1200.0],
        "units": [10, None, 12, 12],
    })
    path = tmp_path / "test_data.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def business_df() -> pd.DataFrame:
    return pd.DataFrame({
        "order_id": range(1, 9),
        "date": pd.date_range("2024-08-01", periods=8, freq="D"),
        "region": ["North", "South", "North", "East", "South", "East", "North", "South"],
        "month": [8] * 8,
        "revenue": [10.5, 20.0, 15.25, 30.0, 12.0, 18.0, 25.0, 22.5],
        "units_text": ["1", "2", "3", "4", "5", "6", "7", "8"],
        "const": ["x"] * 8,
    })


class TestProfileDataset:
    """Tests for profile_dataset()."""

    def test_returns_schema(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert "schema" in result
        assert "date" in result["schema"]
        assert "revenue" in result["schema"]

    def test_row_and_column_counts(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert result["row_count"] == 4
        assert result["column_count"] == 4

    def test_detects_missing_values(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert "units" in result["missing_values"]
        assert result["missing_values"]["units"]["count"] == 1
        assert result["missing_values"]["units"]["percent"] == 25.0

    def test_detects_duplicates(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert result["duplicate_count"] == 1
        assert any("1 duplicate rows" in flag for flag in result["quality_flags"])

    def test_numeric_summary(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert "revenue" in result["numeric_summary"]
        assert "mean" in result["numeric_summary"]["revenue"]
        assert result["numeric_summary"]["revenue"]["mean"] == 1225.0
        assert result["numeric_summary"]["revenue"]["max"] == 1500.0

    def test_sample_rows(self, sample_csv: Path):
        result = profile_dataset(str(sample_csv))
        assert len(result["sample_rows"]) > 0

    def test_output_is_strict_json(self, sample_csv: Path):
        """NaN in sample rows / stats must not leak (FastAPI cannot serialise NaN)."""
        result = profile_dataset(str(sample_csv))
        json.dumps(result, allow_nan=False)
        assert result["sample_rows"][1]["units"] is None

    def test_unsupported_file_raises(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{}")
        with pytest.raises(ValueError, match="Unsupported file type"):
            profile_dataset(str(path))

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="not found"):
            profile_dataset(str(tmp_path / "nope.csv"))

    def test_empty_file_raises(self, tmp_path: Path):
        path = tmp_path / "empty.csv"
        path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            profile_dataset(str(path))

    def test_malformed_excel_raises_cleanly(self, tmp_path: Path):
        path = tmp_path / "broken.xlsx"
        path.write_bytes(b"this is not a workbook")
        with pytest.raises(ValueError, match="Could not parse"):
            profile_dataset(str(path))

    def test_header_only_csv_is_flagged_empty(self, tmp_path: Path):
        path = tmp_path / "header_only.csv"
        path.write_text("a,b,c\n")
        result = profile_dataset(str(path))
        assert result["row_count"] == 0
        assert result["quality_flags"] == ["Dataset is empty."]

    def test_latin1_csv_is_decoded(self, tmp_path: Path):
        path = tmp_path / "latin.csv"
        path.write_bytes("city,sales\nZ\xfcrich,10\nMalm\xf6,20\n".encode("latin-1"))
        result = profile_dataset(str(path))
        assert result["row_count"] == 2

    def test_excel_roundtrip(self, tmp_path: Path):
        path = tmp_path / "book.xlsx"
        pd.DataFrame({"d": pd.to_datetime(["2024-01-01", "2024-02-01"]), "v": [1, 2]}).to_excel(path, index=False)
        result = profile_dataset(str(path))
        assert result["column_types"]["d"] == "datetime"
        assert result["date_ranges"]["d"]["min"].startswith("2024-01-01")


class TestSemanticTypes:
    """Semantic typing and planner hints."""

    def test_column_types(self, business_df: pd.DataFrame):
        types = profile_dataframe(business_df)["column_types"]
        assert types["order_id"] == "identifier"
        assert types["date"] == "datetime"
        assert types["region"] == "categorical"
        assert types["month"] == "date_part"
        assert types["revenue"] == "numeric"
        assert types["units_text"] == "numeric"

    def test_numeric_text_is_flagged(self, business_df: pd.DataFrame):
        result = profile_dataframe(business_df)
        info = next(c for c in result["columns"] if c["name"] == "units_text")
        assert info["stored_as_text"] is True
        assert any("units_text" in f for f in result["quality_flags"])
        assert result["numeric_summary"]["units_text"]["mean"] == 4.5

    def test_candidates(self, business_df: pd.DataFrame):
        result = profile_dataframe(business_df)
        assert result["candidate_metrics"] == ["revenue", "units_text"]
        assert result["candidate_dimensions"] == ["region"]
        assert result["date_columns"] == ["date"]
        assert "month" in result["period_columns"]
        assert result["identifier_columns"] == ["order_id"]

    def test_date_range(self, business_df: pd.DataFrame):
        rng = profile_dataframe(business_df)["date_ranges"]["date"]
        assert rng["min"].startswith("2024-08-01")
        assert rng["max"].startswith("2024-08-08")
        assert rng["span_days"] == 7

    def test_constant_column_flagged(self, business_df: pd.DataFrame):
        flags = profile_dataframe(business_df)["quality_flags"]
        assert any("Constant columns" in f and "const" in f for f in flags)

    def test_month_name_column_is_period_label(self):
        df = pd.DataFrame({"month": ["August", "September"] * 3, "revenue": [1, 2, 3, 4, 5, 6]})
        result = profile_dataframe(df)
        assert result["column_types"]["month"] == "categorical"
        assert "month" in result["period_columns"]

    def test_empty_column_and_high_missing_flags(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4], "b": [None] * 4, "c": [1, None, None, None]})
        result = profile_dataframe(df)
        assert result["column_types"]["b"] == "empty"
        flags = " ".join(result["quality_flags"])
        assert "Completely empty columns: b" in flags
        assert "High missing values (>20%): c" in flags

    def test_no_metric_or_period_flags(self):
        df = pd.DataFrame({"name": ["a", "b", "c"]})
        flags = " ".join(profile_dataframe(df)["quality_flags"])
        assert "No numeric metric columns" in flags
        assert "No date or period column" in flags

    def test_single_row_has_no_nan_in_stats(self):
        result = profile_dataframe(pd.DataFrame({"x": [5.0]}))
        json.dumps(result, allow_nan=False)
        assert result["numeric_summary"]["x"]["std"] is None
