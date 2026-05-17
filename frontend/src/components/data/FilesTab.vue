<script setup lang="ts">
import { api } from "../../api/client";
import { useFetch } from "../../api/useFetch";
import Card from "../Card.vue";

type FileEntry = { path: string; size_bytes: number; modified_at: number };

const query = useFetch<{
  files: FileEntry[];
  root: string;
  total_files: number;
  total_bytes: number;
}>({
  key: ["data", "files"],
  fetcher: () => api.get("/api/v1/data/files"),
});
</script>

<template>
  <Card title="Files on disk">
    <template #right>
      <span v-if="query.data.value" class="text-xs text-slate-500">
        {{ query.data.value.total_files }} files ·
        {{ (query.data.value.total_bytes / 1024 / 1024).toFixed(1) }} MB
      </span>
    </template>
    <p v-if="query.isLoading.value || !query.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="query.data.value.files.length === 0" class="text-slate-500 text-sm">
      No source files cached yet.
    </p>
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs uppercase text-slate-500">
          <th>Path</th><th>Size</th><th>Modified</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="f in query.data.value.files" :key="f.path" class="border-t">
          <td class="py-1 font-mono text-xs">{{ f.path }}</td>
          <td class="font-mono text-xs">{{ (f.size_bytes / 1024).toFixed(1) }} KB</td>
          <td class="text-slate-600 text-xs">{{ new Date(f.modified_at * 1000).toLocaleString() }}</td>
        </tr>
      </tbody>
    </table>
  </Card>
</template>
