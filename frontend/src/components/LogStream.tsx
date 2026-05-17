import { useEffect, useRef, useState } from "react";

type LogEntry = { id: number; ts: string | null; level: string; line: string };

type Props = {
  runTable: "refdata_run" | "training_run" | "eval_job";
  runId: number;
  height?: string;
  onDone?: (status: string) => void;
};

export default function LogStream({ runTable, runId, height = "12rem", onDone }: Props) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<string>("running");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Hold onDone in a ref so a fresh closure each render doesn't tear down
  // the EventSource (which would drop log lines).
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    setEntries([]);
    setError(null);
    setStatus("running");
    const url = `/api/v1/jobs/${runTable}/${runId}/stream`;
    const es = new EventSource(url);
    es.addEventListener("log", (ev) => {
      try {
        const entry = JSON.parse((ev as MessageEvent).data) as LogEntry;
        setEntries((prev) => [...prev, entry]);
      } catch {
        /* ignore */
      }
    });
    es.addEventListener("done", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as { status: string };
        setStatus(data.status);
        onDoneRef.current?.(data.status);
      } catch {
        /* ignore */
      }
      es.close();
    });
    es.addEventListener("error", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as { message: string };
        setError(data.message);
      } catch {
        setError("disconnected");
      }
      es.close();
    });
    return () => es.close();
  }, [runTable, runId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries.length]);

  const color = (lvl: string) =>
    lvl === "error" ? "text-red-300" : lvl === "warn" ? "text-amber-300" : "text-slate-100";

  return (
    <div className="border rounded bg-slate-900 text-slate-100">
      <div className="px-3 py-1 text-xs flex items-center gap-2 border-b border-slate-700">
        <span className="font-mono text-slate-400">{runTable}/{runId}</span>
        <span
          className={
            "px-1.5 py-0.5 rounded text-xs " +
            (status === "success"
              ? "bg-emerald-700"
              : status === "failed"
              ? "bg-red-700"
              : "bg-blue-700 animate-pulse")
          }
        >
          {status}
        </span>
        {error && <span className="text-red-400 ml-auto">{error}</span>}
      </div>
      <div
        ref={scrollRef}
        className="font-mono text-xs px-3 py-2 overflow-auto whitespace-pre-wrap"
        style={{ height }}
      >
        {entries.length === 0 ? (
          <div className="text-slate-500">Waiting for output…</div>
        ) : (
          entries.map((e) => (
            <div key={e.id} className={color(e.level)}>
              <span className="text-slate-500">
                {e.ts ? new Date(e.ts).toLocaleTimeString() : ""}
              </span>{" "}
              {e.line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
