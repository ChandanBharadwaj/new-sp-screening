import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

type Rule = {
  id: number;
  name: string;
  phrase: string;
  threshold: number;
  conditions: Record<string, unknown> | null;
  origin_iso: string | null;
  destination_iso: string | null;
  active: boolean;
  version: number;
  created_by: string | null;
  created_at: string | null;
};

type TestResp = {
  phrase_similarity: number;
  threshold: number;
  delta_above_threshold: number;
};

const EMPTY: Partial<Rule> & { conditions_json: string } = {
  name: "",
  phrase: "",
  threshold: 0.5,
  origin_iso: "",
  destination_iso: "",
  active: true,
  conditions_json: "",
};

export default function RuleManager() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<typeof EMPTY>(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [testText, setTestText] = useState("");
  const [testResp, setTestResp] = useState<TestResp | null>(null);

  const rules = useQuery({
    queryKey: ["rules"],
    queryFn: () => api.get<{ items: Rule[] }>("/api/v1/rules"),
  });

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: draft.name,
        phrase: draft.phrase,
        threshold: Number(draft.threshold),
        conditions: draft.conditions_json ? JSON.parse(draft.conditions_json) : null,
        origin_iso: draft.origin_iso || null,
        destination_iso: draft.destination_iso || null,
        active: draft.active,
      };
      if (editId) return api.post<Rule>(`/api/v1/rules/${editId}`, body); // PUT via plain fetch below
      return api.post<Rule>("/api/v1/rules", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      setDraft(EMPTY);
      setEditId(null);
    },
  });

  // Override PUT since our api.client only has POST/GET helpers.
  const saveEdit = async () => {
    if (!editId) return save.mutate();
    const body = {
      name: draft.name,
      phrase: draft.phrase,
      threshold: Number(draft.threshold),
      conditions: draft.conditions_json ? JSON.parse(draft.conditions_json) : null,
      origin_iso: draft.origin_iso || null,
      destination_iso: draft.destination_iso || null,
      active: draft.active,
    };
    const r = await fetch(`/api/v1/rules/${editId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    qc.invalidateQueries({ queryKey: ["rules"] });
    setDraft(EMPTY);
    setEditId(null);
  };

  const testDraft = async () => {
    const r = await api.post<TestResp>("/api/v1/rules/test-phrase", {
      phrase: draft.phrase,
      cargo_text: testText,
      threshold: Number(draft.threshold),
    });
    setTestResp(r);
  };

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-2">Rules</h2>
        {rules.isLoading || !rules.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : rules.data.items.length === 0 ? (
          <p className="text-slate-500 text-sm">No rules yet. Create one →</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th>Name</th><th>Phrase</th><th>Thr.</th><th>Route</th><th>Active</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rules.data.items.map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="py-1">{r.name} <span className="text-slate-400 text-xs">v{r.version}</span></td>
                  <td className="max-w-xs truncate" title={r.phrase}>{r.phrase}</td>
                  <td className="font-mono">{r.threshold.toFixed(2)}</td>
                  <td className="font-mono text-xs">{(r.origin_iso ?? "*")} → {(r.destination_iso ?? "*")}</td>
                  <td>{r.active ? "✓" : "—"}</td>
                  <td>
                    <button
                      className="text-xs text-blue-700 hover:underline"
                      onClick={() => {
                        setEditId(r.id);
                        setDraft({
                          name: r.name,
                          phrase: r.phrase,
                          threshold: r.threshold,
                          origin_iso: r.origin_iso ?? "",
                          destination_iso: r.destination_iso ?? "",
                          active: r.active,
                          conditions_json: r.conditions ? JSON.stringify(r.conditions) : "",
                        });
                      }}
                    >edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-3">{editId ? `Edit rule #${editId}` : "New rule"}</h2>
        <div className="grid gap-2 text-sm">
          <label className="text-xs text-slate-500">Name</label>
          <input className="border rounded px-2 py-1" value={draft.name ?? ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <label className="text-xs text-slate-500">Phrase</label>
          <textarea className="border rounded px-2 py-1" rows={3} value={draft.phrase ?? ""} onChange={(e) => setDraft({ ...draft, phrase: e.target.value })} />
          <label className="text-xs text-slate-500">Threshold (0.0 – 1.0)</label>
          <input type="number" min={0} max={1} step={0.01} className="border rounded px-2 py-1 w-24"
                 value={draft.threshold ?? 0.5} onChange={(e) => setDraft({ ...draft, threshold: Number(e.target.value) })} />
          <div className="flex gap-2">
            <div>
              <label className="text-xs text-slate-500">Origin</label>
              <input className="border rounded px-2 py-1 w-20 block" value={draft.origin_iso ?? ""} onChange={(e) => setDraft({ ...draft, origin_iso: e.target.value.toUpperCase() })} />
            </div>
            <div>
              <label className="text-xs text-slate-500">Destination</label>
              <input className="border rounded px-2 py-1 w-20 block" value={draft.destination_iso ?? ""} onChange={(e) => setDraft({ ...draft, destination_iso: e.target.value.toUpperCase() })} />
            </div>
          </div>
          <label className="text-xs text-slate-500">Conditions JSON (optional)</label>
          <textarea className="border rounded px-2 py-1 font-mono text-xs" rows={3}
                    placeholder='{"min_value": 5000, "currency_in": ["USD"]}'
                    value={draft.conditions_json ?? ""} onChange={(e) => setDraft({ ...draft, conditions_json: e.target.value })} />
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.active ?? true} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} /> active</label>
          <button
            className="bg-slate-900 text-white px-3 py-2 rounded text-sm w-fit mt-2"
            onClick={editId ? saveEdit : () => save.mutate()}
            disabled={!draft.name || !draft.phrase}
          >{editId ? "Save new version" : "Create rule"}</button>
        </div>

        <hr className="my-4" />
        <h3 className="text-xs uppercase text-slate-500 mb-2">Test draft phrase</h3>
        <textarea className="border rounded px-2 py-1 w-full" rows={2}
                  placeholder="sample cargo text"
                  value={testText} onChange={(e) => setTestText(e.target.value)} />
        <button
          className="bg-slate-200 px-3 py-1 rounded text-sm mt-2"
          disabled={!draft.phrase || !testText}
          onClick={testDraft}
        >Test</button>
        {testResp && (
          <div className="mt-3 text-sm">
            <div>Similarity: <span className="font-mono">{testResp.phrase_similarity.toFixed(3)}</span></div>
            <div>Threshold: <span className="font-mono">{testResp.threshold.toFixed(2)}</span></div>
            <div>Delta: <span className={"font-mono " + (testResp.delta_above_threshold >= 0 ? "text-emerald-700" : "text-red-700")}>{testResp.delta_above_threshold.toFixed(3)}</span></div>
          </div>
        )}
      </section>
    </div>
  );
}
