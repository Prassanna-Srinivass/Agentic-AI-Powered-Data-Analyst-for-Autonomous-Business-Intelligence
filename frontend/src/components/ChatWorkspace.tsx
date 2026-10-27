/**
 * ChatWorkspace Component
 *
 * The main conversational interface where users ask business questions
 * and receive analysis results with findings, charts, and evidence.
 */

import React, { useState } from "react";

interface ChatWorkspaceProps {
  datasetId: string | null;
}

// TODO: Implement chat interface with message history, question input,
//       analysis progress, findings display, and chart rendering (Day 5)
const ChatWorkspace: React.FC<ChatWorkspaceProps> = ({ datasetId }) => {
  const [question, setQuestion] = useState("");

  return (
    <div>
      {/* TODO: Build chat workspace UI (Day 5) */}
      <p>ChatWorkspace component — placeholder</p>
    </div>
  );
};

export default ChatWorkspace;
