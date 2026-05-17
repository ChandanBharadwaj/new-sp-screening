<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: string }>();

const cls = computed(() =>
  props.status === "success"
    ? "bg-emerald-100 text-emerald-800"
    : props.status === "running"
    ? "bg-blue-100 text-blue-800 animate-pulse"
    : props.status === "failed"
    ? "bg-red-100 text-red-800"
    : "bg-slate-100 text-slate-600"
);
</script>

<template>
  <span :class="['px-2 py-0.5 rounded text-xs', cls]">{{ status }}</span>
</template>
