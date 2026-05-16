import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

type FileSlot = {
  key: string;
  label: string;
  path: string;
  accept?: string;
  optional?: boolean;
  present: boolean;
  size_bytes: number | null;
};

type ParamDef = {
  type: "int" | "float" | "str";
  default: string | number | null;
  required?: boolean;
  enum?: string[];
};

type Source = {
  source: string;
  label: string;
  kind: "taxonomy" | "labels" | "sanctions" | "derived";
  auto_download: boolean;
  publisher_url: string | null;
  files: FileSlot[];
  params_schema: Record<string, ParamDef>;
  depends_on: string[];
  row_count: number;
  ready_to_run: boolean;
  last_run: {
    id: number;
    started_at: string | null;
    finished_at: string | null;
    rows_upserted: number | null;
    status: string;
    error_message: string | null;
  } | null;
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

function ParamForm({
  schema,
  values,
  onChange,
}: {
  schema: Record<string, ParamDef>;
  values: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
}) {
  const entries = Object.entries(schema);
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {entries.map(([k, def]) => (
        <label key={k} className="text-xs flex flex-col">
          <span className="text-slate-500">{k}{def.required && " *"}</span>
          {def.enum ? (
            <select
              className="border rounded px-2 py-1 text-sm"
              value={values[k] ?? String(def.default ?? "")}
              onChange={(e) => onChange({ ...values, [k]: e.target.value })}
            >
              {def.enum.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          ) : (
            <input
              className="border rounded px-2 py-1 text-sm w-24"
              placeholder={def.default != null ? String(def.default) : ""}
              value={values[k] ?? ""}
              onChange={(e) => onChange({ ...values, [k]: e.target.value })}
            />
          )}
        </label>
      ))}
    </div>
  );
}

function coerceParams(schema: Record<string, ParamDef>, values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, def] of Object.entries(schema)) {
    const raw = values[k];
    if (raw === undefined || raw === "") {
      if (def.default !== null && def.default !== undefined) out[k] = def.default;
      continue;
    }
    if (def.type === "int") out[k] = parseInt(raw, 10);
    else if (def.type === "float") out[k] = parseFloat(raw);
    else out[k] = raw;
  }
  return out;
}

function SourceCard({ source }: { source: Source }) {
  const qc = useQueryClient();
  const [params, setParams] = useState<Record<string, string>>({});

  const run = useMutation({
    mutationFn: () =>
      api.post("/api/v1/admin/refdata/" + source.source + "/run", {
        params: coerceParams(source.params_schema, params),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "sources"] }),
  });

  const upload = useMutation({
    mutationFn: async (args: { key: string; file: File }) => {
      const form = new FormData();
      form.append("file", args.file);
      return api.postForm(
        "/api/v1/admin/refdata/" + source.source + "/upload?key=" + args.key,
        form
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "sources"] }),
  });

  const lr = source.last_run;
  const progressPct =
    lr?.rows_upserted && source.row_count > 0 && lr.status === "running"
      ? Math.min(100, Math.round(100 * (lr.rows_upserted / Math.max(source.row_count, lr.rows_upserted))))
      : null;

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold">{source.label}</h3>
          <div className="text-xs text-slate-500 font-mono mt-0.5">
            {source.source} · kind={source.kind}
            {source.depends_on.length > 0 && <> · depends on {source.depends_on.join(", ")}</>}
            {source.publisher_url && (
              <> · <a className="text-blue-700 hover:underline" href={source.publisher_url} target="_blank" rel="noreferrer">publisher</a></>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {lr ? <StatusBadge status={lr.status} /> : <StatusBadge status="never_run" />}
          <span className="text-slate-500">rows: <span className="font-mono">{source.row_count.toLocaleString()}</span></span>
        </div>
      </div>

      {source.files.length > 0 && (
        <div className="mt-3 grid gap-2 text-sm">
          {source.files.map((f) => (
            <div key={f.key} className="flex items-center gap-3">
              <span className="w-40 text-slate-500 text-xs">{f.label}{f.optional && " (optional)"}</span>
              {f.present ? (
                <span className="text-emerald-700 text-xs">
                  ✓ {f.path} ({Math.round((f.size_bytes ?? 0) / 1024)} KB)
                </span>
              ) : (
                <span className="text-slate-400 text-xs">{f.path} (not uploaded)</span>
              )}
              <label className="ml-auto text-xs text-blue-700 hover:underline cursor-pointer">
                Upload
                <input
                  type="file"
                  className="hidden"
                  accept={f.accept}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) upload.mutate({ key: f.key, file });
                  }}
                />
              </label>
            </div>
          ))}
        </div>
      )}

      <ParamForm schema={source.params_schema} values={params} onChange={setParams} />

      <div className="mt-3 flex items-center gap-3">
        <button
          className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
          disabled={!source.ready_to_run || run.isPending}
          onClick={() => run.mutate()}
        >
          {lr?.status === "running" ? "Running…" : "Run"}
        </button>
        {!source.ready_to_run && (
          <span className="text-xs text-amber-700">Upload required files first.</span>
        )}
        {run.isError && <span className="text-xs text-red-700">{(run.error as Error).message}</span>}
        {progressPct !== null && (
          <div className="flex items-center gap-2 ml-2">
            <div className="w-32 h-2 bg-slate-200 rounded">
              <div className="h-2 bg-emerald-500 rounded" style={{ width: progressPct + "%" }} />
            </div>
            <span className="text-xs font-mono">{lr?.rows_upserted}</span>
          </div>
        )}
        {lr?.status === "running" && progressPct === null && (
          <span className="text-xs text-blue-700">
            running…
            {lr.rows_upserted ? ` ${lr.rows_upserted} rows` : ""}
          </span>
        )}
      </div>

      {lr?.error_message && (
        <pre className="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto">{lr.error_message}</pre>
      )}

      {lr?.finished_at && (
        <div className="mt-2 text-xs text-slate-500">
          last finished: {new Date(lr.finished_at).toLocaleString()} · {lr.rows_upserted ?? 0} rows
        </div>
      )}
    </div>
  );
}

