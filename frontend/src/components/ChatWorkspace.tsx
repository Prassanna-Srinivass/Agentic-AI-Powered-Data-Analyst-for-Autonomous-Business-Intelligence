/**
 * ChatWorkspace Component
 *
 * The main conversational interface where users ask business questions
 * and receive analysis results with findings, charts, and evidence.
 */

import React, { useState, useEffect, useRef, useCallback } from "react";
import { startAnalysis, openAnalysisStream, getAnalysis, getReportDownloadUrl, type AnalysisJob, type JobStatus, type AnalysisStep } from "../api/analysis";
import AnalysisProgress from "./AnalysisProgress";
import FindingsPanel from "./FindingsPanel";

interface ChatWorkspaceProps {
  datasetId: string | null;
}

type MessageRole = "user" | "assistant" | "system";

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  jobId?: string;
  analysisJob?: AnalysisJob;
  timestamp: Date;
}

const ChatWorkspace: React.FC<ChatWorkspaceProps> = ({ datasetId }) => {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [streamClose, setStreamClose] = useState<(() => void) | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const assistantMessageRef = useRef<ChatMessage | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Clean up stream on unmount or job change
  useEffect(() => {
    return () => {
      if (streamClose) streamClose();
    };
  }, [streamClose, currentJobId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || !datasetId || isAnalyzing) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsAnalyzing(true);

    const userQuestion = question.trim();
    setQuestion("");

    try {
      const { id: jobId } = await startAnalysis(datasetId, userQuestion);
      setCurrentJobId(jobId);

      // Add assistant message placeholder
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        jobId,
        timestamp: new Date(),
      };
      assistantMessageRef.current = assistantMessage;
      setMessages((prev) => [...prev, assistantMessage]);

      // Open SSE stream for live updates
      const closeStream = openAnalysisStream(jobId, {
        onStatus: (status: JobStatus) => {
          const msg = assistantMessageRef.current;
          if (!msg) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msg.id ? { ...m, content: `Status: ${status}` } : m
            )
          );
        },
        onStep: (step: AnalysisStep) => {
          const msg = assistantMessageRef.current;
          if (!msg) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msg.id
                ? { ...m, content: `Step ${step.step_number}: ${step.tool_name} - ${step.output_summary || "running..."}` }
                : m
            )
          );
        },
        onDone: async (result) => {
          setIsAnalyzing(false);
          setStreamClose(null);
          assistantMessageRef.current = null;

          if (result.status === "completed") {
            const job = await getAnalysis(jobId);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, analysisJob: job, content: job.answer || "Analysis completed" }
                  : m
              )
            );
          } else {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, content: `Analysis failed: ${result.error || "Unknown error"}` }
                  : m
              )
            );
          }
        },
        onError: () => {
          setIsAnalyzing(false);
          setStreamClose(null);
          // Capture the message before clearing the ref
          const msg = assistantMessageRef.current;
          assistantMessageRef.current = null;
          if (!msg) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msg.id
                ? { ...m, content: "Connection lost. Please check the analysis status." }
                : m
            )
          );
        },
      });

      setStreamClose(closeStream);
    } catch (err) {
      setIsAnalyzing(false);
      const errorMessage = err instanceof Error ? err.message : "Failed to start analysis";
      const msg = assistantMessageRef.current;
      if (!msg) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msg.id
            ? { ...m, content: `Error: ${errorMessage}` }
            : m
        )
      );
    }
  };

  const handleDownloadReport = async (jobId: string) => {
    try {
      const url = getReportDownloadUrl(jobId);
      const response = await fetch(url);
      if (response.ok) {
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = downloadUrl;
        a.download = `analysis-report-${jobId}.md`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(downloadUrl);
        document.body.removeChild(a);
      }
    } catch (err) {
      console.error("Failed to download report:", err);
    }
  };

  if (!datasetId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-500">
        <svg className="h-16 w-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p className="text-lg">Upload a dataset to start investigating</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full min-h-0">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] px-4 py-3 rounded-2xl ${
                message.role === "user"
                  ? "bg-blue-600 text-white rounded-br-none"
                  : "bg-white border border-gray-200 rounded-bl-none"
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>

              {/* Analysis Results */}
              {message.analysisJob && (
                <div className="mt-4 space-y-4 border-t border-gray-200 pt-4">
                  {/* Answer */}
                  <div className="prose prose-sm max-w-none">
                    <p className="font-medium text-gray-900">{message.analysisJob.answer}</p>
                  </div>

                  {/* Analysis Progress */}
                  {message.analysisJob.steps.length > 0 && (
                    <AnalysisProgress
                      steps={message.analysisJob.steps}
                      status={message.analysisJob.status}
                    />
                  )}

                  {/* Findings */}
                  {message.analysisJob.findings.length > 0 && (
                    <FindingsPanel findings={message.analysisJob.findings} />
                  )}

                  {/* Charts */}
                  {message.analysisJob.chart_specs.length > 0 && (
                    <div>
                      <h4 className="font-medium text-gray-900 mb-2">Charts</h4>
                      <div className="space-y-4">
                        {message.analysisJob.chart_specs.map((chart, idx) => (
                          <div key={idx} className="chart-container">
                            <ChartRenderer spec={chart} />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Limitations */}
                  {message.analysisJob.limitations.length > 0 && (
                    <div className="rounded-lg bg-amber-50 border border-amber-200 p-4">
                      <h4 className="font-medium text-amber-800 mb-2 flex items-center gap-2">
                        <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                        </svg>
                        Limitations
                      </h4>
                      <ul className="space-y-1 text-sm text-amber-700">
                        {message.analysisJob.limitations.map((lim, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <span className="mt-0.5">•</span>
                            <span>{lim}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Download Report */}
                  <div className="flex items-center gap-4 pt-4 border-t border-gray-200">
                    <button
                      onClick={() => message.analysisJob && handleDownloadReport(message.analysisJob.id)}
                      className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      Download Report (Markdown)
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-gray-200 p-4 bg-white">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your data..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={isAnalyzing || !datasetId}
            aria-label="Enter your business question"
          />
          <button
            type="submit"
            disabled={!question.trim() || isAnalyzing || !datasetId}
            className="px-6 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isAnalyzing ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Analyzing...
              </span>
            ) : (
              "Analyze"
            )}
          </button>
        </form>
        <p className="mt-2 text-xs text-gray-500 text-center">
          Example: "Why did revenue decrease in September?" or "How did units sold change from January to February?"
        </p>
      </div>
    </div>
  );
};

// Simple Chart Renderer using Plotly
const ChartRenderer: React.FC<{ spec: Record<string, unknown> }> = ({ spec }) => {
  const plotRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!plotRef.current) return;

    try {
      // Dynamic import to avoid SSR issues
      import("plotly.js-basic-dist-min").then((Plotly) => {
        Plotly.default.newPlot(plotRef.current!, spec as any, { responsive: true });
      });
    } catch (err) {
      setError("Failed to render chart");
    }
  }, [spec]);

  if (error) {
    return (
      <div className="text-center text-red-500 py-8">
        Failed to render chart: {error}
      </div>
    );
  }

  return <div ref={plotRef} className="w-full h-96" />;
};

export default ChatWorkspace;