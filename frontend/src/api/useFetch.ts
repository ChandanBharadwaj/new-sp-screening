import {
  computed,
  isRef,
  onScopeDispose,
  ref,
  unref,
  watch,
  type ComputedRef,
  type Ref,
} from "vue";

export type Key = readonly unknown[];
export type MaybeRef<T> = T | Ref<T> | ComputedRef<T>;
export type Interval<T> = number | ((data: T | undefined) => number | false);

export interface UseFetchOptions<T> {
  key: MaybeRef<Key>;
  fetcher: (signal: AbortSignal) => Promise<T>;
  enabled?: MaybeRef<boolean>;
  refetchInterval?: Interval<T>;
  initialData?: T;
}

export interface UseFetchResult<T> {
  data: Ref<T | undefined>;
  error: Ref<Error | null>;
  isLoading: ComputedRef<boolean>;
  isFetching: Ref<boolean>;
  refetch: () => Promise<void>;
}

type Entry = { keyStr: () => string; refetch: () => Promise<void> };
const registry = new Set<Entry>();

export function invalidateQueries(prefix: Key): void {
  const prefixStr = JSON.stringify(prefix);
  const trimmed = prefixStr.slice(0, -1); // drop trailing ']' so we can prefix-match array members
  for (const entry of registry) {
    const k = entry.keyStr();
    if (k === prefixStr || k.startsWith(trimmed + ",") || k.startsWith(trimmed + "]")) {
      void entry.refetch();
    }
  }
}

export function useFetch<T>(opts: UseFetchOptions<T>): UseFetchResult<T> {
  const data = ref(opts.initialData) as Ref<T | undefined>;
  const error = ref<Error | null>(null);
  const isFetching = ref(false);
  const isLoading = computed(() => isFetching.value && data.value === undefined);

  let reqId = 0;
  let ctrl: AbortController | null = null;
  let pollHandle: ReturnType<typeof setTimeout> | null = null;

  const keyStr = computed(() => JSON.stringify(unref(opts.key)));
  const enabledRef = computed(() =>
    opts.enabled === undefined ? true : Boolean(unref(opts.enabled))
  );

  function clearPoll() {
    if (pollHandle) {
      clearTimeout(pollHandle);
      pollHandle = null;
    }
  }

  function scheduleNext() {
    clearPoll();
    const ri = opts.refetchInterval;
    if (ri == null) return;
    const ms = typeof ri === "function" ? ri(data.value) : ri;
    if (typeof ms === "number" && ms > 0) {
      pollHandle = setTimeout(() => {
        void run();
      }, ms);
    }
  }

  async function run(): Promise<void> {
    if (!enabledRef.value) return;
    ctrl?.abort();
    ctrl = new AbortController();
    const my = ++reqId;
    isFetching.value = true;
    try {
      const result = await opts.fetcher(ctrl.signal);
      if (my !== reqId) return;
      data.value = result;
      error.value = null;
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      if (my !== reqId) return;
      error.value = e instanceof Error ? e : new Error(String(e));
    } finally {
      if (my === reqId) {
        isFetching.value = false;
        scheduleNext();
      }
    }
  }

  watch(
    [keyStr, enabledRef],
    () => {
      clearPoll();
      void run();
    },
    { immediate: true }
  );

  const entry: Entry = { keyStr: () => keyStr.value, refetch: run };
  registry.add(entry);

  onScopeDispose(() => {
    ctrl?.abort();
    clearPoll();
    registry.delete(entry);
  });

  return { data, error, isLoading, isFetching, refetch: run };
}

// re-export so callers don't have to know about `isRef`
export { isRef };
