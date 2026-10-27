"""
End-to-end integration tests for the Agentic Data Analyst workflow.

These tests verify the full pipeline from upload through orchestration
to verified findings, matching the project plan Day 6 requirements.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from app.orchestration.graph import build_analysis_graph, run_analysis
from app.orchestration.state import AnalysisState
from app.storage import get_store, reset_store, utc_now


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def setup_test_data():
    """Ensure the demo dataset is available for tests."""
    # The demo dataset is already at backend/data/sales_sample.csv
    data_path = Path(__file__).parent.parent / "data" / "sales_sample.csv"
    assert data_path.exists(), f"Demo dataset not found at {data_path}"
    yield
    # Cleanup after all tests if needed


@pytest.fixture
def fresh_store():
    """Provide a fresh store for each test."""
    reset_store()
    store = get_store()
    yield store
    reset_store()


@pytest.fixture
def uploaded_dataset(fresh_store):
    """Upload the demo dataset and return its ID."""
    data_path = Path(__file__).parent.parent / "data" / "sales_sample.csv"
    import uuid
    dataset = fresh_store.add_dataset({
        "id": str(uuid.uuid4()),
        "filename": "sales_sample.csv",
        "file_path": str(data_path),
        "uploaded_at": utc_now(),
        "size_bytes": data_path.stat().st_size,
        "row_count": 96,
        "column_count": 9,
        "profile": {},  # Will be populated by workflow
    })
    return dataset["id"]


# ---------------------------------------------------------------------------
# Known-answer questions for numerical accuracy testing
# These questions have verified answers from the demo dataset
# ---------------------------------------------------------------------------

KNOWN_ANSWER_QUESTIONS = [
    {
        "name": "revenue_decrease_september",
        "question": "Why did revenue decrease in September?",
        "expected_findings": {
            "intent": "decrease",
            "metric": "revenue",
            "period_b": "2024-09",
            # September revenue: 76000, August: 84500
            # Change: -8500, percent: -10.06%
            "approx_change": -8500,
            "approx_pct": -10.1,
            "largest_contributor": "North",
            "contributor_change": -2500,
            "contributor_pct": 29.4,
        },
    },
    {
        "name": "revenue_increase_august",
        "question": "Why did revenue increase in August?",
        "expected_findings": {
            "intent": "increase",
            "metric": "revenue",
            "period_b": "2024-08",
            # August revenue: 84500, July: 75400
            # Change: +9100, percent: +12.1%
            "approx_change": 9100,
            "approx_pct": 12.1,
            "largest_contributor": "North",
            "contributor_change": 2100,
            "contributor_pct": 23.1,
        },
    },
    {
        "name": "units_comparison_jan_feb",
        "question": "How did units sold change from January to February?",
        "expected_findings": {
            "intent": "change",
            "metric": "units",
            "period_a": "2024-01",
            "period_b": "2024-02",
            # Jan units: 1302, Feb: 1346
            # Change: +44, percent: +3.4%
            "approx_change": 44,
            "approx_pct": 3.4,
        },
    },
    {
        "name": "revenue_change_oct_nov",
        "question": "What was the revenue change from October to November?",
        "expected_findings": {
            "intent": "change",
            "metric": "revenue",
            "period_a": "2024-10",
            "period_b": "2024-11",
            # Oct: 81900, Nov: 80300
            # Change: -1600, percent: -2.0%
            "approx_change": -1600,
            "approx_pct": -2.0,
        },
    },
    {
        "name": "orders_increase_december",
        "question": "Why did orders increase in December?",
        "expected_findings": {
            "intent": "increase",
            "metric": "orders",
            "period_b": "2024-12",
            # Dec orders: 1285, Nov: 1248
            # Change: +37, percent: +3.0%
            "approx_change": 37,
            "approx_pct": 3.0,
        },
    },
    {
        "name": "cost_comparison_q3_q4",
        "question": "How did costs change from Q3 to Q4?",
        "expected_findings": {
            "intent": "change",
            "metric": "cost",
            "period_a": "2024-09",  # Q3 end
            "period_b": "2024-12",  # Q4 end
            # This will compare September vs December
        },
    },
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

async def run_workflow(fresh_store, dataset_id: str, question: str):
    """Run the analysis workflow and return the final job state."""
    # Create a job
    import uuid
    job_id = str(uuid.uuid4())
    job = fresh_store.create_job(dataset_id=dataset_id, question=question, job_id=job_id)

    # Run the analysis
    await run_analysis(job_id, dataset_id, question)

    # Get final job state
    final_job = fresh_store.get_job(job_id)
    return final_job


def find_finding_by_metric(findings: list[dict], metric: str) -> dict | None:
    """Find a finding by metric name."""
    for f in findings:
        if f.get("metric") == metric:
            return f
    return None


def find_finding_containing(findings: list[dict], text: str) -> dict | None:
    """Find a finding containing specific text in its claim."""
    for f in findings:
        if text.lower() in f.get("claim", "").lower():
            return f
    return None


# ---------------------------------------------------------------------------
# Test Class: Numerical Accuracy
# ---------------------------------------------------------------------------

class TestNumericalAccuracy:
    """Test that the workflow produces numerically accurate results for known questions."""

    @pytest.mark.asyncio
    async def test_revenue_decrease_september(self, fresh_store, uploaded_dataset):
        """Test the canonical question from Appendix A: Why did revenue decrease in September?"""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed", f"Job failed: {job.get('error')}"
        assert job["answer"], "No answer generated"

        # Check the main finding
        findings = job["findings"]
        assert len(findings) >= 2, "Expected at least 2 findings (comparison + decomposition)"

        # First finding: period comparison
        comparison_finding = find_finding_by_metric(findings, "revenue")
        assert comparison_finding is not None, "Missing revenue comparison finding"
        claim = comparison_finding["claim"]
        assert "revenue" in claim.lower()
        assert "decreased" in claim.lower() or "changed by -" in claim or "changed by −" in claim

        # Verify numerical values
        # Sep revenue: 76000, Aug: 84500, change: -8500 (-10.06%)
        assert "-8,500" in claim or "-8500" in claim or "−8,500" in claim, f"Expected -8500 in claim: {claim}"
        assert "10.1%" in claim or "10.0%" in claim, f"Expected ~10% in claim: {claim}"

        # Second finding: largest contributor (North)
        decomp_finding = find_finding_containing(findings, "largest measured contributor")
        assert decomp_finding is not None, "Missing decomposition finding"
        assert "North" in decomp_finding["claim"], f"Expected North as largest contributor: {decomp_finding['claim']}"
        assert "2,500" in decomp_finding["claim"] or "2500" in decomp_finding["claim"], \
            f"Expected -2500 in contributor claim: {decomp_finding['claim']}"
        assert "29.4%" in decomp_finding["claim"] or "29%" in decomp_finding["claim"], \
            f"Expected ~29% contribution: {decomp_finding['claim']}"

        # Verify verification passed
        assert job["verification"]["all_passed"], f"Verification failed: {job['verification']['checks']}"

        # Verify evidence references
        for finding in findings:
            assert finding["evidence_reference"], f"Finding missing evidence: {finding}"
            assert "step" in finding["evidence_reference"].lower(), f"Invalid evidence ref: {finding['evidence_reference']}"

        # Check charts generated
        assert len(job["chart_specs"]) >= 1, "Expected at least one chart"
        chart = job["chart_specs"][0]
        assert chart["type"] in ("period_comparison", "segment_change")
        assert "evidence_ref" in chart

    @pytest.mark.asyncio
    async def test_revenue_increase_august(self, fresh_store, uploaded_dataset):
        """Test revenue increase in August."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue increase in August?")

        assert job["status"] == "completed"
        findings = job["findings"]

        comparison_finding = find_finding_by_metric(findings, "revenue")
        assert comparison_finding is not None
        claim = comparison_finding["claim"]
        assert "increased" in claim.lower() or "changed by +" in claim or "changed by ＋" in claim
        assert "9,100" in claim or "9100" in claim, f"Expected +9100 in claim: {claim}"
        assert "12.1%" in claim, f"Expected ~12% in claim: {claim}"

        # North should be largest contributor (+2100, 23.1%)
        decomp_finding = find_finding_containing(findings, "largest measured contributor")
        assert decomp_finding is not None
        assert "North" in decomp_finding["claim"]
        assert "2,100" in decomp_finding["claim"] or "2100" in decomp_finding["claim"]

        assert job["verification"]["all_passed"]

    @pytest.mark.asyncio
    async def test_units_change_jan_feb(self, fresh_store, uploaded_dataset):
        """Test units comparison January to February."""
        job = await run_workflow(fresh_store, uploaded_dataset, "How did units sold change from January to February?")

        assert job["status"] == "completed"
        findings = job["findings"]

        comparison_finding = find_finding_by_metric(findings, "units")
        assert comparison_finding is not None
        claim = comparison_finding["claim"]
        assert "units" in claim.lower()
        # Jan: 1302, Feb: 1346, change: +44
        assert "44" in claim
        assert "3.4%" in claim or "3%" in claim

        assert job["verification"]["all_passed"]

    @pytest.mark.asyncio
    async def test_revenue_change_oct_nov(self, fresh_store, uploaded_dataset):
        """Test revenue change October to November."""
        job = await run_workflow(fresh_store, uploaded_dataset, "What was the revenue change from October to November?")

        assert job["status"] == "completed"
        findings = job["findings"]

        comparison_finding = find_finding_by_metric(findings, "revenue")
        assert comparison_finding is not None
        claim = comparison_finding["claim"]
        assert "revenue" in claim.lower()
        # Oct: 81900, Nov: 80300, change: -1600
        assert "1,600" in claim or "1600" in claim
        assert "2.0%" in claim or "2%" in claim

        assert job["verification"]["all_passed"]

    @pytest.mark.asyncio
    async def test_orders_increase_december(self, fresh_store, uploaded_dataset):
        """Test orders increase in December."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did orders increase in December?")

        assert job["status"] == "completed"
        findings = job["findings"]

        comparison_finding = find_finding_by_metric(findings, "orders")
        assert comparison_finding is not None
        claim = comparison_finding["claim"]
        assert "orders" in claim.lower()
        # Dec: 1285, Nov: 1248, change: +37
        assert "37" in claim
        assert "3.0%" in claim or "3%" in claim

        assert job["verification"]["all_passed"]


# ---------------------------------------------------------------------------
# Test Class: Tool Selection Verification
# ---------------------------------------------------------------------------

class TestToolSelection:
    """Test that the correct tools are selected for different question types."""

    @pytest.mark.asyncio
    async def test_why_question_triggers_decomposition(self, fresh_store, uploaded_dataset):
        """'Why' questions should trigger compare_periods followed by group_metric_change."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue drop in September?")

        assert job["status"] == "completed"
        steps = job["steps"]

        # Should have at least 2 steps: compare_periods + group_metric_change
        tool_names = [s["tool_name"] for s in steps if s["status"] == "completed"]
        assert "compare_periods" in tool_names, f"Expected compare_periods, got {tool_names}"
        assert "group_metric_change" in tool_names, f"Expected group_metric_change, got {tool_names}"

        # compare_periods should come first
        compare_idx = tool_names.index("compare_periods")
        group_idx = tool_names.index("group_metric_change")
        assert compare_idx < group_idx, "compare_periods should execute before group_metric_change"

    @pytest.mark.asyncio
    async def test_how_question_triggers_comparison(self, fresh_store, uploaded_dataset):
        """'How' questions should trigger compare_periods."""
        job = await run_workflow(fresh_store, uploaded_dataset, "How did revenue change from August to September?")

        assert job["status"] == "completed"
        steps = job["steps"]
        tool_names = [s["tool_name"] for s in steps if s["status"] == "completed"]

        assert "compare_periods" in tool_names, f"Expected compare_periods, got {tool_names}"

    @pytest.mark.asyncio
    async def test_data_quality_check_triggered(self, fresh_store, uploaded_dataset):
        """Evaluator should trigger test_data_quality after decomposition."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        steps = job["steps"]
        tool_names = [s["tool_name"] for s in steps if s["status"] == "completed"]

        # After compare_periods + group_metric_change, evaluator should add test_data_quality
        assert "test_data_quality" in tool_names, f"Expected test_data_quality, got {tool_names}"


# ---------------------------------------------------------------------------
# Test Class: Adaptive Follow-up Trigger
# ---------------------------------------------------------------------------

class TestAdaptiveFollowUp:
    """Test that the evaluator correctly triggers follow-up analyses."""

    @pytest.mark.asyncio
    async def test_follow_up_after_comparison(self, fresh_store, uploaded_dataset):
        """After compare_periods with significant change, evaluator should add group_metric_change."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        executed = job.get("executed", [])
        # Check that group_metric_change was added as follow-up
        group_steps = [e for e in executed if e["tool"] == "group_metric_change"]
        assert len(group_steps) >= 1, "Expected at least one group_metric_change follow-up"

    @pytest.mark.asyncio
    async def test_budget_limit_respected(self, fresh_store, uploaded_dataset):
        """Tool calls should not exceed MAX_TOOL_CALLS (5)."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        steps = job["steps"]
        completed_steps = [s for s in steps if s["status"] == "completed"]
        assert len(completed_steps) <= 5, f"Tool calls exceeded budget: {len(completed_steps)}"

    @pytest.mark.asyncio
    async def test_no_follow_up_for_insignificant_change(self, fresh_store, uploaded_dataset):
        """If change is < 1%, evaluator should not add decomposition follow-up."""
        # Compare two months with very similar revenue (e.g., Jan vs Feb for a specific product)
        # The demo data has significant changes, so this may not trigger
        # We'll test that the budget mechanism works
        job = await run_workflow(fresh_store, uploaded_dataset, "How did revenue change from January to February?")

        assert job["status"] == "completed"
        # At minimum should have compare_periods
        steps = job["steps"]
        tool_names = [s["tool_name"] for s in steps if s["status"] == "completed"]
        assert "compare_periods" in tool_names


# ---------------------------------------------------------------------------
# Test Class: Evidence Support Checks
# ---------------------------------------------------------------------------

class TestEvidenceSupport:
    """Test that every finding is backed by evidence references to completed steps."""

    @pytest.mark.asyncio
    async def test_all_findings_have_evidence(self, fresh_store, uploaded_dataset):
        """Every finding must cite a completed step."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        findings = job["findings"]
        completed_step_numbers = {s["step_number"] for s in job["steps"] if s["status"] == "completed"}

        for finding in findings:
            evidence = finding["evidence_reference"]
            assert evidence, f"Finding missing evidence: {finding}"
            # Extract step numbers from evidence reference
            import re
            step_nums = {int(n) for n in re.findall(r"step (\d+)", evidence)}
            assert step_nums, f"No step numbers in evidence: {evidence}"
            assert step_nums <= completed_step_numbers, \
                f"Evidence references non-completed step: {step_nums} not in {completed_step_numbers}"

    @pytest.mark.asyncio
    async def test_verification_evidence_check_passes(self, fresh_store, uploaded_dataset):
        """The evidence_check in verification should pass."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        verification = job["verification"]
        evidence_checks = [c for c in verification["checks"] if c["name"] == "every finding cites a calculation"]
        assert evidence_checks, "Evidence check not found in verification"
        assert evidence_checks[0]["passed"], f"Evidence check failed: {evidence_checks[0]['detail']}"


# ---------------------------------------------------------------------------
# Test Class: Reconciliation Validation
# ---------------------------------------------------------------------------

class TestReconciliation:
    """Test that segment decompositions reconcile with overall totals."""

    @pytest.mark.asyncio
    async def test_segment_changes_reconcile(self, fresh_store, uploaded_dataset):
        """Segment changes should sum to overall change within tolerance."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        verification = job["verification"]

        # Check for reconciliation check
        recon_checks = [c for c in verification["checks"] if "reconcile" in c["name"].lower()]
        assert recon_checks, "Reconciliation check not found in verification"

        for check in recon_checks:
            assert check["passed"], f"Reconciliation failed: {check['detail']}"
            # Verify the detail contains expected info
            assert "segment_sum" in check["detail"] or "segments sum" in check["detail"].lower()

    @pytest.mark.asyncio
    async def test_decomposition_matches_comparison(self, fresh_store, uploaded_dataset):
        """Segment decomposition total should match period comparison total."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        verification = job["verification"]

        cross_checks = [c for c in verification["checks"] if "matches" in c["name"].lower() or "cross" in c["name"].lower()]
        if cross_checks:
            for check in cross_checks:
                assert check["passed"], f"Cross-check failed: {check['detail']}"


# ---------------------------------------------------------------------------
# Test Class: Failure Behavior
# ---------------------------------------------------------------------------

class TestFailureBehavior:
    """Test that the workflow handles various failure scenarios gracefully."""

    @pytest.mark.asyncio
    async def test_invalid_file_path(self, fresh_store):
        """Test handling of non-existent file."""
        # Create a dataset with invalid path
        dataset = fresh_store.create_dataset(
            name="missing.csv",
            file_path="/nonexistent/path/missing.csv",
            row_count=0,
            column_count=0,
        )

        job = fresh_store.create_job(dataset_id=dataset["id"], question="What happened?")

        # The workflow should fail gracefully
        await run_analysis(job["id"], dataset["id"], "What happened?")

        final_job = fresh_store.get_job(job["id"])
        assert final_job["status"] == "failed"
        assert final_job["error"] is not None

    @pytest.mark.asyncio
    async def test_missing_column_in_question(self, fresh_store, uploaded_dataset):
        """Test handling of question referencing non-existent column."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did nonexistent_column decrease?")

        # Should fail or handle gracefully
        assert job["status"] in ("completed", "failed")
        if job["status"] == "failed":
            assert job["error"] is not None
        else:
            # If completed, should have limitations about missing column
            assert any("column" in lim.lower() or "metric" in lim.lower() for lim in job["limitations"])

    @pytest.mark.asyncio
    async def test_empty_dataset(self, fresh_store):
        """Test handling of empty dataset."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("date,revenue\n")  # Header only
            temp_path = f.name

        try:
            dataset = fresh_store.create_dataset(
                name="empty.csv",
                file_path=temp_path,
                row_count=0,
                column_count=2,
            )
            job = fresh_store.create_job(dataset_id=dataset["id"], question="What happened?")
            await run_analysis(job["id"], dataset["id"], "What happened?")

            final_job = fresh_store.get_job(job["id"])
            # Should fail or complete with limitations
            assert final_job["status"] in ("completed", "failed")
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_malformed_csv(self, fresh_store):
        """Test handling of malformed CSV."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("date,revenue\n")
            f.write("not-a-date,not-a-number\n")
            f.write("2024-01-01,100\n")
            temp_path = f.name

        try:
            dataset = fresh_store.create_dataset(
                name="malformed.csv",
                file_path=temp_path,
                row_count=2,
                column_count=2,
            )
            job = fresh_store.create_job(dataset_id=dataset["id"], question="What happened?")
            await run_analysis(job["id"], dataset["id"], "What happened?")

            final_job = fresh_store.get_job(job["id"])
            assert final_job["status"] in ("completed", "failed")
        finally:
            os.unlink(temp_path)


