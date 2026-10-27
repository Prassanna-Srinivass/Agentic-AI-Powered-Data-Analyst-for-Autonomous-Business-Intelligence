"""Tests for the SQLite metadata store."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.storage import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "meta.db")


@pytest.fixture
def job_id(store: Store) -> str:
    store.create_job("dataset-1", "question?", "job-1")
    return "job-1"


class TestDatasets:
    def test_roundtrip_and_ordering(self, store: Store):
        store.add_dataset({"id": "a", "uploaded_at": "2024-01-01T00:00:00", "filename": "a.csv"})
        store.add_dataset({"id": "b", "uploaded_at": "2024-02-01T00:00:00", "filename": "b.csv"})
        assert store.get_dataset("a")["filename"] == "a.csv"
        assert [d["id"] for d in store.list_datasets()] == ["b", "a"]
        assert store.get_dataset("missing") is None

    def test_nan_and_numpy_values_are_stored_as_valid_json(self, store: Store):
        import numpy as np

        store.add_dataset({
            "id": "a", "uploaded_at": "t",
            "profile": {"nan": float("nan"), "inf": math.inf, "np": np.int64(3), "arr": np.array([1.5, np.nan])},
        })
        profile = store.get_dataset("a")["profile"]
        assert profile == {"nan": None, "inf": None, "np": 3, "arr": [1.5, None]}

    def test_survives_new_store_instance(self, tmp_path: Path):
        Store(tmp_path / "x.db").add_dataset({"id": "a", "uploaded_at": "t"})
        assert Store(tmp_path / "x.db").get_dataset("a") is not None


class TestJobs:
    def test_new_job_defaults(self, store: Store, job_id: str):
        job = store.get_job(job_id)
        assert job["status"] == "pending"
        assert job["steps"] == [] and job["findings"] == []
        assert job["completed_at"] is None

    def test_update_job_and_completion_timestamp(self, store: Store, job_id: str):
        store.update_job(job_id, status="executing")
        assert store.get_job(job_id)["completed_at"] is None
        store.update_job(job_id, status="completed", answer="x" * 5000)
        job = store.get_job(job_id)
        assert job["completed_at"] is not None
        assert len(job["answer"]) == 5000  # long text is not truncated

    def test_completed_jobs_are_frozen(self, store: Store, job_id: str):
        store.update_job(job_id, status="completed", answer="final")
        assert store.update_job(job_id, answer="changed", status="failed") is None
        assert store.add_step(job_id, "late_tool") == {}
        assert store.add_finding(job_id, claim="late") == {}
        assert store.fail_job(job_id, "late failure") is None
        job = store.get_job(job_id)
        assert job["answer"] == "final" and job["status"] == "completed"
        assert job["steps"] == [] and job["findings"] == []

    def test_steps_are_numbered_and_updatable(self, store: Store, job_id: str):
        first = store.add_step(job_id, "profile_dataset")
        second = store.add_step(job_id, "compare_periods", input_summary="a vs b")
        assert (first["step_number"], second["step_number"]) == (1, 2)
        assert first["status"] == "running"
        updated = store.update_step(job_id, 2, status="completed", output_summary="done")
        assert updated["status"] == "completed" and updated["input_summary"] == "a vs b"
        with pytest.raises(KeyError):
            store.update_step(job_id, 99, status="completed")
        with pytest.raises(ValueError):
            store.update_step(job_id, 1, tool_name="hack")

    def test_findings(self, store: Store, job_id: str):
        store.add_finding(job_id, "claim", metric="revenue", value=float("nan"))
        finding = store.get_job(job_id)["findings"][0]
        assert finding["claim"] == "claim" and finding["value"] is None

    def test_invalid_updates(self, store: Store, job_id: str):
        with pytest.raises(ValueError, match="Cannot update"):
            store.update_job(job_id, steps=[])
        with pytest.raises(ValueError, match="Invalid job status"):
            store.update_job(job_id, status="exploded")
        with pytest.raises(KeyError):
            store.update_job("missing", status="planning")

    def test_fail_job_records_error(self, store: Store, job_id: str):
        store.fail_job(job_id, "boom")
        job = store.get_job(job_id)
        assert job["status"] == "failed" and job["error"] == "boom" and job["errors"] == ["boom"]
        assert job["completed_at"] is not None

    def test_active_job_count_and_orphan_cleanup(self, store: Store):
        for i in range(3):
            store.create_job("d", "q", f"j{i}")
        store.update_job("j0", status="completed")
        assert store.count_active_jobs() == 2
        assert store.fail_orphaned_jobs("restarted") == 2
        assert store.count_active_jobs() == 0
        assert store.get_job("j1")["error"] == "restarted"
        assert store.get_job("j0")["status"] == "completed"

    def test_stored_data_is_strict_json(self, store: Store, job_id: str, tmp_path: Path):
        store.update_job(job_id, verification={"x": float("inf")})
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(tmp_path / "meta.db")) as conn:
            raw = conn.execute("SELECT data FROM analysis_jobs").fetchone()[0]
        json.loads(raw, parse_constant=lambda c: pytest.fail(f"non-standard JSON constant {c}"))
