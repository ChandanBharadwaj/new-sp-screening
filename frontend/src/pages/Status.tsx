import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type SystemStatus = {
  engine_version: string;
  uptime_seconds: number;
  postgres: { reachable: boolean };
  redis: { reachable: boolean };
};

type ModelInfo = {
  name: string;
  loaded: boolean;
  load_time_ms: number | null;
  last_call_ms: number | null;
  dim?: number;
  fallback?: boolean;
};

type RefdataSource = {
  source: string;
  command: string;
  last_run: {
    started_at?: string;
    finished_at?: string;
    rows_upserted?: number;
    status: string;
    error_message?: string;
  };
  row_count: number;
};

type EvalRunRow = {
  id: number;
  ran_at: string;
  classifier: string;
  split: string;
  top1_subheading: number | null;
  top3_subheading: number | null;
  top1_chapter: number | null;
  mrr: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  n_examples: number | null;
};

type Batch = {
  batch_id: string;
  filename: string | null;
  status: string;
  total_rows: number;
  completed_rows: number;
  failed_rows: number;
  created_at: string;
};

function Dot({ ok }: { ok: boolean }) {
  return <span className={"inline-block w-2 h-2 rounded-full " + (ok ? "bg-emerald-500" : "bg-red-500")} />;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border rounded-lg p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">{title}</h2>
      {children}
    </section>
  );
}

