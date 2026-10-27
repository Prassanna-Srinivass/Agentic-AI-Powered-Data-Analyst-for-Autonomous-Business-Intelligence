"""Pydantic request/response models shared by the API routers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

JobStatus = Literal[
    "pending", "profiling", "planning", "executing", "verifying", "completed", "failed"
]


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

class DatasetOut(BaseModel):
    """A dataset as exposed to clients. The server-side ``file_path`` is never returned."""

    id: str
    filename: str
    uploaded_at: str
    size_bytes: int = 0
    row_count: int = 0
    column_count: int = 0
    profile: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class AnalysisRequest(BaseModel):
    """Payload to start a new analysis."""

    dataset_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty.")
        return value


class AnalysisStartOut(BaseModel):
    id: str
    status: JobStatus


class StepOut(BaseModel):
    step_number: int
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    status: str = "pending"
    result: dict[str, Any] | None = None


class FindingOut(BaseModel):
    claim: str
    metric: str = ""
    value: Any = None
    evidence_reference: str = ""
    confidence: str = ""
    limitation: str = ""


class AnalysisJobOut(BaseModel):
    id: str
    dataset_id: str
    question: str
    status: JobStatus
    created_at: str
    completed_at: str | None = None
    steps: list[StepOut] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    answer: str | None = None
    chart_specs: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    intent: str | None = None
    verification: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AnalysisEventsOut(BaseModel):
    """Polling fallback for ``GET /analysis/{id}/events`` (non-SSE clients)."""

    id: str
    status: JobStatus
    steps: list[StepOut] = Field(default_factory=list)


class ReportOut(BaseModel):
    id: str
    question: str
    dataset: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus
    created_at: str | None = None
    completed_at: str | None = None
    generated_at: str
    answer: str | None = None
    findings: list[FindingOut] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    intent: str | None = None
    steps: list[StepOut] = Field(default_factory=list)
    chart_specs: list[dict[str, Any]] = Field(default_factory=list)
