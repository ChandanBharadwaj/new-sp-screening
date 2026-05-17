<script setup lang="ts">
import { computed, reactive, ref } from "vue";
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
  abstained: boolean;
  abstain_reason: string | null;
  sanctions_count: number;
  max_sanction_similarity: number;
  rules_count: number;
  max_rule_delta: number;
  engine_version: string | null;
  created_at: string;
};

type Sort = "recent" | "risk_desc" | "confidence_asc";

const PAGE_SIZE = 50;

const filters = reactive({
  origin_iso: "",
  destination_iso: "",
  chapter: "",
  abstained: false,
  has_sanctions: false,
  has_rules: false,
  since: "", // YYYY-MM-DD
});
const sort = ref<Sort>("recent");
const offset = ref(0);

function buildUrl(): string {
  const params = new URLSearchParams();
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset.value));
  params.set("sort", sort.value);
  if (filters.origin_iso) params.set("origin_iso", filters.origin_iso.toUpperCase());
  if (filters.destination_iso) params.set("destination_iso", filters.destination_iso.toUpperCase());
  if (filters.chapter) params.set("chapter", filters.chapter);
  if (filters.abstained) params.set("abstained", "true");
  if (filters.has_sanctions) params.set("has_sanctions", "true");
  if (filters.has_rules) params.set("has_rules", "true");
  if (filters.since) params.set("since", new Date(filters.since).toISOString());
  return "/api/v1/results?" + params.toString();
}

const url = computed(buildUrl);

const q = useFetch<{ items: Row[]; total: number; limit: number; offset: number }>({
  key: computed(() => ["results", url.value]),
  refetchInterval: 5000,
  fetcher: () => api.get<{ items: Row[]; total: number; limit: number; offset: number }>(url.value),
});

function resetOffset() {
  offset.value = 0;
}

function clearFilters() {
  filters.origin_iso = "";
  filters.destination_iso = "";
  filters.chapter = "";
  filters.abstained = false;
  filters.has_sanctions = false;
  filters.has_rules = false;
  filters.since = "";
  sort.value = "recent";
  offset.value = 0;
}

const totalPages = computed(() => {
  const total = q.data.value?.total ?? 0;
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
});
const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1);
</script>

