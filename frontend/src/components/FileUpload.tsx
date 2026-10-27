/**
 * FileUpload Component
 *
 * Drag-and-drop or click-to-upload component for CSV/XLSX files.
 * Validates file type and size before sending to the backend.
 */

import React, { useCallback, useState, useRef } from "react";
import { uploadDataset } from "../api/datasets";

interface FileUploadProps {
  onUploadSuccess: (datasetId: string, filename: string, profile: Record<string, unknown>) => void;
  onUploadError?: (error: string) => void;
}

const ALLOWED_EXTENSIONS = [".csv", ".xlsx", ".xls"];
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB

const FileUpload: React.FC<FileUploadProps> = ({ onUploadSuccess, onUploadError }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (!ALLOWED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      return `Invalid file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File size exceeds ${MAX_FILE_SIZE / (1024 * 1024)} MB limit`;
    }
    return null;
  };

  const handleUpload = useCallback(
    async (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        onUploadError?.(validationError);
        setError(validationError);
        return;
      }

      setError(null);
      setIsUploading(true);

      try {
        const result = await uploadDataset(file);
        onUploadSuccess(result.id, result.filename, result.profile);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Upload failed";
        onUploadError?.(errorMessage);
        setError(errorMessage);
      } finally {
        setIsUploading(false);
      }
    },
    [onUploadSuccess, onUploadError]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleUpload(file);
    },
    [handleUpload]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleUpload(file);
      // Reset input value to allow selecting the same file again
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    [handleUpload]
  );

  const handleClick = () => fileInputRef.current?.click();

  return (
    <div
      className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
        isDragging ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-blue-400"
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && handleClick()}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_EXTENSIONS.join(",")}
        onChange={handleFileSelect}
        className="hidden"
        disabled={isUploading}
      />

      {isUploading ? (
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-3 border-blue-500 border-t-transparent" />
          <p className="text-gray-600">Uploading and profiling...</p>
        </div>
      ) : (
        <div className="space-y-4">
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3 3m0 0l-3-3m3 3V12"
            />
          </svg>
          <div className="space-y-2">
            <p className="text-lg font-medium text-gray-900">Drag and drop a CSV or Excel file</p>
            <p className="text-sm text-gray-500">or click to browse</p>
          </div>
          <p className="text-xs text-gray-400">
            Supports: {ALLOWED_EXTENSIONS.join(", ")} • Max size: 50 MB
          </p>
        </div>
      )}

      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
          {error}
        </div>
      )}
    </div>
  );
};

export default FileUpload;