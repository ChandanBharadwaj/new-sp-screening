<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/client";
import { useFetch, invalidateQueries } from "../api/useFetch";

type RuleSourceFilter = "all" | "manual" | "materialized" | "keyword_lists";

const MATERIALIZED_PREFIX = "sanctions_source:";
const KEYWORD_LIST_INNER_PREFIX = "KW:";

function isMaterialized(r: { created_by: string | null }): boolean {
  return !!r.created_by && r.created_by.startsWith(MATERIALIZED_PREFIX);
}

function isKeywordList(r: { created_by: string | null }): boolean {
  return (
    isMaterialized(r) &&
    r.created_by!.slice(MATERIALIZED_PREFIX.length).startsWith(KEYWORD_LIST_INNER_PREFIX)
  );
}

function ruleOrigin(r: { created_by: string | null }): string {
  if (isKeywordList(r)) {
    // sanctions_source:KW:<name> → "Keyword list — <name>"
    const name = r.created_by!.slice(
      MATERIALIZED_PREFIX.length + KEYWORD_LIST_INNER_PREFIX.length
    );
    return `Keyword list — ${name}`;
  }
  if (isMaterialized(r)) return r.created_by!.slice(MATERIALIZED_PREFIX.length);
  return "Manual";
}

type PhraseGroup = { mode: "any_of" | "all_of"; phrases: string[] };

type Rule = {
  id: number;
  name: string;
  phrase: string;
  phrase_group: PhraseGroup | null;
  threshold: number;
  conditions: Record<string, unknown> | null;
  origin_iso: string | null;
  destination_iso: string | null;
  active: boolean;
  version: number;
  created_by: string | null;
  created_at: string | null;
};

type TestResp = {
  phrase_similarity: number;
  threshold: number;
  delta_above_threshold: number;
};

type ComposeKind = "single" | "any_of" | "all_of";

type Draft = {
  name: string;
  phrase: string;
  threshold: number;
  origin_iso: string;
  destination_iso: string;
  active: boolean;
  conditions_json: string;
  compose_kind: ComposeKind;
  extra_phrases: string[];
};

const EMPTY: Draft = {
  name: "",
  phrase: "",
  threshold: 0.5,
  origin_iso: "",
  destination_iso: "",
  active: true,
  conditions_json: "",
  compose_kind: "single",
  extra_phrases: [],
};

const draft = ref<Draft>({ ...EMPTY });
const editId = ref<number | null>(null);
const testText = ref("");
const testResp = ref<TestResp | null>(null);
const savePending = ref(false);
const saveError = ref<Error | null>(null);

const rules = useFetch<{ items: Rule[] }>({
  key: ["rules"],
  fetcher: () => api.get<{ items: Rule[] }>("/api/v1/rules"),
});

const sourceFilter = ref<RuleSourceFilter>("all");

const filteredRules = computed<Rule[]>(() => {
  const items = rules.data.value?.items ?? [];
  if (sourceFilter.value === "manual") return items.filter((r) => !isMaterialized(r));
  if (sourceFilter.value === "keyword_lists") return items.filter(isKeywordList);
  if (sourceFilter.value === "materialized")
    return items.filter((r) => isMaterialized(r) && !isKeywordList(r));
  return items;
});

function buildBody() {
  const phrase_group: PhraseGroup | null =
    draft.value.compose_kind === "single"
      ? null
      : {
          mode: draft.value.compose_kind,
          phrases: [draft.value.phrase, ...draft.value.extra_phrases].filter((p) => p && p.trim()),
        };
  return {
    name: draft.value.name,
    phrase: draft.value.phrase,
    phrase_group,
    threshold: Number(draft.value.threshold),
    conditions: draft.value.conditions_json ? JSON.parse(draft.value.conditions_json) : null,
    origin_iso: draft.value.origin_iso || null,
    destination_iso: draft.value.destination_iso || null,
    active: draft.value.active,
  };
}

function addExtraPhrase() {
  draft.value.extra_phrases = [...draft.value.extra_phrases, ""];
}

function removeExtraPhrase(i: number) {
  draft.value.extra_phrases = draft.value.extra_phrases.filter((_, idx) => idx !== i);
}

