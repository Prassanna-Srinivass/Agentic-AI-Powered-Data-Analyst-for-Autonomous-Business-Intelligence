"""
Charts — the approved ``create_chart`` tool.

Returns Plotly-compatible JSON specifications (``data`` + ``layout``) built *only* from tool
results that already passed verification. No plotting library runs on the server and no data
is re-aggregated here, so a chart can never show a number the verifier did not check.

Chart spec shape::

    {"id": str, "kind": str, "title": str, "data": [trace, ...], "layout": {...},
     "evidence_reference": "step N"}
"""

from __future__ import annotations

from typing import Any

CHART_KINDS = ("period_comparison", "segment_change")

INCREASE_COLOR = "#16a34a"
DECREASE_COLOR = "#dc2626"
NEUTRAL_COLOR = "#2563eb"
MAX_SEGMENTS_SHOWN = 10


def create_chart(kind: str, result: dict[str, Any], evidence_reference: str) -> dict[str, Any]:
    """
    Build a chart specification from a verified tool result.

    Parameters
    ----------
    kind : str
        ``period_comparison`` (a ``compare_periods`` result) or ``segment_change`` (a
        ``group_metric_change`` result).
    result : dict
        The verified tool output.
    evidence_reference : str
        Reference to the step whose calculation backs the chart, e.g. ``"step 1"``.

    Raises
    ------
    ValueError
        For an unknown ``kind``, a result that does not match it, or missing evidence.
    """
    if kind not in CHART_KINDS:
        raise ValueError(f"Unsupported chart kind '{kind}'. Supported: {', '.join(CHART_KINDS)}.")
    if not evidence_reference:
        raise ValueError("A chart requires an evidence reference.")

    try:
        if kind == "period_comparison":
            title, data, layout = _period_comparison(result)
        else:
            title, data, layout = _segment_change(result)
    except KeyError as exc:
        raise ValueError(f"Result is missing '{exc.args[0]}' required for a {kind} chart.") from exc

    return {
        "id": f"{kind}-{evidence_reference.replace(' ', '-')}",
        "kind": kind,
        "title": title,
        "data": data,
        "layout": {"title": {"text": title}, "margin": {"t": 50, "r": 20, "b": 60, "l": 70}, **layout},
        "evidence_reference": evidence_reference,
    }


def _period_comparison(result: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    metric = result["metric"]
    a_total, b_total = result["period_a_total"], result["period_b_total"]
    if a_total is None or b_total is None:
        raise ValueError("Cannot chart a comparison with missing totals.")
    change = result["absolute_change"] or 0
    color_b = INCREASE_COLOR if change > 0 else DECREASE_COLOR if change < 0 else NEUTRAL_COLOR
    aggregation = result.get("aggregation", "sum")

    title = f"{metric} ({aggregation}): {result['period_a']} vs {result['period_b']}"
    data = [{
        "type": "bar",
        "x": [str(result["period_a"]), str(result["period_b"])],
        "y": [a_total, b_total],
        "text": [f"{a_total:,.2f}", f"{b_total:,.2f}"],
        "textposition": "outside",
        "marker": {"color": [NEUTRAL_COLOR, color_b]},
        "hovertemplate": "%{x}: %{y:,.2f}<extra></extra>",
    }]
    layout = {"xaxis": {"title": {"text": "Period"}}, "yaxis": {"title": {"text": metric}}, "showlegend": False}
    return title, data, layout


def _segment_change(result: dict[str, Any]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    metric, group_by = result["metric"], result["group_by"]
    segments = result["segments"][:MAX_SEGMENTS_SHOWN]
    if not segments:
        raise ValueError("Cannot chart a decomposition without segments.")

    ordered = list(reversed(segments))  # horizontal bars render bottom-up; keep the largest on top
    changes = [s["absolute_change"] for s in ordered]
    title = f"Change in {metric} by {group_by}: {result['period_a']} → {result['period_b']}"
    data = [{
        "type": "bar",
        "orientation": "h",
        "y": [s["group"] for s in ordered],
        "x": changes,
        "text": [f"{c:+,.2f}" for c in changes],
        "textposition": "auto",
        "marker": {"color": [INCREASE_COLOR if c > 0 else DECREASE_COLOR if c < 0 else NEUTRAL_COLOR for c in changes]},
        "hovertemplate": "%{y}: %{x:+,.2f}<extra></extra>",
    }]
    layout = {
        "xaxis": {"title": {"text": f"Change in {metric}"}, "zeroline": True},
        "yaxis": {"title": {"text": group_by}, "automargin": True},
        "showlegend": False,
    }
    return title, data, layout
