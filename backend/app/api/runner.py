"""
Job runner — executes the analysis workflow for a job and guarantees a final state.

The orchestrator (``app.orchestration.graph.run_analysis``) does the actual work and reports
progress through ``app.storage``. This wrapper adds the API-level guarantees from the plan:

* the workflow runs in a worker thread with its own event loop, so heavy pandas work never
  blocks request handling or SSE streams;
* a wall-clock limit (``MAX_JOB_SECONDS``) — on timeout the job is marked failed and, because
  finished jobs are frozen in the store, a late write from the abandoned workflow is ignored;
* any exception becomes a sanitised ``failed`` job (raw exception text can contain cell data,
  so only the exception type is exposed and logged);
* a workflow that returns without completing the job is reported as a failure, never left
  "pending" forever.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.config import get_settings
from app.storage import TERMINAL_STATUSES, get_store

logger = logging.getLogger(__name__)

WorkflowFn = Callable[[str, str, str], Awaitable[object]]


def _load_workflow() -> WorkflowFn:
    # Imported lazily so the API can start (and be tested) without the LLM stack installed.
    from app.orchestration.graph import run_analysis

    return run_analysis


def _run_in_thread(workflow: WorkflowFn, job_id: str, dataset_id: str, question: str) -> None:
    asyncio.run(workflow(job_id, dataset_id, question))  # type: ignore[arg-type]


async def execute_job(job_id: str) -> None:
    """Run the workflow for ``job_id`` and make sure the job ends ``completed`` or ``failed``."""
    store = get_store()
    job = store.get_job(job_id)
    if job is None:
        logger.error("execute_job: unknown job_id=%s", job_id)
        return

    timeout = get_settings().max_job_seconds
    started = time.monotonic()
    try:
        workflow = _load_workflow()
        await asyncio.wait_for(
            asyncio.to_thread(_run_in_thread, workflow, job_id, job["dataset_id"], job["question"]),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error("job timed out job_id=%s limit_s=%s", job_id, timeout)
        store.fail_job(job_id, f"The analysis exceeded the {timeout:.0f}-second time limit and was stopped.")
        return
    except Exception as exc:
        logger.error("job failed job_id=%s error=%s", job_id, type(exc).__name__)
        store.fail_job(job_id, f"The analysis failed unexpectedly ({type(exc).__name__}).")
        return

    final = store.get_job(job_id)
    if final is None or final["status"] not in TERMINAL_STATUSES:
        store.fail_job(job_id, "The analysis workflow finished without producing a result.")
    logger.info(
        "job finished job_id=%s status=%s duration_s=%.2f",
        job_id, (store.get_job(job_id) or {}).get("status"), time.monotonic() - started,
    )
