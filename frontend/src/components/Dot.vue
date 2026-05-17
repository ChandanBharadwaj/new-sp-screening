<script setup lang="ts">
defineProps<{ ok: boolean }>();
</script>

<template>
  <span :class="['inline-block w-2 h-2 rounded-full', ok ? 'bg-emerald-500' : 'bg-red-500']" />
</template>
