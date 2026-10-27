/**
 * DatasetProfileView Component
 *
 * Displays the schema, sample rows, missing values, quality flags,
 * and numeric summaries for an uploaded dataset.
 */

import React from "react";

interface DatasetProfileViewProps {
  profile: Record<string, unknown> | null;
  filename: string;
}

// TODO: Implement profile display with schema table, quality alerts,
//       and sample data preview (Day 5)
const DatasetProfileView: React.FC<DatasetProfileViewProps> = ({ profile, filename }) => {
  return (
    <div>
      {/* TODO: Build dataset profile view (Day 5) */}
      <p>DatasetProfileView component — placeholder for {filename}</p>
    </div>
  );
};

export default DatasetProfileView;
