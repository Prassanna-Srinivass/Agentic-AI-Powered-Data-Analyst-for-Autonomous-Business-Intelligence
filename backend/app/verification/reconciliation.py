"""
Reconciliation — verify that subgroup totals align with overall totals.

Approved tool: validate_reconciliation
    Check that segment contributions sum to the reported overall change
    within a configurable tolerance.
"""

from __future__ import annotations

import math
from typing import Any

# Segment values are rounded individually (4 decimals), so a tiny absolute slack is needed
# for totals close to zero.
ABSOLUTE_TOLERANCE = 0.01


def validate_reconciliation(
    overall_change: float,
    segment_changes: dict[str, float],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """
    Check that subgroup changes reconcile with the overall change.

    Parameters
    ----------
    overall_change : float
        The total reported change across all segments.
    segment_changes : dict[str, float]
        Mapping of segment name → change amount.
    tolerance : float
        Acceptable difference between the sum of segments and the overall change, as a
        fraction of ``abs(overall_change)`` (default 1%). A small absolute slack
        (``ABSOLUTE_TOLERANCE``) is always allowed so rounding never fails a zero total.

    Returns
    -------
    dict
        reconciled: bool — whether the values match within tolerance
        segment_sum: float — sum of all segment changes
        difference: float — absolute difference from overall change
        allowed_difference: float — the largest difference that would still reconcile
        segments: dict — the input segment changes
    """
    if tolerance < 0:
        raise ValueError("tolerance must not be negative.")
    values = [float(v) for v in segment_changes.values()]
    if not all(math.isfinite(v) for v in values) or not math.isfinite(float(overall_change)):
        raise ValueError("Reconciliation inputs must be finite numbers.")

    segment_sum = math.fsum(values)
    difference = abs(float(overall_change) - segment_sum)
    allowed = max(ABSOLUTE_TOLERANCE, abs(float(overall_change)) * tolerance)

    return {
        "reconciled": bool(difference <= allowed),
        "overall_change": overall_change,
        "segment_sum": round(segment_sum, 4),
        "difference": round(difference, 4),
        "allowed_difference": round(allowed, 4),
        "tolerance": tolerance,
        "segments": segment_changes,
    }
