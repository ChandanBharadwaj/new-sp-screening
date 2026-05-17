<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  days: number | null;
  severity: "green" | "amber" | "red" | "gray";
}>();

const classes = computed(() => {
  switch (props.severity) {
    case "green":
      return "bg-emerald-100 text-emerald-800";
    case "amber":
      return "bg-amber-100 text-amber-800";
    case "red":
      return "bg-red-100 text-red-800";
    default:
      return "bg-slate-100 text-slate-600";
  }
});

const label = computed(() => {
  if (props.days === null || props.days === undefined) return "never loaded";
  if (props.days === 0) return "today";
  if (props.days === 1) return "1 day old";
  return `${props.days} days old`;
});
</script>

<template>
  <span :class="['px-2 py-0.5 rounded text-xs font-medium', classes]" :title="`Last successful refresh: ${label}`">
    {{ label }}
  </span>
</template>
