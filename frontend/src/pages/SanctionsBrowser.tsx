import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type Source = { source: string; count: number };
type Cell = { origin_iso: string; destination_iso: string; count: number };
type Item = {
  id: number;
  source: string;
  source_record_id: string;
  description: string;
  hs_codes: string[];
  restriction_type: string | null;
  provenance_url: string | null;
  origin_iso: string | null;
  destination_iso: string | null;
};

export default function SanctionsBrowser() {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");

  const sources = useQuery({
    queryKey: ["sanctions", "sources"],
    queryFn: () => api.get<{ sources: Source[] }>("/api/v1/sanctions/sources"),
  });

  const heatmap = useQuery({
    queryKey: ["sanctions", "heatmap"],
    queryFn: () => api.get<{ cells: Cell[] }>("/api/v1/sanctions/heatmap"),
  });

  const items = useQuery({
    queryKey: ["sanctions", "by-pair", origin, destination],
    queryFn: () =>
      api.get<{ items: Item[] }>(
        `/api/v1/sanctions/by-country-pair?${origin ? `origin=${origin}` : ""}${
          destination ? `&destination=${destination}` : ""
        }`
      ),
  });

  const origins = Array.from(new Set((heatmap.data?.cells ?? []).map((c) => c.origin_iso))).sort();
  const destinations = Array.from(new Set((heatmap.data?.cells ?? []).map((c) => c.destination_iso))).sort();
  const heatLookup = new Map<string, number>();
  for (const c of heatmap.data?.cells ?? []) heatLookup.set(`${c.origin_iso}>${c.destination_iso}`, c.count);
  const maxCount = Math.max(1, ...((heatmap.data?.cells ?? []).map((c) => c.count)));

  return (
    <div className="grid gap-4">
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-2">Sources</h2>
        {sources.isLoading || !sources.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : sources.data.sources.length === 0 ? (
          <p className="text-slate-500 text-sm">
            No sanctions data ingested yet. Run e.g. <code className="text-xs">python -m app.refdata.sanctions.eu_dual_use.ingest --file ./data/sanctions/eu_dual_use_annex_i.xlsx</code>
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {sources.data.sources.map((s) => (
              <span key={s.source} className="px-2 py-1 rounded bg-slate-100 text-sm">
                <span className="font-mono">{s.source}</span>: {s.count.toLocaleString()}
              </span>
            ))}
          </div>
        )}
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-2">Country-pair heatmap</h2>
        {heatmap.isLoading || !heatmap.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : heatmap.data.cells.length === 0 ? (
          <p className="text-slate-500 text-sm">No country rules yet.</p>
        ) : (
          <div className="overflow-auto">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="px-2 py-1 text-slate-500">origin ↓ / dest →</th>
                  {destinations.map((d) => (
                    <th key={d} className="px-2 py-1 font-mono">{d}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {origins.map((o) => (
                  <tr key={o}>
                    <td className="px-2 py-1 font-mono text-slate-700">{o}</td>
                    {destinations.map((d) => {
                      const n = heatLookup.get(`${o}>${d}`) ?? 0;
                      const alpha = n > 0 ? 0.15 + 0.85 * (n / maxCount) : 0;
                      return (
                        <td
                          key={d}
                          className="px-2 py-1 text-center cursor-pointer"
                          style={{ background: n > 0 ? `rgba(220,38,38,${alpha})` : undefined }}
                          onClick={() => {
                            setOrigin(o === "*" ? "" : o);
                            setDestination(d === "*" ? "" : d);
                          }}
                          title={n > 0 ? `${n} rules` : ""}
                        >
                          {n > 0 ? n : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm uppercase text-slate-500">Sanction records</h2>
          <input
            className="border rounded px-2 py-1 text-sm w-20 ml-auto"
            placeholder="origin"
            value={origin}
            onChange={(e) => setOrigin(e.target.value.toUpperCase())}
          />
          <input
            className="border rounded px-2 py-1 text-sm w-20"
            placeholder="dest"
            value={destination}
            onChange={(e) => setDestination(e.target.value.toUpperCase())}
          />
        </div>
        {items.isLoading || !items.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : items.data.items.length === 0 ? (
          <p className="text-slate-500 text-sm">No matching records.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>Source</th><th>ID</th><th>Description</th><th>HS</th><th>Type</th><th>Route</th><th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {items.data.items.slice(0, 200).map((it) => (
                <tr key={it.id} className="border-t align-top">
                  <td className="py-1 font-mono">{it.source}</td>
                  <td className="font-mono text-xs">{it.source_record_id}</td>
                  <td className="max-w-md truncate" title={it.description}>{it.description}</td>
                  <td className="font-mono text-xs">{it.hs_codes.join(", ")}</td>
                  <td>{it.restriction_type ?? "—"}</td>
                  <td className="font-mono text-xs">{(it.origin_iso ?? "*")} → {(it.destination_iso ?? "*")}</td>
                  <td>{it.provenance_url ? <a className="text-blue-700 hover:underline text-xs" href={it.provenance_url} target="_blank" rel="noreferrer">link</a> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
