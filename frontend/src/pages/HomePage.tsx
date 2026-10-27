/**
 * HomePage — Main investigation workspace.
 *
 * Combines file upload, dataset profile, chat workspace,
 * analysis progress, findings, and chart display.
 */

import React, { useState } from "react";
import FileUpload from "../components/FileUpload";
import DatasetProfileView from "../components/DatasetProfileView";
import ChatWorkspace from "../components/ChatWorkspace";
import { listDatasets, getDatasetProfile } from "../api/datasets";
import type { DatasetProfile } from "../api/datasets";

const HomePage: React.FC = () => {
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [datasetProfile, setDatasetProfile] = useState<DatasetProfile | null>(null);
  const [datasets, setDatasets] = useState<DatasetProfile[]>([]);
  const [activeTab, setActiveTab] = useState<"chat" | "profile">("chat");

  const loadDatasets = async () => {
    try {
      const data = await listDatasets();
      setDatasets(data);
      // If we have a datasetId but no profile, load the latest
      if (datasetId && !datasetProfile) {
        const profile = await getDatasetProfile(datasetId);
        setDatasetProfile(profile);
      }
    } catch (err) {
      console.error("Failed to load datasets:", err);
    }
  };

  const handleUploadSuccess = async (id: string, filename: string, profile: Record<string, unknown>) => {
    setDatasetId(id);
    // Create a temporary profile object with the data from upload
    const tempProfile: DatasetProfile = {
      id,
      filename,
      uploaded_at: new Date().toISOString(),
      size_bytes: 0,
      row_count: (profile.row_count as number) || 0,
      column_count: (profile.column_count as number) || 0,
      profile,
    };
    setDatasetProfile(tempProfile);
    loadDatasets();
  };

  const handleUploadError = (error: string) => {
    console.error("Upload error:", error);
    alert(`Upload failed: ${error}`);
  };

  const handleDatasetSelect = async (id: string) => {
    setDatasetId(id);
    try {
      const profile = await getDatasetProfile(id);
      setDatasetProfile(profile);
    } catch (err) {
      console.error("Failed to load dataset profile:", err);
    }
  };

  const handleNewDataset = () => {
    setDatasetId(null);
    setDatasetProfile(null);
    setActiveTab("chat");
  };

  // Load datasets on mount
  React.useEffect(() => {
    loadDatasets();
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <svg className="h-8 w-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              <h1 className="text-xl font-bold text-gray-900">Agentic AI-Powered Data Analyst</h1>
            </div>
            <div className="flex items-center gap-4">
              {datasetId && (
                <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-blue-50 rounded-lg">
                  <svg className="h-4 w-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                  </svg>
                  <span className="text-sm font-medium text-blue-800 truncate max-w-xs">
                    {datasetProfile?.filename || "Dataset loaded"}
                  </span>
                  <button
                    onClick={handleNewDataset}
                    className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                  >
                    Change
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {!datasetId ? (
          /* Upload State */
          <div className="max-w-2xl mx-auto">
            <div className="text-center mb-8">
              <h2 className="text-2xl font-bold text-gray-900 mb-2">Upload Your Data</h2>
              <p className="text-gray-600">
                Start by uploading a CSV or Excel file. The system will profile your data
                and prepare it for investigation.
              </p>
            </div>
            <FileUpload onUploadSuccess={handleUploadSuccess} onUploadError={handleUploadError} />
            
            {/* Recent Datasets */}
            {datasets.length > 0 && (
              <div className="mt-8">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Datasets</h3>
                <div className="space-y-2">
                  {datasets.slice(0, 5).map((ds) => (
                    <button
                      key={ds.id}
                      onClick={() => handleDatasetSelect(ds.id)}
                      className="w-full text-left p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-medium text-gray-900 truncate">{ds.filename}</p>
                          <p className="text-sm text-gray-500">
                            {ds.row_count.toLocaleString()} rows × {ds.column_count} columns
                          </p>
                        </div>
                        <svg className="h-5 w-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Investigation Workspace */
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-200px)] min-h-[600px]">
            {/* Left Panel: Dataset Profile */}
            <aside className="lg:col-span-1">
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden h-full flex flex-col">
                {/* Tab Navigation */}
                <div className="border-b border-gray-200">
                  <nav className="flex" aria-label="Dataset tabs">
                    <button
                      onClick={() => setActiveTab("profile")}
                      className={`flex-1 py-3 px-4 text-sm font-medium text-center border-b-2 transition-colors ${
                        activeTab === "profile"
                          ? "border-blue-500 text-blue-600"
                          : "border-transparent text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Profile
                    </button>
                    <button
                      onClick={() => setActiveTab("chat")}
                      className={`flex-1 py-3 px-4 text-sm font-medium text-center border-b-2 transition-colors ${
                        activeTab === "chat"
                          ? "border-blue-500 text-blue-600"
                          : "border-transparent text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Chat
                    </button>
                  </nav>
                </div>

                {/* Tab Content */}
                <div className="flex-1 overflow-y-auto p-4">
                  {activeTab === "profile" && (
                    <DatasetProfileView profile={datasetProfile?.profile || null} filename={datasetProfile?.filename || "Dataset"} />
                  )}
                  {activeTab === "chat" && (
                    <div className="space-y-4">
                      <div className="text-center text-gray-500 py-8">
                        <svg className="h-12 w-12 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        <p className="text-sm">Switch to the chat panel on the right to ask questions about your data.</p>
                      </div>
                      <div className="rounded-lg bg-gray-50 p-4">
                        <h4 className="font-medium text-gray-900 mb-2">Suggested Questions</h4>
                        <ul className="space-y-2 text-sm text-gray-600">
                          <li className="flex items-center gap-2 cursor-pointer hover:text-gray-900">
                            <svg className="h-4 w-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            "Why did revenue decrease in September?"
                          </li>
                          <li className="flex items-center gap-2 cursor-pointer hover:text-gray-900">
                            <svg className="h-4 w-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            "How did units sold change from January to February?"
                          </li>
                          <li className="flex items-center gap-2 cursor-pointer hover:text-gray-900">
                            <svg className="h-4 w-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            "What are the data quality issues in this dataset?"
                          </li>
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </aside>

            {/* Center + Right Panel: Chat Workspace */}
            <div className="lg:col-span-3">
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden h-full">
                <ChatWorkspace datasetId={datasetId} />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default HomePage;