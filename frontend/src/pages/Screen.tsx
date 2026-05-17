import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

type Candidate = {
  hs_code: string;
  level: string;
  chapter: string;
  title: string;
  score: number;
  score_components: Record<string, number>;
};

type SanctionMatch = {
  source: string;
  source_record_id: string;
  description: string;
  similarity: number;
  hs_code_overlap: string[];
  restriction_type: string | null;
  provenance_url: string | null;
};

type RuleMatch = {
  rule_id: number;
  rule_name: string;
  phrase: string;
  phrase_similarity: number;
  threshold: number;
  delta_above_threshold: number;
  conditions_satisfied: boolean;
};

type ScreenResponse = {
  shipment_id: string;
  engine_version: string;
  hs_classification: {
    top_candidates: Candidate[];
    chapter_distribution: Record<string, number>;
    confidence_metrics: Record<string, number | boolean | null>;
  };
  sanction_matches: SanctionMatch[];
  rule_matches: RuleMatch[];
  extracted_entities: Record<string, unknown>;
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

export default function Screen() {
  const [commodity, setCommodity] = useState("");
  const [cargo, setCargo] = useState("");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [externalRef, setExternalRef] = useState("");

  const screen = useMutation({
    mutationFn: () =>
      api.post<ScreenResponse>("/api/v1/screen", {
        external_ref: externalRef || null,
        commodity_text: commodity,
        cargo_text: cargo || null,
        origin_iso: origin || null,
        destination_iso: destination || null,
      }),
  });

  const result = screen.data;

  return (
    <div className="grid gap-4">
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Screen a single shipment
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-xs text-slate-500">Commodity text *</span>
            <input
              className="border rounded px-2 py-1"
              placeholder="e.g. stainless steel screws"
              value={commodity}
              onChange={(e) => setCommodity(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-xs text-slate-500">Cargo / packing text (optional)</span>
            <input
              className="border rounded px-2 py-1"
              placeholder="e.g. wooden crates"
              value={cargo}
              onChange={(e) => setCargo(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Origin (ISO-2)</span>
            <input
              className="border rounded px-2 py-1 font-mono uppercase"
              maxLength={2}
              value={origin}
              onChange={(e) => setOrigin(e.target.value.toUpperCase())}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Destination (ISO-2)</span>
            <input
              className="border rounded px-2 py-1 font-mono uppercase"
              maxLength={2}
              value={destination}
              onChange={(e) => setDestination(e.target.value.toUpperCase())}
            />
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-xs text-slate-500">External reference (optional)</span>
            <input
              className="border rounded px-2 py-1"
              value={externalRef}
              onChange={(e) => setExternalRef(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
            disabled={!commodity || screen.isPending}
            onClick={() => screen.mutate()}
          >
            {screen.isPending ? "Screening…" : "Screen shipment"}
          </button>
          {screen.isError && (
            <span className="text-xs text-red-700">{(screen.error as Error).message}</span>
          )}
          {result && (
            <Link
              to={`/results/${result.shipment_id}`}
              className="text-xs text-blue-700 hover:underline"
            >
              View permanent result page →
            </Link>
          )}
        </div>
      </section>

      {result && (
        <>
          <section className="bg-white border rounded-lg p-4 shadow-sm">
            <h3 className="text-sm uppercase text-slate-500 mb-2">
              HS Classification (top candidates)
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500">
                  <th>HS Code</th>
                  <th>Level</th>
                  <th>Title</th>
                  <th>Score</th>
                  <th>Components</th>
                </tr>
              </thead>
              <tbody>
                {result.hs_classification.top_candidates.map((c) => (
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
            <h3 className="text-sm uppercase text-slate-500 mb-2">Sanction matches</h3>
            {result.sanction_matches.length === 0 ? (
              <p className="text-slate-500 text-sm">No sanction matches.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-slate-500">
                    <th>Source</th>
                    <th>ID</th>
                    <th>Description</th>
                    <th>Similarity</th>
                    <th>HS overlap</th>
                    <th>Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {result.sanction_matches.map((m) => (
                    <tr key={m.source_record_id + m.source} className="border-t align-top">
                      <td className="py-1 font-mono">{m.source}</td>
                      <td className="font-mono text-xs">{m.source_record_id}</td>
                      <td className="max-w-md truncate" title={m.description}>
                        {m.description}
                      </td>
                      <td className="font-mono">{m.similarity.toFixed(3)}</td>
                      <td className="font-mono text-xs">{m.hs_code_overlap.join(", ") || "—"}</td>
                      <td>
                        {m.provenance_url ? (
                          <a
                            className="text-blue-700 hover:underline text-xs"
                            href={m.provenance_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            link
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="bg-white border rounded-lg p-4 shadow-sm">
            <h3 className="text-sm uppercase text-slate-500 mb-2">Rule matches</h3>
            {result.rule_matches.length === 0 ? (
              <p className="text-slate-500 text-sm">No rule matches.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-slate-500">
                    <th>Rule</th>
                    <th>Phrase</th>
                    <th>Sim.</th>
                    <th>Δ</th>
                    <th>Conds</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rule_matches.map((r) => (
                    <tr key={r.rule_id} className="border-t">
                      <td className="py-1">{r.rule_name}</td>
                      <td className="max-w-md truncate" title={r.phrase}>
                        {r.phrase}
                      </td>
                      <td className="font-mono">{r.phrase_similarity.toFixed(3)}</td>
                      <td
                        className={
                          "font-mono " +
                          (r.delta_above_threshold >= 0 ? "text-emerald-700" : "text-slate-500")
                        }
                      >
                        {r.delta_above_threshold.toFixed(3)}
                      </td>
                      <td>{r.conditions_satisfied ? "✓" : "✗"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="bg-white border rounded-lg p-4 shadow-sm">
            <h3 className="text-sm uppercase text-slate-500 mb-2">Confidence</h3>
            <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">
              {JSON.stringify(result.hs_classification.confidence_metrics, null, 2)}
            </pre>
          </section>

          <section className="bg-white border rounded-lg p-4 shadow-sm">
            <h3 className="text-sm uppercase text-slate-500 mb-2">Latency (ms)</h3>
            <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto">
              {JSON.stringify(result.latency_ms, null, 2)}
            </pre>
          </section>
        </>
      )}
    </div>
  );
}
