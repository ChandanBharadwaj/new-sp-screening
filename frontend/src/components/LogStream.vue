<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useEventSource, type LogEntry } from "../api/useEventSource";

const props = withDefaults(
  defineProps<{
    runTable: "refdata_run" | "training_run" | "eval_job";
    runId: number;
    height?: string;
  }>(),
  { height: "12rem" }
);

const emit = defineEmits<{ done: [status: string] }>();

const entries = ref<LogEntry[]>([]);
const scrollRef = ref<HTMLDivElement | null>(null);

const url = computed(() => `/api/v1/jobs/${props.runTable}/${props.runId}/stream`);

// Reset entries whenever we point at a new run.
watch(url, () => {
  entries.value = [];
});

const { status, error } = useEventSource({
  url,
  onLog: (entry) => {
    entries.value.push(entry);
  },
  onDone: (s) => emit("done", s),
});

watch(
  () => entries.value.length,
  () => {
    void nextTick(() => {
      if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
    });
  }
);

function levelClass(level: string) {
  return level === "error" ? "text-red-300" : level === "warn" ? "text-amber-300" : "text-slate-100";
}

function formatTs(ts: string | null) {
  return ts ? new Date(ts).toLocaleTimeString() : "";
}

const statusClass = computed(() =>
  status.value === "success"
    ? "bg-emerald-700"
    : status.value === "failed"
    ? "bg-red-700"
    : "bg-blue-700 animate-pulse"
);
</script>

<template>
  <div class="border rounded bg-slate-900 text-slate-100">
    <div class="px-3 py-1 text-xs flex items-center gap-2 border-b border-slate-700">
      <span class="font-mono text-slate-400">{{ runTable }}/{{ runId }}</span>
      <span :class="['px-1.5 py-0.5 rounded text-xs', statusClass]">{{ status }}</span>
      <span v-if="error" class="text-red-400 ml-auto">{{ error }}</span>
    </div>
    <div
      ref="scrollRef"
      class="font-mono text-xs px-3 py-2 overflow-auto whitespace-pre-wrap"
      :style="{ height }"
    >
      <div v-if="entries.length === 0" class="text-slate-500">Waiting for output…</div>
      <div v-for="e in entries" :key="e.id" :class="levelClass(e.level)">
        <span class="text-slate-500">{{ formatTs(e.ts) }}</span> {{ e.line }}
      </div>
    </div>
  </div>
</template>
