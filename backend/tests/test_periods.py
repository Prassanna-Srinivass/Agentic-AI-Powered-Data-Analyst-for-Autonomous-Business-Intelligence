"""
Tests for period label resolution.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.analytics.periods import PeriodResolver, resolve_period_pair


@pytest.fixture
def dates() -> pd.Series:
    return pd.Series([
        "2023-08-10", "2024-01-31", "2024-02-01", "2024-03-31",
        "2024-04-01", "2024-08-15", "2024-08-16", "2024-09-01", None,
    ])


def rows(match) -> list[int]:
    return [int(i) for i in match.mask[match.mask].index]


class TestPeriodResolver:
    def test_year(self, dates: pd.Series):
        assert rows(PeriodResolver(dates).resolve("2024")) == [1, 2, 3, 4, 5, 6, 7]

    def test_year_month_variants(self, dates: pd.Series):
        resolver = PeriodResolver(dates)
        assert rows(resolver.resolve("2024-08")) == [5, 6]
        assert rows(resolver.resolve("2024/8")) == [5, 6]
        assert rows(resolver.resolve("August 2024")) == [5, 6]
        assert rows(resolver.resolve("aug 2024")) == [5, 6]
        assert rows(resolver.resolve("2024 August")) == [5, 6]

    def test_quarter(self, dates: pd.Series):
        resolver = PeriodResolver(dates)
        assert rows(resolver.resolve("2024-Q1")) == [1, 2, 3]
        assert rows(resolver.resolve("Q1 2024")) == [1, 2, 3]
        assert rows(resolver.resolve("q3 2024")) == [5, 6, 7]  # Aug 15, Aug 16, Sep 1

    def test_single_day(self, dates: pd.Series):
        assert rows(PeriodResolver(dates).resolve("2024-08-15")) == [5]

    def test_month_name_only_notes_multiple_years(self, dates: pd.Series):
        match = PeriodResolver(dates).resolve("August")
        assert rows(match) == [0, 5, 6]
        assert match.method == "month_of_year"
        assert "2023" in match.note and "2024" in match.note

    def test_month_end_boundaries_are_inclusive(self, dates: pd.Series):
        resolver = PeriodResolver(dates)
        assert 1 in rows(resolver.resolve("2024-01"))
        assert 3 in rows(resolver.resolve("2024-03"))
        assert 4 not in rows(resolver.resolve("2024-03"))

    def test_timestamps_with_time_component(self):
        series = pd.Series(pd.to_datetime(["2024-08-31 23:59:59", "2024-09-01 00:00:00"]))
        resolver = PeriodResolver(series)
        assert rows(resolver.resolve("2024-08")) == [0]
        assert rows(resolver.resolve("2024-09-01")) == [1]

    def test_exact_label_beats_date_logic(self):
        series = pd.Series(["2024", "2024-05", "2025"])
        assert rows(PeriodResolver(series).resolve("2024")) == [0]

    def test_numeric_year_column(self):
        series = pd.Series([2023.0, 2024.0, 2024.0])
        assert rows(PeriodResolver(series).resolve("2024")) == [1, 2]

    def test_substring_fallback_is_flagged(self):
        series = pd.Series(["FY24-Q1", "FY24-Q2", "FY25-Q1"])
        match = PeriodResolver(series).resolve("FY24")
        assert rows(match) == [0, 1]
        assert match.method == "substring" and match.note

    def test_no_match_lists_examples(self, dates: pd.Series):
        with pytest.raises(ValueError, match="matched no rows.*2023-08-10"):
            PeriodResolver(dates).resolve("2030-01")

    def test_empty_label(self, dates: pd.Series):
        with pytest.raises(ValueError, match="must not be empty"):
            PeriodResolver(dates).resolve("  ")

    def test_missing_values_never_match(self):
        series = pd.Series(["a", None, "a"])
        assert rows(PeriodResolver(series).resolve("a")) == [0, 2]


class TestResolvePair:
    def test_identical_periods(self, dates: pd.Series):
        with pytest.raises(ValueError, match="different"):
            resolve_period_pair(dates, "2024-08", "2024-08")

    def test_overlap_warning(self, dates: pd.Series):
        _, _, warnings_ = resolve_period_pair(dates, "2024", "2024-08")
        assert any("overlap" in w for w in warnings_)

    def test_no_warnings_for_clean_pair(self, dates: pd.Series):
        _, _, warnings_ = resolve_period_pair(dates, "2024-01", "2024-08")
        assert warnings_ == []
