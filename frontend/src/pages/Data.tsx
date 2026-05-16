import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type Tab = "training" | "shipments" | "evalruns" | "refdataruns" | "files";

const TABS: { id: Tab; label: string }[] = [
  { id: "training", label: "Training examples" },
  { id: "shipments", label: "Shipments" },
  { id: "evalruns", label: "Eval runs" },
  { id: "refdataruns", label: "Refdata runs" },
  { id: "files", label: "Files on disk" },
];

function Card({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="bg-white border rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

function TrainingExamplesTab() {
  const [source, setSource] = useState<string>("");
  const [q, setQ] = useState("");
  const [chapter, setChapter] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const query = useQuery({
    queryKey: ["data", "training", source, q, chapter, offset],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (source) sp.set("source", source);
      if (q) sp.set("q", q);
      if (chapter) sp.set("chapter", chapter);
      sp.set("limit", String(limit));
      sp.set("offset", String(offset));
      return api.get<{
        items: { id: number; source: string; source_id: string | null; description: string; hs_code: string | null; created_at: string | null }[];
        total: number;
        by_source: Record<string, number>;
      }>("/api/v1/data/training-examples?" + sp.toString());
    },
  });

  return (
    <Card title="Training examples (hs_training_example)">
      <div className="flex flex-wrap items-end gap-2 text-sm mb-3">
        <label className="flex flex-col">
          <span className="text-xs text-slate-500">Source</span>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={source}
            onChange={(e) => { setSource(e.target.value); setOffset(0); }}
          >
            <option value="">all</option>
            {query.data && Object.keys(query.data.by_source).map((s) => (
              <option key={s} value={s}>{s} ({query.data.by_source[s]})</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          <span className="text-xs text-slate-500">Search</span>
          <input className="border rounded px-2 py-1 text-sm w-64" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="description contains…" />
        </label>
        <label className="flex flex-col">
          <span className="text-xs text-slate-500">Chapter</span>
          <input className="border rounded px-2 py-1 text-sm w-20" value={chapter} onChange={(e) => { setChapter(e.target.value); setOffset(0); }} placeholder="62" />
        </label>
        <div className="ml-auto text-xs text-slate-500">
          {query.data && <>showing {offset + 1}–{Math.min(offset + (query.data.items.length), query.data.total)} of {query.data.total.toLocaleString()}</>}
        </div>
      </div>
      {query.isLoading || !query.data ? (
        <p className="text-slate-500">Loading…</p>
      ) : query.data.items.length === 0 ? (
        <p className="text-slate-500 text-sm">No rows. Run the relevant source from <a href="/admin" className="text-blue-700 hover:underline">Admin</a>.</p>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>Source</th><th>Source ID</th><th>HS</th><th>Description</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="py-1 font-mono text-xs">{r.source}</td>
                  <td className="font-mono text-xs">{r.source_id ?? "—"}</td>
                  <td className="font-mono">{r.hs_code ?? "—"}</td>
                  <td className="max-w-2xl truncate" title={r.description}>{r.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center gap-2 mt-3 text-sm">
            <button className="px-3 py-1 bg-slate-200 rounded text-xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>← Prev</button>
            <button className="px-3 py-1 bg-slate-200 rounded text-xs" disabled={offset + limit >= (query.data.total ?? 0)} onClick={() => setOffset(offset + limit)}>Next →</button>
          </div>
        </>
      )}
    </Card>
  );
}

function ShipmentsTab() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const query = useQuery({
    queryKey: ["data", "shipments", q, offset],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (q) sp.set("q", q);
      sp.set("limit", String(limit));
      sp.set("offset", String(offset));
      return api.get<{
        items: { id: string; external_ref: string | null; commodity_text: string; cargo_text: string | null; origin_iso: string | null; destination_iso: string | null; shipment_value: number | null; currency: string | null; created_at: string | null }[];
        total: number;
      }>("/api/v1/data/shipments?" + sp.toString());
    },
  });
  return (
    <Card title="Shipments">
      <div className="flex items-end gap-2 text-sm mb-3">
        <input className="border rounded px-2 py-1 w-64" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="commodity contains…" />
        <div className="ml-auto text-xs text-slate-500">
          {query.data && <>total {query.data.total.toLocaleString()}</>}
        </div>
      </div>
      {query.isLoading || !query.data ? <p className="text-slate-500">Loading…</p> : query.data.items.length === 0 ? <p className="text-slate-500 text-sm">No shipments yet.</p> : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>When</th><th>Ref</th><th>Commodity</th><th>Route</th><th>Value</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="text-slate-600 py-1">{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
                  <td>{r.external_ref ?? "—"}</td>
                  <td className="max-w-md truncate" title={r.commodity_text}>{r.commodity_text}</td>
                  <td className="font-mono text-xs">{(r.origin_iso ?? "??")} → {(r.destination_iso ?? "??")}</td>
                  <td className="font-mono text-xs">{r.shipment_value ? `${r.shipment_value} ${r.currency ?? ""}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center gap-2 mt-3 text-sm">
            <button className="px-3 py-1 bg-slate-200 rounded text-xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>← Prev</button>
            <button className="px-3 py-1 bg-slate-200 rounded text-xs" disabled={offset + limit >= (query.data.total ?? 0)} onClick={() => setOffset(offset + limit)}>Next →</button>
          </div>
        </>
      )}
    </Card>
  );
}

function EvalRunsTab() {
  const query = useQuery({
    queryKey: ["data", "evalruns"],
    queryFn: () => api.get<{ items: { id: number; ran_at: string; classifier: string; split: string; top1_subheading: number | null; top3_subheading: number | null; top1_chapter: number | null; mrr: number | null; p50_ms: number | null; p95_ms: number | null; n_examples: number | null }[] }>("/api/v1/data/eval-runs"),
  });
  return (
    <Card title="Eval runs">
      {query.isLoading || !query.data ? <p className="text-slate-500">Loading…</p> : query.data.items.length === 0 ? <p className="text-slate-500 text-sm">No eval runs yet.</p> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th>Ran</th><th>Classifier</th><th>Split</th><th>top1-sub</th><th>top3-sub</th><th>top1-chap</th><th>MRR</th><th>p50</th><th>p95</th><th>n</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((r) => (
              <tr key={r.id} className="border-t">
                <td className="text-slate-600 py-1">{new Date(r.ran_at).toLocaleString()}</td>
                <td className="font-mono">{r.classifier}</td>
                <td>{r.split}</td>
                <td className="font-mono">{r.top1_subheading?.toFixed(3) ?? "—"}</td>
                <td className="font-mono">{r.top3_subheading?.toFixed(3) ?? "—"}</td>
                <td className="font-mono">{r.top1_chapter?.toFixed(3) ?? "—"}</td>
                <td className="font-mono">{r.mrr?.toFixed(3) ?? "—"}</td>
                <td className="font-mono">{r.p50_ms?.toFixed(0) ?? "—"}</td>
                <td className="font-mono">{r.p95_ms?.toFixed(0) ?? "—"}</td>
                <td className="font-mono">{r.n_examples ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function RefdataRunsTab() {
  const query = useQuery({
    queryKey: ["data", "refdataruns"],
    queryFn: () => api.get<{ items: { id: number; source: string; started_at: string; finished_at: string | null; rows_upserted: number; status: string; error_message: string | null; notes: string | null }[] }>("/api/v1/data/refdata-runs?limit=100"),
    refetchInterval: 3000,
  });
  return (
    <Card title="Refdata runs (live)">
      {query.isLoading || !query.data ? <p className="text-slate-500">Loading…</p> : query.data.items.length === 0 ? <p className="text-slate-500 text-sm">No runs yet.</p> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th>Source</th><th>Started</th><th>Finished</th><th>Rows</th><th>Status</th><th>Error / notes</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((r) => (
              <tr key={r.id} className="border-t align-top">
                <td className="py-1 font-mono">{r.source}</td>
                <td className="text-slate-600 text-xs">{new Date(r.started_at).toLocaleString()}</td>
                <td className="text-slate-600 text-xs">{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                <td className="font-mono">{r.rows_upserted}</td>
                <td>
                  <span className={"px-2 py-0.5 rounded text-xs " + (
                    r.status === "success" ? "bg-emerald-100 text-emerald-800" :
                    r.status === "running" ? "bg-blue-100 text-blue-800 animate-pulse" :
                    r.status === "failed" ? "bg-red-100 text-red-800" :
                    "bg-slate-100 text-slate-600")}>{r.status}</span>
                </td>
                <td className="text-xs text-slate-600">{r.error_message ?? r.notes ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function FilesTab() {
  const query = useQuery({
    queryKey: ["data", "files"],
    queryFn: () => api.get<{ files: { path: string; size_bytes: number; modified_at: number }[]; root: string; total_files: number; total_bytes: number }>("/api/v1/data/files"),
  });
  return (
    <Card title="Files on disk" right={query.data && <span className="text-xs text-slate-500">{query.data.total_files} files · {(query.data.total_bytes / 1024 / 1024).toFixed(1)} MB</span>}>
      {query.isLoading || !query.data ? <p className="text-slate-500">Loading…</p> : query.data.files.length === 0 ? <p className="text-slate-500 text-sm">No source files cached yet.</p> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500"><th>Path</th><th>Size</th><th>Modified</th></tr>
          </thead>
          <tbody>
            {query.data.files.map((f) => (
              <tr key={f.path} className="border-t">
                <td className="py-1 font-mono text-xs">{f.path}</td>
                <td className="font-mono text-xs">{(f.size_bytes / 1024).toFixed(1)} KB</td>
                <td className="text-slate-600 text-xs">{new Date(f.modified_at * 1000).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Data() {
  const [tab, setTab] = useState<Tab>("training");
  return (
    <div className="grid gap-4">
      <div className="flex gap-1 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={"px-3 py-1.5 rounded text-sm " + (tab === t.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200")}
            onClick={() => setTab(t.id)}
          >{t.label}</button>
        ))}
      </div>
      {tab === "training" && <TrainingExamplesTab />}
      {tab === "shipments" && <ShipmentsTab />}
      {tab === "evalruns" && <EvalRunsTab />}
      {tab === "refdataruns" && <RefdataRunsTab />}
      {tab === "files" && <FilesTab />}
    </div>
  );
}
