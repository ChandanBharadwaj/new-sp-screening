import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type HsNode = {
  code: string;
  level: number;
  parent_code: string | null;
  chapter: string;
  title: string;
  description: string | null;
  children?: HsNode[];
};

export default function HsBrowser() {
  const [search, setSearch] = useState("");
  const [code, setCode] = useState<string | null>(null);

  const root = useQuery({
    queryKey: ["hs", "tree"],
    queryFn: () => api.get<{ items: HsNode[] }>("/api/v1/hs/tree"),
  });
  const detail = useQuery({
    queryKey: ["hs", code],
    queryFn: () => api.get<HsNode>(`/api/v1/hs/${code}`),
    enabled: !!code,
  });
  const searchRes = useQuery({
    queryKey: ["hs", "search", search],
    queryFn: () => api.get<{ items: HsNode[] }>(`/api/v1/hs/search?q=${encodeURIComponent(search)}`),
    enabled: search.length > 1,
  });

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-2">Browse</h2>
        <input
          className="w-full border rounded px-2 py-1 mb-3 text-sm"
          placeholder="Search HS titles…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search.length > 1 ? (
          searchRes.data?.items.length ? (
            <ul className="text-sm">
              {searchRes.data.items.map((n) => (
                <li key={n.code}>
                  <button className="text-left hover:underline" onClick={() => setCode(n.code)}>
                    <span className="font-mono">{n.code}</span> · {n.title}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-slate-500">No matches.</p>
          )
        ) : root.isLoading ? (
          <p className="text-slate-500">Loading chapters…</p>
        ) : root.data?.items.length === 0 ? (
          <p className="text-slate-500 text-sm">No HS data yet — run <code className="text-xs">python -m app.refdata.hts.ingest</code>.</p>
        ) : (
          <ul className="text-sm">
            {root.data?.items.map((n) => (
              <li key={n.code}>
                <button className="text-left hover:underline" onClick={() => setCode(n.code)}>
                  <span className="font-mono">{n.code}</span> · {n.title}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="bg-white border rounded-lg p-4 shadow-sm">
        <h2 className="text-sm uppercase text-slate-500 mb-2">Detail</h2>
        {!code ? (
          <p className="text-slate-500 text-sm">Pick a code from the left.</p>
        ) : detail.isLoading || !detail.data ? (
          <p className="text-slate-500">Loading…</p>
        ) : (
          <div className="text-sm">
            <h3 className="font-semibold"><span className="font-mono">{detail.data.code}</span> · {detail.data.title}</h3>
            <p className="text-xs text-slate-500 mt-1">Level {detail.data.level} · Chapter {detail.data.chapter}</p>
            {detail.data.description && <p className="mt-2">{detail.data.description}</p>}
            {detail.data.children && detail.data.children.length > 0 && (
              <>
                <h4 className="mt-4 text-xs uppercase text-slate-500">Children</h4>
                <ul>
                  {detail.data.children.map((c) => (
                    <li key={c.code}>
                      <button className="text-left hover:underline" onClick={() => setCode(c.code)}>
                        <span className="font-mono">{c.code}</span> · {c.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
