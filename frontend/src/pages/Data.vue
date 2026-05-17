<script setup lang="ts">
import { ref } from "vue";
import TrainingExamplesTab from "../components/data/TrainingExamplesTab.vue";
import ShipmentsTab from "../components/data/ShipmentsTab.vue";
import EvalRunsTab from "../components/data/EvalRunsTab.vue";
import RefdataRunsTab from "../components/data/RefdataRunsTab.vue";
import FilesTab from "../components/data/FilesTab.vue";

type Tab = "training" | "shipments" | "evalruns" | "refdataruns" | "files";

const TABS: { id: Tab; label: string }[] = [
  { id: "training", label: "Training examples" },
  { id: "shipments", label: "Shipments" },
  { id: "evalruns", label: "Eval runs" },
  { id: "refdataruns", label: "Refdata runs" },
  { id: "files", label: "Files on disk" },
];

const tab = ref<Tab>("training");
</script>

<template>
  <div class="grid gap-4">
    <div class="flex gap-1 flex-wrap">
      <button
        v-for="t in TABS"
        :key="t.id"
        :class="[
          'px-3 py-1.5 rounded text-sm',
          tab === t.id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200',
        ]"
        @click="tab = t.id"
      >{{ t.label }}</button>
    </div>
    <TrainingExamplesTab v-if="tab === 'training'" />
    <ShipmentsTab v-else-if="tab === 'shipments'" />
    <EvalRunsTab v-else-if="tab === 'evalruns'" />
    <RefdataRunsTab v-else-if="tab === 'refdataruns'" />
    <FilesTab v-else-if="tab === 'files'" />
  </div>
</template>