export default function Admin() {
  const qc = useQueryClient();
  const sources = useQuery({
    queryKey: ["admin", "sources"],
    queryFn: () => api.get<{ sources: Source[] }>("/api/v1/admin/refdata/sources"),
    refetchInterval: 3000,
  });

  const runAll = useMutation({
    mutationFn: () => api.post("/api/v1/admin/refdata/run-all", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "sources"] }),
  });

  const reset = useMutation({
    mutationFn: (body: { include_rules: boolean; include_results: boolean }) =>
      api.post("/api/v1/admin/refdata/reset", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "sources"] }),
  });

  const [confirmReset, setConfirmReset] = useState(false);
  const [includeRules, setIncludeRules] = useState(false);
  const [includeResults, setIncludeResults] = useState(true);

  const grouped: Record<string, Source[]> = {};
  for (const s of sources.data?.sources ?? []) {
    grouped[s.kind] = grouped[s.kind] ?? [];
    grouped[s.kind].push(s);
  }

  const kindLabels: Record<string, string> = {
    taxonomy: "HS taxonomy",
    labels: "Labeled training data",
    derived: "Derived (depend on data above)",
    sanctions: "Sanctions & controlled goods",
  };
  const kindOrder = ["taxonomy", "labels", "derived", "sanctions"];

  return (
    <div className="grid gap-4">
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-lg font-semibold">Data ingestion</h2>
        <p className="text-sm text-slate-600 mt-1">
          Trigger each refdata loader from the UI. Files the publisher does not auto-serve are
          uploaded here once and persist under <code className="font-mono">./data/</code>.
          Reset truncates ingested data tables but keeps source files on disk so you can re-run
          any loader without re-downloading.
        </p>
        <div className="flex flex-wrap gap-2 mt-3">
          <button
            className="bg-emerald-700 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
            disabled={runAll.isPending}
            onClick={() => runAll.mutate()}
          >Run all ready sources</button>
          {!confirmReset ? (
            <button
              className="bg-red-700 text-white px-4 py-2 rounded text-sm ml-auto"
              onClick={() => setConfirmReset(true)}
            >Reset data…</button>
          ) : (
            <div className="ml-auto flex items-center gap-3 bg-red-50 border border-red-300 rounded px-3 py-2">
              <span className="text-xs text-red-800">Truncate ingested tables?</span>
              <label className="text-xs flex items-center gap-1">
                <input type="checkbox" checked={includeResults} onChange={(e) => setIncludeResults(e.target.checked)} /> screening results
              </label>
              <label className="text-xs flex items-center gap-1">
                <input type="checkbox" checked={includeRules} onChange={(e) => setIncludeRules(e.target.checked)} /> rules
              </label>
              <button
                className="bg-red-700 text-white px-2 py-1 rounded text-xs"
                onClick={() => {
                  reset.mutate({ include_rules: includeRules, include_results: includeResults });
                  setConfirmReset(false);
                }}
              >Confirm</button>
              <button className="text-xs text-slate-600" onClick={() => setConfirmReset(false)}>Cancel</button>
            </div>
          )}
        </div>
        {(runAll.data || reset.data) && (
          <pre className="mt-3 text-xs bg-slate-50 p-2 rounded overflow-auto">
            {JSON.stringify(runAll.data ?? reset.data, null, 2)}
          </pre>
        )}
      </section>

      {sources.isLoading || !sources.data ? (
        <p className="text-slate-500">Loading sources…</p>
      ) : (
        kindOrder
          .filter((k) => grouped[k]?.length)
          .map((k) => (
            <div key={k}>
              <h3 className="text-sm uppercase tracking-wide text-slate-500 mb-2">{kindLabels[k]}</h3>
              <div className="grid gap-3">
                {grouped[k].map((s) => (
                  <SourceCard key={s.source} source={s} />
                ))}
              </div>
            </div>
          ))
      )}
    </div>
  );
}
