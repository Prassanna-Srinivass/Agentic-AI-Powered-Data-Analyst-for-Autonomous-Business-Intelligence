/**
 * AnalysisProgress Component
 *
 * Shows the step-by-step progress of an ongoing analysis,
 * including which tools are being called and their status.
 */

import React from "react";
import type { AnalysisStep } from "../api/analysis";

interface AnalysisProgressProps {
  steps: AnalysisStep[];
  status: string;
}

const statusColors: Record<string, string> = {
  pending: "bg-gray-200 text-gray-600",
  running: "bg-blue-500 text-white animate-pulse",
  completed: "bg-green-500 text-white",
  failed: "bg-red-500 text-white",
};

const statusIcons: Record<string, React.ReactNode> = {
  pending: (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  running: (
    <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  ),
  completed: (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  failed: (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
};

const getToolDisplayName = (tool: string): string => {
  const names: Record<string, string> = {
    compare_periods: "Compare Periods",
    group_metric_change: "Group Metric Change",
    test_data_quality: "Data Quality Check",
    detect_anomalies: "Anomaly Detection",
    profile_dataset: "Dataset Profiling",
  };
  return names[tool] || tool;
};

const AnalysisProgress: React.FC<AnalysisProgressProps> = ({ steps, status }) => {
  if (steps.length === 0) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <h4 className="font-medium text-gray-900">Analysis Progress</h4>
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[status] || "bg-gray-200 text-gray-600"}`}>
            {statusIcons[status]}
            <span className="ml-1 capitalize">{status}</span>
          </span>
        </div>
      </div>
      <div className="divide-y divide-gray-100">
        {steps.map((step) => (
          <div
            key={step.step_number}
            className={`px-4 py-3 flex items-start gap-4 transition-colors ${
              step.status === "running" ? "bg-blue-50" : ""
            } ${step.status === "completed" ? "bg-green-50" : ""} ${
              step.status === "failed" ? "bg-red-50" : ""
            }`}
          >
            <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium text-white">
              {statusIcons[step.status] || (
                <span className={`bg-${statusColors[step.status]?.split(" ")[0] || "gray-200"}`}>
                  {step.step_number}
                </span>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm text-gray-900">{getToolDisplayName(step.tool_name)}</span>
                <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusColors[step.status] || "bg-gray-200 text-gray-600"}`}>
                  {step.status}
                </span>
              </div>
              {step.input_summary && (
                <p className="mt-1 text-sm text-gray-500 font-mono">{step.input_summary}</p>
              )}
              {step.output_summary && step.status === "completed" && (
                <p className="mt-1 text-sm text-gray-700">{step.output_summary}</p>
              )}
              {step.status === "failed" && step.output_summary && (
                <p className="mt-1 text-sm text-red-600">Error: {step.output_summary}</p>
              )}
            </div>
            <div className="flex-shrink-0 text-right text-sm text-gray-400">
              Step {step.step_number}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default AnalysisProgress;