export default function Status() {
  const sys = useQuery({
    queryKey: ["status", "system"],
    queryFn: () => api.get<SystemStatus>("/api/v1/status/system"),
    refetchInterval: 10000,
  });
  const models = useQuery({
    queryKey: ["status", "models"],
    queryFn: () => api.get<{ models: ModelInfo[] }>("/api/v1/status/models"),
    refetchInterval: 10000,
  });
  const refdata = useQuery({
    queryKey: ["status", "refdata"],
    queryFn: () =>
      api.get<{ sources: RefdataSource[]; totals: { hs_code: number; hs_training_example: number } }>(
        "/api/v1/status/refdata"
      ),
    refetchInterval: 10000,
  });
  const evalRuns = useQuery({
    queryKey: ["status", "eval"],
    queryFn: () =>
      api.get<{ runs: EvalRunRow[]; thresholds: Record<string, number>; latest_pass_fail: Record<string, boolean> | null }>(
        "/api/v1/status/eval"
      ),
    refetchInterval: 10000,
  });
  const batches = useQuery({
    queryKey: ["status", "batches"],
    queryFn: () => api.get<{ batches: Batch[] }>("/api/v1/status/batches"),
    refetchInterval: 5000,
  });

  return (
    <div className="grid gap-4">
      <Card title="System">
        {sys.isLoading || !sys.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><div className="text-slate-500">Engine</div><div className="font-mono">{sys.data.engine_version}</div></div>
            <div><div className="text-slate-500">Uptime</div><div className="font-mono">{sys.data.uptime_seconds}s</div></div>
            <div className="flex items-center gap-2"><Dot ok={sys.data.postgres.reachable} /> Postgres</div>
            <div className="flex items-center gap-2"><Dot ok={sys.data.redis.reachable} /> Redis</div>
          </div>
        )}
      </Card>

      <Card title="Models">
        {models.isLoading || !models.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {models.data.models.map((m) => (
              <div key={m.name} className="border rounded p-3">
                <div className="flex items-center gap-2"><Dot ok={m.loaded} /><span className="font-semibold capitalize">{m.name}</span></div>
                <div className="text-xs text-slate-500 mt-1">Load: {m.load_time_ms ?? "—"}ms</div>
                <div className="text-xs text-slate-500">Last call: {m.last_call_ms ?? "—"}ms</div>
                {m.fallback && <div className="text-xs text-amber-600 mt-1">Using heuristic fallback</div>}
                {m.dim && <div className="text-xs text-slate-500">Dim: {m.dim}</div>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Reference data">
        {refdata.isLoading || !refdata.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : (
          <>
            <div className="mb-3 text-xs text-slate-500">
              hs_code total: <span className="font-mono">{refdata.data.totals.hs_code}</span>
              {" · "}
              hs_training_example total: <span className="font-mono">{refdata.data.totals.hs_training_example}</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500">
                  <th className="py-2">Source</th>
                  <th>Status</th>
                  <th>Last ran</th>
                  <th>Rows</th>
                  <th>Re-run command</th>
                </tr>
              </thead>
              <tbody>
                {refdata.data.sources.map((s) => (
                  <tr key={s.source} className="border-t">
                    <td className="py-2 font-medium">{s.source}</td>
                    <td>
                      <span className={
                        "px-2 py-0.5 rounded text-xs " +
                        (s.last_run.status === "success" ? "bg-emerald-100 text-emerald-800" :
                         s.last_run.status === "running" ? "bg-blue-100 text-blue-800" :
                         s.last_run.status === "failed" ? "bg-red-100 text-red-800" :
                         "bg-slate-100 text-slate-600")
                      }>{s.last_run.status}</span>
                    </td>
                    <td className="text-slate-600">{s.last_run.finished_at ? new Date(s.last_run.finished_at).toLocaleString() : "—"}</td>
                    <td className="font-mono">{s.row_count}</td>
                    <td>
                      <button
                        className="text-xs font-mono bg-slate-100 px-2 py-1 rounded hover:bg-slate-200"
                        onClick={() => navigator.clipboard.writeText(s.command)}
                        title="Copy to clipboard"
                      >{s.command}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      <Card title="Eval">
        {evalRuns.isLoading || !evalRuns.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : evalRuns.data.runs.length === 0 ? (
          <p className="text-slate-500 text-sm">No eval runs yet. Run <code className="text-xs">python -m eval.runners.run_eval --classifier pipeline --split test</code></p>
        ) : (
          <>
            {evalRuns.data.latest_pass_fail && (
              <div className="flex flex-wrap gap-2 mb-3">
                {Object.entries(evalRuns.data.latest_pass_fail).map(([k, v]) => (
                  <span key={k} className={"px-2 py-1 rounded text-xs " + (v ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800")}>{k}: {v ? "PASS" : "FAIL"}</span>
                ))}
              </div>
            )}
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500">
                  <th>Ran</th><th>Classifier</th><th>Split</th><th>Top-1 sub</th><th>Top-3 sub</th><th>Top-1 chap</th><th>MRR</th><th>p95 ms</th>
                </tr>
              </thead>
              <tbody>
                {evalRuns.data.runs.slice(0, 10).map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="text-slate-600">{new Date(r.ran_at).toLocaleString()}</td>
                    <td className="font-mono">{r.classifier}</td>
                    <td>{r.split}</td>
                    <td className="font-mono">{r.top1_subheading?.toFixed(3) ?? "—"}</td>
                    <td className="font-mono">{r.top3_subheading?.toFixed(3) ?? "—"}</td>
                    <td className="font-mono">{r.top1_chapter?.toFixed(3) ?? "—"}</td>
                    <td className="font-mono">{r.mrr?.toFixed(3) ?? "—"}</td>
                    <td className="font-mono">{r.p95_ms?.toFixed(0) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      <Card title="Recent batches">
        {batches.isLoading || !batches.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : batches.data.batches.length === 0 ? (
          <p className="text-slate-500 text-sm">No batch jobs yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>ID</th><th>File</th><th>Status</th><th>Progress</th><th>Created</th>
              </tr>
            </thead>
            <tbody>
              {batches.data.batches.map((b) => {
                const pct = b.total_rows ? Math.round((100 * (b.completed_rows + b.failed_rows)) / b.total_rows) : 0;
                return (
                  <tr key={b.batch_id} className="border-t">
                    <td className="font-mono text-xs">{b.batch_id.slice(0, 8)}</td>
                    <td>{b.filename ?? "—"}</td>
                    <td>{b.status}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-32 h-2 bg-slate-200 rounded"><div className="h-2 bg-emerald-500 rounded" style={{ width: pct + "%" }} /></div>
                        <span className="font-mono text-xs">{b.completed_rows}/{b.total_rows}</span>
                      </div>
                    </td>
                    <td className="text-slate-600">{new Date(b.created_at).toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
