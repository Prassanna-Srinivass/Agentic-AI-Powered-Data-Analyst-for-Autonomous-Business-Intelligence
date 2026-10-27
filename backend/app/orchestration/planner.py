"""
Planner — Turns a natural-language question into a structured plan using known columns
and allowed tools.

The planner uses a two-stage approach:
1. Rule-based extraction (metric, date column, dimensions, periods, filters)
2. LLM with structured output for intent classification and plan generation

Falls back to rule-based plan if LLM is unavailable or fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any

from app.orchestration.state import AnalysisState, PlanStep

logger = logging.getLogger(__name__)

# Supported intents
INTENTS = (
    "compare_periods",
    "decompose_change",
    "data_quality",
    "detect_anomalies",
    "profile",
    "unknown",
)

# Approved tools (matching tools.py)
ANALYTIC_TOOLS = (
    "compare_periods",
    "group_metric_change",
    "test_data_quality",
    "detect_anomalies",
)

MAX_TOOL_CALLS = 5


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------

_PERIOD_WORDS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
    "q1": 1, "q2": 4, "q3": 7, "q4": 10,
    "quarter 1": 1, "quarter 2": 4, "quarter 3": 7, "quarter 4": 10,
}

_COMPARISON_WORDS = {
    "compare", "versus", "vs", "against", "change", "difference",
    "increase", "decrease", "fell", "dropped", "rose", "grew",
    "higher", "lower", "more", "less", "decline", "growth",
    "why", "what happened", "explain", "investigate",
}

_DECOMPOSE_WORDS = {
    "by", "breakdown", "break down", "decompose", "contributors",
    "segments", "drivers", "across", "per", "each",
}

_QUALITY_WORDS = {
    "quality", "missing", "null", "duplicate", "clean", "issues",
    "problems", "errors", "outliers", "anomalies", "inconsistent",
}

_ANOMALY_WORDS = {
    "anomaly", "anomalies", "outlier", "outliers", "unusual",
    "unexpected", "strange", "odd", "abnormal",
}


def _extract_metric(question: str, candidate_metrics: list[str]) -> str | None:
    """Extract metric from question using candidate metrics from profile."""
    question_lower = question.lower()
    for metric in candidate_metrics:
        if metric.lower() in question_lower:
            return metric
    return None


def _extract_date_column(question: str, date_columns: list[str]) -> str | None:
    """Extract date column from question."""
    question_lower = question.lower()
    for col in date_columns:
        if col.lower() in question_lower:
            return col
    return date_columns[0] if date_columns else None


def _extract_dimension(question: str, candidate_dimensions: list[str]) -> str | None:
    """Extract grouping dimension from question."""
    question_lower = question.lower()
    for dim in candidate_dimensions:
        if dim.lower() in question_lower:
            return dim
    return None


def _extract_periods(question: str) -> list[str]:
    """Extract period references from question (months, quarters, years)."""
    question_lower = question.lower()
    found = []
    seen_months = set()

    # Look for month names - use word boundary matching to avoid partial matches (e.g., "dec" in "decrease")
    for word, month in _PERIOD_WORDS.items():
        # Use regex with word boundaries to match whole words only
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, question_lower):
            # Only add if we haven't seen this month yet
            if month not in seen_months:
                seen_months.add(month)
                # Check for year nearby
                year_match = re.search(rf"{re.escape(word)}\s+(\d{{4}})", question_lower)
                if year_match:
                    found.append(f"{word.capitalize()} {year_match.group(1)}")
                else:
                    found.append(word.capitalize())

    # Look for "X vs Y" or "X compared to Y" patterns
    vs_patterns = [
        r"(\w+\s+\d{4})\s+(?:vs|versus|compared to|against)\s+(\w+\s+\d{4})",
        r"(\w+)\s+(?:vs|versus|compared to|against)\s+(\w+)",
    ]
    for pattern in vs_patterns:
        matches = re.findall(pattern, question_lower)
        for m in matches:
            found.extend(m)

    return found


def _infer_periods_from_profile(profile: dict[str, Any], date_column: str | None) -> tuple[str | None, str | None]:
    """Infer period_a and period_b from the profile's date ranges."""
    if not date_column or date_column not in profile.get("date_ranges", {}):
        return None, None

    date_range = profile["date_ranges"][date_column]
    # For MVP, just return the min and max as period labels
    return date_range.get("min", "").split("T")[0], date_range.get("max", "").split("T")[0]


