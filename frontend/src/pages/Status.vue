<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import Card from "../components/Card.vue";
import Dot from "../components/Dot.vue";
import StalenessBadge from "../components/StalenessBadge.vue";
import RefdataRunButton from "../components/status/RefdataRunButton.vue";
import ThresholdsEditor from "../components/status/ThresholdsEditor.vue";

type SystemStatus = {
  engine_version: string;
  uptime_seconds: number;
  postgres: { reachable: boolean };
  redis: { reachable: boolean };
};

type ModelInfo = {
  name: string;
  loaded: boolean;
  load_time_ms: number | null;
  last_call_ms: number | null;
  dim?: number;
  fallback?: boolean;
};

type Severity = "green" | "amber" | "red" | "gray";

type RefdataSource = {
  source: string;
  command?: string;
  last_run: {
    started_at?: string;
    finished_at?: string;
    rows_upserted?: number;
    status: string;
    error_message?: string;
  };
  row_count: number;
  staleness_days?: number | null;
  staleness_severity?: Severity;
};

type SanctionsStatus = {
  sources: RefdataSource[];
  worst_staleness_severity: Severity;
  totals: { sanctioned_commodity: number; country_rule: number };
};

type EvalRunRow = {
  id: number;
  ran_at: string;
  classifier: string;
  split: string;
  top1_subheading: number | null;
  top3_subheading: number | null;
  top1_chapter: number | null;
  mrr: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  n_examples: number | null;
};

type Batch = {
  batch_id: string;
  filename: string | null;
  status: string;
  total_rows: number;
  completed_rows: number;
  failed_rows: number;
  created_at: string;
};

const sys = useFetch<SystemStatus>({
  key: ["status", "system"],
  refetchInterval: 10000,
  fetcher: () => api.get<SystemStatus>("/api/v1/status/system"),
});
const models = useFetch<{ models: ModelInfo[] }>({
  key: ["status", "models"],
  refetchInterval: 10000,
  fetcher: () => api.get("/api/v1/status/models"),
});
const refdata = useFetch<{
  sources: RefdataSource[];
  totals: { hs_code: number; hs_training_example: number };
}>({
  key: ["status", "refdata"],
  refetchInterval: 10000,
  fetcher: () => api.get("/api/v1/status/refdata"),
});
const sanctions = useFetch<SanctionsStatus>({
  key: ["status", "sanctions"],
  refetchInterval: 10000,
  fetcher: () => api.get("/api/v1/status/sanctions"),
});
const evalRuns = useFetch<{
  runs: EvalRunRow[];
  thresholds: Record<string, number>;
  latest_pass_fail: Record<string, boolean> | null;
}>({
  key: ["status", "eval"],
  refetchInterval: 10000,
  fetcher: () => api.get("/api/v1/status/eval"),
});
const batches = useFetch<{ batches: Batch[] }>({
  key: ["status", "batches"],
  refetchInterval: 5000,
  fetcher: () => api.get("/api/v1/status/batches"),
});

function refdataStatusClass(s: string) {
  return s === "success"
    ? "bg-emerald-100 text-emerald-800"
    : s === "running"
    ? "bg-blue-100 text-blue-800 animate-pulse"
    : s === "failed"
    ? "bg-red-100 text-red-800"
    : "bg-slate-100 text-slate-600";
}

function batchPct(b: Batch) {
  return b.total_rows ? Math.round((100 * (b.completed_rows + b.failed_rows)) / b.total_rows) : 0;
}

const evalRunsTop = computed(() => (evalRuns.data.value?.runs ?? []).slice(0, 10));
</script>

