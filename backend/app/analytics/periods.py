"""
Period resolution — turn a user/LLM supplied period label into a row mask.

Supported period specifications (case-insensitive):

====================  =====================================================
Specification         Example
====================  =====================================================
Exact cell label      ``"August"``, ``"2024-08"``, ``"Q3 FY24"``
Year                  ``"2024"``
Year-month            ``"2024-08"``, ``"2024/8"``
Month name + year     ``"August 2024"``, ``"Aug 2024"``, ``"2024 August"``
Quarter               ``"2024-Q3"``, ``"Q3 2024"``
Month name only       ``"August"`` (matches that month in every year present)
Single day            ``"2024-08-15"``
====================  =====================================================

Resolution order: exact label match → date-based match (only when the column parses as dates)
→ literal substring match (never a regex). A period that matches no rows raises ``ValueError``
rather than silently producing a total of zero.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

import pandas as pd

from app.analytics.utils import try_parse_datetime, value_label

_MONTHS: dict[str, int] = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9

_MONTH_NAMES_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_YEAR = re.compile(r"^(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})[-/.](\d{1,2})$")
_QUARTER_A = re.compile(r"^(\d{4})[-/\s]*q([1-4])$")
_QUARTER_B = re.compile(r"^q([1-4])[-/\s]*(\d{4})$")
_MONTH_YEAR = re.compile(rf"^({_MONTH_NAMES_RE})\.?[\s,/-]*(\d{{4}})$")
_YEAR_MONTH_NAME = re.compile(rf"^(\d{{4}})[\s,/-]*({_MONTH_NAMES_RE})\.?$")
_MONTH_ONLY = re.compile(rf"^({_MONTH_NAMES_RE})\.?$")


@dataclass
class PeriodMatch:
    """Result of resolving a period label against a column."""

    label: str
    mask: pd.Series
    method: str  # exact | date_range | month_of_year | substring
    note: str | None = None

    @property
    def row_count(self) -> int:
        return int(self.mask.sum())


class PeriodResolver:
    """Resolves period labels against one column, parsing dates at most once."""

    def __init__(self, series: pd.Series):
        self.series = series
        self._parsed: pd.Series | None = None
        self._parsed_done = False
        self._text: pd.Series | None = None

    # -- lazily computed views ------------------------------------------------
    @property
    def text(self) -> pd.Series:
        if self._text is None:
            series = self.series
            if pd.api.types.is_float_dtype(series):
                # Numeric period columns (e.g. year/month numbers) read back as 2024.0.
                series = series.map(value_label)
            self._text = series.astype(str).str.strip().str.casefold()
        return self._text

    @property
    def parsed(self) -> pd.Series | None:
        if not self._parsed_done:
            self._parsed = try_parse_datetime(self.series)
            self._parsed_done = True
        return self._parsed

    # -- public API -----------------------------------------------------------
    def resolve(self, period: str) -> PeriodMatch:
        label = str(period).strip()
        if not label:
            raise ValueError("Period label must not be empty.")

        present = self.series.notna()
        key = label.casefold()

        exact = (self.text == key) & present
        if exact.any():
            return PeriodMatch(label, exact, "exact")

        parsed = self.parsed
        if parsed is not None:
            match = self._match_dates(key, parsed)
            if match is not None:
                mask, method, note = match
                mask = mask & present
                if mask.any():
                    return PeriodMatch(label, mask, method, note)

        substring = self.text.str.contains(key, regex=False, na=False) & present
        if substring.any():
            return PeriodMatch(
                label,
                substring,
                "substring",
                f"Period '{label}' was matched as a text fragment; verify it selects the intended rows.",
            )

        raise ValueError(
            f"Period '{label}' matched no rows. Example values in the column: {self._examples()}"
        )

    # -- helpers --------------------------------------------------------------
    def _examples(self, n: int = 5) -> list[str]:
        values = self.series.dropna().astype(str).str.slice(0, 40).unique()[:n]
        return [str(v) for v in values]

    @staticmethod
    def _range_mask(parsed: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        return (parsed >= start) & (parsed < end)

    def _match_dates(
        self, key: str, parsed: pd.Series
    ) -> tuple[pd.Series, str, str | None] | None:
        if m := _YEAR.match(key):
            year = int(m.group(1))
            return self._month_span(parsed, year, 1, 12)

        if m := _YEAR_MONTH.match(key):
            year, month = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                return self._month_span(parsed, year, month, month)
            return None

        if m := _QUARTER_A.match(key):
            return self._quarter(parsed, int(m.group(1)), int(m.group(2)))
        if m := _QUARTER_B.match(key):
            return self._quarter(parsed, int(m.group(2)), int(m.group(1)))

        if m := _MONTH_YEAR.match(key):
            month = _MONTHS[m.group(1)]
            return self._month_span(parsed, int(m.group(2)), month, month)
        if m := _YEAR_MONTH_NAME.match(key):
            month = _MONTHS[m.group(2)]
            return self._month_span(parsed, int(m.group(1)), month, month)

        if m := _MONTH_ONLY.match(key):
            month = _MONTHS[m.group(1)]
            mask = parsed.dt.month == month
            years = sorted(parsed[mask].dt.year.dropna().unique())
            note = None
            if len(years) > 1:
                note = (
                    f"Month '{key}' appears in multiple years ({', '.join(str(int(y)) for y in years)}); "
                    "all of them are included. Specify a year (e.g. 'August 2024') to be exact."
                )
            return mask, "month_of_year", note

        if re.search(r"\d", key):
            try:
                day = pd.Timestamp(key)
            except (ValueError, TypeError):
                return None
            if day.tzinfo is not None:
                day = day.tz_convert("UTC").tz_localize(None)
            return self._range_mask(parsed, day.normalize(), day.normalize() + pd.Timedelta(days=1)), "date_range", None
        return None

    def _month_span(
        self, parsed: pd.Series, year: int, first_month: int, last_month: int
    ) -> tuple[pd.Series, str, str | None]:
        start = pd.Timestamp(year=year, month=first_month, day=1)
        end = pd.Timestamp(year=year, month=last_month, day=1) + pd.offsets.MonthBegin(1)
        return self._range_mask(parsed, start, end), "date_range", None

    def _quarter(
        self, parsed: pd.Series, year: int, quarter: int
    ) -> tuple[pd.Series, str, str | None]:
        first = (quarter - 1) * 3 + 1
        return self._month_span(parsed, year, first, first + 2)


def resolve_period_pair(
    series: pd.Series, period_a: str, period_b: str
) -> tuple[PeriodMatch, PeriodMatch, list[str]]:
    """
    Resolve two periods against the same column and collect warnings.

    Raises ``ValueError`` if the periods are identical or either matches no rows.
    Warnings describe fuzzy matching and overlapping periods.
    """
    if str(period_a).strip().casefold() == str(period_b).strip().casefold():
        raise ValueError("period_a and period_b must be different.")

    resolver = PeriodResolver(series)
    a = resolver.resolve(period_a)
    b = resolver.resolve(period_b)

    warnings_: list[str] = []
    for match in (a, b):
        if match.note:
            warnings_.append(match.note)
    overlap = int((a.mask & b.mask).sum())
    if overlap:
        warnings_.append(
            f"The two periods overlap on {overlap} rows; totals are not independent. "
            "Use more specific period labels."
        )
    return a, b, warnings_
