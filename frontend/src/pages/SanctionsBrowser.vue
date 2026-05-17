<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";

type Source = { source: string; count: number };
type Cell = { origin_iso: string; destination_iso: string; count: number };
type Item = {
  id: number;
  source: string;
  source_record_id: string;
  description: string;
  hs_codes: string[];
  restriction_type: string | null;
  provenance_url: string | null;
  origin_iso: string | null;
  destination_iso: string | null;
};

const origin = ref("");
const destination = ref("");

const sources = useFetch<{ sources: Source[] }>({
  key: ["sanctions", "sources"],
  fetcher: () => api.get<{ sources: Source[] }>("/api/v1/sanctions/sources"),
});

const heatmap = useFetch<{ cells: Cell[] }>({
  key: ["sanctions", "heatmap"],
  fetcher: () => api.get<{ cells: Cell[] }>("/api/v1/sanctions/heatmap"),
});

const items = useFetch<{ items: Item[] }>({
  key: computed(() => ["sanctions", "by-pair", origin.value, destination.value] as const),
  fetcher: () => {
    const qp: string[] = [];
    if (origin.value) qp.push(`origin=${origin.value}`);
    if (destination.value) qp.push(`destination=${destination.value}`);
    return api.get<{ items: Item[] }>(`/api/v1/sanctions/by-country-pair?${qp.join("&")}`);
  },
});

const origins = computed(() =>
  Array.from(new Set((heatmap.data.value?.cells ?? []).map((c) => c.origin_iso))).sort()
);
const destinations = computed(() =>
  Array.from(new Set((heatmap.data.value?.cells ?? []).map((c) => c.destination_iso))).sort()
);
const heatLookup = computed(() => {
  const m = new Map<string, number>();
  for (const c of heatmap.data.value?.cells ?? []) {
    m.set(`${c.origin_iso}>${c.destination_iso}`, c.count);
  }
  return m;
});
const maxCount = computed(() =>
  Math.max(1, ...(heatmap.data.value?.cells ?? []).map((c) => c.count))
);

function cellBg(o: string, d: string): string | undefined {
  const n = heatLookup.value.get(`${o}>${d}`) ?? 0;
  if (n <= 0) return undefined;
  const alpha = 0.15 + 0.85 * (n / maxCount.value);
  return `rgba(220,38,38,${alpha})`;
}

function cellCount(o: string, d: string): number {
  return heatLookup.value.get(`${o}>${d}`) ?? 0;
}

function pickCell(o: string, d: string) {
  origin.value = o === "*" ? "" : o;
  destination.value = d === "*" ? "" : d;
}
</script>

<template>
  <div class="grid gap-4">
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm uppercase text-slate-500 mb-2">Sources</h2>
      <p v-if="sources.isLoading.value || !sources.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="sources.data.value.sources.length === 0" class="text-slate-500 text-sm">
        No sanctions data ingested yet. Run e.g.
        <code class="text-xs">python -m app.refdata.sanctions.eu_dual_use.ingest --file ./data/sanctions/eu_dual_use_annex_i.xlsx</code>
      </p>
      <div v-else class="flex flex-wrap gap-2">
        <span v-for="s in sources.data.value.sources" :key="s.source" class="px-2 py-1 rounded bg-slate-100 text-sm">
          <span class="font-mono">{{ s.source }}</span>: {{ s.count.toLocaleString() }}
        </span>
      </div>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm uppercase text-slate-500 mb-2">Country-pair heatmap</h2>
      <p v-if="heatmap.isLoading.value || !heatmap.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="heatmap.data.value.cells.length === 0" class="text-slate-500 text-sm">No country rules yet.</p>
      <div v-else class="overflow-auto">
        <table class="text-xs">
          <thead>
            <tr>
              <th class="px-2 py-1 text-slate-500">origin ↓ / dest →</th>
              <th v-for="d in destinations" :key="d" class="px-2 py-1 font-mono">{{ d }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in origins" :key="o">
              <td class="px-2 py-1 font-mono text-slate-700">{{ o }}</td>
              <td
                v-for="d in destinations"
                :key="d"
                class="px-2 py-1 text-center cursor-pointer"
                :style="{ background: cellBg(o, d) }"
                :title="cellCount(o, d) > 0 ? `${cellCount(o, d)} rules` : ''"
                @click="pickCell(o, d)"
              >
                {{ cellCount(o, d) > 0 ? cellCount(o, d) : "" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <div class="flex items-center gap-2 mb-3">
        <h2 class="text-sm uppercase text-slate-500">Sanction records</h2>
        <input
          :value="origin"
          @input="origin = ($event.target as HTMLInputElement).value.toUpperCase()"
          class="border rounded px-2 py-1 text-sm w-20 ml-auto"
          placeholder="origin"
        />
        <input
          :value="destination"
          @input="destination = ($event.target as HTMLInputElement).value.toUpperCase()"
          class="border rounded px-2 py-1 text-sm w-20"
          placeholder="dest"
        />
      </div>
      <p v-if="items.isLoading.value || !items.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="items.data.value.items.length === 0" class="text-slate-500 text-sm">No matching records.</p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>Source</th><th>ID</th><th>Description</th><th>HS</th><th>Type</th><th>Route</th><th>Provenance</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in items.data.value.items.slice(0, 200)" :key="it.id" class="border-t align-top">
            <td class="py-1 font-mono">{{ it.source }}</td>
            <td class="font-mono text-xs">{{ it.source_record_id }}</td>
            <td class="max-w-md truncate" :title="it.description">{{ it.description }}</td>
            <td class="font-mono text-xs">{{ it.hs_codes.join(", ") }}</td>
            <td>{{ it.restriction_type ?? "—" }}</td>
            <td class="font-mono text-xs">{{ it.origin_iso ?? "*" }} → {{ it.destination_iso ?? "*" }}</td>
            <td>
              <a v-if="it.provenance_url" class="text-blue-700 hover:underline text-xs" :href="it.provenance_url" target="_blank" rel="noreferrer">link</a>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
