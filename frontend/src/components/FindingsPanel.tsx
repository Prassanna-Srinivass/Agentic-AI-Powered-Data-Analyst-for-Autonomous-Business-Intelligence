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

// TODO: Implement findings display cards with evidence and limitations (Day 5)
const FindingsPanel: React.FC<FindingsPanelProps> = ({ findings }) => {
  return (
    <div>
      {/* TODO: Build findings panel UI (Day 5) */}
      <p>FindingsPanel component — placeholder ({findings.length} findings)</p>
    </div>
  );
};

export default FindingsPanel;
