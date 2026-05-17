<script setup lang="ts">
import { ref } from "vue";
import { api } from "../../api/client";
import { invalidateQueries } from "../../api/useFetch";

const props = defineProps<{ source: string }>();
const pending = ref(false);

async function run() {
  pending.value = true;
  try {
    await api.post("/api/v1/admin/refdata/" + props.source + "/run", {});
    invalidateQueries(["status", "refdata"]);
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <button
    class="text-xs bg-slate-900 text-white px-2 py-1 rounded hover:bg-slate-700 disabled:opacity-50"
    :disabled="pending"
    @click="run"
  >{{ pending ? "…" : "Run" }}</button>
</template>
