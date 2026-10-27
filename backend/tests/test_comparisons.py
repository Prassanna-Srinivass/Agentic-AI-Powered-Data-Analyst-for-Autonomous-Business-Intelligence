"""
Tests for the comparison analytics tools.

Verifies period comparison and group metric decomposition
against known expected values (calculated by hand).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.analytics.comparisons import compare_periods, group_metric_change


@pytest.fixture
def sales_df() -> pd.DataFrame:
    """Create a sample sales DataFrame for testing.

    August total = 10,000; September total = 9,000 -> change -1,000 (-10%).
    Region changes: North -1000, South +200, East -200.
    """
    return pd.DataFrame({
        "month": ["August", "August", "August", "September", "September", "September"],
        "region": ["North", "South", "East", "North", "South", "East"],
        "revenue": [5000, 3000, 2000, 4000, 3200, 1800],
    })


@pytest.fixture
def dated_df() -> pd.DataFrame:
    """Same figures as ``sales_df`` but with real ISO dates (two rows per region and month)."""
    rows = []
    for region, aug, sep in [("North", 5000, 4000), ("South", 3000, 3200), ("East", 2000, 1800)]:
        rows += [
            ("2024-08-05", region, aug / 2), ("2024-08-20", region, aug / 2),
            ("2024-09-05", region, sep / 2), ("2024-09-20", region, sep / 2),
        ]
    # A July row must never leak into either comparison.
    rows.append(("2024-07-15", "North", 777))
    return pd.DataFrame(rows, columns=["date", "region", "revenue"])


class TestComparePeriods:
    """Tests for compare_periods()."""

    def test_returns_expected_keys(self, sales_df: pd.DataFrame):
        result = compare_periods(sales_df, "revenue", "month", "August", "September")
        assert "metric" in result
        assert "period_a_total" in result
        assert "period_b_total" in result
        assert "absolute_change" in result
        assert "percent_change" in result

    def test_known_answer_label_periods(self, sales_df: pd.DataFrame):
        result = compare_periods(sales_df, "revenue", "month", "August", "September")
        assert result["period_a_total"] == 10000
        assert result["period_b_total"] == 9000
        assert result["absolute_change"] == -1000
        assert result["percent_change"] == -10.0
        assert result["direction"] == "decrease"
        assert result["period_a_row_count"] == 3
        assert result["period_b_row_count"] == 3

    def test_known_answer_date_column_with_month_names(self, dated_df: pd.DataFrame):
        result = compare_periods(dated_df, "revenue", "date", "August 2024", "September 2024")
        assert result["period_a_total"] == 10000
        assert result["period_b_total"] == 9000
        assert result["percent_change"] == -10.0
        assert result["period_a_match"] == "date_range"

    @pytest.mark.parametrize(
        ("a", "b"),
        [("2024-08", "2024-09"), ("Aug 2024", "Sep 2024"), ("august", "september")],
    )
    def test_period_label_variants_are_equivalent(self, dated_df: pd.DataFrame, a: str, b: str):
        result = compare_periods(dated_df, "revenue", "date", a, b)
        assert result["absolute_change"] == -1000

    def test_percent_change_uses_absolute_baseline(self):
        df = pd.DataFrame({"p": ["a", "b"], "v": [-100.0, -50.0]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["absolute_change"] == 50
        assert result["percent_change"] == 50.0  # improved from -100 to -50

    def test_zero_baseline_has_no_percent(self):
        df = pd.DataFrame({"p": ["a", "b"], "v": [0.0, 10.0]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["absolute_change"] == 10
        assert result["percent_change"] is None

    def test_aggregation_mean_and_count(self, sales_df: pd.DataFrame):
        mean = compare_periods(sales_df, "revenue", "month", "August", "September", aggregation="mean")
        assert mean["period_a_total"] == pytest.approx(3333.3333)
        assert mean["period_b_total"] == 3000
        count = compare_periods(sales_df, "revenue", "month", "August", "September", aggregation="count")
        assert count["period_a_total"] == 3
        assert count["absolute_change"] == 0
        assert count["direction"] == "no_change"

    def test_text_currency_metric_is_parsed(self):
        df = pd.DataFrame({"p": ["a", "a", "b"], "v": ["$1,000.50", "(200)", "$300"]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["period_a_total"] == 800.5
        assert result["period_b_total"] == 300

    def test_currency_before_parentheses_is_negative(self):
        df = pd.DataFrame({"p": ["a", "a", "b"], "v": ["£(5)", "€1,200", "12%"]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["period_a_total"] == 1195
        assert result["period_b_total"] == 12

    def test_missing_metric_values_are_ignored(self):
        df = pd.DataFrame({"p": ["a", "a", "b"], "v": [10.0, None, 5.0]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["period_a_total"] == 10
        assert result["period_a_row_count"] == 2

    def test_non_numeric_cells_are_reported(self):
        df = pd.DataFrame({"p": ["a", "a", "a", "b"], "v": ["1", "2", "3", "oops"]})
        result = compare_periods(df, "v", "p", "a", "b")
        assert result["excluded_non_numeric_rows"] == 1
        assert any("non-numeric" in w for w in result["warnings"])

    def test_json_safe(self, sales_df: pd.DataFrame):
        json.dumps(compare_periods(sales_df, "revenue", "month", "August", "September"), allow_nan=False)

    def test_regex_characters_are_literal(self):
        df = pd.DataFrame({"p": ["a(1)", "b+2"], "v": [1.0, 2.0]})
        result = compare_periods(df, "v", "p", "a(1)", "b+2")
        assert result["absolute_change"] == 1

    # --- failure behaviour -------------------------------------------------------------
    def test_missing_metric_column(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Metric column 'nope'"):
            compare_periods(sales_df, "nope", "month", "August", "September")

    def test_missing_date_column(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Date column 'nope'"):
            compare_periods(sales_df, "revenue", "nope", "August", "September")

    def test_unknown_period_raises_instead_of_zero(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="matched no rows"):
            compare_periods(sales_df, "revenue", "month", "August", "October")

    def test_identical_periods_rejected(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="different"):
            compare_periods(sales_df, "revenue", "month", "August", "august")

    def test_non_numeric_metric_rejected(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="not numeric"):
            compare_periods(sales_df, "region", "month", "August", "September")

    def test_unsupported_aggregation(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Unsupported aggregation"):
            compare_periods(sales_df, "revenue", "month", "August", "September", aggregation="mode")

    def test_overlapping_periods_warn(self):
        df = pd.DataFrame({"d": ["2024-08-01", "2024-08-02", "2024-09-01"], "v": [1.0, 2.0, 3.0]})
        result = compare_periods(df, "v", "d", "2024-08-01", "2024-08")
        assert any("overlap" in w for w in result["warnings"])


class TestGroupMetricChange:
    """Tests for group_metric_change()."""

    def test_returns_expected_keys(self, sales_df: pd.DataFrame):
        result = group_metric_change(
            sales_df, "revenue", "month", "region", "August", "September"
        )
        assert "metric" in result
        assert "group_by" in result
        assert "segments" in result

    def test_known_segment_contributions(self, sales_df: pd.DataFrame):
        result = group_metric_change(sales_df, "revenue", "month", "region", "August", "September")
        assert result["total_change"] == -1000
        by_group = {s["group"]: s for s in result["segments"]}

        assert by_group["North"]["absolute_change"] == -1000
        assert by_group["North"]["percent_change"] == -20.0
        assert by_group["North"]["contribution_pct"] == 100.0
        assert by_group["South"]["absolute_change"] == 200
        assert by_group["South"]["contribution_pct"] == -20.0
        assert by_group["East"]["absolute_change"] == -200
        assert by_group["East"]["percent_change"] == -10.0
        assert by_group["East"]["contribution_pct"] == 20.0

        assert sum(s["contribution_pct"] for s in result["segments"]) == pytest.approx(100.0)

    def test_sorted_by_absolute_change_with_stable_ties(self, sales_df: pd.DataFrame):
        result = group_metric_change(sales_df, "revenue", "month", "region", "August", "September")
        assert [s["group"] for s in result["segments"]] == ["North", "East", "South"]

    def test_largest_contributor_and_offset(self, sales_df: pd.DataFrame):
        result = group_metric_change(sales_df, "revenue", "month", "region", "August", "September")
        assert result["direction"] == "decrease"
        assert result["largest_contributor"]["group"] == "North"
        assert result["largest_offset"]["group"] == "South"

    def test_reconciliation_self_check(self, sales_df: pd.DataFrame):
        result = group_metric_change(sales_df, "revenue", "month", "region", "August", "September")
        assert result["reconciliation"]["reconciled"] is True
        assert result["reconciliation"]["segment_sum"] == -1000
        assert sum(result["segment_changes"].values()) == -1000

    def test_matches_compare_periods(self, dated_df: pd.DataFrame):
        total = compare_periods(dated_df, "revenue", "date", "2024-08", "2024-09")
        grouped = group_metric_change(dated_df, "revenue", "date", "region", "2024-08", "2024-09")
        assert grouped["total_change"] == total["absolute_change"]
        assert grouped["period_a_total"] == total["period_a_total"]

    def test_group_present_in_only_one_period(self):
        df = pd.DataFrame({
            "m": ["a", "a", "b", "b"],
            "g": ["x", "y", "x", "z"],
            "v": [10.0, 5.0, 12.0, 4.0],
        })
        result = group_metric_change(df, "v", "m", "g", "a", "b")
        by_group = {s["group"]: s for s in result["segments"]}
        assert by_group["y"]["period_b_value"] == 0 and by_group["y"]["absolute_change"] == -5
        assert by_group["z"]["period_a_value"] == 0 and by_group["z"]["percent_change"] is None
        assert result["total_change"] == 1
        assert result["reconciliation"]["reconciled"]

    def test_missing_group_values_are_not_dropped(self):
        df = pd.DataFrame({
            "m": ["a", "a", "b", "b"],
            "g": ["x", None, "x", None],
            "v": [10.0, 5.0, 12.0, 1.0],
        })
        result = group_metric_change(df, "v", "m", "g", "a", "b")
        by_group = {s["group"]: s for s in result["segments"]}
        assert by_group["(missing)"]["absolute_change"] == -4
        assert result["total_change"] == -2
        assert result["reconciliation"]["reconciled"]
        assert any("(missing)" in w for w in result["warnings"])

    def test_zero_total_change_has_no_contribution(self):
        df = pd.DataFrame({"m": ["a", "a", "b", "b"], "g": ["x", "y", "x", "y"], "v": [5.0, 5.0, 7.0, 3.0]})
        result = group_metric_change(df, "v", "m", "g", "a", "b")
        assert result["total_change"] == 0
        assert result["direction"] == "no_change"
        assert result["largest_contributor"] is None
        assert all(s["contribution_pct"] is None for s in result["segments"])

    def test_max_segments_merges_remainder(self):
        groups = [f"g{i}" for i in range(6)]
        df = pd.DataFrame({
            "m": ["a"] * 6 + ["b"] * 6,
            "g": groups * 2,
            "v": [10.0] * 6 + [10.0 - i for i in range(6)],
        })
        result = group_metric_change(df, "v", "m", "g", "a", "b", max_segments=3)
        assert [s["group"] for s in result["segments"]] == ["g5", "g4", "(other)"]
        assert result["segment_count"] == 6
        assert result["segments"][-1]["absolute_change"] == -6  # g3 + g2 + g1 + g0 = -3-2-1-0
        assert result["reconciliation"]["reconciled"]

    def test_count_aggregation(self, sales_df: pd.DataFrame):
        extra = pd.concat([sales_df, sales_df.iloc[[3]]], ignore_index=True)  # extra September North row
        result = group_metric_change(extra, "revenue", "month", "region", "August", "September", aggregation="count")
        assert result["total_change"] == 1
        assert result["largest_contributor"]["group"] == "North"

    def test_non_additive_aggregation_rejected(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Unsupported aggregation"):
            group_metric_change(sales_df, "revenue", "month", "region", "August", "September", aggregation="mean")

    def test_invalid_columns(self, sales_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Group column 'nope'"):
            group_metric_change(sales_df, "revenue", "month", "nope", "August", "September")
        with pytest.raises(ValueError, match="must differ"):
            group_metric_change(sales_df, "revenue", "month", "month", "August", "September")

    def test_json_safe(self, sales_df: pd.DataFrame):
        json.dumps(
            group_metric_change(sales_df, "revenue", "month", "region", "August", "September"),
            allow_nan=False,
        )
