import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type Row = {
  result_id: string;
  shipment_id: string;
  external_ref: string | null;
  commodity_text: string;
  origin_iso: string | null;
  destination_iso: string | null;
  top1_hs_code: string | null;
  top1_chapter: string | null;
  top1_score: number | null;
  engine_version: string | null;
  created_at: string;
};

export default function Results() {
  const q = useQuery({
    queryKey: ["results"],
    queryFn: () => api.get<{ items: Row[] }>("/api/v1/results?limit=100"),
    refetchInterval: 5000,
  });

  return (
    <section className="bg-white border rounded-lg p-4 shadow-sm">
      <h2 className="text-lg font-semibold mb-3">Screening results</h2>
      {q.isLoading || !q.data ? (
        <p className="text-slate-500">Loading…</p>
      ) : q.data.items.length === 0 ? (
        <p className="text-slate-500 text-sm">No results yet. Upload a CSV or POST <code>/api/v1/screen</code>.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="py-2">Created</th><th>Ref</th><th>Commodity</th><th>Route</th><th>Top-1 HS</th><th>Score</th><th></th>
            </tr>
          </thead>
          <tbody>
            {q.data.items.map((r) => (
              <tr key={r.result_id} className="border-t">
                <td className="text-slate-600 py-2">{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.external_ref ?? "—"}</td>
                <td className="max-w-md truncate" title={r.commodity_text}>{r.commodity_text}</td>
                <td className="font-mono text-xs">{(r.origin_iso ?? "??")} → {(r.destination_iso ?? "??")}</td>
                <td className="font-mono">{r.top1_hs_code ?? "—"}</td>
                <td className="font-mono">{r.top1_score?.toFixed(3) ?? "—"}</td>
                <td><Link to={`/results/${r.result_id}`} className="text-blue-700 hover:underline">Inspect</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
