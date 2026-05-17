<script setup lang="ts">
import { RouterLink } from "vue-router";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";

type Row = {
  result_id: string;
  shipment_id: string;
  external_ref: string | null;
  commodity_text: string;
  origin_iso: string | null;
  destination_iso: string | null;
  top1_hs_code: string | null;
  top1_chapter: string | null;
  top1_score: number | null;
  engine_version: string | null;
  created_at: string;
};

const q = useFetch<{ items: Row[] }>({
  key: ["results"],
  refetchInterval: 5000,
  fetcher: () => api.get<{ items: Row[] }>("/api/v1/results?limit=100"),
});
</script>

<template>
  <section class="bg-white border rounded-lg p-4 shadow-sm">
    <h2 class="text-lg font-semibold mb-3">Screening results</h2>
    <p v-if="q.isLoading.value || !q.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="q.data.value.items.length === 0" class="text-slate-500 text-sm">
      No results yet. Upload a CSV or POST <code>/api/v1/screen</code>.
    </p>
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs uppercase text-slate-500">
          <th class="py-2">Created</th><th>Ref</th><th>Commodity</th><th>Route</th>
          <th>Top-1 HS</th><th>Score</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in q.data.value.items" :key="r.result_id" class="border-t">
          <td class="text-slate-600 py-2">{{ new Date(r.created_at).toLocaleString() }}</td>
          <td>{{ r.external_ref ?? "—" }}</td>
          <td class="max-w-md truncate" :title="r.commodity_text">{{ r.commodity_text }}</td>
          <td class="font-mono text-xs">{{ r.origin_iso ?? "??" }} → {{ r.destination_iso ?? "??" }}</td>
          <td class="font-mono">{{ r.top1_hs_code ?? "—" }}</td>
          <td class="font-mono">{{ r.top1_score?.toFixed(3) ?? "—" }}</td>
          <td>
            <RouterLink :to="`/results/${r.result_id}`" class="text-blue-700 hover:underline">Inspect</RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
