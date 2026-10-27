"""
Tests for the data quality checks and the anomaly detector.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.analytics import data_quality
from app.analytics.data_quality import detect_anomalies


def run_quality(df: pd.DataFrame, date_column: str | None = None) -> dict:
    # Called through the module so pytest does not mistake the tool for a test function.
    return data_quality.test_data_quality(df, date_column)


def checks(report: dict, check: str) -> list[dict]:
    return [i for i in report["issues"] if i["check"] == check]


@pytest.fixture
def clean_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-08-01", periods=10, freq="D"),
        "region": ["North", "South"] * 5,
        "revenue": [100.0 + i for i in range(10)],
    })


class TestDataQuality:
    def test_clean_dataset_passes(self, clean_df: pd.DataFrame):
        report = run_quality(clean_df, "date")
        assert report["passed"] is True
        assert report["flags"] == []
        assert report["duplicate_rows"] == 0
        assert report["missing_summary"] == {}
        assert report["row_count"] == 10
        assert report["column_count"] == 3

    def test_duplicates_are_counted(self, clean_df: pd.DataFrame):
        df = pd.concat([clean_df, clean_df.iloc[[0, 1]]], ignore_index=True)
        report = run_quality(df)
        assert report["duplicate_rows"] == 2
        assert report["duplicate_percent"] == pytest.approx(16.67)
        issue = checks(report, "duplicate_rows")[0]
        assert issue["severity"] == "high"  # > 10 % of rows
        assert report["passed"] is False

    def test_missing_values_and_severity(self):
        df = pd.DataFrame({
            "a": [1, 2, None, 4, 5, 6, 7, 8, 9, 10],      # 10 % -> low
            "b": [1, None, None, 4, 5, 6, 7, 8, 9, 10],    # 20 % -> medium
            "c": [None] * 6 + [1, 2, 3, 4],                # 60 % -> high
            "d": [None] * 10,                              # empty
        })
        report = run_quality(df)
        assert report["missing_summary"]["a"] == {"count": 1, "percent": 10.0}
        assert report["missing_summary"]["c"]["percent"] == 60.0
        severity = {i["column"]: i["severity"] for i in report["issues"] if i["check"] == "missing_values"}
        assert severity == {"a": "low", "b": "medium", "c": "high"}
        assert report["empty_columns"] == ["d"]
        assert checks(report, "empty_column")[0]["severity"] == "high"

    def test_constant_column(self, clean_df: pd.DataFrame):
        clean_df["currency"] = "USD"
        report = run_quality(clean_df)
        assert report["constant_columns"] == ["currency"]

    def test_inconsistent_category_spelling(self, clean_df: pd.DataFrame):
        clean_df.loc[1, "region"] = "south "
        clean_df.loc[3, "region"] = "SOUTH"
        report = run_quality(clean_df)
        groups = report["inconsistent_categories"]["region"]
        assert groups == [{"normalized": "south", "variants": ["SOUTH", "South", "south "]}]
        assert checks(report, "inconsistent_categories")[0]["severity"] == "medium"
        assert report["passed"] is False

    def test_whitespace_is_flagged(self, clean_df: pd.DataFrame):
        clean_df.loc[0, "region"] = " North"
        report = run_quality(clean_df)
        assert checks(report, "whitespace")[0]["count"] == 1

    def test_mixed_types_and_numeric_text(self):
        df = pd.DataFrame({
            "mixed": ["1", "2", "3", "4", "oops"],
            "text_numbers": ["1", "2", "3", "4", "5"],
        })
        report = run_quality(df)
        assert checks(report, "mixed_types")[0]["column"] == "mixed"
        assert checks(report, "mixed_types")[0]["count"] == 1
        assert checks(report, "numeric_stored_as_text")[0]["column"] == "text_numbers"
        # informational findings are not surfaced as flags
        assert not any("stored as text" in f for f in report["flags"])

    def test_negative_revenue_flagged(self, clean_df: pd.DataFrame):
        clean_df.loc[2, "revenue"] = -50.0
        report = run_quality(clean_df)
        assert checks(report, "negative_values")[0]["count"] == 1

    def test_empty_dataframe(self):
        report = run_quality(pd.DataFrame({"a": []}))
        assert report["passed"] is False
        assert checks(report, "empty_dataset")

    def test_issues_sorted_by_severity(self, clean_df: pd.DataFrame):
        clean_df["currency"] = "USD"            # low
        clean_df.loc[0:5, "revenue"] = None     # high
        severities = [i["severity"] for i in run_quality(clean_df)["issues"]]
        assert severities == sorted(severities, key=data_quality.SEVERITY_ORDER.__getitem__)

    def test_report_is_json_safe(self, clean_df: pd.DataFrame):
        clean_df.loc[3, "revenue"] = None
        json.dumps(run_quality(clean_df, "date"), allow_nan=False)

    def test_unknown_date_column(self, clean_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Date column 'nope'"):
            run_quality(clean_df, "nope")


class TestDateConsistency:
    def test_clean_daily_dates(self, clean_df: pd.DataFrame):
        info = run_quality(clean_df, "date")["date_consistency"]
        assert info["is_date_like"] is True
        assert info["min"].startswith("2024-08-01")
        assert info["max"].startswith("2024-08-10")
        assert info["span_days"] == 9
        assert info["row_order"] == "ascending"
        assert info["inferred_frequency"] == "daily"
        assert info["gap_count"] == 0
        assert info["unparseable_count"] == 0

    def test_daily_gap_detected(self, clean_df: pd.DataFrame):
        df = clean_df.drop(index=[4, 5, 6]).reset_index(drop=True)  # 5th..7th Aug missing
        report = run_quality(df, "date")
        info = report["date_consistency"]
        assert info["gap_count"] == 1
        assert info["gaps"] == [{"after": "2024-08-04", "before": "2024-08-08", "missing_periods": 3}]
        assert checks(report, "date_gaps")

    def test_monthly_gap_detected(self):
        df = pd.DataFrame({"d": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-05-01"]), "v": range(4)})
        info = run_quality(df, "d")["date_consistency"]
        assert info["inferred_frequency"] == "monthly"
        assert info["gap_count"] == 1
        assert info["gaps"][0]["missing_periods"] == 1

    def test_unparseable_dates(self):
        df = pd.DataFrame({"d": ["2024-08-01", "2024-08-02", "2024-08-03", "2024-08-04", "not a date"], "v": range(5)})
        report = run_quality(df, "d")
        assert report["date_consistency"]["unparseable_count"] == 1
        assert checks(report, "unparseable_dates")[0]["severity"] == "medium"

    def test_row_order_unordered(self, clean_df: pd.DataFrame):
        df = clean_df.sample(frac=1, random_state=3).reset_index(drop=True)
        assert run_quality(df, "date")["date_consistency"]["row_order"] == "unordered"

    def test_future_dates(self):
        df = pd.DataFrame({"d": pd.to_datetime(["2024-08-01", "2024-08-02", "2200-01-01"]), "v": range(3)})
        report = run_quality(df, "d")
        assert report["date_consistency"]["future_dates"] == 1
        assert checks(report, "future_dates")

    def test_period_labels_skip_date_checks(self):
        df = pd.DataFrame({"month": ["August", "September"] * 3, "v": range(6)})
        report = run_quality(df, "month")
        assert report["date_consistency"]["is_date_like"] is False
        assert checks(report, "date_not_parsed")[0]["severity"] == "info"
        assert report["passed"] is True


class TestDetectAnomalies:
    @pytest.fixture
    def df(self) -> pd.DataFrame:
        # Sorted: -40 10 11 12 12 13 14 15 15 95 -> Q1 = 11.25, Q3 = 14.75, IQR = 3.5,
        # bounds 6.0 .. 20.0, so 95 and -40 are the only outliers.
        return pd.DataFrame({"v": [10, 11, 12, 12, 13, 14, 15, 15, 95, -40]})

    def test_iqr_known_answer(self, df: pd.DataFrame):
        result = detect_anomalies(df, "v", "iqr")
        s = result["summary"]
        assert (s["q1"], s["q3"], s["iqr"]) == (11.25, 14.75, 3.5)
        assert (s["lower_bound"], s["upper_bound"]) == (6.0, 20.0)
        assert result["anomaly_count"] == 2
        values = {a["row_index"]: a for a in result["anomalies"]}
        assert values[8]["value"] == 95 and values[8]["direction"] == "high"
        assert values[9]["value"] == -40 and values[9]["direction"] == "low"
        assert s["n_values"] == 10

    def test_iqr_bounds_formula(self, df: pd.DataFrame):
        s = detect_anomalies(df, "v", "iqr")["summary"]
        q1, q3 = float(df["v"].quantile(0.25)), float(df["v"].quantile(0.75))
        assert s["q1"] == pytest.approx(q1)
        assert s["q3"] == pytest.approx(q3)
        assert s["lower_bound"] == pytest.approx(q1 - 1.5 * (q3 - q1))
        assert s["upper_bound"] == pytest.approx(q3 + 1.5 * (q3 - q1))

    def test_ordered_largest_deviation_first(self, df: pd.DataFrame):
        result = detect_anomalies(df, "v", "iqr")
        assert result["anomalies"][0]["value"] == 95  # |score| larger than for -40

    def test_zscore_known_answer(self):
        values = [10.0] * 30 + [100.0]
        result = detect_anomalies(pd.DataFrame({"v": values}), "v", "zscore")
        assert result["anomaly_count"] == 1
        anomaly = result["anomalies"][0]
        assert anomaly["row_index"] == 30 and anomaly["value"] == 100
        series = pd.Series(values)
        expected_z = (100 - series.mean()) / series.std(ddof=1)
        assert anomaly["score"] == pytest.approx(expected_z, abs=1e-3)

    def test_method_aliases(self, df: pd.DataFrame):
        assert detect_anomalies(df, "v", "z-score")["method"] == "zscore"
        assert detect_anomalies(df, "v", "IQR")["method"] == "iqr"

    def test_custom_threshold(self, df: pd.DataFrame):
        strict = detect_anomalies(df, "v", "iqr", threshold=0.1)["anomaly_count"]
        lenient = detect_anomalies(df, "v", "iqr", threshold=100)["anomaly_count"]
        assert strict > 2
        assert lenient == 0

    def test_max_anomalies_truncates_list_but_not_count(self):
        df = pd.DataFrame({"v": [1.0] * 50 + [1000.0, 2000.0, 3000.0]})
        result = detect_anomalies(df, "v", "iqr", max_anomalies=2)
        assert result["anomaly_count"] == 3
        assert len(result["anomalies"]) == 2
        assert result["truncated"] is True
        assert result["anomalies"][0]["value"] == 3000

    def test_no_anomalies(self):
        result = detect_anomalies(pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8]}), "v")
        assert result["anomaly_count"] == 0
        assert result["anomalies"] == []
        assert result["summary"]["anomaly_percent"] == 0.0

    def test_constant_column_zscore_has_no_anomalies(self):
        result = detect_anomalies(pd.DataFrame({"v": [5.0] * 10}), "v", "zscore")
        assert result["anomaly_count"] == 0
        assert any("zero variance" in w for w in result["warnings"])

    def test_zero_iqr_warns(self):
        result = detect_anomalies(pd.DataFrame({"v": [5.0] * 9 + [50.0]}), "v", "iqr")
        assert result["anomaly_count"] == 1
        assert any("interquartile range is zero" in w for w in result["warnings"])

    def test_small_sample_zscore_warning(self):
        result = detect_anomalies(pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, 100.0]}), "v", "zscore")
        assert any("mathematically impossible" in w for w in result["warnings"])

    def test_too_few_values(self):
        result = detect_anomalies(pd.DataFrame({"v": [1.0, 2.0]}), "v")
        assert result["anomaly_count"] == 0
        assert any("At least" in w for w in result["warnings"])

    def test_missing_values_ignored_and_index_labels_kept(self):
        df = pd.DataFrame({"v": [1.0, None, 1.0, 1.0, 1.0, 1.0, 500.0]}, index=list("abcdefg"))
        result = detect_anomalies(df, "v")
        assert result["summary"]["n_missing"] == 1
        assert result["anomalies"][0]["index_label"] == "g"
        assert result["anomalies"][0]["row_index"] == 6

    def test_text_numbers_are_coerced(self):
        df = pd.DataFrame({"v": ["1", "1", "1", "1", "1", "1", "$900"]})
        assert detect_anomalies(df, "v")["anomaly_count"] == 1

    def test_json_safe(self, df: pd.DataFrame):
        json.dumps(detect_anomalies(df, "v"), allow_nan=False)
        json.dumps(detect_anomalies(pd.DataFrame({"v": [5.0] * 10}), "v", "zscore"), allow_nan=False)

    def test_invalid_inputs(self, df: pd.DataFrame):
        with pytest.raises(ValueError, match="not found"):
            detect_anomalies(df, "nope")
        with pytest.raises(ValueError, match="Unsupported method"):
            detect_anomalies(df, "v", "magic")
        with pytest.raises(ValueError, match="threshold"):
            detect_anomalies(df, "v", threshold=-1)
        with pytest.raises(ValueError, match="not numeric"):
            detect_anomalies(pd.DataFrame({"v": list("abcdef")}), "v")
