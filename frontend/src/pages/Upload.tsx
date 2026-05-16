import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type UploadResp = { batch_id: string; total_rows: number; status: string };
type BatchStatus = {
  batch_id: string;
  filename: string;
  status: string;
  total_rows: number;
  completed_rows: number;
  failed_rows: number;
};

export default function Upload() {
  const [file, setFile] = useState<File | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("pick a file first");
      const form = new FormData();
      form.append("file", file);
      return api.postForm<UploadResp>("/api/v1/batch/upload", form);
    },
    onSuccess: (r) => setBatchId(r.batch_id),
  });

  const status = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => api.get<BatchStatus>(`/api/v1/batch/${batchId}`),
    enabled: !!batchId,
    refetchInterval: 2000,
  });

  return (
    <div className="grid gap-4">
      <section className="bg-white border rounded-lg p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-3">Upload a shipment CSV</h2>
        <p className="text-sm text-slate-600 mb-4">
          Required column: <code className="bg-slate-100 px-1 rounded">commodity_text</code>.
          Optional: <code className="bg-slate-100 px-1 rounded">cargo_text</code>,
          {" "}<code className="bg-slate-100 px-1 rounded">origin_iso</code>,
          {" "}<code className="bg-slate-100 px-1 rounded">destination_iso</code>,
          {" "}<code className="bg-slate-100 px-1 rounded">external_ref</code>.
        </p>
        <div className="flex items-center gap-3">
          <input
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <button
            className="bg-slate-900 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
            disabled={!file || upload.isPending}
            onClick={() => upload.mutate()}
          >
            {upload.isPending ? "Uploading…" : "Upload"}
          </button>
        </div>
        {upload.isError && <p className="text-red-600 text-sm mt-2">{(upload.error as Error).message}</p>}
      </section>

      {batchId && (
        <section className="bg-white border rounded-lg p-6 shadow-sm">
          <h2 className="text-lg font-semibold mb-3">Batch progress</h2>
          {status.isLoading || !status.data ? (
            <p className="text-slate-500">Loading…</p>
          ) : (
            <div className="text-sm">
              <div className="mb-2">Batch <code className="bg-slate-100 px-1 rounded">{status.data.batch_id}</code></div>
              <div className="mb-2">Status: <strong>{status.data.status}</strong></div>
              <div className="mb-2">Completed: {status.data.completed_rows} / {status.data.total_rows} (failed: {status.data.failed_rows})</div>
              <div className="w-full h-3 bg-slate-200 rounded overflow-hidden">
                <div
                  className="h-3 bg-emerald-500"
                  style={{ width: ((100 * (status.data.completed_rows + status.data.failed_rows)) / Math.max(status.data.total_rows, 1)) + "%" }}
                />
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