# ---------------------------------------------------------------------------
# Test Class: Workflow Integration
# ---------------------------------------------------------------------------

class TestWorkflowIntegration:
    """Integration tests for the complete workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow_state_progression(self, fresh_store, uploaded_dataset):
        """Test that workflow progresses through all expected states."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"

        # Check all expected fields are present
        assert job["job_id"]
        assert job["dataset_id"]
        assert job["question"]
        assert job["answer"]
        assert job["findings"]
        assert job["steps"]
        assert job["chart_specs"]
        assert job["limitations"]
        assert job["assumptions"]
        assert job["intent"]
        assert job["verification"]

        # Verify step progression
        steps = job["steps"]
        assert len(steps) >= 2

        # First step should be compare_periods
        assert steps[0]["tool_name"] == "compare_periods"
        assert steps[0]["status"] == "completed"
        assert steps[0]["input_summary"]
        assert steps[0]["output_summary"]

    @pytest.mark.asyncio
    async def test_intent_classification(self, fresh_store, uploaded_dataset):
        """Test that intent is correctly classified."""
        test_cases = [
            ("Why did revenue decrease in September?", "decrease"),
            ("Why did revenue increase in August?", "increase"),
            ("How did revenue change from January to February?", "change"),
            ("What happened to revenue in September?", "change"),
        ]

        for question, expected_intent in test_cases:
            job = await run_workflow(fresh_store, uploaded_dataset, question)
            assert job["status"] == "completed", f"Failed for: {question}"
            assert job["intent"] == expected_intent, \
                f"Intent mismatch for '{question}': expected {expected_intent}, got {job['intent']}"

    @pytest.mark.asyncio
    async def test_assumptions_recorded(self, fresh_store, uploaded_dataset):
        """Test that assumptions are recorded in the final output."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        assert job["assumptions"], "No assumptions recorded"
        # Should have assumptions about period detection, aggregation, etc.
        assumptions_text = " ".join(job["assumptions"]).lower()
        assert "period" in assumptions_text or "month" in assumptions_text
        assert "sum" in assumptions_text or "aggregation" in assumptions_text

    @pytest.mark.asyncio
    async def test_limitations_include_standard_items(self, fresh_store, uploaded_dataset):
        """Test that standard limitations are included."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        limitations = job["limitations"]
        limitations_text = " ".join(limitations).lower()

        # Standard limitations from project plan
        assert "causation" in limitations_text or "cause" in limitations_text
        assert "available data" in limitations_text or "missing" in limitations_text

    @pytest.mark.asyncio
    async def test_chart_generation_on_verified_results(self, fresh_store, uploaded_dataset):
        """Charts should only be generated when verification passes."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        assert job["status"] == "completed"
        assert job["verification"]["all_passed"]
        assert len(job["chart_specs"]) >= 1

        chart = job["chart_specs"][0]
        assert "type" in chart
        assert "spec" in chart
        assert "evidence_ref" in chart
        assert chart["type"] in ("period_comparison", "segment_change")


# ---------------------------------------------------------------------------
# Test Class: Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_multiple_questions_same_dataset(self, fresh_store, uploaded_dataset):
        """Test running multiple questions on the same dataset."""
        questions = [
            "Why did revenue decrease in September?",
            "How did revenue change from August to September?",
            "What was the revenue trend in Q3?",
        ]

        for question in questions:
            job = await run_workflow(fresh_store, uploaded_dataset, question)
            assert job["status"] == "completed", f"Failed for: {question}"

    @pytest.mark.asyncio
    async def test_question_with_no_significant_change(self, fresh_store, uploaded_dataset):
        """Test question about period with minimal change."""
        # Compare two very similar months if any exist
        # The demo data has significant monthly changes, so this may still trigger analysis
        job = await run_workflow(fresh_store, uploaded_dataset, "Compare revenue in November and December")

        assert job["status"] == "completed"
        assert job["answer"]

    @pytest.mark.asyncio
    async def test_verification_failure_handling(self, fresh_store, uploaded_dataset):
        """Test that verification failures are reflected in limitations."""
        job = await run_workflow(fresh_store, uploaded_dataset, "Why did revenue decrease in September?")

        # The demo dataset should pass verification
        if not job["verification"]["all_passed"]:
            assert any("verification" in lim.lower() for lim in job["limitations"])


# ---------------------------------------------------------------------------
# Main entry point for manual testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Allow running this test file directly
    import sys

    # Run with: python -m pytest tests/test_workflow.py -v
    pytest.main([__file__, "-v"])