def _classify_intent(question: str) -> str:
    """Rule-based intent classification."""
    question_lower = question.lower()

    # Check for anomaly detection
    if any(w in question_lower for w in _ANOMALY_WORDS):
        return "detect_anomalies"

    # Check for data quality
    if any(w in question_lower for w in _QUALITY_WORDS):
        return "data_quality"

    # Check for decomposition - 'why' questions often imply decomposition
    # Check decomposition words first
    if any(w in question_lower for w in _DECOMPOSE_WORDS):
        return "decompose_change"
    
    # Check for 'why' questions about changes - distinguish decrease vs increase
    if "why" in question_lower:
        if any(w in question_lower for w in ["decrease", "fell", "dropped", "decline"]):
            return "decrease"
        if any(w in question_lower for w in ["increase", "rose", "grew", "growth"]):
            return "increase"
        if any(w in question_lower for w in ["change"]):
            return "decompose_change"

    # Check for comparison
    if any(w in question_lower for w in _COMPARISON_WORDS):
        return "compare_periods"

    # Default
    return "unknown"


def _build_rule_based_plan(
    intent: str,
    metric: str | None,
    date_column: str | None,
    dimension: str | None,
    period_a: str | None,
    period_b: str | None,
    profile: dict[str, Any],
) -> list[PlanStep]:
    """Build a plan using only rule-based logic."""
    plan = []

    if intent == "detect_anomalies" and metric:
        plan.append(PlanStep(
            tool="detect_anomalies",
            params={"metric": metric, "method": "iqr"},
            rationale=f"Detect anomalies in {metric} using IQR method",
        ))

    elif intent == "data_quality":
        plan.append(PlanStep(
            tool="test_data_quality",
            params={"date_column": date_column} if date_column else {},
            rationale="Run data quality checks on the dataset",
        ))

    elif intent in ("compare_periods", "decompose_change", "decrease", "increase", "unknown") and metric and date_column:
        # Default to comparing the two most recent periods if not specified
        if not period_a or not period_b:
            inferred_a, inferred_b = _infer_periods_from_profile(profile, date_column)
            period_a = period_a or inferred_a
            period_b = period_b or inferred_b

        if period_a and period_b:
            plan.append(PlanStep(
                tool="compare_periods",
                params={
                    "metric": metric,
                    "date_column": date_column,
                    "period_a": period_a,
                    "period_b": period_b,
                    "aggregation": "sum",
                },
                rationale=f"Compare {metric} between {period_a} and {period_b}",
            ))

            # For decompose_change intent, the evaluator will add group_metric_change as a follow-up
            # after the comparison step completes. We don't add it here to avoid duplication.

    return plan


# ---------------------------------------------------------------------------
# LLM Planner
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a planning agent for an evidence-backed data analyst.
Given a user question and dataset profile, produce a structured plan using ONLY these approved tools:

1. compare_periods - Compare a metric between two time periods
   Required: metric, date_column, period_a, period_b
   Optional: aggregation (sum, mean, count)

2. group_metric_change - Break down a metric's change by a categorical dimension
   Required: metric, date_column, group_column, period_a, period_b
   Optional: aggregation (sum, mean, count)

3. test_data_quality - Check for missing values, duplicates, date issues
   Optional: date_column

4. detect_anomalies - Find anomalous values in a metric using IQR or z-score
   Required: metric
   Optional: method (iqr, zscore)

Constraints:
- Maximum 5 tool calls per question
- Only use columns that exist in the profile
- Periods must match the data's date format
- Output valid JSON only

