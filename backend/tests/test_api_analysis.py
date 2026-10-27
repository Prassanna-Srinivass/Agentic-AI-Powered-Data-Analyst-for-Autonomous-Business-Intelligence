"""
Tests for the analysis endpoints.

The real LangGraph workflow is not required here: a small fake workflow stands in for
``run_analysis`` and reports progress through the store exactly as the orchestrator will.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.storage import get_store

QUESTION = "Why did revenue decrease in September?"


async def good_workflow(job_id: str, dataset_id: str, question: str) -> None:
    store = get_store()
    store.update_job(job_id, status="profiling")
    store.update_job(job_id, status="executing")
    step = store.add_step(job_id, "compare_periods", input_summary="revenue: August vs September")
    store.update_step(job_id, step["step_number"], status="completed", output_summary="-10.0%")
    step2 = store.add_step(job_id, "group_metric_change", input_summary="by region")
    store.update_step(job_id, step2["step_number"], status="completed", output_summary="North -1000")
    store.add_finding(
        job_id,
        claim="Revenue decreased by 10.0% from August to September.",
        metric="revenue",
        value=-10.0,
        evidence_reference="step 1",
        confidence="high",
        limitation="Only two months of data.",
    )
    store.update_job(
        job_id,
        status="completed",
        answer="Revenue fell 10.0%; the largest measured contributor was North.",
        limitations=["Observed contribution does not prove causation."],
        verification={"segments_reconcile": True},
        chart_specs=[{"type": "bar", "title": "Revenue change by region"}],
    )


async def crashing_workflow(job_id: str, dataset_id: str, question: str) -> None:
    raise RuntimeError("secret cell value 4111-1111-1111-1111")


async def lazy_workflow(job_id: str, dataset_id: str, question: str) -> None:
    get_store().update_job(job_id, status="planning")


async def slow_workflow(job_id: str, dataset_id: str, question: str) -> None:
    await asyncio.sleep(1.6)
    get_store().update_job(job_id, status="completed", answer="too late")


def use_workflow(monkeypatch: pytest.MonkeyPatch, workflow) -> None:
    monkeypatch.setattr("app.api.runner._load_workflow", lambda: workflow)


def start(client: TestClient, dataset_id: str, question: str = QUESTION):
    return client.post("/analysis", json={"dataset_id": dataset_id, "question": question})


@pytest.fixture
def completed_job(client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch) -> str:
    use_workflow(monkeypatch, good_workflow)
    response = start(client, dataset_id)
    assert response.status_code == 202
    return response.json()["id"]


class TestStartAnalysis:
    def test_returns_job_id_and_pending_status(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, good_workflow)
        response = start(client, dataset_id)
        assert response.status_code == 202
        assert response.json()["status"] == "pending"
        uuid.UUID(response.json()["id"])

    def test_unknown_dataset(self, client: TestClient):
        response = start(client, "nope")
        assert response.status_code == 404
        assert response.json()["detail"] == "Dataset not found."

    @pytest.mark.parametrize("question", ["", "   ", "\n\t"])
    def test_blank_question_rejected(self, client: TestClient, dataset_id: str, question: str):
        assert start(client, dataset_id, question).status_code == 422

    def test_too_long_question_rejected(self, client: TestClient, dataset_id: str):
        response = start(client, dataset_id, "x" * 1001)
        assert response.status_code == 422
        assert "too long" in response.json()["detail"]

    def test_missing_fields_rejected(self, client: TestClient):
        assert client.post("/analysis", json={"question": QUESTION}).status_code == 422
        assert client.post("/analysis", json={}).status_code == 422

    def test_too_many_active_jobs(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("MAX_ACTIVE_JOBS", "1")
        get_store().create_job(dataset_id, "already running", str(uuid.uuid4()))
        response = start(client, dataset_id)
        assert response.status_code == 429
        assert response.headers["retry-after"] == "10"

    def test_finished_jobs_do_not_count_as_active(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, good_workflow)
        monkeypatch.setenv("MAX_ACTIVE_JOBS", "1")
        assert start(client, dataset_id).status_code == 202
        assert start(client, dataset_id).status_code == 202


class TestJobLifecycle:
    def test_completed_job_has_steps_findings_and_answer(self, client: TestClient, completed_job: str):
        job = client.get(f"/analysis/{completed_job}").json()
        assert job["status"] == "completed"
        assert job["question"] == QUESTION
        assert job["completed_at"] is not None
        assert [s["tool_name"] for s in job["steps"]] == ["compare_periods", "group_metric_change"]
        assert [s["step_number"] for s in job["steps"]] == [1, 2]
        assert job["steps"][0]["output_summary"] == "-10.0%"
        assert job["findings"][0]["value"] == -10.0
        assert job["findings"][0]["evidence_reference"] == "step 1"
        assert "largest measured contributor" in job["answer"]
        assert job["chart_specs"][0]["type"] == "bar"
        assert job["verification"] == {"segments_reconcile": True}
        assert job["error"] is None

    def test_workflow_receives_job_inputs(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        seen: dict[str, str] = {}

        async def spy(job_id: str, ds_id: str, question: str) -> None:
            seen.update(job_id=job_id, dataset_id=ds_id, question=question)
            get_store().update_job(job_id, status="completed", answer="ok")

        use_workflow(monkeypatch, spy)
        job_id = start(client, dataset_id, "  padded question  ").json()["id"]
        assert seen == {"job_id": job_id, "dataset_id": dataset_id, "question": "padded question"}

    def test_crash_becomes_sanitised_failure(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, crashing_workflow)
        job_id = start(client, dataset_id).json()["id"]
        job = client.get(f"/analysis/{job_id}").json()
        assert job["status"] == "failed"
        assert "RuntimeError" in job["error"]
        assert "4111" not in json.dumps(job)

    def test_workflow_that_never_completes_is_failed(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, lazy_workflow)
        job_id = start(client, dataset_id).json()["id"]
        job = client.get(f"/analysis/{job_id}").json()
        assert job["status"] == "failed"
        assert "without producing a result" in job["error"]

    def test_timeout_fails_job_and_late_writes_are_ignored(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, slow_workflow)
        monkeypatch.setenv("MAX_JOB_SECONDS", "1")
        job_id = start(client, dataset_id).json()["id"]
        job = client.get(f"/analysis/{job_id}").json()
        assert job["status"] == "failed"
        assert "time limit" in job["error"]

        time.sleep(1.2)  # let the abandoned workflow attempt its late write
        job = client.get(f"/analysis/{job_id}").json()
        assert job["status"] == "failed"
        assert job["answer"] is None

    def test_unknown_job(self, client: TestClient):
        assert client.get("/analysis/nope").status_code == 404


class TestEvents:
    def test_json_snapshot_for_polling_clients(self, client: TestClient, completed_job: str):
        body = client.get(f"/analysis/{completed_job}/events").json()
        assert body["status"] == "completed"
        assert len(body["steps"]) == 2

    def test_unknown_job(self, client: TestClient):
        assert client.get("/analysis/nope/events").status_code == 404

    def test_sse_stream_replays_progress_and_closes(self, client: TestClient, completed_job: str):
        with client.stream(
            "GET", f"/analysis/{completed_job}/events", headers={"Accept": "text/event-stream"}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            text = "".join(response.iter_text())

        events = []
        for block in text.strip().split("\n\n"):
            lines = dict(line.split(": ", 1) for line in block.splitlines())
            events.append((lines["event"], json.loads(lines["data"])))

        assert [name for name, _ in events] == ["status", "step", "step", "done"]
        assert events[0][1]["status"] == "completed"
        assert events[1][1]["tool_name"] == "compare_periods"
        assert events[3][1] == {"id": completed_job, "status": "completed", "error": None}

    def test_sse_for_failed_job_reports_error(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, crashing_workflow)
        job_id = start(client, dataset_id).json()["id"]
        with client.stream("GET", f"/analysis/{job_id}/events", headers={"Accept": "text/event-stream"}) as r:
            text = "".join(r.iter_text())
        assert "event: done" in text
        assert '"status": "failed"' in text


class TestReport:
    def test_json_report(self, client: TestClient, completed_job: str):
        response = client.get(f"/analysis/{completed_job}/report")
        assert response.status_code == 200
        report = response.json()
        assert report["id"] == completed_job
        assert report["question"] == QUESTION
        assert "largest measured contributor" in report["answer"]
        assert report["findings"][0]["claim"].startswith("Revenue decreased")
        assert report["dataset"]["filename"] == "sales.csv"
        assert "Only two months of data." in report["limitations"]
        assert any("causation" in item for item in report["limitations"])
        assert len(report["steps"]) == 2

    def test_markdown_download(self, client: TestClient, completed_job: str):
        response = client.get(f"/analysis/{completed_job}/report", params={"format": "md"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert f"analysis-{completed_job[:8]}.md" in response.headers["content-disposition"]
        text = response.text
        for expected in (
            "# Analysis report", QUESTION, "## Findings", "Revenue decreased by 10.0%",
            "evidence: step 1", "## Investigation steps", "`compare_periods`", "## Limitations",
            "sales.csv",
        ):
            assert expected in text

    def test_markdown_does_not_let_data_inject_structure(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        async def workflow(job_id: str, ds_id: str, question: str) -> None:
            get_store().add_finding(job_id, claim="ok\n# Injected heading\n- fake bullet")
            get_store().update_job(job_id, status="completed", answer="done")

        use_workflow(monkeypatch, workflow)
        job_id = start(client, dataset_id).json()["id"]
        text = client.get(f"/analysis/{job_id}/report", params={"format": "md"}).text
        assert "\n# Injected heading" not in text

    def test_invalid_format(self, client: TestClient, completed_job: str):
        assert client.get(f"/analysis/{completed_job}/report", params={"format": "pdf"}).status_code == 422

    def test_not_completed(self, client: TestClient, dataset_id: str):
        job = get_store().create_job(dataset_id, QUESTION, str(uuid.uuid4()))
        response = client.get(f"/analysis/{job['id']}/report")
        assert response.status_code == 409
        assert "not yet completed" in response.json()["detail"]

    def test_failed_job_has_no_report(
        self, client: TestClient, dataset_id: str, monkeypatch: pytest.MonkeyPatch
    ):
        use_workflow(monkeypatch, crashing_workflow)
        job_id = start(client, dataset_id).json()["id"]
        response = client.get(f"/analysis/{job_id}/report")
        assert response.status_code == 409
        assert "RuntimeError" in response.json()["detail"]

    def test_unknown_job(self, client: TestClient):
        assert client.get("/analysis/nope/report").status_code == 404


def test_unfinished_jobs_fail_on_restart(api_env):
    """A job left running by a previous process is failed at startup instead of hanging."""
    from app.main import app

    with TestClient(app) as first:
        upload = first.post("/datasets/upload", files={"file": ("a.csv", b"x,y\n1,2\n", "text/csv")})
        job = get_store().create_job(upload.json()["id"], QUESTION, str(uuid.uuid4()))
        get_store().update_job(job["id"], status="executing")

    with TestClient(app) as second:
        restarted = second.get(f"/analysis/{job['id']}").json()
    assert restarted["status"] == "failed"
    assert "restarted" in restarted["error"]
