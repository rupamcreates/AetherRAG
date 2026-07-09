"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Upload, AlertCircle, FileText, CheckCircle2, RefreshCw } from "lucide-react";

interface DocumentUploaderProps {
  onUploadSuccess: () => void;
}

export default function DocumentUploader({ onUploadSuccess }: DocumentUploaderProps) {
  const { getToken } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setStatus("idle");
      setErrorMessage("");
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setStatus("uploading");
    setErrorMessage("");

    try {
      const token = await getToken();
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
      
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${apiUrl}/documents/upload`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to upload file");
      }

      setStatus("success");
      setFile(null);
      
      // Trigger refresh on parent component
      onUploadSuccess();
      
      // Reset state after a delay
      setTimeout(() => {
        setStatus("idle");
      }, 3000);
      
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setErrorMessage(err.message || "An unexpected error occurred.");
    }
  };

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <h3 className="text-sm font-semibold text-zinc-200 mb-2">Upload Source Document</h3>
      <form onSubmit={handleUpload} className="space-y-3">
        <label className="flex flex-col items-center justify-center border border-dashed border-zinc-700 hover:border-zinc-500 rounded-lg p-6 cursor-pointer bg-zinc-950 transition-colors">
          <div className="flex flex-col items-center justify-center text-center space-y-1">
            <Upload className="h-6 w-6 text-zinc-500 mb-1" />
            <p className="text-xs font-medium text-zinc-300">
              {file ? file.name : "Select Document File"}
            </p>
            <p className="text-[10px] text-zinc-500">
              PDF, DOCX, CSV, XLSX, TXT, PNG, JPG
            </p>
          </div>
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,.doc,.csv,.xlsx,.xls,.txt,.png,.jpg,.jpeg"
            onChange={handleFileChange}
            disabled={status === "uploading"}
          />
        </label>

        {file && status !== "uploading" && status !== "success" && (
          <button
            type="submit"
            className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold hover:bg-indigo-500 transition-all text-white"
          >
            <Upload className="h-3.5 w-3.5" />
            Upload File
          </button>
        )}

        {status === "uploading" && (
          <div className="flex items-center justify-center gap-2 text-xs text-zinc-400 py-1">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-400" />
            Uploading & parsing...
          </div>
        )}

        {status === "success" && (
          <div className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-950/20 border border-emerald-800/30 rounded-lg p-2">
            <CheckCircle2 className="h-4 w-4" />
            Uploaded successfully! Ingestion queued.
          </div>
        )}

        {status === "error" && (
          <div className="flex items-start gap-1.5 text-xs text-rose-400 bg-rose-950/20 border border-rose-800/30 rounded-lg p-2">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div className="break-all">{errorMessage}</div>
          </div>
        )}
      </form>
    </div>
  );
}