<template>
  <div class="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
    <aside class="bg-white border rounded-lg p-4 shadow-sm space-y-3 self-start md:sticky md:top-4">
      <h3 class="text-sm font-semibold uppercase text-slate-500">Filters</h3>
      <div>
        <label class="block text-xs text-slate-600 mb-1">Origin ISO</label>
        <input
          v-model="filters.origin_iso"
          maxlength="2"
          placeholder="e.g. US"
          class="w-full border rounded px-2 py-1 text-sm uppercase"
          @change="resetOffset"
        />
      </div>
      <div>
        <label class="block text-xs text-slate-600 mb-1">Destination ISO</label>
        <input
          v-model="filters.destination_iso"
          maxlength="2"
          placeholder="e.g. IR"
          class="w-full border rounded px-2 py-1 text-sm uppercase"
          @change="resetOffset"
        />
      </div>
      <div>
        <label class="block text-xs text-slate-600 mb-1">Chapter</label>
        <input
          v-model="filters.chapter"
          maxlength="2"
          placeholder="e.g. 72"
          class="w-full border rounded px-2 py-1 text-sm font-mono"
          @change="resetOffset"
        />
      </div>
      <div>
        <label class="block text-xs text-slate-600 mb-1">Since</label>
        <input
          v-model="filters.since"
          type="date"
          class="w-full border rounded px-2 py-1 text-sm"
          @change="resetOffset"
        />
      </div>
      <fieldset class="space-y-1 pt-2 border-t">
        <legend class="text-xs text-slate-600 mb-1">Flags</legend>
        <label class="flex items-center gap-2 text-sm">
          <input v-model="filters.abstained" type="checkbox" @change="resetOffset" />
          Abstained only
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input v-model="filters.has_sanctions" type="checkbox" @change="resetOffset" />
          Has sanctions hits
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input v-model="filters.has_rules" type="checkbox" @change="resetOffset" />
          Has rule hits
        </label>
      </fieldset>
      <button
        class="w-full mt-2 text-xs text-slate-500 hover:text-slate-800 underline"
        @click="clearFilters"
      >
        Reset all
      </button>
    </aside>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold">
          Screening results
          <span v-if="q.data.value" class="text-sm font-normal text-slate-500">
            ({{ q.data.value.total }})
          </span>
        </h2>
        <div class="flex items-center gap-2 text-sm">
          <label class="text-slate-600">Sort:</label>
          <select v-model="sort" class="border rounded px-2 py-1" @change="resetOffset">
            <option value="recent">Most recent</option>
            <option value="risk_desc">Highest risk</option>
            <option value="confidence_asc">Lowest confidence</option>
          </select>
        </div>
      </div>

      <p v-if="q.isLoading.value || !q.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="q.data.value.items.length === 0" class="text-slate-500 text-sm">
        No results match these filters.
      </p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th class="py-2">Created</th>
            <th>Ref</th>
            <th>Commodity</th>
            <th>Route</th>
            <th>Top-1 HS</th>
            <th>Score</th>
            <th>Flags</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in q.data.value.items" :key="r.result_id" class="border-t">
            <td class="text-slate-600 py-2">{{ new Date(r.created_at).toLocaleString() }}</td>
            <td>{{ r.external_ref ?? "—" }}</td>
            <td class="max-w-md truncate" :title="r.commodity_text">{{ r.commodity_text }}</td>
            <td class="font-mono text-xs">
              {{ r.origin_iso ?? "??" }} → {{ r.destination_iso ?? "??" }}
            </td>
            <td class="font-mono">{{ r.top1_hs_code ?? "—" }}</td>
            <td class="font-mono">{{ r.top1_score?.toFixed(3) ?? "—" }}</td>
            <td>
              <span
                v-if="r.abstained"
                class="inline-block px-1.5 py-0.5 text-xs rounded bg-amber-100 text-amber-800 mr-1"
                :title="r.abstain_reason ?? 'abstained'"
              >abstain</span>
              <span
                v-if="r.sanctions_count > 0"
                class="inline-block px-1.5 py-0.5 text-xs rounded mr-1"
                :class="r.max_sanction_similarity >= 0.8
                  ? 'bg-red-100 text-red-800'
                  : 'bg-orange-100 text-orange-800'"
                :title="`${r.sanctions_count} hits, max sim ${r.max_sanction_similarity.toFixed(2)}`"
              >S {{ r.sanctions_count }}</span>
              <span
                v-if="r.rules_count > 0"
                class="inline-block px-1.5 py-0.5 text-xs rounded bg-indigo-100 text-indigo-800"
                :title="`${r.rules_count} rule hits, max Δ ${r.max_rule_delta.toFixed(2)}`"
              >R {{ r.rules_count }}</span>
            </td>
            <td>
              <RouterLink :to="`/results/${r.result_id}`" class="text-blue-700 hover:underline">Inspect</RouterLink>
            </td>
          </tr>
        </tbody>
      </table>

      <nav
        v-if="q.data.value && q.data.value.total > PAGE_SIZE"
        class="flex items-center justify-between mt-4 text-sm"
      >
        <button
          class="px-3 py-1 border rounded disabled:opacity-40"
          :disabled="offset === 0"
          @click="offset = Math.max(0, offset - PAGE_SIZE)"
        >
          ← Previous
        </button>
        <span class="text-slate-600">Page {{ currentPage }} of {{ totalPages }}</span>
        <button
          class="px-3 py-1 border rounded disabled:opacity-40"
          :disabled="offset + PAGE_SIZE >= (q.data.value?.total ?? 0)"
          @click="offset = offset + PAGE_SIZE"
        >
          Next →
        </button>
      </nav>
    </section>
  </div>
</template>
