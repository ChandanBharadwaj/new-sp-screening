import { onScopeDispose, ref, watch, type ComputedRef, type Ref } from "vue";

export type LogEntry = {
  id: number;
  ts: string | null;
  level: string;
  line: string;
};

export interface UseEventSourceOptions {
  url: Ref<string> | ComputedRef<string>;
  onLog?: (entry: LogEntry) => void;
  onDone?: (status: string) => void;
  onError?: (msg: string) => void;
}

export interface UseEventSourceResult {
  status: Ref<string>;
  error: Ref<string | null>;
  close: () => void;
}

export function useEventSource(opts: UseEventSourceOptions): UseEventSourceResult {
  const status = ref<string>("running");
  const error = ref<string | null>(null);
  let es: EventSource | null = null;

  // Keep callbacks in a mutable holder so the handlers always see the
  // latest version without re-opening the connection.
  const handlers = {
    onLog: opts.onLog,
    onDone: opts.onDone,
    onError: opts.onError,
  };

  function close() {
    if (es) {
      es.close();
      es = null;
    }
  }

  function open(url: string) {
    close();
    status.value = "running";
    error.value = null;
    const source = new EventSource(url);
    es = source;
    source.addEventListener("log", (ev) => {
      try {
        const entry = JSON.parse((ev as MessageEvent).data) as LogEntry;
        handlers.onLog?.(entry);
      } catch {
        /* ignore */
      }
    });
    source.addEventListener("done", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as { status: string };
        status.value = data.status;
        handlers.onDone?.(data.status);
      } catch {
        /* ignore */
      }
      close();
    });
    source.addEventListener("error", (ev) => {
      let msg = "disconnected";
      try {
        const data = JSON.parse((ev as MessageEvent).data ?? "{}") as { message?: string };
        if (data.message) msg = data.message;
      } catch {
        /* ignore */
      }
      error.value = msg;
      handlers.onError?.(msg);
      close();
    });
  }

  watch(
    opts.url,
    (next) => {
      open(next);
    },
    { immediate: true }
  );

  onScopeDispose(close);

  return { status, error, close };
}