<template>
  <div class="grid gap-4">
    <Card title="System">
      <p v-if="sys.isLoading.value || !sys.data.value" class="text-slate-500">Loading…</p>
      <div v-else class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <div class="text-slate-500">Engine</div>
          <div class="font-mono">{{ sys.data.value.engine_version }}</div>
        </div>
        <div>
          <div class="text-slate-500">Uptime</div>
          <div class="font-mono">{{ sys.data.value.uptime_seconds }}s</div>
        </div>
        <div class="flex items-center gap-2"><Dot :ok="sys.data.value.postgres.reachable" /> Postgres</div>
        <div class="flex items-center gap-2"><Dot :ok="sys.data.value.redis.reachable" /> Redis</div>
      </div>
    </Card>

    <Card title="Models">
      <p v-if="models.isLoading.value || !models.data.value" class="text-slate-500">Loading…</p>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <div v-for="m in models.data.value.models" :key="m.name" class="border rounded p-3">
          <div class="flex items-center gap-2">
            <Dot :ok="m.loaded" /><span class="font-semibold capitalize">{{ m.name }}</span>
          </div>
          <div class="text-xs text-slate-500 mt-1">Load: {{ m.load_time_ms ?? "—" }}ms</div>
          <div class="text-xs text-slate-500">Last call: {{ m.last_call_ms ?? "—" }}ms</div>
          <div v-if="m.fallback" class="text-xs text-amber-600 mt-1">Using heuristic fallback</div>
          <div v-if="m.dim" class="text-xs text-slate-500">Dim: {{ m.dim }}</div>
        </div>
      </div>
    </Card>

    <Card title="Reference data">
      <p v-if="refdata.isLoading.value || !refdata.data.value" class="text-slate-500">Loading…</p>
      <template v-else>
        <div class="mb-3 text-xs text-slate-500 flex items-center gap-3">
          <span>hs_code total: <span class="font-mono">{{ refdata.data.value.totals.hs_code }}</span></span>
          <span>
            hs_training_example total:
            <span class="font-mono">{{ refdata.data.value.totals.hs_training_example }}</span>
          </span>
          <RouterLink class="ml-auto text-blue-700 hover:underline" to="/admin">Manage in Admin →</RouterLink>
        </div>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th class="py-2">Source</th><th>Status</th><th>Last ran</th><th>Rows</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in refdata.data.value.sources" :key="s.source" class="border-t">
              <td class="py-2 font-medium">{{ s.source }}</td>
              <td>
                <span :class="['px-2 py-0.5 rounded text-xs', refdataStatusClass(s.last_run.status)]">
                  {{ s.last_run.status }}
                </span>
              </td>
              <td class="text-slate-600">
                {{ s.last_run.finished_at ? new Date(s.last_run.finished_at).toLocaleString() : "—" }}
                <StalenessBadge
                  v-if="s.staleness_severity"
                  class="ml-2"
                  :days="s.staleness_days ?? null"
                  :severity="s.staleness_severity"
                />
              </td>
              <td class="font-mono">
                {{ s.row_count }}<template v-if="s.last_run.status === 'running' && s.last_run.rows_upserted">
                  ({{ s.last_run.rows_upserted }}…)</template>
              </td>
              <td><RefdataRunButton :source="s.source" /></td>
            </tr>
          </tbody>
        </table>
      </template>
    </Card>

    <Card title="Sanctions sources">
      <p v-if="sanctions.isLoading.value || !sanctions.data.value" class="text-slate-500">Loading…</p>
      <template v-else>
        <div
          v-if="sanctions.data.value.worst_staleness_severity === 'red'"
          class="mb-3 p-3 rounded bg-red-50 border border-red-200 text-sm text-red-800"
        >
          <strong>Stale sanctions data.</strong>
          One or more sanctions sources have not been refreshed in over 30 days.
          Screenings are still running, but their sanction matches may miss recent designations.
          <RouterLink class="underline" to="/admin">Refresh now →</RouterLink>
        </div>
        <div
          v-else-if="sanctions.data.value.worst_staleness_severity === 'amber'"
          class="mb-3 p-3 rounded bg-amber-50 border border-amber-200 text-xs text-amber-800"
        >
          One or more sanctions sources are 7–30 days old.
          <RouterLink class="underline" to="/admin">Refresh →</RouterLink>
        </div>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th class="py-2">Source</th><th>Status</th><th>Last refreshed</th><th>Rows</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sanctions.data.value.sources" :key="s.source" class="border-t">
              <td class="py-2 font-medium">{{ s.source }}</td>
              <td>
                <span :class="['px-2 py-0.5 rounded text-xs', refdataStatusClass(s.last_run.status)]">
                  {{ s.last_run.status }}
                </span>
              </td>
              <td class="text-slate-600">
                {{ s.last_run.finished_at ? new Date(s.last_run.finished_at).toLocaleString() : "—" }}
                <StalenessBadge
                  v-if="s.staleness_severity"
                  class="ml-2"
                  :days="s.staleness_days ?? null"
                  :severity="s.staleness_severity"
                />
              </td>
              <td class="font-mono">{{ s.row_count }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </Card>

    <Card title="Thresholds">
      <ThresholdsEditor />
    </Card>

    <Card title="Eval">
      <p v-if="evalRuns.isLoading.value || !evalRuns.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="evalRuns.data.value.runs.length === 0" class="text-slate-500 text-sm">
        No eval runs yet.
        <RouterLink to="/training" class="text-blue-700 hover:underline">Run one from /training →</RouterLink>
      </p>
      <template v-else>
        <div v-if="evalRuns.data.value.latest_pass_fail" class="flex flex-wrap gap-2 mb-3">
          <span
            v-for="(v, k) in evalRuns.data.value.latest_pass_fail"
            :key="k"
            :class="['px-2 py-1 rounded text-xs', v ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800']"
          >
            {{ k }}: {{ v ? "PASS" : "FAIL" }}
          </span>
        </div>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th>Ran</th><th>Classifier</th><th>Split</th><th>Top-1 sub</th><th>Top-3 sub</th>
              <th>Top-1 chap</th><th>MRR</th><th>p95 ms</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in evalRunsTop" :key="r.id" class="border-t">
              <td class="text-slate-600">{{ new Date(r.ran_at).toLocaleString() }}</td>
              <td class="font-mono">{{ r.classifier }}</td>
              <td>{{ r.split }}</td>
              <td class="font-mono">{{ r.top1_subheading?.toFixed(3) ?? "—" }}</td>
              <td class="font-mono">{{ r.top3_subheading?.toFixed(3) ?? "—" }}</td>
              <td class="font-mono">{{ r.top1_chapter?.toFixed(3) ?? "—" }}</td>
              <td class="font-mono">{{ r.mrr?.toFixed(3) ?? "—" }}</td>
              <td class="font-mono">{{ r.p95_ms?.toFixed(0) ?? "—" }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </Card>

    <Card title="Recent batches">
      <p v-if="batches.isLoading.value || !batches.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="batches.data.value.batches.length === 0" class="text-slate-500 text-sm">
        No batch jobs yet.
      </p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>ID</th><th>File</th><th>Status</th><th>Progress</th><th>Created</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches.data.value.batches" :key="b.batch_id" class="border-t">
            <td class="font-mono text-xs">{{ b.batch_id.slice(0, 8) }}</td>
            <td>{{ b.filename ?? "—" }}</td>
            <td>{{ b.status }}</td>
            <td>
              <div class="flex items-center gap-2">
                <div class="w-32 h-2 bg-slate-200 rounded">
                  <div class="h-2 bg-emerald-500 rounded" :style="{ width: batchPct(b) + '%' }" />
                </div>
                <span class="font-mono text-xs">{{ b.completed_rows }}/{{ b.total_rows }}</span>
              </div>
            </td>
            <td class="text-slate-600">{{ new Date(b.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>