async function save() {
  savePending.value = true;
  saveError.value = null;
  try {
    const body = buildBody();
    if (editId.value) {
      await api.put<Rule>(`/api/v1/rules/${editId.value}`, body);
    } else {
      await api.post<Rule>("/api/v1/rules", body);
    }
    invalidateQueries(["rules"]);
    draft.value = { ...EMPTY };
    editId.value = null;
  } catch (e: any) {
    saveError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    savePending.value = false;
  }
}

async function testDraft() {
  testResp.value = await api.post<TestResp>("/api/v1/rules/test-phrase", {
    phrase: draft.value.phrase,
    cargo_text: testText.value,
    threshold: Number(draft.value.threshold),
  });
}

function beginEdit(r: Rule) {
  editId.value = r.id;
  const groupPhrases = r.phrase_group?.phrases ?? [];
  // First phrase in the group lives in `phrase` (also used as embed seed); the rest
  // go into extra_phrases. If group is null we're in single mode.
  const extra = groupPhrases.length > 0 ? groupPhrases.slice(1) : [];
  draft.value = {
    name: r.name,
    phrase: r.phrase,
    threshold: r.threshold,
    origin_iso: r.origin_iso ?? "",
    destination_iso: r.destination_iso ?? "",
    active: r.active,
    conditions_json: r.conditions ? JSON.stringify(r.conditions) : "",
    compose_kind: r.phrase_group?.mode ?? "single",
    extra_phrases: extra,
  };
}
</script>

