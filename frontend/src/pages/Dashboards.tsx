import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from "recharts";
import { api } from "../api/client";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border rounded-lg p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">{title}</h2>
      {children}
    </section>
  );
}

export default function Dashboards() {
  const chap = useQuery({
    queryKey: ["dash", "chapter-volume"],
    queryFn: () => api.get<{ items: { chapter: string; count: number }[] }>("/api/v1/dashboards/chapter-volume"),
  });
  const sanctions = useQuery({
    queryKey: ["dash", "sanction-hits"],
    queryFn: () => api.get<{ items: { source: string; count: number }[] }>("/api/v1/dashboards/sanction-hits-by-source"),
  });
  const heat = useQuery({
    queryKey: ["dash", "country-heatmap"],
    queryFn: () => api.get<{ cells: { origin_iso: string; destination_iso: string; count: number }[] }>("/api/v1/dashboards/country-pair-heatmap"),
  });
  const hist = useQuery({
    queryKey: ["dash", "histograms"],
    queryFn: () => api.get<{ top1_score: { bucket: number; count: number }[] }>("/api/v1/dashboards/score-histograms"),
  });
  const trend = useQuery({
    queryKey: ["dash", "override-trend"],
    queryFn: () => api.get<{ items: { chapter: string; rate: number; corrections: number; total: number }[] }>("/api/v1/dashboards/override-rate-trend"),
  });

  return (
    <div className="grid gap-4">
      <Card title="Volume by HS chapter">
        {chap.data && chap.data.items.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chap.data.items.slice(0, 20)}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="chapter" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#0f172a" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-slate-500 text-sm">No screening results yet.</p>
        )}
      </Card>

      <Card title="Sanction hits by source">
        {sanctions.data && sanctions.data.items.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={sanctions.data.items}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="source" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#b91c1c" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-slate-500 text-sm">No sanction hits yet.</p>
        )}
      </Card>

      <Card title="Country-pair heatmap">
        {heat.data && heat.data.cells.length > 0 ? (
          <table className="text-xs">
            <tbody>
              {heat.data.cells.slice(0, 100).map((c, i) => (
                <tr key={i}>
                  <td className="px-2 py-1 font-mono">{c.origin_iso}</td>
                  <td className="px-2 py-1">→</td>
                  <td className="px-2 py-1 font-mono">{c.destination_iso}</td>
                  <td className="px-2 py-1 font-mono">{c.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-slate-500 text-sm">No shipment routes seen yet.</p>
        )}
      </Card>

      <Card title="Top-1 score distribution">
        {hist.data && hist.data.top1_score.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={hist.data.top1_score}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bucket" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#0369a1" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-slate-500 text-sm">No score data yet.</p>
        )}
      </Card>

      <Card title="Override rate by chapter">
        {trend.data && trend.data.items.length > 0 ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trend.data.items}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="chapter" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="rate" stroke="#16a34a" />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-slate-500 text-sm">No feedback yet.</p>
        )}
      </Card>
    </div>
  );
}
