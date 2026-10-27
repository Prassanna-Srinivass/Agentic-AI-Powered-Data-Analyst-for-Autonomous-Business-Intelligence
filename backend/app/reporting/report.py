"""
Report generation — turn a completed analysis job into a JSON document or Markdown file.

Everything in the report comes from the stored job (verified findings, steps, limitations);
nothing is recomputed or invented here. Text originating from uploaded data or from a model is
treated as untrusted: it is rendered as plain text and never interpreted.
"""

from __future__ import annotations

import re
from typing import Any

from app.storage import utc_now

CAUSATION_NOTE = (
    "Measured contributions describe what the data shows; they do not by themselves "
    "establish causation."
)

_WHITESPACE = re.compile(r"\s+")


def build_report(job: dict[str, Any], dataset: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the JSON report for a job (keeps ``id``, ``question``, ``findings``, ``answer``)."""
    limitations = list(job.get("limitations") or [])
    for finding in job.get("findings") or []:
        text = finding.get("limitation")
        if text and text not in limitations:
            limitations.append(text)
    if CAUSATION_NOTE not in limitations:
        limitations.append(CAUSATION_NOTE)

    return {
        "id": job["id"],
        "question": job["question"],
        "dataset": (
            {"id": dataset["id"], "filename": dataset.get("filename")} if dataset else {"id": job["dataset_id"]}
        ),
        "status": job["status"],
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "generated_at": utc_now(),
        "answer": job.get("answer"),
        "findings": job.get("findings") or [],
        "verification": job.get("verification") or {},
        "limitations": limitations,
        "steps": job.get("steps") or [],
        "chart_specs": job.get("chart_specs") or [],
    }


def _line(value: Any) -> str:
    """Single-line plain text (collapses newlines so data cannot inject Markdown structure)."""
    return _WHITESPACE.sub(" ", str(value)).strip()


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report produced by :func:`build_report` as Markdown."""
    out: list[str] = ["# Analysis report", ""]
    out.append(f"**Question:** {_line(report['question'])}")
    dataset = report.get("dataset") or {}
    if dataset.get("filename"):
        out.append(f"**Dataset:** {_line(dataset['filename'])}")
    if report.get("completed_at"):
        out.append(f"**Completed:** {report['completed_at']}")
    out.append("")

    out += ["## Answer", "", report.get("answer") or "_No answer was produced._", ""]

    findings = report.get("findings") or []
    out += ["## Findings", ""]
    if findings:
        for i, f in enumerate(findings, start=1):
            out.append(f"{i}. {_line(f.get('claim', ''))}")
            details = []
            if f.get("metric"):
                details.append(f"metric: {_line(f['metric'])}")
            if f.get("value") is not None:
                details.append(f"value: {_line(f['value'])}")
            if f.get("evidence_reference"):
                details.append(f"evidence: {_line(f['evidence_reference'])}")
            if f.get("confidence"):
                details.append(f"confidence: {_line(f['confidence'])}")
            if details:
                out.append(f"   - {'; '.join(details)}")
            if f.get("limitation"):
                out.append(f"   - limitation: {_line(f['limitation'])}")
    else:
        out.append("_No findings were recorded._")
    out.append("")

    verification = report.get("verification") or {}
    if verification:
        out += ["## Verification", ""]
        for key, value in verification.items():
            out.append(f"- {_line(key)}: {_line(value)}")
        out.append("")

    steps = report.get("steps") or []
    if steps:
        out += ["## Investigation steps", ""]
        for s in steps:
            line = f"{s.get('step_number')}. `{_line(s.get('tool_name', ''))}` ({_line(s.get('status', ''))})"
            if s.get("input_summary"):
                line += f" — {_line(s['input_summary'])}"
            out.append(line)
            if s.get("output_summary"):
                out.append(f"   - result: {_line(s['output_summary'])}")
        out.append("")

    out += ["## Limitations", ""]
    out += [f"- {_line(item)}" for item in report.get("limitations") or []]
    out.append("")

    charts = report.get("chart_specs") or []
    if charts:
        out += [f"_This analysis includes {len(charts)} chart(s); view them in the app or via the JSON report._", ""]

    return "\n".join(out)
