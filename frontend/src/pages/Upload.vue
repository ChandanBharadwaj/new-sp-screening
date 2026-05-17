<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";

type UploadResp = { batch_id: string; total_rows: number; status: string };
type BatchStatus = {
  batch_id: string;
  filename: string;
  status: string;
  total_rows: number;
  completed_rows: number;
  failed_rows: number;
};

const file = ref<File | null>(null);
const batchId = ref<string | null>(null);
const uploading = ref(false);
const uploadError = ref<Error | null>(null);

async function submit() {
  if (!file.value) return;
  uploading.value = true;
  uploadError.value = null;
  try {
    const form = new FormData();
    form.append("file", file.value);
    const r = await api.postForm<UploadResp>("/api/v1/batch/upload", form);
    batchId.value = r.batch_id;
  } catch (e: any) {
    uploadError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    uploading.value = false;
  }
}

function onFileChange(ev: Event) {
  const target = ev.target as HTMLInputElement;
  file.value = target.files?.[0] ?? null;
}

const status = useFetch<BatchStatus>({
  key: computed(() => ["batch", batchId.value] as const),
  enabled: computed(() => !!batchId.value),
  refetchInterval: 2000,
  fetcher: () => api.get<BatchStatus>(`/api/v1/batch/${batchId.value}`),
});

const progressPct = computed(() => {
  const d = status.data.value;
  if (!d) return 0;
  return (100 * (d.completed_rows + d.failed_rows)) / Math.max(d.total_rows, 1);
});

type ErrorRow = {
  row_index: number;
  raw_row: Record<string, string | null> | null;
  error_message: string;
  created_at: string | null;
};

const showErrors = ref(false);
const errorsEnabled = computed(
  () => !!batchId.value && showErrors.value && (status.data.value?.failed_rows ?? 0) > 0
);

const errors = useFetch<{ items: ErrorRow[]; total: number }>({
  key: computed(() => ["batch-errors", batchId.value] as const),
  enabled: errorsEnabled,
  fetcher: () =>
    api.get<{ items: ErrorRow[]; total: number }>(
      `/api/v1/batch/${batchId.value}/errors?limit=500`
    ),
});

const errorsCsvUrl = computed(() =>
  batchId.value ? `/api/v1/batch/${batchId.value}/errors.csv` : "#"
);
</script>

<template>
  <div class="grid gap-4">
    <section class="bg-white border rounded-lg p-6 shadow-sm">
      <h2 class="text-lg font-semibold mb-3">Upload a shipment CSV</h2>
      <p class="text-sm text-slate-600 mb-4">
        Required column: <code class="bg-slate-100 px-1 rounded">commodity_text</code>.
        Optional: <code class="bg-slate-100 px-1 rounded">cargo_text</code>,
        <code class="bg-slate-100 px-1 rounded">origin_iso</code>,
        <code class="bg-slate-100 px-1 rounded">destination_iso</code>,
        <code class="bg-slate-100 px-1 rounded">external_ref</code>.
      </p>
      <div class="flex items-center gap-3">
        <input type="file" accept=".csv" class="text-sm" @change="onFileChange" />
        <button
          class="bg-slate-900 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          :disabled="!file || uploading"
          @click="submit"
        >
          {{ uploading ? "Uploading…" : "Upload" }}
        </button>
      </div>
      <p v-if="uploadError" class="text-red-600 text-sm mt-2">{{ uploadError.message }}</p>
    </section>

    <section v-if="batchId" class="bg-white border rounded-lg p-6 shadow-sm">
      <h2 class="text-lg font-semibold mb-3">Batch progress</h2>
      <p v-if="status.isLoading.value || !status.data.value" class="text-slate-500">Loading…</p>
      <div v-else class="text-sm">
        <div class="mb-2">Batch <code class="bg-slate-100 px-1 rounded">{{ status.data.value.batch_id }}</code></div>
        <div class="mb-2">Status: <strong>{{ status.data.value.status }}</strong></div>
        <div class="mb-2">
          Completed: {{ status.data.value.completed_rows }} / {{ status.data.value.total_rows }}
          (failed: {{ status.data.value.failed_rows }})
        </div>
        <div class="w-full h-3 bg-slate-200 rounded overflow-hidden">
          <div class="h-3 bg-emerald-500" :style="{ width: progressPct + '%' }" />
        </div>

        <div v-if="status.data.value.failed_rows > 0" class="mt-4 pt-4 border-t">
          <div class="flex items-center justify-between mb-2">
            <button
              class="text-sm text-blue-700 hover:underline"
              @click="showErrors = !showErrors"
            >
              {{ showErrors ? "Hide" : "Show" }} {{ status.data.value.failed_rows }} failed rows
            </button>
            <a
              :href="errorsCsvUrl"
              class="text-sm text-slate-600 hover:text-slate-900"
              download
            >
              Download errors as CSV
            </a>
          </div>
          <div v-if="showErrors">
            <p v-if="errors.isLoading.value" class="text-slate-500 text-sm">Loading errors…</p>
            <table v-else-if="errors.data.value" class="w-full text-xs mt-2">
              <thead>
                <tr class="text-left uppercase text-slate-500">
                  <th class="py-1">Row</th>
                  <th>External ref</th>
                  <th>Commodity</th>
                  <th>Route</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="e in errors.data.value.items" :key="e.row_index" class="border-t align-top">
                  <td class="py-1 font-mono">{{ e.row_index }}</td>
                  <td>{{ e.raw_row?.external_ref ?? "—" }}</td>
                  <td class="max-w-xs truncate" :title="e.raw_row?.commodity_text ?? ''">
                    {{ e.raw_row?.commodity_text ?? "—" }}
                  </td>
                  <td class="font-mono">
                    {{ e.raw_row?.origin_iso ?? "??" }} → {{ e.raw_row?.destination_iso ?? "??" }}
                  </td>
                  <td class="text-red-700">{{ e.error_message }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
