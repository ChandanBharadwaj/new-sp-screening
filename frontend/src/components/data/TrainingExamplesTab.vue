<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../../api/client";
import { useFetch } from "../../api/useFetch";
import Card from "../Card.vue";

type Row = {
  id: number;
  source: string;
  source_id: string | null;
  description: string;
  hs_code: string | null;
  created_at: string | null;
};

const source = ref("");
const q = ref("");
const chapter = ref("");
const offset = ref(0);
const limit = 50;

const query = useFetch<{ items: Row[]; total: number; by_source: Record<string, number> }>({
  key: computed(() => ["data", "training", source.value, q.value, chapter.value, offset.value] as const),
  fetcher: () => {
    const sp = new URLSearchParams();
    if (source.value) sp.set("source", source.value);
    if (q.value) sp.set("q", q.value);
    if (chapter.value) sp.set("chapter", chapter.value);
    sp.set("limit", String(limit));
    sp.set("offset", String(offset.value));
    return api.get(`/api/v1/data/training-examples?${sp.toString()}`);
  },
});

function changeSource(v: string) {
  source.value = v;
  offset.value = 0;
}
function changeQ(v: string) {
  q.value = v;
  offset.value = 0;
}
function changeChapter(v: string) {
  chapter.value = v;
  offset.value = 0;
}
function prev() {
  offset.value = Math.max(0, offset.value - limit);
}
function next() {
  offset.value = offset.value + limit;
}
</script>

<template>
  <Card title="Training examples (hs_training_example)">
    <div class="flex flex-wrap items-end gap-2 text-sm mb-3">
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Source</span>
        <select
          :value="source"
          class="border rounded px-2 py-1 text-sm"
          @change="changeSource(($event.target as HTMLSelectElement).value)"
        >
          <option value="">all</option>
          <option v-for="(count, s) in query.data.value?.by_source ?? {}" :key="s" :value="s">
            {{ s }} ({{ count }})
          </option>
        </select>
      </label>
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Search</span>
        <input
          :value="q"
          class="border rounded px-2 py-1 text-sm w-64"
          placeholder="description contains…"
          @input="changeQ(($event.target as HTMLInputElement).value)"
        />
      </label>
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Chapter</span>
        <input
          :value="chapter"
          class="border rounded px-2 py-1 text-sm w-20"
          placeholder="62"
          @input="changeChapter(($event.target as HTMLInputElement).value)"
        />
      </label>
      <div v-if="query.data.value" class="ml-auto text-xs text-slate-500">
        showing {{ offset + 1 }}–{{ Math.min(offset + query.data.value.items.length, query.data.value.total) }}
        of {{ query.data.value.total.toLocaleString() }}
      </div>
    </div>
    <p v-if="query.isLoading.value || !query.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="query.data.value.items.length === 0" class="text-slate-500 text-sm">
      No rows. Run the relevant source from
      <a href="/admin" class="text-blue-700 hover:underline">Admin</a>.
    </p>
    <template v-else>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>Source</th><th>Source ID</th><th>HS</th><th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in query.data.value.items" :key="r.id" class="border-t">
            <td class="py-1 font-mono text-xs">{{ r.source }}</td>
            <td class="font-mono text-xs">{{ r.source_id ?? "—" }}</td>
            <td class="font-mono">{{ r.hs_code ?? "—" }}</td>
            <td class="max-w-2xl truncate" :title="r.description">{{ r.description }}</td>
          </tr>
        </tbody>
      </table>
      <div class="flex items-center gap-2 mt-3 text-sm">
        <button class="px-3 py-1 bg-slate-200 rounded text-xs" :disabled="offset === 0" @click="prev">← Prev</button>
        <button
          class="px-3 py-1 bg-slate-200 rounded text-xs"
          :disabled="offset + limit >= (query.data.value.total ?? 0)"
          @click="next"
        >Next →</button>
      </div>
    </template>
  </Card>
</template>
