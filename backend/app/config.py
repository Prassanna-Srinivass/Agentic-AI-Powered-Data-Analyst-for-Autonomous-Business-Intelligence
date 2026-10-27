"""
Application settings, read from environment variables (optionally via a ``.env`` file).

Settings are read on every call to :func:`get_settings` so tests can override them with
``monkeypatch.setenv``. Secrets (API keys) are never stored here; they stay in the environment.

======================  =========================================  ==============================
Variable                Meaning                                    Default
======================  =========================================  ==============================
UPLOAD_DIR              Where uploaded files are stored            ``backend/data/uploads``
DATABASE_PATH           SQLite metadata database                   ``backend/data/app.db``
MAX_UPLOAD_MB           Maximum upload size in megabytes           ``50``
MAX_QUESTION_CHARS      Maximum length of an analysis question     ``1000``
MAX_JOB_SECONDS         Wall-clock limit for one analysis job      ``120``
MAX_ACTIVE_JOBS         Jobs allowed to run at the same time       ``3``
CORS_ORIGINS            Comma-separated allowed browser origins    local Vite dev servers
LLM_PROVIDER            ``auto`` (use OpenAI if a key is set),     ``auto``
                        ``openai``, or ``none`` (rules only)
LLM_MODEL               Tool-calling model used for planning       ``gpt-4o``
LLM_TIMEOUT_SECONDS     Per-request model timeout                  ``30``
======================  =========================================  ==============================

The model API key is read from ``OPENAI_API_KEY`` (never stored in settings or logged).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

try:  # python-dotenv is optional at import time
    from dotenv import load_dotenv

    load_dotenv(REPO_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
)


@dataclass(frozen=True)
class Settings:
    upload_dir: Path
    database_path: Path
    max_upload_bytes: int
    max_question_chars: int
    max_job_seconds: float
    max_active_jobs: int
    cors_origins: tuple[str, ...]
    llm_provider: str
    llm_model: str
    llm_timeout_seconds: float


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _path_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else BACKEND_DIR / path


def get_settings() -> Settings:
    origins = os.environ.get("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS
    return Settings(
        upload_dir=_path_env("UPLOAD_DIR", BACKEND_DIR / "data" / "uploads"),
        database_path=_path_env("DATABASE_PATH", BACKEND_DIR / "data" / "app.db"),
        max_upload_bytes=_int_env("MAX_UPLOAD_MB", 50) * 1024 * 1024,
        max_question_chars=_int_env("MAX_QUESTION_CHARS", 1000),
        max_job_seconds=float(_int_env("MAX_JOB_SECONDS", 120)),
        max_active_jobs=_int_env("MAX_ACTIVE_JOBS", 3),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        llm_provider=(os.environ.get("LLM_PROVIDER") or "auto").strip().lower(),
        llm_model=(os.environ.get("LLM_MODEL") or "gpt-4o").strip(),
        llm_timeout_seconds=float(_int_env("LLM_TIMEOUT_SECONDS", 30)),
    )
