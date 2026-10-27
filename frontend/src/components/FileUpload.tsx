/**
 * FileUpload Component
 *
 * Drag-and-drop or click-to-upload component for CSV/XLSX files.
 * Validates file type and size before sending to the backend.
 */

import React, { useCallback, useState } from "react";

interface FileUploadProps {
  onUploadSuccess: (datasetId: string, filename: string) => void;
  onUploadError?: (error: string) => void;
}

// TODO: Implement drag-and-drop UI and upload logic (Day 5)
const FileUpload: React.FC<FileUploadProps> = ({ onUploadSuccess, onUploadError }) => {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const handleUpload = useCallback(async (file: File) => {
    // Placeholder — will be wired to api/datasets.ts
    console.log("Uploading:", file.name);
    setIsUploading(true);
    try {
      // TODO: Call uploadDataset(file) from api/datasets.ts
      // const result = await uploadDataset(file);
      // onUploadSuccess(result.id, result.filename);
    } catch (err) {
      onUploadError?.(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }, [onUploadSuccess, onUploadError]);

  return (
    <div>
      {/* TODO: Build drag-and-drop upload UI (Day 5) */}
      <p>FileUpload component — placeholder</p>
    </div>
  );
};

export default FileUpload;
