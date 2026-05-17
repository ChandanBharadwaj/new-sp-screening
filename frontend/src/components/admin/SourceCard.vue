<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../../api/client";
import { invalidateQueries } from "../../api/useFetch";
import StatusBadge from "../StatusBadge.vue";
import LogStream from "../LogStream.vue";

export type FileSlot = {
  key: string;
  label: string;
  path: string;
  accept?: string;
  optional?: boolean;
  present: boolean;
  size_bytes: number | null;
};

export type ParamDef = {
  type: "int" | "float" | "str";
  default: string | number | null;
  required?: boolean;
  enum?: string[];
};

export type Source = {
  source: string;
  label: string;
  kind: "taxonomy" | "labels" | "sanctions" | "derived";
  auto_download: boolean;
  publisher_url: string | null;
  files: FileSlot[];
  params_schema: Record<string, ParamDef>;
  depends_on: string[];
  row_count: number;
  ready_to_run: boolean;
  last_run: {
    id: number;
    started_at: string | null;
    finished_at: string | null;
    rows_upserted: number | null;
    status: string;
    error_message: string | null;
  } | null;
};

const props = defineProps<{ source: Source }>();

const params = ref<Record<string, string>>({});
const runPending = ref(false);
const runError = ref<Error | null>(null);

function coerceParams(): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, def] of Object.entries(props.source.params_schema)) {
    const raw = params.value[k];
    if (raw === undefined || raw === "") {
      if (def.default !== null && def.default !== undefined) out[k] = def.default;
      continue;
    }
    if (def.type === "int") out[k] = parseInt(raw, 10);
    else if (def.type === "float") out[k] = parseFloat(raw);
    else out[k] = raw;
  }
  return out;
}

async function run() {
  runPending.value = true;
  runError.value = null;
  try {
    await api.post("/api/v1/admin/refdata/" + props.source.source + "/run", {
      params: coerceParams(),
    });
    invalidateQueries(["admin", "sources"]);
  } catch (e: any) {
    runError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    runPending.value = false;
  }
}

async function uploadFile(key: string, ev: Event) {
  const target = ev.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  await api.postForm(
    "/api/v1/admin/refdata/" + props.source.source + "/upload?key=" + key,
    form
  );
  invalidateQueries(["admin", "sources"]);
}

const lr = computed(() => props.source.last_run);
const runLabel = computed(() => (props.source.auto_download ? "Reload from internet" : "Run"));

const progressPct = computed(() => {
  const r = lr.value;
  if (!r) return null;
  if (r.rows_upserted == null || props.source.row_count <= 0 || r.status !== "running") return null;
  return Math.min(
    100,
    Math.round(100 * (r.rows_upserted / Math.max(props.source.row_count, r.rows_upserted)))
  );
});

function entries(obj: Record<string, ParamDef>) {
  return Object.entries(obj);
}
</script>

<template>
  <div class="border rounded-lg p-4 bg-white shadow-sm">
    <div class="flex items-start justify-between gap-3 flex-wrap">
      <div>
        <div class="flex items-center gap-2 flex-wrap">
          <h3 class="font-semibold">{{ source.label }}</h3>
          <span
            v-if="source.auto_download"
            class="px-1.5 py-0.5 rounded text-xs bg-indigo-100 text-indigo-800"
          >Internet source</span>
          <span v-else class="px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-600">File upload</span>
        </div>
        <div class="text-xs text-slate-500 font-mono mt-0.5">
          {{ source.source }} · kind={{ source.kind }}
          <template v-if="source.depends_on.length > 0">
            · depends on {{ source.depends_on.join(", ") }}
          </template>
        </div>
        <div v-if="source.publisher_url" class="text-xs mt-1">
          Source:
          <a
            class="text-blue-700 hover:underline break-all"
            :href="source.publisher_url"
            target="_blank"
            rel="noreferrer"
          >{{ source.publisher_url }}</a>
        </div>
        <div v-if="lr?.finished_at" class="text-xs text-slate-500 mt-1">
          Last loaded: {{ new Date(lr.finished_at).toLocaleString() }}
        </div>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <StatusBadge :status="lr ? lr.status : 'never_run'" />
        <span class="text-slate-500">
          rows: <span class="font-mono">{{ source.row_count.toLocaleString() }}</span>
        </span>
      </div>
    </div>

    <div v-if="source.files.length > 0" class="mt-3 grid gap-2 text-sm">
      <div v-for="f in source.files" :key="f.key" class="flex items-center gap-3">
        <span class="w-40 text-slate-500 text-xs">
          {{ f.label }}<template v-if="f.optional"> (optional)</template>
        </span>
        <span v-if="f.present" class="text-emerald-700 text-xs">
          ✓ {{ f.path }} ({{ Math.round((f.size_bytes ?? 0) / 1024) }} KB)
        </span>
        <span v-else class="text-slate-400 text-xs">{{ f.path }} (not uploaded)</span>
        <label class="ml-auto text-xs text-blue-700 hover:underline cursor-pointer">
          Upload
          <input
            type="file"
            class="hidden"
            :accept="f.accept"
            @change="uploadFile(f.key, $event)"
          />
        </label>
      </div>
    </div>

    <div v-if="entries(source.params_schema).length > 0" class="flex flex-wrap gap-2 mt-2">
      <label v-for="[k, def] in entries(source.params_schema)" :key="k" class="text-xs flex flex-col">
        <span class="text-slate-500">{{ k }}<template v-if="def.required"> *</template></span>
        <select
          v-if="def.enum"
          v-model="params[k]"
          class="border rounded px-2 py-1 text-sm"
        >
          <option v-for="v in def.enum" :key="v" :value="v">{{ v }}</option>
        </select>
        <input
          v-else
          v-model="params[k]"
          class="border rounded px-2 py-1 text-sm w-24"
          :placeholder="def.default != null ? String(def.default) : ''"
        />
      </label>
    </div>

    <div class="mt-3 flex items-center gap-3">
      <button
        class="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
        :disabled="!source.ready_to_run || runPending"
        @click="run"
      >
        {{ lr?.status === "running" ? "Running…" : runLabel }}
      </button>
      <span v-if="!source.ready_to_run" class="text-xs text-amber-700">Upload required files first.</span>
      <span v-if="runError" class="text-xs text-red-700">{{ runError.message }}</span>
      <div v-if="progressPct !== null" class="flex items-center gap-2 ml-2">
        <div class="w-32 h-2 bg-slate-200 rounded">
          <div class="h-2 bg-emerald-500 rounded" :style="{ width: progressPct + '%' }" />
        </div>
        <span class="text-xs font-mono">{{ lr?.rows_upserted }}</span>
      </div>
      <span v-if="lr?.status === 'running' && progressPct === null" class="text-xs text-blue-700">
        running…<template v-if="lr.rows_upserted"> {{ lr.rows_upserted }} rows</template>
      </span>
    </div>

    <pre v-if="lr?.error_message" class="mt-2 text-xs bg-red-50 text-red-800 p-2 rounded overflow-auto">
{{ lr.error_message }}
    </pre>

    <div v-if="lr?.status === 'running' && lr?.id" class="mt-3">
      <LogStream run-table="refdata_run" :run-id="lr.id" height="10rem" />
    </div>
  </div>
</template>
