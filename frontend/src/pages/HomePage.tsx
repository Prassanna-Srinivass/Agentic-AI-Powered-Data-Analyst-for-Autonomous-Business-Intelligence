/**
 * HomePage — Main investigation workspace.
 *
 * Combines file upload, dataset profile, chat workspace,
 * analysis progress, findings, and chart display.
 */

import React, { useState } from "react";

// TODO: Wire up components and layout (Day 5)
// import FileUpload from "../components/FileUpload";
// import DatasetProfileView from "../components/DatasetProfileView";
// import ChatWorkspace from "../components/ChatWorkspace";
// import AnalysisProgress from "../components/AnalysisProgress";
// import FindingsPanel from "../components/FindingsPanel";

const HomePage: React.FC = () => {
  const [datasetId, setDatasetId] = useState<string | null>(null);

  return (
    <div>
      {/* TODO: Build the main workspace layout (Day 5)
          - Left panel: dataset upload + profile
          - Center: chat workspace with question input
          - Right panel: findings + charts
      */}
      <h1>Agentic AI-Powered Data Analyst</h1>
      <p>Investigation workspace — placeholder</p>
    </div>
  );
};

export default HomePage;
