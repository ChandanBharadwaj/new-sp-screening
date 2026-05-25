<script setup lang="ts">
import { ref, watch } from "vue";
import { api } from "../../api/client";
import { invalidateQueries } from "../../api/useFetch";

export type KeywordListItem = {
  name: string;
  label: string | null;
  origin_iso: string | null;
  destination_iso: string | null;
  direction: "import_from" | "export_to" | "both" | null;
  restriction_type: string;
  default_threshold: number;
  active: boolean;
  source_file: string | null;
  row_count: number;
  last_ingested_at: string | null;
  updated_at: string | null;
  source_key: string;
  file_present: boolean;
  active_rules: number;
  sanctioned_commodities: number;
};

const props = defineProps<{ item: KeywordListItem }>();
const emit = defineEmits<{ (e: "deleted"): void }>();

const draft = ref({
  label: props.item.label ?? "",
  origin_iso: props.item.origin_iso ?? "",
  destination_iso: props.item.destination_iso ?? "",
  direction: props.item.direction ?? "",
  restriction_type: props.item.restriction_type,
  default_threshold: props.item.default_threshold,
  active: props.item.active,
});

const savePending = ref(false);
const uploadPending = ref(false);
const runPending = ref(false);
const deletePending = ref(false);
const confirmDelete = ref(false);
const saveError = ref<Error | null>(null);
const uploadError = ref<Error | null>(null);
const runError = ref<Error | null>(null);

watch(
  () => props.item,
  (next) => {
    draft.value = {
      label: next.label ?? "",
      origin_iso: next.origin_iso ?? "",
      destination_iso: next.destination_iso ?? "",
      direction: next.direction ?? "",
      restriction_type: next.restriction_type,
      default_threshold: next.default_threshold,
      active: next.active,
    };
  }
);

async function save() {
  savePending.value = true;
  saveError.value = null;
  try {
    await api.put(`/api/v1/admin/keyword-lists/${props.item.name}`, {
      label: draft.value.label || null,
      origin_iso: draft.value.origin_iso ? draft.value.origin_iso.toUpperCase() : null,
      destination_iso: draft.value.destination_iso ? draft.value.destination_iso.toUpperCase() : null,
      direction: draft.value.direction || null,
      restriction_type: draft.value.restriction_type,
      default_threshold: Number(draft.value.default_threshold),
      active: draft.value.active,
    });
    invalidateQueries(["admin", "keyword-lists"]);
  } catch (e: any) {
    saveError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    savePending.value = false;
  }
}

async function onUploadFile(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploadPending.value = true;
  uploadError.value = null;
  try {
    const fd = new FormData();
    fd.append("file", file);
    await api.postForm(`/api/v1/admin/keyword-lists/${props.item.name}/upload`, fd);
    invalidateQueries(["admin", "keyword-lists"]);
  } catch (e: any) {
    uploadError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    uploadPending.value = false;
    input.value = "";
  }
}

async function run() {
  runPending.value = true;
  runError.value = null;
  try {
    await api.post(`/api/v1/admin/keyword-lists/${props.item.name}/run`, {});
    invalidateQueries(["admin", "keyword-lists"]);
    invalidateQueries(["rules"]);
  } catch (e: any) {
    runError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    runPending.value = false;
  }
}

async function doDelete() {
  deletePending.value = true;
  try {
    await api.del(`/api/v1/admin/keyword-lists/${props.item.name}`);
    invalidateQueries(["admin", "keyword-lists"]);
    invalidateQueries(["rules"]);
    emit("deleted");
  } finally {
    deletePending.value = false;
    confirmDelete.value = false;
  }
}
</script>

