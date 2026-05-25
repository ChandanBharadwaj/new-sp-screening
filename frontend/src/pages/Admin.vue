<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/client";
import { useFetch, invalidateQueries } from "../api/useFetch";
import SourceCard, { type Source } from "../components/admin/SourceCard.vue";
import RuleMaterializationPanel, {
  type RuleMaterializationItem,
} from "../components/admin/RuleMaterializationPanel.vue";
import KeywordListPanel, {
  type KeywordListItem,
} from "../components/admin/KeywordListPanel.vue";

const sources = useFetch<{ sources: Source[] }>({
  key: ["admin", "sources"],
  refetchInterval: 3000,
  fetcher: () => api.get<{ sources: Source[] }>("/api/v1/admin/refdata/sources"),
});

const ruleMaterialization = useFetch<{ items: RuleMaterializationItem[] }>({
  key: ["admin", "rule-materialization"],
  fetcher: () =>
    api.get<{ items: RuleMaterializationItem[] }>("/api/v1/admin/rule-materialization"),
});

const keywordLists = useFetch<{ items: KeywordListItem[] }>({
  key: ["admin", "keyword-lists"],
  fetcher: () =>
    api.get<{ items: KeywordListItem[] }>("/api/v1/admin/keyword-lists"),
});

const newListName = ref("");
const newListLabel = ref("");
const createPending = ref(false);
const createError = ref<Error | null>(null);

async function createList() {
  if (!newListName.value) return;
  createPending.value = true;
  createError.value = null;
  try {
    await api.put(`/api/v1/admin/keyword-lists/${newListName.value}`, {
      label: newListLabel.value || null,
    });
    invalidateQueries(["admin", "keyword-lists"]);
    newListName.value = "";
    newListLabel.value = "";
  } catch (e: any) {
    createError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    createPending.value = false;
  }
}

const runAllPending = ref(false);
const resetPending = ref(false);
const runAllResult = ref<unknown>(null);
const resetResult = ref<unknown>(null);
const confirmReset = ref(false);
const includeRules = ref(false);
const includeResults = ref(true);

async function runAll() {
  runAllPending.value = true;
  try {
    runAllResult.value = await api.post("/api/v1/admin/refdata/run-all", {});
    invalidateQueries(["admin", "sources"]);
  } finally {
    runAllPending.value = false;
  }
}

async function doReset() {
  resetPending.value = true;
  try {
    resetResult.value = await api.post("/api/v1/admin/refdata/reset", {
      include_rules: includeRules.value,
      include_results: includeResults.value,
    });
    invalidateQueries(["admin", "sources"]);
    confirmReset.value = false;
  } finally {
    resetPending.value = false;
  }
}

const KIND_LABELS: Record<string, string> = {
  taxonomy: "HS taxonomy",
  labels: "Labeled training data",
  derived: "Derived (depend on data above)",
  sanctions: "Sanctions & controlled goods",
};
const KIND_ORDER = ["taxonomy", "labels", "derived", "sanctions"] as const;

const grouped = computed(() => {
  const out: Record<string, Source[]> = {};
  for (const s of sources.data.value?.sources ?? []) {
    (out[s.kind] ||= []).push(s);
  }
  return out;
});

const orderedKinds = computed(() =>
  KIND_ORDER.filter((k) => (grouped.value[k]?.length ?? 0) > 0)
);
</script>

