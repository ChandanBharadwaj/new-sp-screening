<script setup lang="ts">
import { api } from "../../api/client";
import { useFetch } from "../../api/useFetch";
import Card from "../Card.vue";

type Row = {
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

const query = useFetch<{ items: Row[] }>({
  key: ["data", "evalruns"],
  fetcher: () => api.get<{ items: Row[] }>("/api/v1/data/eval-runs"),
});
</script>

<template>
  <Card title="Eval runs">
    <p v-if="query.isLoading.value || !query.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="query.data.value.items.length === 0" class="text-slate-500 text-sm">No eval runs yet.</p>
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs uppercase text-slate-500">
          <th>Ran</th><th>Classifier</th><th>Split</th><th>top1-sub</th><th>top3-sub</th>
          <th>top1-chap</th><th>MRR</th><th>p50</th><th>p95</th><th>n</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in query.data.value.items" :key="r.id" class="border-t">
          <td class="text-slate-600 py-1">{{ new Date(r.ran_at).toLocaleString() }}</td>
          <td class="font-mono">{{ r.classifier }}</td>
          <td>{{ r.split }}</td>
          <td class="font-mono">{{ r.top1_subheading?.toFixed(3) ?? "—" }}</td>
          <td class="font-mono">{{ r.top3_subheading?.toFixed(3) ?? "—" }}</td>
          <td class="font-mono">{{ r.top1_chapter?.toFixed(3) ?? "—" }}</td>
          <td class="font-mono">{{ r.mrr?.toFixed(3) ?? "—" }}</td>
          <td class="font-mono">{{ r.p50_ms?.toFixed(0) ?? "—" }}</td>
          <td class="font-mono">{{ r.p95_ms?.toFixed(0) ?? "—" }}</td>
          <td class="font-mono">{{ r.n_examples ?? "—" }}</td>
        </tr>
      </tbody>
    </table>
  </Card>
</template>
