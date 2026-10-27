/**
 * FindingsPanel Component
 *
 * Displays verified findings from an analysis — each with
 * claim, metric value, evidence reference, and limitations.
 */

import React from "react";
import type { Finding } from "../api/analysis";

interface FindingsPanelProps {
  findings: Finding[];
}

const confidenceColors: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-amber-100 text-amber-800",
  low: "bg-red-100 text-red-800",
  "": "bg-gray-100 text-gray-800",
};

const FindingsPanel: React.FC<FindingsPanelProps> = ({ findings }) => {
  if (findings.length === 0) return null;

  return (
    <div className="space-y-4">
      <h4 className="font-medium text-gray-900">Key Findings</h4>
      <div className="space-y-3">
        {findings.map((finding, index) => (
          <div
            key={index}
            className="finding-card border border-gray-200 rounded-lg p-4 bg-white shadow-sm"
          >
            {/* Main Claim */}
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
                <span className="text-sm font-medium text-blue-700">{index + 1}</span>
              </div>
              <div className="flex-1">
                <p className="text-gray-900">{finding.claim}</p>

                {/* Metric & Value */}
                {(finding.metric || finding.value !== null && finding.value !== undefined) && (
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                    {finding.metric && (
                      <span className="px-2 py-1 bg-blue-50 text-blue-700 rounded-full font-mono">
                        {finding.metric}
                      </span>
                    )}
                    {finding.value !== null && finding.value !== undefined && (
                      <span className="px-2 py-1 bg-gray-50 text-gray-700 rounded-full font-mono">
                        Value: {String(finding.value)}
                      </span>
                    )}
                    {finding.confidence && (
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${confidenceColors[finding.confidence]}`}>
                        {finding.confidence} confidence
                      </span>
                    )}
                  </div>
                )}

                {/* Evidence Reference */}
                {finding.evidence_reference && (
                  <div className="finding-evidence mt-2">
                    <span className="font-medium text-gray-600">Evidence: </span>
                    <span className="font-mono text-gray-500">{finding.evidence_reference}</span>
                  </div>
                )}

                {/* Limitation */}
                {finding.limitation && (
                  <div className="finding-limitation mt-2">
                    <span className="font-medium text-amber-800">Limitation: </span>
                    <span className="text-amber-700">{finding.limitation}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default FindingsPanel;