"""
Dataset API — upload, list, and profile endpoints.

Endpoints:
    POST   /datasets/upload       Upload and validate a CSV/XLSX file; return dataset ID and profile.
    GET    /datasets               List uploaded datasets for the current local session.
    GET    /datasets/{id}/profile  Return schema, quality summary, and sample metadata.

Upload safety (project plan, section 07):
    * explicit extension allow-list, content signature check, and a hard size limit
    * the original filename is only a display label; files are stored under a random UUID
    * malformed, empty, or oversized files are rejected and removed from disk
    * profiling runs in a worker thread and failures return sanitised messages (no cell data)
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.analytics.profiling import profile_dataset
from app.analytics.utils import DatasetLoadError
from app.api.schemas import DatasetOut
from app.config import get_settings
from app.storage import get_store, utc_now

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
CHUNK_BYTES = 1024 * 1024
MAX_FILENAME_LENGTH = 255
MAX_XLSX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024  # guards against zip bombs

_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_filename(raw: str | None) -> str:
    """Display-only filename: no directories, no control characters, bounded length."""
    name = Path((raw or "").replace("\\", "/")).name
    name = _CONTROL_CHARS.sub("", name).strip()
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = Path(name).suffix[:16]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return name or "upload"


async def _save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> int:
    """Stream the upload to ``dest`` enforcing ``max_bytes``; delete the partial file on failure."""
    limit_mb = max_bytes // (1024 * 1024)
    too_large = HTTPException(
        status_code=413, detail=f"File exceeds the maximum upload size of {limit_mb} MB."
    )
    if upload.size is not None and upload.size > max_bytes:
        raise too_large

    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := await upload.read(CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise too_large
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return written


def _check_signature(path: Path, ext: str) -> None:
    """Reject files whose content does not match their extension."""
    with path.open("rb") as handle:
        head = handle.read(8192)

    if ext == ".xlsx":
        if not head.startswith(_XLSX_MAGIC):
            raise HTTPException(status_code=400, detail="The file is not a valid .xlsx workbook.")
        try:
            with zipfile.ZipFile(path) as archive:
                total = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="The file is not a valid .xlsx workbook.") from exc
        if total > MAX_XLSX_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=413, detail="The workbook expands to an unsupported size.")
    elif ext == ".xls":
        if not head.startswith(_XLS_MAGIC):
            raise HTTPException(status_code=400, detail="The file is not a valid .xls workbook.")
    elif b"\x00" in head:
        raise HTTPException(status_code=400, detail="The file does not look like a text CSV file.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=DatasetOut, status_code=201)
async def upload_dataset(file: UploadFile = File(...)) -> DatasetOut:
    """Upload and validate a CSV/XLSX file; return dataset ID and profile."""
    settings = get_settings()

    filename = _clean_filename(file.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dataset_id = str(uuid.uuid4())
    file_path = settings.upload_dir / f"{dataset_id}{ext}"

    size = await _save_upload(file, file_path, settings.max_upload_bytes)

    try:
        _check_signature(file_path, ext)
        profile = await asyncio.to_thread(profile_dataset, str(file_path))
        if profile["row_count"] == 0:
            raise HTTPException(status_code=422, detail="The file contains no data rows.")
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except DatasetLoadError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc).replace(file_path.name, filename)) from exc
    except ValueError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # never echo parser internals (they can contain cell data)
        file_path.unlink(missing_ok=True)
        logger.error("profiling failed dataset_id=%s error=%s", dataset_id, type(exc).__name__)
        raise HTTPException(status_code=500, detail="The file could not be processed.") from exc

    record = get_store().add_dataset({
        "id": dataset_id,
        "filename": filename,
        "file_path": str(file_path),
        "uploaded_at": utc_now(),
        "size_bytes": size,
        "row_count": profile["row_count"],
        "column_count": profile["column_count"],
        "profile": profile,
    })
    logger.info(
        "dataset uploaded dataset_id=%s rows=%d columns=%d bytes=%d",
        dataset_id, record["row_count"], record["column_count"], size,
    )
    return DatasetOut.model_validate(record)


@router.get("", response_model=list[DatasetOut])
async def list_datasets() -> list[DatasetOut]:
    """List uploaded datasets for the current local session/user (newest first)."""
    return [DatasetOut.model_validate(d) for d in get_store().list_datasets()]


@router.get("/{dataset_id}/profile", response_model=DatasetOut)
async def get_dataset_profile(dataset_id: str) -> DatasetOut:
    """Return schema, quality summary, and sample metadata."""
    dataset = get_store().get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return DatasetOut.model_validate(dataset)
