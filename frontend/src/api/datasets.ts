/**
 * API Client — Dataset endpoints.
 *
 * Wraps fetch calls to the FastAPI backend for dataset operations:
 *   - uploadDataset: POST /datasets/upload
 *   - listDatasets:  GET  /datasets
 *   - getProfile:    GET  /datasets/{id}/profile
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface DatasetProfile {
  id: string;
  filename: string;
  uploaded_at: string;
  size_bytes: number;
  row_count: number;
  column_count: number;
  profile: Record<string, unknown>;
}

/** Extract a readable message from a FastAPI error body (string or validation list). */
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
 * Upload a CSV or XLSX file and receive a dataset ID + profile.
 */
export async function uploadDataset(file: File): Promise<DatasetProfile> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/datasets/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error(await errorMessage(res, "Upload failed"));

  return res.json();
}

/**
 * List all uploaded datasets (newest first).
 */
export async function listDatasets(): Promise<DatasetProfile[]> {
  const res = await fetch(`${API_BASE}/datasets`);
  if (!res.ok) throw new Error("Failed to fetch datasets");
  return res.json();
}

/**
 * Get the full profile for a specific dataset.
 */
export async function getDatasetProfile(datasetId: string): Promise<DatasetProfile> {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}/profile`);
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to fetch dataset profile"));
  return res.json();
}
