<script setup lang="ts">
import { ref, watch } from "vue";
import { api } from "../../api/client";
import { invalidateQueries } from "../../api/useFetch";

export type RuleMaterializationItem = {
  source: string;
  label: string;
  enabled: boolean;
  default_threshold: number;
  phrase_strategy: "description_only" | "with_aliases" | "split_lists";
  updated_at: string | null;
  active_rules: number;
};

type RunResult = {
  source: string;
  created: number;
  updated: number;
  deactivated: number;
  applied: number;
};

const props = defineProps<{ item: RuleMaterializationItem }>();

const draft = ref({
  enabled: props.item.enabled,
  default_threshold: props.item.default_threshold,
  phrase_strategy: props.item.phrase_strategy,
});
const savePending = ref(false);
const runPending = ref(false);
const saveError = ref<Error | null>(null);
const runError = ref<Error | null>(null);
const lastRun = ref<RunResult | null>(null);

// If the parent reloads the list (e.g. after a Run), the prop changes; reset
// the local draft so it reflects whatever the server now says.
watch(
  () => props.item,
  (next) => {
    draft.value = {
      enabled: next.enabled,
      default_threshold: next.default_threshold,
      phrase_strategy: next.phrase_strategy,
    };
  }
);

const STRATEGY_LABELS: Record<RuleMaterializationItem["phrase_strategy"], string> = {
  description_only: "Description only",
  with_aliases: "Description + aliases",
  split_lists: "Split lists + aliases",
};

async function save() {
  savePending.value = true;
  saveError.value = null;
  try {
    await api.put(`/api/v1/admin/rule-materialization/${props.item.source}`, {
      enabled: draft.value.enabled,
      default_threshold: Number(draft.value.default_threshold),
      phrase_strategy: draft.value.phrase_strategy,
    });
    invalidateQueries(["admin", "rule-materialization"]);
  } catch (e: any) {
    saveError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    savePending.value = false;
  }
}

async function run() {
  runPending.value = true;
  runError.value = null;
  try {
    lastRun.value = await api.post<RunResult>(
      `/api/v1/admin/rule-materialization/${props.item.source}/run`,
      {}
    );
    invalidateQueries(["admin", "rule-materialization"]);
    invalidateQueries(["rules"]);
  } catch (e: any) {
    runError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    runPending.value = false;
  }
}
</script>

<template>
  <div class="bg-white border rounded-lg p-4 shadow-sm" :data-source="item.source">
    <div class="flex items-start justify-between gap-3 mb-2">
      <div class="min-w-0">
        <div class="font-medium truncate">{{ item.label }}</div>
        <div class="font-mono text-xs text-slate-500">{{ item.source }}</div>
      </div>
      <div class="text-right shrink-0">
        <div class="text-xs uppercase text-slate-500">Active rules</div>
        <div class="text-2xl font-mono">{{ item.active_rules }}</div>
      </div>
    </div>

    <div class="grid sm:grid-cols-3 gap-3 text-sm mt-3">
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Enabled</span>
        <label class="inline-flex items-center gap-2 mt-1">
          <input
            type="checkbox"
            v-model="draft.enabled"
            class="w-4 h-4"
            :aria-label="`Enable rule materialization for ${item.source}`"
          />
          <span class="text-xs">
            {{ draft.enabled ? "on — auto-run after ingest" : "off — no rules generated" }}
          </span>
        </label>
      </label>

      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Default threshold</span>
        <input
          v-model.number="draft.default_threshold"
          type="number"
          min="0"
          max="1"
          step="0.05"
          class="border rounded px-2 py-1 font-mono text-sm mt-1"
        />
      </label>

      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Phrase strategy</span>
        <select v-model="draft.phrase_strategy" class="border rounded px-2 py-1 text-sm mt-1">
          <option v-for="(label, val) in STRATEGY_LABELS" :key="val" :value="val">
            {{ label }}
          </option>
        </select>
      </label>
    </div>

    <div class="flex flex-wrap items-center gap-2 mt-4">
      <button
        class="bg-slate-900 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="savePending"
        @click="save"
      >
        {{ savePending ? "Saving…" : "Save config" }}
      </button>
      <button
        class="bg-emerald-700 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="runPending || !item.enabled"
        :title="
          !item.enabled
            ? 'Enable and save first — disabled sources skip materialization'
            : 'Re-derive ScreeningRule rows from current sanction data for this source'
        "
        @click="run"
      >
        {{ runPending ? "Running…" : "Re-materialize now" }}
      </button>
      <span v-if="item.updated_at" class="text-xs text-slate-500 ml-auto">
        Config updated {{ item.updated_at }}
      </span>
    </div>

    <div v-if="lastRun" class="mt-3 text-xs bg-slate-50 border rounded p-2 font-mono">
      Applied {{ lastRun.applied }}
      <span class="text-slate-500">
        (created {{ lastRun.created }} · updated {{ lastRun.updated }} ·
        deactivated {{ lastRun.deactivated }})
      </span>
    </div>
    <div v-if="saveError" class="mt-2 text-xs text-red-700">{{ saveError.message }}</div>
    <div v-if="runError" class="mt-2 text-xs text-red-700">{{ runError.message }}</div>
  </div>
</template>
