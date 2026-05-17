<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <section class="bg-white border rounded-lg p-4 shadow-sm">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">{{ title }}</h2>
      <slot name="right" />
    </div>
    <slot />
  </section>
</template>
