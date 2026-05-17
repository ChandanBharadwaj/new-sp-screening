<script setup lang="ts">
import { computed } from "vue";
import { api } from "../../api/client";
import { useFetch } from "../../api/useFetch";
import Card from "../Card.vue";

type Row = {
  id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  rows_upserted: number;
  status: string;
  error_message: string | null;
  notes: string | null;
};

const query = useFetch<{ items: Row[] }>({
  key: ["data", "refdataruns"],
  refetchInterval: 3000,
  fetcher: () => api.get<{ items: Row[] }>("/api/v1/data/refdata-runs?limit=100"),
});

function badgeClass(status: string) {
  return status === "success"
    ? "bg-emerald-100 text-emerald-800"
    : status === "running"
    ? "bg-blue-100 text-blue-800 animate-pulse"
    : status === "failed"
    ? "bg-red-100 text-red-800"
    : "bg-slate-100 text-slate-600";
}

const items = computed(() => query.data.value?.items ?? []);
</script>

<template>
  <Card title="Refdata runs (live)">
    <p v-if="query.isLoading.value || !query.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="items.length === 0" class="text-slate-500 text-sm">No runs yet.</p>
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs uppercase text-slate-500">
          <th>Source</th><th>Started</th><th>Finished</th><th>Rows</th><th>Status</th><th>Error / notes</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in items" :key="r.id" class="border-t align-top">
          <td class="py-1 font-mono">{{ r.source }}</td>
          <td class="text-slate-600 text-xs">{{ new Date(r.started_at).toLocaleString() }}</td>
          <td class="text-slate-600 text-xs">
            {{ r.finished_at ? new Date(r.finished_at).toLocaleString() : "—" }}
          </td>
          <td class="font-mono">{{ r.rows_upserted }}</td>
          <td>
            <span :class="['px-2 py-0.5 rounded text-xs', badgeClass(r.status)]">{{ r.status }}</span>
          </td>
          <td class="text-xs text-slate-600">{{ r.error_message ?? r.notes ?? "—" }}</td>
        </tr>
      </tbody>
    </table>
  </Card>
</template>
