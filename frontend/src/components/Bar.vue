<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{ value: number; max?: number }>(), { max: 1 });

const pct = computed(() => Math.min(100, Math.max(0, (props.value / props.max) * 100)));
</script>

<template>
  <div class="w-24 h-2 bg-slate-200 rounded">
    <div class="h-2 bg-slate-700 rounded" :style="{ width: pct + '%' }" />
  </div>
</template>
