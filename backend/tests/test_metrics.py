"""
Tests for metric aggregation and trend helpers.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.analytics.metrics import aggregate_metric, metric_trend


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2024-07-15", "2024-08-01", "2024-08-20", "2024-09-02", "2024-09-30", "2024-10-01"],
        "region": ["North", "North", "South", "South", "East", None],
        "revenue": [100.0, 200.0, 300.0, 50.0, 25.0, 10.0],
    })


class TestAggregateMetric:
    def test_overall_sum(self, df: pd.DataFrame):
        result = aggregate_metric(df, "revenue")
        assert result["value"] == 685
        assert result["row_count"] == 6
        assert result["groups"] == []

    @pytest.mark.parametrize(
        ("agg", "expected"),
        [("mean", 685 / 6), ("median", 75.0), ("min", 10), ("max", 300), ("count", 6)],
    )
    def test_other_aggregations(self, df: pd.DataFrame, agg: str, expected: float):
        assert aggregate_metric(df, "revenue", agg)["value"] == pytest.approx(expected, abs=1e-3)

    def test_grouped_sum_with_shares(self, df: pd.DataFrame):
        result = aggregate_metric(df, "revenue", group_column="region")
        groups = {g["group"]: g for g in result["groups"]}
        assert [g["group"] for g in result["groups"]] == ["South", "North", "East", "(missing)"]
        assert groups["South"]["value"] == 350
        assert groups["South"]["share_pct"] == pytest.approx(51.09, abs=0.01)
        assert groups["(missing)"]["value"] == 10
        assert sum(g["value"] for g in result["groups"]) == result["value"]

    def test_top_n_merges_remainder_for_sum(self, df: pd.DataFrame):
        result = aggregate_metric(df, "revenue", group_column="region", top_n=2)
        assert [g["group"] for g in result["groups"]] == ["South", "North", "(other)"]
        assert result["groups"][-1]["value"] == 35
        assert result["group_count"] == 4
        assert sum(g["value"] for g in result["groups"]) == result["value"]

    def test_top_n_truncates_for_mean(self, df: pd.DataFrame):
        result = aggregate_metric(df, "revenue", "mean", group_column="region", top_n=2)
        assert len(result["groups"]) == 2
        assert all(g["share_pct"] is None for g in result["groups"])
        assert result["warnings"]

    def test_errors(self, df: pd.DataFrame):
        with pytest.raises(ValueError, match="not found"):
            aggregate_metric(df, "nope")
        with pytest.raises(ValueError, match="Group column"):
            aggregate_metric(df, "revenue", group_column="nope")
        with pytest.raises(ValueError, match="Unsupported aggregation"):
            aggregate_metric(df, "revenue", "mode")
        with pytest.raises(ValueError, match="not numeric"):
            aggregate_metric(df, "region")

    def test_json_safe(self, df: pd.DataFrame):
        json.dumps(aggregate_metric(df, "revenue", group_column="region"), allow_nan=False)


class TestMetricTrend:
    def test_monthly_sum(self, df: pd.DataFrame):
        result = metric_trend(df, "revenue", "date")
        assert [(p["period"], p["value"], p["row_count"]) for p in result["points"]] == [
            ("2024-07", 100, 1),
            ("2024-08", 500, 2),
            ("2024-09", 75, 2),
            ("2024-10", 10, 1),
        ]

    def test_quarterly_and_mean(self, df: pd.DataFrame):
        result = metric_trend(df, "revenue", "date", freq="quarter", aggregation="mean")
        by_period = {p["period"]: p["value"] for p in result["points"]}
        assert by_period["2024Q3"] == pytest.approx(675 / 5)
        assert by_period["2024Q4"] == 10

    def test_daily_only_includes_periods_with_data(self, df: pd.DataFrame):
        assert len(metric_trend(df, "revenue", "date", freq="day")["points"]) == 6

    def test_unparseable_dates_excluded_and_reported(self):
        frame = pd.DataFrame({
            "d": ["2024-01-01", "2024-01-02", "2024-02-01", "2024-02-02", "garbage"],
            "v": [1.0, 2.0, 3.0, 4.0, 100.0],
        })
        result = metric_trend(frame, "v", "d")
        assert result["excluded_unparseable_dates"] == 1
        assert sum(p["value"] for p in result["points"]) == 10

    def test_errors(self, df: pd.DataFrame):
        with pytest.raises(ValueError, match="Unsupported freq"):
            metric_trend(df, "revenue", "date", freq="fortnight2")
        with pytest.raises(ValueError, match="not a date column"):
            metric_trend(df, "revenue", "region")
        with pytest.raises(ValueError, match="Date column"):
            metric_trend(df, "revenue", "nope")

    def test_json_safe(self, df: pd.DataFrame):
        json.dumps(metric_trend(df, "revenue", "date"), allow_nan=False)