<template>
  <div class="grid md:grid-cols-2 gap-4">
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <div class="flex items-center justify-between mb-2 gap-2">
        <h2 class="text-sm uppercase text-slate-500">Rules</h2>
        <label class="text-xs flex items-center gap-2">
          Show:
          <select v-model="sourceFilter" class="border rounded px-1 py-0.5 text-xs">
            <option value="all">All</option>
            <option value="manual">Manual only</option>
            <option value="materialized">Sanctions-materialized</option>
            <option value="keyword_lists">Keyword lists</option>
          </select>
        </label>
      </div>
      <p v-if="rules.isLoading.value || !rules.data.value" class="text-slate-500">Loading…</p>
      <p v-else-if="rules.data.value.items.length === 0" class="text-slate-500 text-sm">No rules yet. Create one →</p>
      <p v-else-if="filteredRules.length === 0" class="text-slate-500 text-sm">
        No rules match the current filter.
      </p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>Name</th><th>Origin</th><th>Phrase</th><th>Thr.</th><th>Route</th><th>Active</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filteredRules" :key="r.id" class="border-t">
            <td class="py-1">{{ r.name }} <span class="text-slate-400 text-xs">v{{ r.version }}</span></td>
            <td>
              <span
                class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono"
                :class="
                  isMaterialized(r)
                    ? 'bg-indigo-100 text-indigo-800'
                    : 'bg-slate-100 text-slate-700'
                "
                :title="
                  isMaterialized(r)
                    ? 'Materialized from sanctions source — managed in Admin → Semantic rule materialization'
                    : 'Operator-authored rule'
                "
              >{{ ruleOrigin(r) }}</span>
            </td>
            <td class="max-w-xs truncate" :title="r.phrase">{{ r.phrase }}</td>
            <td class="font-mono">{{ r.threshold.toFixed(2) }}</td>
            <td class="font-mono text-xs">{{ r.origin_iso ?? "*" }} → {{ r.destination_iso ?? "*" }}</td>
            <td>{{ r.active ? "✓" : "—" }}</td>
            <td>
              <button
                class="text-xs hover:underline"
                :class="
                  isMaterialized(r)
                    ? 'text-slate-400 cursor-not-allowed hover:no-underline'
                    : 'text-blue-700'
                "
                :disabled="isMaterialized(r)"
                :title="
                  isMaterialized(r)
                    ? 'Managed by sanctions source — edit in Admin → Semantic rule materialization'
                    : ''
                "
                @click="!isMaterialized(r) && beginEdit(r)"
              >edit</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm uppercase text-slate-500 mb-3">
        {{ editId ? `Edit rule #${editId}` : "New rule" }}
      </h2>
      <div class="grid gap-2 text-sm">
        <label class="text-xs text-slate-500">Name</label>
        <input v-model="draft.name" class="border rounded px-2 py-1" />

        <label class="text-xs text-slate-500">Composition</label>
        <div class="flex gap-3 text-xs">
          <label class="flex items-center gap-1">
            <input type="radio" value="single" v-model="draft.compose_kind" /> single phrase
          </label>
          <label class="flex items-center gap-1">
            <input type="radio" value="any_of" v-model="draft.compose_kind" /> any of (max)
          </label>
          <label class="flex items-center gap-1">
            <input type="radio" value="all_of" v-model="draft.compose_kind" /> all of (min)
          </label>
        </div>

        <label class="text-xs text-slate-500">
          {{ draft.compose_kind === "single" ? "Phrase" : "Primary phrase" }}
        </label>
        <textarea v-model="draft.phrase" class="border rounded px-2 py-1" rows="3" />

        <template v-if="draft.compose_kind !== 'single'">
          <label class="text-xs text-slate-500">
            Additional phrases ({{ draft.compose_kind === "any_of" ? "any can fire" : "all must fire" }})
          </label>
          <div v-for="(_, i) in draft.extra_phrases" :key="i" class="flex gap-2">
            <input
              v-model="draft.extra_phrases[i]"
              class="border rounded px-2 py-1 flex-1"
              placeholder="another phrase"
            />
            <button
              type="button"
              class="text-xs text-red-700 hover:underline"
              @click="removeExtraPhrase(i)"
            >remove</button>
          </div>
          <button
            type="button"
            class="text-xs text-blue-700 hover:underline w-fit"
            @click="addExtraPhrase"
          >+ add phrase</button>
        </template>

        <label class="text-xs text-slate-500">Threshold (0.0 – 1.0)</label>
        <input
          v-model.number="draft.threshold"
          type="number"
          min="0"
          max="1"
          step="0.01"
          class="border rounded px-2 py-1 w-24"
        />
        <div class="flex gap-2">
          <div>
            <label class="text-xs text-slate-500">Origin</label>
            <input
              :value="draft.origin_iso"
              @input="draft.origin_iso = ($event.target as HTMLInputElement).value.toUpperCase()"
              class="border rounded px-2 py-1 w-20 block"
            />
          </div>
          <div>
            <label class="text-xs text-slate-500">Destination</label>
            <input
              :value="draft.destination_iso"
              @input="draft.destination_iso = ($event.target as HTMLInputElement).value.toUpperCase()"
              class="border rounded px-2 py-1 w-20 block"
            />
          </div>
        </div>
        <label class="text-xs text-slate-500">Conditions JSON (optional)</label>
        <textarea
          v-model="draft.conditions_json"
          class="border rounded px-2 py-1 font-mono text-xs"
          rows="3"
          placeholder='{"min_value": 5000, "currency_in": ["USD"]}'
        />
        <label class="flex items-center gap-2 text-xs">
          <input v-model="draft.active" type="checkbox" /> active
        </label>
        <button
          class="bg-slate-900 text-white px-3 py-2 rounded text-sm w-fit mt-2 disabled:opacity-50"
          :disabled="!draft.name || !draft.phrase || savePending"
          @click="save"
        >
          {{ editId ? "Save new version" : "Create rule" }}
        </button>
        <span v-if="saveError" class="text-xs text-red-700">{{ saveError.message }}</span>
      </div>

      <hr class="my-4" />
      <h3 class="text-xs uppercase text-slate-500 mb-2">Test draft phrase</h3>
      <textarea
        v-model="testText"
        class="border rounded px-2 py-1 w-full"
        rows="2"
        placeholder="sample cargo text"
      />
      <button
        class="bg-slate-200 px-3 py-1 rounded text-sm mt-2"
        :disabled="!draft.phrase || !testText"
        @click="testDraft"
      >Test</button>
      <div v-if="testResp" class="mt-3 text-sm">
        <div>Similarity: <span class="font-mono">{{ testResp.phrase_similarity.toFixed(3) }}</span></div>
        <div>Threshold: <span class="font-mono">{{ testResp.threshold.toFixed(2) }}</span></div>
        <div>
          Delta:
          <span :class="['font-mono', testResp.delta_above_threshold >= 0 ? 'text-emerald-700' : 'text-red-700']">
            {{ testResp.delta_above_threshold.toFixed(3) }}
          </span>
        </div>
      </div>
    </section>
  </div>
</template>
