"""
Agentic AI-Powered Data Analyst — FastAPI Application Entry Point.

This module initializes the FastAPI application, registers routers,
configures CORS middleware, and sets up application lifecycle events.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, datasets
from app.config import get_settings
from app.storage import get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # --- Startup ---
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    orphaned = get_store().fail_orphaned_jobs("The server restarted while this analysis was running.")
    if orphaned:
        logger.warning("marked %d unfinished job(s) from a previous run as failed", orphaned)
    logger.info("Agentic Data Analyst API starting up")
    yield
    # --- Shutdown ---
    logger.info("Agentic Data Analyst API shutting down")


app = FastAPI(
    title="Agentic AI-Powered Data Analyst",
    description=(
        "A conversational analytics system that plans and executes bounded "
        "multi-step investigations over uploaded data, adapts to findings, "
        "and presents verified, explainable business insights."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite frontend to connect during development
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ---------------------------------------------------------------------------
# Register API routers
# ---------------------------------------------------------------------------
app.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
app.include_router(analysis.router, prefix="/analysis", tags=["Analysis"])


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "service": "Agentic AI-Powered Data Analyst",
        "status": "running",
        "version": "0.1.0",
    }