<template>
  <div class="grid gap-4">
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-lg font-semibold">Data ingestion</h2>
      <p class="text-sm text-slate-600 mt-1">
        Trigger each refdata loader from the UI. Files the publisher does not auto-serve are
        uploaded here once and persist under <code class="font-mono">./data/</code>.
        Reset truncates ingested data tables but keeps source files on disk so you can re-run
        any loader without re-downloading.
      </p>
      <div class="flex flex-wrap gap-2 mt-3">
        <button
          class="bg-emerald-700 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          :disabled="runAllPending"
          @click="runAll"
        >Run all ready sources</button>
        <button
          v-if="!confirmReset"
          class="bg-red-700 text-white px-4 py-2 rounded text-sm ml-auto"
          @click="confirmReset = true"
        >Reset data…</button>
        <div
          v-else
          class="ml-auto flex items-center gap-3 bg-red-50 border border-red-300 rounded px-3 py-2"
        >
          <span class="text-xs text-red-800">Truncate ingested tables?</span>
          <label class="text-xs flex items-center gap-1">
            <input v-model="includeResults" type="checkbox" /> screening results
          </label>
          <label class="text-xs flex items-center gap-1">
            <input v-model="includeRules" type="checkbox" /> rules
          </label>
          <button class="bg-red-700 text-white px-2 py-1 rounded text-xs" @click="doReset">Confirm</button>
          <button class="text-xs text-slate-600" @click="confirmReset = false">Cancel</button>
        </div>
      </div>
      <pre
        v-if="runAllResult || resetResult"
        class="mt-3 text-xs bg-slate-50 p-2 rounded overflow-auto"
      >{{ JSON.stringify(runAllResult ?? resetResult, null, 2) }}</pre>
    </section>

    <p v-if="sources.isLoading.value || !sources.data.value" class="text-slate-500">Loading sources…</p>
    <template v-else>
      <div v-for="k in orderedKinds" :key="k">
        <h3 class="text-sm uppercase tracking-wide text-slate-500 mb-2">{{ KIND_LABELS[k] }}</h3>
        <div class="grid gap-3">
          <SourceCard v-for="s in grouped[k]" :key="s.source" :source="s" />
        </div>
      </div>
    </template>

    <section class="bg-white border rounded-lg p-4 shadow-sm mt-2">
      <h2 class="text-lg font-semibold">Keyword lists</h2>
      <p class="text-sm text-slate-600 mt-1">
        Operator-curated CSV lists of sanctioned words and phrases (e.g. "seafood").
        Each list lands its keywords in the same
        <code class="font-mono text-xs">sanctioned_commodity</code> table as
        OFAC/EU/UN data and is materialized into
        <code class="font-mono text-xs">screening_rule</code> rows automatically.
        CSV must contain a <code class="font-mono text-xs">keywords</code> column with
        one entry per row.
      </p>

      <div class="flex flex-wrap items-end gap-2 mt-3 bg-slate-50 border rounded p-3">
        <label class="flex flex-col">
          <span class="text-xs text-slate-500">List name (lowercase, no spaces)</span>
          <input
            v-model="newListName"
            class="border rounded px-2 py-1 text-sm font-mono w-48"
            placeholder="seafood"
          />
        </label>
        <label class="flex flex-col">
          <span class="text-xs text-slate-500">Label (optional)</span>
          <input
            v-model="newListLabel"
            class="border rounded px-2 py-1 text-sm w-64"
            placeholder="Restricted seafood"
          />
        </label>
        <button
          class="bg-slate-900 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
          :disabled="!newListName || createPending"
          @click="createList"
        >Create list</button>
        <span v-if="createError" class="text-xs text-red-700">{{ createError.message }}</span>
      </div>

      <p
        v-if="keywordLists.isLoading.value || !keywordLists.data.value"
        class="text-slate-500 text-sm mt-3"
      >Loading…</p>
      <p
        v-else-if="keywordLists.data.value.items.length === 0"
        class="text-slate-500 text-sm mt-3"
      >No keyword lists yet. Create one above, upload a CSV, then click Run.</p>
      <div v-else class="grid gap-3 mt-3">
        <KeywordListPanel
          v-for="kl in keywordLists.data.value.items"
          :key="kl.name"
          :item="kl"
        />
      </div>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm mt-2">
      <h2 class="text-lg font-semibold">Semantic rule materialization</h2>
      <p class="text-sm text-slate-600 mt-1">
        Convert ingested commodity risk data (per source) into
        <code class="font-mono text-xs">screening_rule</code> rows that the cross-encoder
        evaluates at screen time. Off by default — flip a source on to opt in.
        Operator-authored rules are unaffected and remain editable on the
        <router-link to="/rules" class="text-blue-700 hover:underline">Rules</router-link>
        page.
      </p>
      <p
        v-if="ruleMaterialization.isLoading.value || !ruleMaterialization.data.value"
        class="text-slate-500 text-sm mt-3"
      >Loading…</p>
      <div v-else class="grid gap-3 mt-3">
        <RuleMaterializationPanel
          v-for="it in ruleMaterialization.data.value.items"
          :key="it.source"
          :item="it"
        />
      </div>
    </section>
  </div>
</template>
