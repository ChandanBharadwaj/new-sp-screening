import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  country_pair_applicable: boolean;
  hs_code_overlap: string[];
  restriction_type: string | null;
  provenance_url: string | null;
  score_components: Record<string, number | boolean>;
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

type Detail = {
  result_id: string;
  shipment_id: string;
  engine_version: string;
  shipment: { commodity_text: string; cargo_text: string | null; origin_iso: string | null; destination_iso: string | null };
  hs_classification: {
    top_candidates: Candidate[];
    chapter_distribution: Record<string, number>;
    confidence_metrics: Record<string, number | boolean>;
  };
  sanction_matches: SanctionMatch[];
  rule_matches: RuleMatch[];
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
  const qc = useQueryClient();
  const [hsCorrection, setHsCorrection] = useState("");
  const [noteText, setNoteText] = useState("");

  const q = useQuery({
    queryKey: ["result", id],
    queryFn: () => api.get<Detail>(`/api/v1/results/${id}`),
    enabled: !!id,
  });

  const feedback = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post("/api/v1/feedback", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["result", id] }),
  });

  if (q.isLoading || !q.data) return <p className="text-slate-500">Loading…</p>;
  const d = q.data;
  const top1 = d.hs_classification.top_candidates[0];

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

        <div className="mt-4 flex items-end gap-2">
          <div>
            <label className="text-xs text-slate-500 block">Correct HS code</label>
            <input className="border rounded px-2 py-1 text-sm font-mono w-32" placeholder="620462"
                   value={hsCorrection} onChange={(e) => setHsCorrection(e.target.value)} />
          </div>
          <button
            className="bg-slate-200 px-3 py-1 rounded text-sm"
            disabled={!hsCorrection || feedback.isPending}
            onClick={() =>
              feedback.mutate({
                result_id: d.result_id,
                event_type: "hs_corrected",
                before_value: { hs_code: top1?.hs_code, score: top1?.score },
                after_value: { hs_code: hsCorrection },
              })
            }
          >Submit correction</button>
        </div>
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Sanction matches</h3>
        {d.sanction_matches.length === 0 ? (
          <p className="text-slate-500 text-sm">No sanction matches.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>Source</th><th>ID</th><th>Description</th><th>Similarity</th><th>HS overlap</th><th>Provenance</th><th></th>
              </tr>
            </thead>
            <tbody>
              {d.sanction_matches.map((m) => (
                <tr key={m.source_record_id + m.source} className="border-t align-top">
                  <td className="py-1 font-mono">{m.source}</td>
                  <td className="font-mono text-xs">{m.source_record_id}</td>
                  <td className="max-w-md truncate" title={m.description}>{m.description}</td>
                  <td className="font-mono">{m.similarity.toFixed(3)}</td>
                  <td className="font-mono text-xs">{m.hs_code_overlap.join(", ") || "—"}</td>
                  <td>{m.provenance_url ? <a className="text-blue-700 hover:underline text-xs" href={m.provenance_url} target="_blank" rel="noreferrer">link</a> : "—"}</td>
                  <td>
                    <button className="text-xs text-red-700 hover:underline"
                            onClick={() => feedback.mutate({
                              result_id: d.result_id,
                              event_type: "sanction_dismissed",
                              before_value: { source: m.source, source_record_id: m.source_record_id, similarity: m.similarity },
                            })}>dismiss</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Rule matches</h3>
        {d.rule_matches.length === 0 ? (
          <p className="text-slate-500 text-sm">No rule matches.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>Rule</th><th>Phrase</th><th>Sim.</th><th>Δ</th><th>Conds</th><th></th>
              </tr>
            </thead>
            <tbody>
              {d.rule_matches.map((r) => (
                <tr key={r.rule_id} className="border-t">
                  <td className="py-1">{r.rule_name}</td>
                  <td className="max-w-md truncate" title={r.phrase}>{r.phrase}</td>
                  <td className="font-mono">{r.phrase_similarity.toFixed(3)}</td>
                  <td className={"font-mono " + (r.delta_above_threshold >= 0 ? "text-emerald-700" : "text-slate-500")}>{r.delta_above_threshold.toFixed(3)}</td>
                  <td>{r.conditions_satisfied ? "✓" : "✗"}</td>
                  <td>
                    <button className="text-xs text-red-700 hover:underline"
                            onClick={() => feedback.mutate({
                              result_id: d.result_id,
                              event_type: "rule_dismissed",
                              before_value: { rule_id: r.rule_id, phrase_similarity: r.phrase_similarity },
                            })}>dismiss</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h3 className="text-sm uppercase text-slate-500 mb-2">Note</h3>
        <textarea className="border rounded px-2 py-1 w-full" rows={2}
                  placeholder="Free-text analyst note"
                  value={noteText} onChange={(e) => setNoteText(e.target.value)} />
        <button
          className="mt-2 bg-slate-200 px-3 py-1 rounded text-sm"
          disabled={!noteText}
          onClick={() => {
            feedback.mutate({
              result_id: d.result_id,
              event_type: "escalated",
              notes: noteText,
            });
            setNoteText("");
          }}
        >Save note</button>
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
