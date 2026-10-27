"""
Dataset API — upload, list, and profile endpoints.

Endpoints:
    POST   /datasets/upload       Upload and validate a CSV/XLSX file; return dataset ID and profile.
    GET    /datasets               List uploaded datasets for the current local session.
    GET    /datasets/{id}/profile  Return schema, quality summary, and sample metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory store (MVP) — swap for SQLite / PostgreSQL later
# ---------------------------------------------------------------------------
_datasets: dict[str, dict[str, Any]] = {}

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """Upload and validate a CSV/XLSX file; return dataset ID and profile."""

    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds maximum upload size of 50 MB.")

    # Persist to disk
    dataset_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{dataset_id}{ext}"
    file_path.write_bytes(contents)

    # TODO: Run profiling (app.analytics.profiling) and store the result
    profile: dict[str, Any] = {}

    _datasets[dataset_id] = {
        "id": dataset_id,
        "filename": file.filename,
        "file_path": str(file_path),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
    }

    return {"id": dataset_id, "filename": file.filename, "profile": profile}


@router.get("/")
async def list_datasets():
    """List uploaded datasets for the current local session/user."""
    return list(_datasets.values())


@router.get("/{dataset_id}/profile")
async def get_dataset_profile(dataset_id: str):
    """Return schema, quality summary, and sample metadata."""
    dataset = _datasets.get(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset
