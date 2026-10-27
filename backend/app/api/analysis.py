"""
Analysis API — start, status, events, and report endpoints.

Endpoints:
    POST   /analysis              Start an analysis question and return a job ID (202).
    GET    /analysis/{id}         Return status, steps, findings, and final answer.
    GET    /analysis/{id}/events  SSE stream for live progress (``Accept: text/event-stream``);
                                  plain JSON snapshot otherwise, so polling clients work too.
    GET    /analysis/{id}/report  Return the report as JSON, or download it with ``?format=md``.

Jobs run in the background (``app.api.runner``); the orchestrator reports progress through
``app.storage``. Limits come from ``app.config`` (question length, concurrent jobs, job time).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.api.runner import execute_job
from app.api.schemas import (
    AnalysisEventsOut,
    AnalysisJobOut,
    AnalysisRequest,
    AnalysisStartOut,
    ReportOut,
)
from app.config import get_settings
from app.reporting.report import build_report, render_markdown
from app.storage import TERMINAL_STATUSES, get_store

router = APIRouter()
logger = logging.getLogger(__name__)

SSE_POLL_INTERVAL_S = 0.5
SSE_HEARTBEAT_S = 15.0
SSE_GRACE_S = 30.0


def _get_job_or_404(job_id: str) -> dict[str, Any]:
    job = get_store().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return job


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=AnalysisStartOut, status_code=202)
async def start_analysis(payload: AnalysisRequest, background_tasks: BackgroundTasks) -> AnalysisStartOut:
    """Start an analysis question and return a job ID."""
    settings = get_settings()
    store = get_store()

    if len(payload.question) > settings.max_question_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Question is too long (maximum {settings.max_question_chars} characters).",
        )
    if store.get_dataset(payload.dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    if store.count_active_jobs() >= settings.max_active_jobs:
        raise HTTPException(
            status_code=429,
            detail="Too many analyses are running. Please wait for one to finish and try again.",
            headers={"Retry-After": "10"},
        )

    job_id = str(uuid.uuid4())
    store.create_job(payload.dataset_id, payload.question, job_id)
    background_tasks.add_task(execute_job, job_id)
    logger.info("analysis queued job_id=%s dataset_id=%s", job_id, payload.dataset_id)
    return AnalysisStartOut(id=job_id, status="pending")


@router.get("/{job_id}", response_model=AnalysisJobOut)
async def get_analysis(job_id: str) -> AnalysisJobOut:
    """Return status, steps, findings, and final answer."""
    return AnalysisJobOut.model_validate(_get_job_or_404(job_id))


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(job_id: str, request: Request) -> AsyncIterator[str]:
    """Emit ``status`` / ``step`` events as the job changes and a final ``done`` event."""
    store = get_store()
    deadline = time.monotonic() + get_settings().max_job_seconds + SSE_GRACE_S
    last_status: str | None = None
    seen_steps: dict[int, str] = {}
    last_beat = time.monotonic()

    while True:
        job = store.get_job(job_id)
        if job is None:
            return

        if job["status"] != last_status:
            last_status = job["status"]
            yield _sse("status", {"id": job_id, "status": last_status})

        for step in job["steps"]:
            signature = json.dumps(step, sort_keys=True)
            if seen_steps.get(step["step_number"]) != signature:
                seen_steps[step["step_number"]] = signature
                yield _sse("step", step)

        if job["status"] in TERMINAL_STATUSES:
            yield _sse("done", {"id": job_id, "status": job["status"], "error": job.get("error")})
            return
        if time.monotonic() > deadline or await request.is_disconnected():
            return

        if time.monotonic() - last_beat >= SSE_HEARTBEAT_S:
            last_beat = time.monotonic()
            yield ": keep-alive\n\n"
        await asyncio.sleep(SSE_POLL_INTERVAL_S)


@router.get("/{job_id}/events", response_model=None)
async def get_analysis_events(job_id: str, request: Request) -> Response | AnalysisEventsOut:
    """SSE stream for live progress; falls back to a JSON snapshot for polling clients."""
    job = _get_job_or_404(job_id)

    if "text/event-stream" in request.headers.get("accept", "").lower():
        return StreamingResponse(
            _event_stream(job_id, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return AnalysisEventsOut.model_validate(job)


@router.get(
    "/{job_id}/report",
    response_model=ReportOut,
    responses={200: {"content": {"text/markdown": {}}, "description": "JSON report or Markdown download."}},
)
async def get_analysis_report(job_id: str, format: Literal["json", "md"] = "json") -> Response | dict[str, Any]:
    """Return the report as JSON, or download it as Markdown with ``?format=md``."""
    job = _get_job_or_404(job_id)

    if job["status"] == "failed":
        raise HTTPException(status_code=409, detail=job.get("error") or "The analysis failed; no report is available.")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Analysis not yet completed.")

    report = build_report(job, get_store().get_dataset(job["dataset_id"]))
    if format == "md":
        return Response(
            content=render_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="analysis-{job_id[:8]}.md"'},
        )
    return report
