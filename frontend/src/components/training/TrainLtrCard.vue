<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../../api/client";
import { useFetch, invalidateQueries } from "../../api/useFetch";
import Card from "../Card.vue";
import StatusBadge from "../StatusBadge.vue";
import LogStream from "../LogStream.vue";

type TrainingRunRow = {
  id: number;
  kind: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  params: Record<string, unknown> | null;
  artifact_path: string | null;
  dataset_csv_path: string | null;
  metrics: {
    dataset?: { n_queries: number; n_rows: number };
    training_time_ms?: number;
    ndcg?: Record<string, number>;
  } | null;
};

const gold = ref("eval/gold/splits/train.jsonl");
const limit = ref("");
const startPending = ref(false);
const startError = ref<Error | null>(null);

const runs = useFetch<{ runs: TrainingRunRow[] }>({
  key: ["training", "runs"],
  refetchInterval: (data) =>
    (data?.runs ?? []).some((r) => r.status === "running") ? 3000 : 15000,
  fetcher: () => api.get<{ runs: TrainingRunRow[] }>("/api/v1/training/runs"),
});

async function startTrain() {
  startPending.value = true;
  startError.value = null;
  try {
    await api.post<{ enqueued_job_id: string }>("/api/v1/training/ltr/run", {
      gold: gold.value || null,
      limit: limit.value ? parseInt(limit.value, 10) : null,
    });
    invalidateQueries(["training", "runs"]);
  } catch (e: any) {
    startError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    startPending.value = false;
  }
}

const latest = computed(() => runs.data.value?.runs[0]);
const running = computed(() => runs.data.value?.runs.find((r) => r.status === "running"));
const previousRuns = computed(() => (runs.data.value?.runs ?? []).slice(1));

function onDone() {
  invalidateQueries(["training", "runs"]);
}
</script>

<template>
  <Card title="Train LTR ranker">
    <p class="text-xs text-slate-500 mb-3">
      Builds the LTR feature dataset from <code>eval/gold/splits/train.jsonl</code> and
      fits a LightGBM lambdarank model into <code>artifacts/ltr.txt</code>. The pipeline
      automatically picks up the new model on the next request.
    </p>
    <div class="grid grid-cols-2 gap-3 text-sm mb-3">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-slate-500">Gold split path</span>
        <input v-model="gold" class="border rounded px-2 py-1 font-mono" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-slate-500">Limit (optional, for smoke runs)</span>
        <input v-model="limit" class="border rounded px-2 py-1 font-mono" placeholder="e.g. 50" />
      </label>
    </div>
    <div class="flex items-center gap-3">
      <button
        class="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="startPending || !!running"
        @click="startTrain"
      >{{ running ? "Running…" : "Train LTR" }}</button>
      <span v-if="startError" class="text-xs text-red-700">{{ startError.message }}</span>
    </div>

    <div v-if="running" class="mt-3">
      <LogStream run-table="training_run" :run-id="running.id" @done="onDone" />
    </div>

    <div v-if="latest" class="mt-4 text-sm">
      <h3 class="text-xs uppercase text-slate-500 mb-1">Latest run</h3>
      <div class="flex items-center gap-3 text-sm">
        <StatusBadge :status="latest.status" />
        <span class="text-slate-500">
          started {{ latest.started_at ? new Date(latest.started_at).toLocaleString() : "—" }}
        </span>
      </div>
      <div v-if="latest.artifact_path" class="text-xs text-slate-600 mt-1">
        artifact: <span class="font-mono">{{ latest.artifact_path }}</span>
      </div>
      <pre
        v-if="latest.metrics"
        class="text-xs bg-slate-50 p-2 mt-2 rounded overflow-auto"
      >{{ JSON.stringify(latest.metrics, null, 2) }}</pre>
      <pre
        v-if="latest.error_message"
        class="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto"
      >{{ latest.error_message }}</pre>
    </div>

    <details v-if="previousRuns.length > 0" class="mt-3">
      <summary class="text-xs text-slate-500 cursor-pointer">
        Previous runs ({{ previousRuns.length }})
      </summary>
      <table class="w-full text-xs mt-2">
        <thead class="text-left text-slate-500">
          <tr>
            <th>ID</th><th>Status</th><th>Started</th><th>Finished</th><th>Artifact</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in previousRuns" :key="r.id" class="border-t">
            <td class="font-mono">{{ r.id }}</td>
            <td><StatusBadge :status="r.status" /></td>
            <td>{{ r.started_at ? new Date(r.started_at).toLocaleString() : "—" }}</td>
            <td>{{ r.finished_at ? new Date(r.finished_at).toLocaleString() : "—" }}</td>
            <td class="font-mono">{{ r.artifact_path ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </Card>
</template>
