"""
Metadata storage — datasets and analysis jobs in a local SQLite database.

The plan allows simple local state for the MVP but asks for clear interfaces so PostgreSQL can
replace it later. Everything the API and the orchestrator need goes through :class:`Store`.

Orchestrator contract (see ``app.orchestration.graph.run_analysis``)
-------------------------------------------------------------------
The API creates the job and then calls ``run_analysis(job_id, dataset_id, question)``. The
workflow reports progress through the store::

    store = get_store()
    dataset = store.get_dataset(dataset_id)                    # includes "file_path" and "profile"
    store.update_job(job_id, status="profiling")               # pending|profiling|planning|executing|verifying
    step = store.add_step(job_id, "compare_periods", input_summary="revenue Aug vs Sep")
    store.update_step(job_id, step["step_number"], status="completed", output_summary="-8.4%")
    store.add_finding(job_id, claim="...", metric="revenue", value=-8.4,
                      evidence_reference="step 1", confidence="high", limitation="...")
    store.update_job(job_id, status="completed", answer="...", chart_specs=[...],
                     limitations=[...], verification={...})

Once a job is ``completed`` or ``failed`` it is frozen: later updates are ignored. That makes
timeouts safe, because a late write from an abandoned workflow cannot overwrite the outcome.

Job records hold JSON-safe data only (NaN/inf become ``None``); strings are stored in full.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.analytics.utils import to_jsonable
from app.config import get_settings

JOB_STATUSES = (
    "pending", "profiling", "planning", "executing", "verifying", "completed", "failed",
)
TERMINAL_STATUSES = frozenset({"completed", "failed"})

_UPDATABLE_JOB_FIELDS = frozenset({
    "status", "answer", "limitations", "chart_specs", "verification",
    "errors", "error", "completed_at", "assumptions", "intent",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value, max_text_length=None), allow_nan=False)


class Store:
    """Thread-safe SQLite-backed store for datasets and analysis jobs."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id          TEXT PRIMARY KEY,
                    uploaded_at TEXT NOT NULL,
                    data        TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id          TEXT PRIMARY KEY,
                    dataset_id  TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    data        TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON analysis_jobs(status);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ datasets
    def add_dataset(self, record: dict[str, Any]) -> dict[str, Any]:
        record = to_jsonable(record, max_text_length=None)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO datasets (id, uploaded_at, data) VALUES (?, ?, ?)",
                (record["id"], record["uploaded_at"], _dumps(record)),
            )
        return record

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT data FROM datasets ORDER BY uploaded_at DESC, id").fetchall()
        return [json.loads(r[0]) for r in rows]

    # ---------------------------------------------------------------------- jobs
    def create_job(self, dataset_id: str, question: str, job_id: str) -> dict[str, Any]:
        job = {
            "id": job_id,
            "dataset_id": dataset_id,
            "question": question,
            "status": "pending",
            "created_at": utc_now(),
            "completed_at": None,
            "steps": [],
            "findings": [],
            "answer": None,
            "chart_specs": [],
            "limitations": [],
            "assumptions": [],
            "intent": None,
            "verification": {},
            "errors": [],
            "error": None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_jobs (id, dataset_id, status, created_at, data) VALUES (?, ?, ?, ?, ?)",
                (job_id, dataset_id, "pending", job["created_at"], _dumps(job)),
            )
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def count_active_jobs(self) -> int:
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM analysis_jobs WHERE status NOT IN ({placeholders})",
                tuple(TERMINAL_STATUSES),
            ).fetchone()
        return int(row[0])

    def _modify_job(self, job_id: str, mutate) -> dict[str, Any] | None:
        """Read-modify-write one job atomically. Returns ``None`` if the job is frozen."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT data FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = json.loads(row[0])
            if job["status"] in TERMINAL_STATUSES:
                return None
            mutate(job)
            conn.execute(
                "UPDATE analysis_jobs SET status = ?, data = ? WHERE id = ?",
                (job["status"], _dumps(job), job_id),
            )
            return job

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        """
        Update top-level job fields (``status``, ``answer``, ``chart_specs``, ``limitations``,
        ``verification``, ``errors``, ``error``, ``completed_at``).

        Raises ``KeyError`` for an unknown job and ``ValueError`` for an invalid field/status.
        Returns the updated job, or ``None`` if the job is already completed/failed (ignored).
        """
        unknown = set(fields) - _UPDATABLE_JOB_FIELDS
        if unknown:
            raise ValueError(f"Cannot update job fields: {', '.join(sorted(unknown))}")
        status = fields.get("status")
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(f"Invalid job status '{status}'.")

        def mutate(job: dict[str, Any]) -> None:
            job.update(to_jsonable(fields, max_text_length=None))
            if job["status"] in TERMINAL_STATUSES and not job.get("completed_at"):
                job["completed_at"] = utc_now()

        return self._modify_job(job_id, mutate)

    def fail_job(self, job_id: str, message: str) -> dict[str, Any] | None:
        """Mark a job failed with a user-safe message (no-op if it already finished)."""
        def mutate(job: dict[str, Any]) -> None:
            job["status"] = "failed"
            job["error"] = message
            job["errors"] = [*job.get("errors", []), message]
            job["completed_at"] = utc_now()

        return self._modify_job(job_id, mutate)

    def add_step(
        self,
        job_id: str,
        tool_name: str,
        input_summary: str = "",
        output_summary: str = "",
        status: str = "running",
        result: Any = None,
    ) -> dict[str, Any]:
        """Append an analysis step and return it (``step_number`` starts at 1).

        ``result`` is the tool's full deterministic output, kept as evidence for the step.
        """
        created: dict[str, Any] = {}

        def mutate(job: dict[str, Any]) -> None:
            step = {
                "step_number": len(job["steps"]) + 1,
                "tool_name": tool_name,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "status": status,
                "result": result,
            }
            job["steps"].append(to_jsonable(step, max_text_length=None))
            created.update(job["steps"][-1])

        if self._modify_job(job_id, mutate) is None:
            return {}
        return created

    def update_step(self, job_id: str, step_number: int, **fields: Any) -> dict[str, Any] | None:
        """Update ``status`` / ``input_summary`` / ``output_summary`` / ``result`` of a step."""
        allowed = {"status", "input_summary", "output_summary", "result"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Cannot update step fields: {', '.join(sorted(unknown))}")

        def mutate(job: dict[str, Any]) -> None:
            for step in job["steps"]:
                if step["step_number"] == step_number:
                    step.update(to_jsonable(fields, max_text_length=None))
                    return
            raise KeyError(f"step {step_number}")

        job = self._modify_job(job_id, mutate)
        if job is None:
            return None
        return next(s for s in job["steps"] if s["step_number"] == step_number)

    def add_finding(
        self,
        job_id: str,
        claim: str,
        metric: str = "",
        value: Any = None,
        evidence_reference: str = "",
        confidence: str = "",
        limitation: str = "",
    ) -> dict[str, Any]:
        """Append a finding (claim + value + evidence reference + limitation)."""
        finding = {
            "claim": claim,
            "metric": metric,
            "value": value,
            "evidence_reference": evidence_reference,
            "confidence": confidence,
            "limitation": limitation,
        }
        finding = to_jsonable(finding, max_text_length=None)
        if self._modify_job(job_id, lambda job: job["findings"].append(finding)) is None:
            return {}
        return finding

    def fail_orphaned_jobs(self, reason: str) -> int:
        """Fail jobs left unfinished by a previous process (call once at startup)."""
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
            ids = [
                r[0] for r in conn.execute(
                    f"SELECT id FROM analysis_jobs WHERE status NOT IN ({placeholders})",
                    tuple(TERMINAL_STATUSES),
                )
            ]
        for job_id in ids:
            self.fail_job(job_id, reason)
        return len(ids)


# ---------------------------------------------------------------------------
# Process-wide accessor
# ---------------------------------------------------------------------------
_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """Return the shared store for the configured ``DATABASE_PATH`` (recreated if it changes)."""
    global _store
    path = get_settings().database_path
    with _store_lock:
        if _store is None or _store.db_path != path:
            _store = Store(path)
        return _store


def reset_store() -> None:
    """Reset the global store (for testing only)."""
    global _store
    with _store_lock:
        _store = None
