<script setup lang="ts">
import { ref, watch } from "vue";
import { api } from "../../api/client";
import { useFetch, invalidateQueries } from "../../api/useFetch";

type ThresholdRow = {
  key: string;
  value: number;
  source: string;
  updated_at: string | null;
};

type ThresholdsResp = { thresholds: ThresholdRow[]; yaml_seed: Record<string, number> };

const q = useFetch<ThresholdsResp>({
  key: ["thresholds"],
  fetcher: () => api.get<ThresholdsResp>("/api/v1/thresholds"),
});

const drafts = ref<Record<string, string>>({});

watch(
  () => q.data.value,
  (data) => {
    if (data) {
      const next: Record<string, string> = {};
      for (const t of data.thresholds) next[t.key] = String(t.value);
      drafts.value = next;
    }
  }
);

const savePending = ref(false);
const saveError = ref<Error | null>(null);

async function save(key: string, value: number) {
  savePending.value = true;
  saveError.value = null;
  try {
    await api.put("/api/v1/thresholds", { key, value });
    invalidateQueries(["thresholds"]);
    invalidateQueries(["status", "eval"]);
  } catch (e: any) {
    saveError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    savePending.value = false;
  }
}

async function resetYaml() {
  savePending.value = true;
  saveError.value = null;
  try {
    await api.post("/api/v1/thresholds/reset", {});
    invalidateQueries(["thresholds"]);
    invalidateQueries(["status", "eval"]);
  } catch (e: any) {
    saveError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    savePending.value = false;
  }
}

function sourceClass(source: string) {
  return source === "ui"
    ? "bg-amber-100 text-amber-800"
    : "bg-slate-100 text-slate-600";
}

function changed(t: ThresholdRow) {
  const draft = drafts.value[t.key] ?? String(t.value);
  const parsed = parseFloat(draft);
  return !Number.isNaN(parsed) && parsed !== t.value;
}
</script>

<template>
  <p v-if="q.isLoading.value || !q.data.value" class="text-slate-500">Loading…</p>
  <div v-else>
    <p class="text-xs text-slate-500 mb-3">
      Live ship-gate thresholds. Edits here only affect the Status pass/fail badges; the CI
      gate (<code>eval.ci.compare</code>) still reads <code>eval/ci/thresholds.yaml</code>.
    </p>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs uppercase text-slate-500">
          <th>Key</th><th>Current</th><th>YAML seed</th><th>Source</th><th>Updated</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in q.data.value.thresholds" :key="t.key" class="border-t">
          <td class="py-2 font-mono">{{ t.key }}</td>
          <td>
            <input
              v-model="drafts[t.key]"
              class="border rounded px-2 py-0.5 text-sm font-mono w-24"
            />
          </td>
          <td class="text-xs font-mono text-slate-500">
            {{ q.data.value.yaml_seed[t.key] ?? "—" }}
          </td>
          <td>
            <span :class="['text-xs px-1.5 py-0.5 rounded', sourceClass(t.source)]">{{ t.source }}</span>
          </td>
          <td class="text-xs text-slate-500">
            {{ t.updated_at ? new Date(t.updated_at).toLocaleString() : "—" }}
          </td>
          <td>
            <button
              class="text-xs bg-slate-900 text-white px-2 py-0.5 rounded disabled:opacity-30"
              :disabled="!changed(t) || savePending"
              @click="save(t.key, parseFloat(drafts[t.key]))"
            >Save</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="mt-3 flex items-center gap-3">
      <button
        class="text-xs bg-slate-200 px-2 py-1 rounded"
        :disabled="savePending"
        @click="resetYaml"
      >Reset all to YAML seed</button>
      <span v-if="saveError" class="text-xs text-red-700">{{ saveError.message }}</span>
    </div>
  </div>
</template>
