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

// TODO: Implement progress timeline with step cards (Day 5)
const AnalysisProgress: React.FC<AnalysisProgressProps> = ({ steps, status }) => {
  return (
    <div>
      {/* TODO: Build analysis progress UI (Day 5) */}
      <p>AnalysisProgress component — placeholder ({status})</p>
    </div>
  );
};

export default AnalysisProgress;
