"""
Reconciliation — verify that subgroup totals align with overall totals.

Approved tool: validate_reconciliation
    Check that segment contributions sum to the reported overall change
    within a configurable tolerance.
"""

from __future__ import annotations

from typing import Any


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
        Acceptable absolute difference between the sum of segments
        and the overall change (default 1%).

    Returns
    -------
    dict
        reconciled: bool — whether the values match within tolerance
        segment_sum: float — sum of all segment changes
        difference: float — absolute difference from overall change
        segments: dict — the input segment changes
    """
    # TODO: Implement reconciliation logic (Day 4)
    # - Sum segment_changes values
    # - Compare with overall_change
    # - Flag if difference exceeds tolerance
    segment_sum = sum(segment_changes.values())
    difference = abs(overall_change - segment_sum)
    reconciled = difference <= abs(overall_change * tolerance)

    return {
        "reconciled": reconciled,
        "overall_change": overall_change,
        "segment_sum": round(segment_sum, 4),
        "difference": round(difference, 4),
        "tolerance": tolerance,
        "segments": segment_changes,
    }
