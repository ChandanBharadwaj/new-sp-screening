import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import LogStream from "../components/LogStream";

type TrainingRunRow = {
  id: number;
  kind: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  params: Record<string, unknown> | null;
  artifact_path: string | null;
  dataset_csv_path: string | null;
  metrics: {
    dataset?: { n_queries: number; n_rows: number };
    training_time_ms?: number;
    ndcg?: Record<string, number>;
  } | null;
};

type EvalJobRow = {
  id: number;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  classifier: string;
  split: string;
  limit_n: number | null;
  eval_run_id: number | null;
};

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "success"
      ? "bg-emerald-100 text-emerald-800"
      : status === "running"
      ? "bg-blue-100 text-blue-800 animate-pulse"
      : status === "failed"
      ? "bg-red-100 text-red-800"
      : "bg-slate-100 text-slate-600";
  return <span className={"px-2 py-0.5 rounded text-xs " + cls}>{status}</span>;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border rounded-lg p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function TrainLtrCard() {
  const qc = useQueryClient();
  const [gold, setGold] = useState("eval/gold/splits/train.jsonl");
  const [limit, setLimit] = useState<string>("");

  const runs = useQuery({
    queryKey: ["training", "runs"],
    queryFn: () => api.get<{ runs: TrainingRunRow[] }>("/api/v1/training/runs"),
    refetchInterval: (q) => {
      const data = q.state.data as { runs: TrainingRunRow[] } | undefined;
      return data?.runs.some((r) => r.status === "running") ? 3000 : 15000;
    },
  });

  const startTrain = useMutation({
    mutationFn: () =>
      api.post<{ enqueued_job_id: string }>("/api/v1/training/ltr/run", {
        gold: gold || null,
        limit: limit ? parseInt(limit, 10) : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training", "runs"] }),
  });

  const latest = runs.data?.runs[0];
  const running = runs.data?.runs.find((r) => r.status === "running");

  return (
    <Card title="Train LTR ranker">
      <p className="text-xs text-slate-500 mb-3">
        Builds the LTR feature dataset from <code>eval/gold/splits/train.jsonl</code> and
        fits a LightGBM lambdarank model into <code>artifacts/ltr.txt</code>. The pipeline
        automatically picks up the new model on the next request.
      </p>
      <div className="grid grid-cols-2 gap-3 text-sm mb-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Gold split path</span>
          <input
            className="border rounded px-2 py-1 font-mono"
            value={gold}
            onChange={(e) => setGold(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Limit (optional, for smoke runs)</span>
          <input
            className="border rounded px-2 py-1 font-mono"
            placeholder="e.g. 50"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
          />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
          disabled={startTrain.isPending || !!running}
          onClick={() => startTrain.mutate()}
        >
          {running ? "Running…" : "Train LTR"}
        </button>
        {startTrain.isError && (
          <span className="text-xs text-red-700">{(startTrain.error as Error).message}</span>
        )}
      </div>

      {running && (
        <div className="mt-3">
          <LogStream
            runTable="training_run"
            runId={running.id}
            onDone={() => qc.invalidateQueries({ queryKey: ["training", "runs"] })}
          />
        </div>
      )}

      {latest && (
        <div className="mt-4 text-sm">
          <h3 className="text-xs uppercase text-slate-500 mb-1">Latest run</h3>
          <div className="flex items-center gap-3 text-sm">
            <StatusBadge status={latest.status} />
            <span className="text-slate-500">
              started {latest.started_at ? new Date(latest.started_at).toLocaleString() : "—"}
            </span>
          </div>
          {latest.artifact_path && (
            <div className="text-xs text-slate-600 mt-1">
              artifact: <span className="font-mono">{latest.artifact_path}</span>
            </div>
          )}
          {latest.metrics && (
            <pre className="text-xs bg-slate-50 p-2 mt-2 rounded overflow-auto">
              {JSON.stringify(latest.metrics, null, 2)}
            </pre>
          )}
          {latest.error_message && (
            <pre className="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto">
              {latest.error_message}
            </pre>
          )}
        </div>
      )}

      {runs.data && runs.data.runs.length > 1 && (
        <details className="mt-3">
          <summary className="text-xs text-slate-500 cursor-pointer">
            Previous runs ({runs.data.runs.length - 1})
          </summary>
          <table className="w-full text-xs mt-2">
            <thead className="text-left text-slate-500">
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Artifact</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.runs.slice(1).map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="font-mono">{r.id}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                  <td>{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                  <td className="font-mono">{r.artifact_path ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}

function RunEvalCard() {
  const qc = useQueryClient();
  const [classifier, setClassifier] = useState<"pipeline" | "baseline_noop">("pipeline");
  const [split, setSplit] = useState<"train" | "dev" | "test">("test");
  const [limit, setLimit] = useState<string>("");

  const jobs = useQuery({
    queryKey: ["eval", "jobs"],
    queryFn: () => api.get<{ jobs: EvalJobRow[] }>("/api/v1/eval/jobs"),
    refetchInterval: (q) => {
      const data = q.state.data as { jobs: EvalJobRow[] } | undefined;
      return data?.jobs.some((j) => j.status === "running") ? 3000 : 15000;
    },
  });

  const startEval = useMutation({
    mutationFn: () =>
      api.post<{ enqueued_job_id: string }>("/api/v1/eval/run", {
        classifier,
        split,
        limit: limit ? parseInt(limit, 10) : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["eval", "jobs"] }),
  });

  const latest = jobs.data?.jobs[0];
  const running = jobs.data?.jobs.find((j) => j.status === "running");

  return (
    <Card title="Run eval">
      <p className="text-xs text-slate-500 mb-3">
        Runs the full eval harness against a gold split and writes an{" "}
        <code>eval_run</code> row.{" "}
        <Link to="/status" className="text-blue-700 hover:underline">
          See results on /status →
        </Link>
      </p>
      <div className="grid grid-cols-3 gap-3 text-sm mb-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Classifier</span>
          <select
            className="border rounded px-2 py-1 font-mono"
            value={classifier}
            onChange={(e) => setClassifier(e.target.value as typeof classifier)}
          >
            <option value="pipeline">pipeline</option>
            <option value="baseline_noop">baseline_noop</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Split</span>
          <select
            className="border rounded px-2 py-1 font-mono"
            value={split}
            onChange={(e) => setSplit(e.target.value as typeof split)}
          >
            <option value="test">test</option>
            <option value="dev">dev</option>
            <option value="train">train</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Limit (optional)</span>
          <input
            className="border rounded px-2 py-1 font-mono"
            placeholder="e.g. 50"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
          />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
          disabled={startEval.isPending || !!running}
          onClick={() => startEval.mutate()}
        >
          {running ? "Running…" : "Run eval"}
        </button>
        {startEval.isError && (
          <span className="text-xs text-red-700">{(startEval.error as Error).message}</span>
        )}
      </div>

      {running && (
        <div className="mt-3">
          <LogStream
            runTable="eval_job"
            runId={running.id}
            onDone={() => qc.invalidateQueries({ queryKey: ["eval", "jobs"] })}
          />
        </div>
      )}

      {jobs.data && jobs.data.jobs.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs uppercase text-slate-500 mb-2">Recent jobs</h3>
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Classifier</th>
                <th>Split</th>
                <th>Limit</th>
                <th>Started</th>
                <th>Eval run</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.jobs.map((j) => (
                <tr key={j.id} className={"border-t " + (j === latest ? "font-medium" : "")}>
                  <td className="font-mono">{j.id}</td>
                  <td><StatusBadge status={j.status} /></td>
                  <td className="font-mono">{j.classifier}</td>
                  <td>{j.split}</td>
                  <td>{j.limit_n ?? "—"}</td>
                  <td>{j.started_at ? new Date(j.started_at).toLocaleString() : "—"}</td>
                  <td className="font-mono">{j.eval_run_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {latest?.error_message && (
            <pre className="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto">
              {latest.error_message}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}

export default function TrainingEval() {
  return (
    <div className="grid gap-4">
      <TrainLtrCard />
      <RunEvalCard />
    </div>
  );
}
