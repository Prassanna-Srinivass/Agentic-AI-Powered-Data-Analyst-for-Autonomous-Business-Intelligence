/**
 * API Client — Analysis endpoints.
 *
 * Wraps fetch calls to the FastAPI backend for analysis operations:
 *   - startAnalysis:      POST /analysis
 *   - getAnalysis:        GET  /analysis/{id}
 *   - getAnalysisEvents:  GET  /analysis/{id}/events   (JSON snapshot, for polling)
 *   - openAnalysisStream: GET  /analysis/{id}/events   (Server-Sent Events)
 *   - getReport:          GET  /analysis/{id}/report
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export type JobStatus =
  | "pending"
  | "profiling"
  | "planning"
  | "executing"
  | "verifying"
  | "completed"
  | "failed";

export interface AnalysisStep {
  step_number: number;
  tool_name: string;
  input_summary: string;
  output_summary: string;
  status: string;
}

export interface Finding {
  claim: string;
  metric: string;
  value: unknown;
  evidence_reference: string;
  confidence: string;
  limitation: string;
}

export interface AnalysisJob {
  id: string;
  dataset_id: string;
  question: string;
  status: JobStatus;
  created_at: string;
  completed_at: string | null;
  steps: AnalysisStep[];
  findings: Finding[];
  answer: string | null;
  chart_specs: Record<string, unknown>[];
  limitations: string[];
  verification: Record<string, unknown>;
  error: string | null;
}

export interface AnalysisReport {
  id: string;
  question: string;
  dataset: { id: string; filename?: string };
  status: JobStatus;
  created_at: string | null;
  completed_at: string | null;
  generated_at: string;
  answer: string | null;
  findings: Finding[];
  verification: Record<string, unknown>;
  limitations: string[];
  steps: AnalysisStep[];
  chart_specs: Record<string, unknown>[];
}

export const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed"];

async function errorMessage(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((d: { msg?: string }) => d.msg ?? "Invalid request").join("; ");
  }
  return fallback;
}

/**
 * Start a new analysis for a given dataset and question.
 */
export async function startAnalysis(
  datasetId: string,
  question: string
): Promise<{ id: string; status: JobStatus }> {
  const res = await fetch(`${API_BASE}/analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, question }),
  });

  if (!res.ok) throw new Error(await errorMessage(res, "Failed to start analysis"));

  return res.json();
}

/**
 * Get the current status, steps, findings, and answer for an analysis job.
 */
export async function getAnalysis(jobId: string): Promise<AnalysisJob> {
  const res = await fetch(`${API_BASE}/analysis/${jobId}`);
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to fetch analysis"));
  return res.json();
}

/**
 * Get live progress for an analysis (polling fallback).
 */
export async function getAnalysisEvents(
  jobId: string
): Promise<{ id: string; status: JobStatus; steps: AnalysisStep[] }> {
  const res = await fetch(`${API_BASE}/analysis/${jobId}/events`);
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to fetch analysis events"));
  return res.json();
}

/**
 * Subscribe to live progress with Server-Sent Events.
 *
 * Events: `status` ({id, status}), `step` (AnalysisStep), and a final `done`
 * ({id, status, error}). The stream closes itself after `done`.
 * Returns a function that closes the connection.
 */
export function openAnalysisStream(
  jobId: string,
  handlers: {
    onStatus?: (status: JobStatus) => void;
    onStep?: (step: AnalysisStep) => void;
    onDone?: (result: { status: JobStatus; error: string | null }) => void;
    onError?: () => void;
  }
): () => void {
  const source = new EventSource(`${API_BASE}/analysis/${jobId}/events`);
  const parse = (e: Event) => JSON.parse((e as MessageEvent).data);

  source.addEventListener("status", (e) => handlers.onStatus?.(parse(e).status));
  source.addEventListener("step", (e) => handlers.onStep?.(parse(e)));
  source.addEventListener("done", (e) => {
    handlers.onDone?.(parse(e));
    source.close();
  });
  source.onerror = () => {
    source.close();
    handlers.onError?.();
  };
  return () => source.close();
}

/**
 * Get the generated report (JSON) for a completed analysis.
 */
export async function getReport(jobId: string): Promise<AnalysisReport> {
  const res = await fetch(`${API_BASE}/analysis/${jobId}/report`);
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to fetch report"));
  return res.json();
}

/**
 * URL that downloads the report as a Markdown file.
 */
export function getReportDownloadUrl(jobId: string): string {
  return `${API_BASE}/analysis/${jobId}/report?format=md`;
}
