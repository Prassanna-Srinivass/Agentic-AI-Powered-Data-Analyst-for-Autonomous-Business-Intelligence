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

const DatasetProfileView: React.FC<DatasetProfileViewProps> = ({ profile, filename }) => {
  if (!profile) return null;

  const schema = (profile.schema as Record<string, unknown>) || {};
  const rowCount = profile.row_count as number;
  const columnCount = profile.column_count as number;
  const qualityFlags = (profile.quality_flags as string[]) || [];
  const candidateMetrics = (profile.candidate_metrics as string[]) || [];
  const candidateDimensions = (profile.candidate_dimensions as string[]) || [];
  const dateColumns = (profile.date_columns as string[]) || [];
  const sampleRows = (profile.sample_rows as Record<string, unknown>[]) || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{filename}</h2>
          <p className="text-sm text-gray-500">
            {rowCount.toLocaleString()} rows × {columnCount} columns
          </p>
        </div>
      </div>

      {/* Quality Flags */}
      {qualityFlags.length > 0 && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-4">
          <h3 className="font-medium text-amber-800 mb-2 flex items-center gap-2">
            <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            Data Quality Alerts
          </h3>
          <ul className="space-y-1 text-sm text-amber-700">
            {qualityFlags.map((flag, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-0.5">•</span>
                <span>{flag}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Column Schema */}
      <div>
        <h3 className="font-medium text-gray-900 mb-3">Column Schema</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Column</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Missing</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Unique</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Role</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {Object.entries(schema).map(([colName, colInfo]: [string, unknown]) => {
                const info = colInfo as Record<string, unknown>;
                const roles: string[] = [];
                if (candidateMetrics.includes(colName)) roles.push("Metric");
                if (candidateDimensions.includes(colName)) roles.push("Dimension");
                if (dateColumns.includes(colName)) roles.push("Date");
                if (roles.length === 0) roles.push("Other");

                return (
                  <tr key={colName} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-mono text-gray-900">{colName}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {info.dtype as string || "unknown"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {typeof info.missing_count === "number" ? info.missing_count : "N/A"}
                      {typeof info.missing_pct === "number" && ` (${info.missing_pct.toFixed(1)}%)`}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {typeof info.unique_count === "number" ? info.unique_count : "N/A"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                        {roles.join(", ")}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Numeric Summaries */}
      {Object.keys(schema).some((col) => {
        const info = schema[col] as Record<string, unknown>;
        return info.summary !== undefined;
      }) && (
        <div>
          <h3 className="font-medium text-gray-900 mb-3">Numeric Summaries</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Column</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Mean</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Std</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Min</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">25%</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">50%</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">75%</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Max</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {Object.entries(schema).map(([colName, colInfo]: [string, unknown]) => {
                  const info = colInfo as Record<string, unknown>;
                  if (!info.summary) return null;

                  const summary = info.summary as Record<string, unknown>;
                  return (
                    <tr key={colName} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono text-gray-900">{colName}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary.mean === "number" ? summary.mean.toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary.std === "number" ? summary.std.toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary.min === "number" ? summary.min.toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary["25%"] === "number" ? summary["25%"].toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary["50%"] === "number" ? summary["50%"].toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary["75%"] === "number" ? summary["75%"].toFixed(2) : "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {typeof summary.max === "number" ? summary.max.toFixed(2) : "N/A"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sample Data */}
      {sampleRows.length > 0 && (
        <div>
          <h3 className="font-medium text-gray-900 mb-3">Sample Data (First 5 Rows)</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {Object.keys(sampleRows[0] || {}).map((col) => (
                    <th key={col} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {sampleRows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="hover:bg-gray-50">
                    {Object.values(row).map((value, colIndex) => (
                      <td key={colIndex} className="px-4 py-3 text-sm text-gray-600 font-mono">
                        {value === null || value === undefined ? (
                          <span className="text-gray-400 italic">null</span>
                        ) : (
                          String(value)
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default DatasetProfileView;