<template>
  <div class="bg-white border rounded-lg p-4 shadow-sm" :data-name="item.name">
    <div class="flex items-start justify-between gap-3 mb-2">
      <div class="min-w-0">
        <div class="font-medium truncate">{{ item.label || item.name }}</div>
        <div class="font-mono text-xs text-slate-500">{{ item.source_key }}</div>
      </div>
      <div class="text-right shrink-0">
        <div class="text-xs uppercase text-slate-500">Active rules</div>
        <div class="text-2xl font-mono">{{ item.active_rules }}</div>
        <div class="text-xs text-slate-500">
          {{ item.sanctioned_commodities }} commodities
        </div>
      </div>
    </div>

    <div class="grid sm:grid-cols-2 gap-3 text-sm mt-3">
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Label (optional)</span>
        <input
          v-model="draft.label"
          type="text"
          class="border rounded px-2 py-1 text-sm mt-1"
        />
      </label>
      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Restriction type</span>
        <input
          v-model="draft.restriction_type"
          type="text"
          class="border rounded px-2 py-1 text-sm mt-1 font-mono"
          placeholder="watchlist"
        />
      </label>

      <div class="flex gap-2">
        <label class="flex flex-col">
          <span class="text-xs text-slate-500">Origin</span>
          <input
            :value="draft.origin_iso"
            @input="draft.origin_iso = ($event.target as HTMLInputElement).value.toUpperCase()"
            maxlength="2"
            class="border rounded px-2 py-1 text-sm mt-1 w-20 font-mono"
            placeholder="ISO"
          />
        </label>
        <label class="flex flex-col">
          <span class="text-xs text-slate-500">Destination</span>
          <input
            :value="draft.destination_iso"
            @input="draft.destination_iso = ($event.target as HTMLInputElement).value.toUpperCase()"
            maxlength="2"
            class="border rounded px-2 py-1 text-sm mt-1 w-20 font-mono"
            placeholder="ISO"
          />
        </label>
      </div>

      <label class="flex flex-col">
        <span class="text-xs text-slate-500">Direction</span>
        <select v-model="draft.direction" class="border rounded px-2 py-1 text-sm mt-1">
          <option value="">— global (any pair)</option>
          <option value="import_from">import_from origin</option>
          <option value="export_to">export_to destination</option>
          <option value="both">both</option>
        </select>
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

      <label class="flex items-center gap-2 text-sm mt-5">
        <input v-model="draft.active" type="checkbox" /> active
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

      <label
        class="bg-slate-100 border px-3 py-1.5 rounded text-sm cursor-pointer hover:bg-slate-200"
        :class="uploadPending ? 'opacity-50 pointer-events-none' : ''"
      >
        {{ uploadPending ? "Uploading…" : (item.file_present ? "Replace CSV" : "Upload CSV") }}
        <input type="file" accept=".csv" class="hidden" @change="onUploadFile" />
      </label>

      <button
        class="bg-emerald-700 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="runPending || !item.file_present || !item.active"
        :title="
          !item.file_present
            ? 'Upload a CSV first'
            : !item.active
              ? 'List is inactive — enable and save first'
              : 'Re-ingest the CSV and materialize rules'
        "
        @click="run"
      >
        {{ runPending ? "Running…" : "Run ingest" }}
      </button>

      <button
        v-if="!confirmDelete"
        class="text-xs text-red-700 ml-auto hover:underline"
        @click="confirmDelete = true"
      >Delete list</button>
      <div v-else class="ml-auto flex items-center gap-2">
        <span class="text-xs text-red-700">Delete this list + all its rules?</span>
        <button
          class="bg-red-700 text-white px-2 py-1 rounded text-xs"
          :disabled="deletePending"
          @click="doDelete"
        >Confirm</button>
        <button class="text-xs text-slate-600" @click="confirmDelete = false">Cancel</button>
      </div>
    </div>

    <div
      v-if="item.last_ingested_at"
      class="mt-3 text-xs text-slate-500"
    >
      Last ingested {{ item.last_ingested_at }} · {{ item.row_count }} rows in file
    </div>
    <div v-if="saveError" class="mt-2 text-xs text-red-700">{{ saveError.message }}</div>
    <div v-if="uploadError" class="mt-2 text-xs text-red-700">{{ uploadError.message }}</div>
    <div v-if="runError" class="mt-2 text-xs text-red-700">{{ runError.message }}</div>
  </div>
</template>
