<script setup lang="ts">
import { computed, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../../api/client";
import { useFetch, invalidateQueries } from "../../api/useFetch";
import Card from "../Card.vue";
import StatusBadge from "../StatusBadge.vue";
import LogStream from "../LogStream.vue";

type EvalJobRow = {
  id: number;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  classifier: string;
  split: string;
  limit_n: number | null;
  eval_run_id: number | null;
};

const classifier = ref<"pipeline" | "baseline_noop">("pipeline");
const split = ref<"train" | "dev" | "test">("test");
const limit = ref("");
const startPending = ref(false);
const startError = ref<Error | null>(null);

const jobs = useFetch<{ jobs: EvalJobRow[] }>({
  key: ["eval", "jobs"],
  refetchInterval: (data) =>
    (data?.jobs ?? []).some((j) => j.status === "running") ? 3000 : 15000,
  fetcher: () => api.get<{ jobs: EvalJobRow[] }>("/api/v1/eval/jobs"),
});

async function startEval() {
  startPending.value = true;
  startError.value = null;
  try {
    await api.post<{ enqueued_job_id: string }>("/api/v1/eval/run", {
      classifier: classifier.value,
      split: split.value,
      limit: limit.value ? parseInt(limit.value, 10) : null,
    });
    invalidateQueries(["eval", "jobs"]);
  } catch (e: any) {
    startError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    startPending.value = false;
  }
}

const latest = computed(() => jobs.data.value?.jobs[0]);
const running = computed(() => jobs.data.value?.jobs.find((j) => j.status === "running"));

function onDone() {
  invalidateQueries(["eval", "jobs"]);
}
</script>

<template>
  <Card title="Run eval">
    <p class="text-xs text-slate-500 mb-3">
      Runs the full eval harness against a gold split and writes an
      <code>eval_run</code> row.
      <RouterLink to="/status" class="text-blue-700 hover:underline">
        See results on /status →
      </RouterLink>
    </p>
    <div class="grid grid-cols-3 gap-3 text-sm mb-3">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-slate-500">Classifier</span>
        <select v-model="classifier" class="border rounded px-2 py-1 font-mono">
          <option value="pipeline">pipeline</option>
          <option value="baseline_noop">baseline_noop</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-slate-500">Split</span>
        <select v-model="split" class="border rounded px-2 py-1 font-mono">
          <option value="test">test</option>
          <option value="dev">dev</option>
          <option value="train">train</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-slate-500">Limit (optional)</span>
        <input v-model="limit" class="border rounded px-2 py-1 font-mono" placeholder="e.g. 50" />
      </label>
    </div>
    <div class="flex items-center gap-3">
      <button
        class="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="startPending || !!running"
        @click="startEval"
      >{{ running ? "Running…" : "Run eval" }}</button>
      <span v-if="startError" class="text-xs text-red-700">{{ startError.message }}</span>
    </div>

    <div v-if="running" class="mt-3">
      <LogStream run-table="eval_job" :run-id="running.id" @done="onDone" />
    </div>

    <div v-if="jobs.data.value && jobs.data.value.jobs.length > 0" class="mt-4">
      <h3 class="text-xs uppercase text-slate-500 mb-2">Recent jobs</h3>
      <table class="w-full text-xs">
        <thead class="text-left text-slate-500">
          <tr>
            <th>ID</th><th>Status</th><th>Classifier</th><th>Split</th><th>Limit</th>
            <th>Started</th><th>Eval run</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="j in jobs.data.value.jobs"
            :key="j.id"
            :class="['border-t', j === latest ? 'font-medium' : '']"
          >
            <td class="font-mono">{{ j.id }}</td>
            <td><StatusBadge :status="j.status" /></td>
            <td class="font-mono">{{ j.classifier }}</td>
            <td>{{ j.split }}</td>
            <td>{{ j.limit_n ?? "—" }}</td>
            <td>{{ j.started_at ? new Date(j.started_at).toLocaleString() : "—" }}</td>
            <td class="font-mono">{{ j.eval_run_id ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
      <pre
        v-if="latest?.error_message"
        class="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto"
      >{{ latest.error_message }}</pre>
    </div>
  </Card>
</template>
