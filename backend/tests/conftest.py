"""Shared pytest fixtures for API tests."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point uploads and the metadata DB at a temp directory and use small limits."""
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("MAX_JOB_SECONDS", "30")
    monkeypatch.setenv("MAX_ACTIVE_JOBS", "3")
    return tmp_path


@pytest.fixture
def client(api_env: Path) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


SALES_ROWS = [
    ("2024-08-05", "North", 5000.0, 50),
    ("2024-08-10", "South", 3000.0, 30),
    ("2024-08-15", "East", 2000.0, 20),
    ("2024-09-05", "North", 4000.0, 40),
    ("2024-09-10", "South", 3200.0, 32),
    ("2024-09-15", "East", 1800.0, None),
]


@pytest.fixture
def sales_csv_bytes() -> bytes:
    df = pd.DataFrame(SALES_ROWS, columns=["date", "region", "revenue", "units"])
    return df.to_csv(index=False).encode()


@pytest.fixture
def sales_xlsx_bytes() -> bytes:
    df = pd.DataFrame(SALES_ROWS, columns=["date", "region", "revenue", "units"])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    return buffer.getvalue()


@pytest.fixture
def dataset_id(client: TestClient, sales_csv_bytes: bytes) -> str:
    response = client.post("/datasets/upload", files={"file": ("sales.csv", sales_csv_bytes, "text/csv")})
    assert response.status_code == 201, response.text
    return response.json()["id"]
