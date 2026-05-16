import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type Detail = {
  result_id: string;
  shipment_id: string;
  engine_version: string;
  shipment: { commodity_text: string; cargo_text: string | null; origin_iso: string | null; destination_iso: string | null };
  hs_classification: {
    top_candidates: Array<{
      hs_code: string;
      level: string;
      chapter: string;
      title: string;
      score: number;
      score_components: Record<string, number>;
    }>;
    chapter_distribution: Record<string, number>;
    confidence_metrics: Record<string, number | boolean>;
  };
  extracted_entities: Record<string, string[] | null>;
  latency_ms: Record<string, number>;
};

function Bar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="w-24 h-2 bg-slate-200 rounded">
      <div className="h-2 bg-slate-700 rounded" style={{ width: pct + "%" }} />
    </div>
  );
}

export default function ResultDetail() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["result", id],
    queryFn: () => api.get<Detail>(`/api/v1/results/${id}`),
    enabled: !!id,
  });

  if (q.isLoading || !q.data) return <p className="text-slate-500">Loading…</p>;
  const d = q.data;
  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Result <code className="text-sm">{d.result_id}</code></h2>
        <Link to="/results" className="text-sm text-blue-700 hover:underline">← back</Link>
      </div>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Shipment</h3>
        <p><strong>Commodity:</strong> {d.shipment.commodity_text}</p>
        {d.shipment.cargo_text && <p><strong>Cargo:</strong> {d.shipment.cargo_text}</p>}
        <p className="text-sm text-slate-600 mt-1">Route: <span className="font-mono">{d.shipment.origin_iso ?? "??"} → {d.shipment.destination_iso ?? "??"}</span></p>
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">HS Classification (top candidates)</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th>HS Code</th><th>Level</th><th>Title</th><th>Score</th><th>Components</th>
            </tr>
          </thead>
          <tbody>
            {d.hs_classification.top_candidates.map((c) => (
              <tr key={c.hs_code} className="border-t align-top">
                <td className="py-2 font-mono">{c.hs_code}</td>
                <td>{c.level}</td>
                <td className="max-w-md">{c.title}</td>
                <td className="font-mono">{c.score.toFixed(3)}</td>
                <td>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    {Object.entries(c.score_components).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2">
                        <span className="text-slate-500 w-24">{k}</span>
                        <Bar value={Number(v)} />
                        <span className="font-mono">{Number(v).toFixed(3)}</span>
                      </div>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Confidence</h3>
        <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">{JSON.stringify(d.hs_classification.confidence_metrics, null, 2)}</pre>
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Extracted entities</h3>
        <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">{JSON.stringify(d.extracted_entities, null, 2)}</pre>
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Latency (ms)</h3>
        <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">{JSON.stringify(d.latency_ms, null, 2)}</pre>
      </section>
    </div>
  );
}