Return format:
{
  "intent": "compare_periods|decompose_change|data_quality|detect_anomalies|profile",
  "assumptions": ["..."],
  "plan": [
    {"tool": "compare_periods", "params": {...}, "rationale": "..."},
    {"tool": "group_metric_change", "params": {...}, "rationale": "...", "depends_on": [1]}
  ]
}"""


def _build_llm_prompt(question: str, profile: dict[str, Any]) -> str:
    """Build the prompt for the LLM."""
    columns_info = []
    for col in profile.get("columns", []):
        col_info = f"- {col['name']} ({col['type']})"
        if col.get("examples"):
            col_info += f" - e.g., {col['examples'][:3]}"
        columns_info.append(col_info)

    return f"""Dataset Profile:
- Rows: {profile.get('row_count', 0)}
- Columns: {profile.get('column_count', 0)}
- Date columns: {', '.join(profile.get('date_columns', [])) or 'none'}
- Numeric metrics: {', '.join(profile.get('candidate_metrics', [])) or 'none'}
- Categorical dimensions: {', '.join(profile.get('candidate_dimensions', [])) or 'none'}

Column Details:
{chr(10).join(columns_info)}

Question: {question}

Return a valid JSON plan."""


async def _call_llm(prompt: str) -> dict[str, Any] | None:
    """Call the LLM with structured output. Returns None if unavailable."""
    # Check if LLM is configured
    provider = os.getenv("LLM_PROVIDER", "").lower()
    model = os.getenv("LLM_MODEL", "")

    if not provider or not model:
        logger.debug("LLM not configured, skipping LLM planning")
        return None

    try:
        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=30,
            )
            content = response.choices[0].message.content
            return json.loads(content) if content else None

        elif provider == "anthropic":
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = await client.messages.create(
                model=model,
                max_tokens=1000,
                temperature=0,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            return json.loads(content)

        else:
            logger.warning("Unknown LLM provider: %s", provider)
            return None

    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def _validate_plan(plan: list[PlanStep], profile: dict[str, Any]) -> list[PlanStep]:
    """Validate that the plan only uses approved tools and existing columns."""
    validated = []
    candidate_metrics = set(profile.get("candidate_metrics", []))
    candidate_dimensions = set(profile.get("candidate_dimensions", []))
    date_columns = set(profile.get("date_columns", []))
    period_columns = set(profile.get("period_columns", []))

    for step in plan:
        tool = step.tool
        params = step.params

        if tool not in ANALYTIC_TOOLS:
            logger.warning("Skipping unapproved tool: %s", tool)
            continue

        # Validate metric
        if "metric" in params and params["metric"] not in candidate_metrics:
            logger.warning("Metric %s not in candidate metrics, skipping", params["metric"])
            continue

        # Validate date column
        if "date_column" in params and params["date_column"] not in date_columns:
            logger.warning("Date column %s not in date columns, skipping", params["date_column"])
            continue

        # Validate group column
        if "group_column" in params and params["group_column"] not in candidate_dimensions:
            logger.warning("Group column %s not in candidate dimensions, skipping", params["group_column"])
            continue

        # Validate periods (basic check - could be enhanced)
        if "period_a" in params and "period_b" in params:
            pass  # Period validation happens at execution time

        validated.append(step)

    return validated[:MAX_TOOL_CALLS]


def _convert_llm_plan(llm_output: dict[str, Any]) -> tuple[str, list[str], list[PlanStep]]:
    """Convert LLM output to intent, assumptions, and plan steps."""
    intent = llm_output.get("intent", "unknown")
    assumptions = llm_output.get("assumptions", [])
    raw_plan = llm_output.get("plan", [])

    plan_steps = []
    for i, step in enumerate(raw_plan):
        plan_steps.append(PlanStep(
            tool=step.get("tool", ""),
            params=step.get("params", {}),
            rationale=step.get("rationale", ""),
            depends_on=step.get("depends_on", []),
        ))

    return intent, assumptions, plan_steps


def _infer_previous_period(period: str, profile: dict[str, Any], date_column: str | None) -> str | None:
    """Infer the previous period for a given period label.
    
    For monthly data, returns the previous month. For quarterly, previous quarter.
    Falls back to the min date from profile if unable to determine.
    """
    logger = __import__('logging').getLogger(__name__)
    logger.info(f"_infer_previous_period called with period={period}, date_column={date_column}")
    
    if not date_column or date_column not in profile.get("date_ranges", {}):
        logger.info(f"No date_column or date_ranges: date_column={date_column}, date_ranges={profile.get('date_ranges', {})}")
        return None
    
    date_range = profile["date_ranges"][date_column]
    min_date_str = date_range.get("min", "")
    max_date_str = date_range.get("max", "")
    
    logger.info(f"date_range: min={min_date_str}, max={max_date_str}")
    
    if not min_date_str or not max_date_str:
        return None
    
    try:
        import pandas as pd
        # Parse the mentioned period
        period_lower = period.strip().lower()
        logger.info(f"period_lower={period_lower}")
        
        # Try to parse as month name
        month_map = {
            'january': 1, 'jan': 1,
            'february': 2, 'feb': 2,
            'march': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'may': 5,
            'june': 6, 'jun': 6,
            'july': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9, 'sept': 9,
            'october': 10, 'oct': 10,
            'november': 11, 'nov': 11,
            'december': 12, 'dec': 12,
        }
        
        # Check if period is a month name
        for name, month in month_map.items():
            if name in period_lower:
                logger.info(f"Matched month name: {name} -> {month}")
                # Extract year if present
                year_match = __import__('re').search(r'(\d{4})', period)
                year = int(year_match.group(1)) if year_match else None
                
                # If no year, try to infer from min/max dates
                if year is None:
                    min_date = pd.Timestamp(min_date_str)
                    max_date = pd.Timestamp(max_date_str)
                    # Assume the most recent year that has this month
                    year = max_date.year
                    if month > max_date.month:
                        year = max_date.year - 1
                    logger.info(f"Inferred year={year} from max_date={max_date}")
                
                # Calculate previous month
                prev_month = month - 1
                prev_year = year
                if prev_month == 0:
                    prev_month = 12
                    prev_year -= 1
                
                # Format as month name
                month_names = [
                    'January', 'February', 'March', 'April', 'May', 'June',
                    'July', 'August', 'September', 'October', 'November', 'December'
                ]
                result = month_names[prev_month - 1]
                logger.info(f"Returning previous period: {result}")
                return result
        
        # If period is a date string, try to parse it
        try:
            period_date = pd.Timestamp(period)
            prev_date = period_date - pd.DateOffset(months=1)
            # Return as month name
            month_names = [
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ]
            result = month_names[prev_date.month - 1]
            logger.info(f"Parsed as date, returning: {result}")
            return result
        except Exception as e:
            logger.info(f"Failed to parse as date: {e}")
            pass
        
    except Exception as e:
        logger.error(f"Exception in _infer_previous_period: {e}")
        pass
    
    # Fallback: return min date as month name
    try:
        import pandas as pd
        min_date = pd.Timestamp(min_date_str)
        month_names = [
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]
        result = month_names[min_date.month - 1]
        logger.info(f"Fallback to min date month: {result}")
        return result
    except Exception as e:
        logger.error(f"Fallback failed: {e}")
        pass
    
    return None


def _generate_rule_based_assumptions(
    intent: str,
    metric: str | None,
    date_column: str | None,
    dimension: str | None,
    period_a: str | None,
    period_b: str | None,
    profile: dict[str, Any],
) -> list[str]:
    """Generate assumptions for the rule-based plan."""
    assumptions = []
    
    if metric:
        assumptions.append(f"Analysis focuses on metric: {metric}")
    
    if date_column:
        assumptions.append(f"Time dimension is based on column: {date_column}")
    
    if period_a and period_b:
        assumptions.append(f"Comparison is between period {period_a} and period {period_b}")
    elif period_a:
        assumptions.append(f"Analysis period is {period_a}")
    
    if dimension:
        assumptions.append(f"Decomposition is by dimension: {dimension}")
    
    if intent in ("decompose_change", "decrease", "increase"):
        assumptions.append("Assumes the change can be meaningfully decomposed by the selected dimension")
        assumptions.append("Assumes additive aggregation (sum) is appropriate for the metric")
    
    if intent == "compare_periods":
        assumptions.append("Assumes the two periods are directly comparable")
    
    candidate_metrics = profile.get("candidate_metrics", [])
    if metric and metric in candidate_metrics:
        assumptions.append(f"Metric '{metric}' is a valid numeric column")
    
    candidate_dimensions = profile.get("candidate_dimensions", [])
    if dimension and dimension in candidate_dimensions:
        assumptions.append(f"Dimension '{dimension}' is a valid categorical column")
    
    return assumptions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_plan(state: AnalysisState) -> AnalysisState:
    """
    Create a structured plan from the user question and dataset profile.

    This is the main entry point called by the plan_node in the graph.
    """
    question = state.question
    profile = state.profile

    # Extract candidate columns from profile
    candidate_metrics = profile.get("candidate_metrics", [])
    candidate_dimensions = profile.get("candidate_dimensions", [])
    date_columns = profile.get("date_columns", [])
    period_columns = profile.get("period_columns", [])

    # Rule-based extraction
    metric = _extract_metric(question, candidate_metrics)
    date_column = _extract_date_column(question, date_columns)
    dimension = _extract_dimension(question, candidate_dimensions)
    periods = _extract_periods(question)

    period_a = periods[0] if len(periods) > 0 else None
    period_b = periods[1] if len(periods) > 1 else None

    # Rule-based intent
    intent = _classify_intent(question)
    logger = __import__('logging').getLogger(__name__)
    logger.info(f"Rule-based intent: {intent}, periods: {periods}, period_a={period_a}, period_b={period_b}")

    # For decompose_change, decrease, or increase intent with only one period mentioned, infer the previous period
    # We need period_a = previous period, period_b = mentioned period for correct change direction
    if intent in ("decompose_change", "decrease", "increase") and period_a and not period_b:
        logger.info(f"Inferring previous period for {period_a}")
        previous_period = _infer_previous_period(period_a, profile, date_column)
        logger.info(f"Inferred previous period: {previous_period}")
        if previous_period:
            # Swap: period_a should be the earlier period (previous), period_b the later (mentioned)
            period_b = period_a
            period_a = previous_period

    # Try LLM planning
    llm_intent = None
    llm_assumptions = []
    llm_plan = []

    try:
        prompt = _build_llm_prompt(question, profile)
        llm_output = await _call_llm(prompt)
        if llm_output:
            llm_intent, llm_assumptions, llm_plan = _convert_llm_plan(llm_output)
            llm_plan = _validate_plan(llm_plan, profile)
    except Exception as exc:
        logger.warning("LLM planning failed: %s", exc)

    # Merge LLM and rule-based (prefer LLM if available)
    final_intent = llm_intent or intent
    if llm_intent:
        final_assumptions = llm_assumptions
        final_plan = llm_plan
    else:
        # Generate rule-based assumptions
        final_assumptions = _generate_rule_based_assumptions(
            intent, metric, date_column, dimension, period_a, period_b, profile
        )
        final_plan = _build_rule_based_plan(
            intent, metric, date_column, dimension, period_a, period_b, profile
        )

    # If still no plan, add a default profiling step
    if not final_plan and profile.get("row_count", 0) > 0:
        final_plan = [PlanStep(
            tool="test_data_quality",
            params={},
            rationale="Default to data quality check when no specific plan could be determined",
        )]

    # Update state
    state.intent = final_intent
    state.params = {
        "metric": metric,
        "date_column": date_column,
        "dimension": dimension,
        "period_a": period_a,
        "period_b": period_b,
    }
    state.assumptions = final_assumptions
    state.plan = final_plan
    state.queue = list(final_plan)  # Initialize queue with plan

    logger.info("Plan created: intent=%s, steps=%d", final_intent, len(final_plan))
    for i, step in enumerate(final_plan, 1):
        logger.info("  Step %d: %s - %s", i, step.tool, step.rationale)

    return state


def get_next_step(state: AnalysisState) -> PlanStep | None:
    """Get the next step from the queue that has its dependencies satisfied."""
    for i, step in enumerate(state.queue):
        if step.status != "pending":
            continue
        # Check dependencies against executed steps (depends_on contains step numbers)
        deps_satisfied = all(
            any(e["step"] == dep and e.get("result") for e in state.executed)
            for dep in step.depends_on
        )
        if deps_satisfied:
            return step
    return None