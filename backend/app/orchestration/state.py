"""
Agent State — Typed state object for the LangGraph orchestration.

This module defines the shared state that flows through every node
of the analysis workflow. It tracks the dataset, question, plan,
executed steps, findings, and verification results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisStep:
    """A single step in the analysis workflow."""
    step_number: int
    tool_name: str
    input_summary: str = ""
    output_summary: str = ""
    status: str = "pending"  # pending | running | completed | failed
    result: Any = None


@dataclass
class Finding:
    """A verified claim produced by the analysis."""
    claim: str
    metric: str = ""
    value: Any = None
    evidence_reference: str = ""
    confidence: str = ""
    limitation: str = ""


@dataclass
class AnalysisState:
    """
    Shared state for the LangGraph analysis workflow.

    This state object is passed through every node and accumulates
    data as the investigation proceeds.
    """

    # --- Identifiers ---
    job_id: str = ""
    dataset_id: str = ""
    question: str = ""

    # --- Dataset info (populated by profile node) ---
    file_path: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)

    # --- Plan (populated by plan node) ---
    plan: list[dict[str, Any]] = field(default_factory=list)

    # --- Execution tracking ---
    steps: list[AnalysisStep] = field(default_factory=list)
    current_step: int = 0
    tool_calls_used: int = 0
    retries_used: int = 0

    # --- Results ---
    findings: list[Finding] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)

    # --- Final output ---
    answer: str = ""
    limitations: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | profiling | planning | executing | verifying | completed | failed

    # --- Error tracking ---
    errors: list[str] = field(default_factory=list)
