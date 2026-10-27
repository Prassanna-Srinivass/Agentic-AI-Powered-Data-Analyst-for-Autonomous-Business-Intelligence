"""Analytics sub-package — deterministic profiling, comparisons, and quality tools."""

from app.analytics.comparisons import compare_periods, group_metric_change
from app.analytics.data_quality import detect_anomalies, test_data_quality
from app.analytics.metrics import aggregate_metric, metric_trend
from app.analytics.profiling import profile_dataframe, profile_dataset

__all__ = [
    "aggregate_metric",
    "compare_periods",
    "detect_anomalies",
    "group_metric_change",
    "metric_trend",
    "profile_dataframe",
    "profile_dataset",
    "test_data_quality",
]
