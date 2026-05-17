<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";

type HsNode = {
  code: string;
  level: number;
  parent_code: string | null;
  chapter: string;
  title: string;
  description: string | null;
  children?: HsNode[];
};

const search = ref("");
const code = ref<string | null>(null);

const root = useFetch<{ items: HsNode[] }>({
  key: ["hs", "tree"],
  fetcher: () => api.get<{ items: HsNode[] }>("/api/v1/hs/tree"),
});

const detail = useFetch<HsNode>({
  key: computed(() => ["hs", code.value] as const),
  enabled: computed(() => !!code.value),
  fetcher: () => api.get<HsNode>(`/api/v1/hs/${code.value}`),
});

const searchRes = useFetch<{ items: HsNode[] }>({
  key: computed(() => ["hs", "search", search.value] as const),
  enabled: computed(() => search.value.length > 1),
  fetcher: () => api.get<{ items: HsNode[] }>(`/api/v1/hs/search?q=${encodeURIComponent(search.value)}`),
});
</script>

<template>
  <div class="grid md:grid-cols-2 gap-4">
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm uppercase text-slate-500 mb-2">Browse</h2>
      <input
        v-model="search"
        class="w-full border rounded px-2 py-1 mb-3 text-sm"
        placeholder="Search HS titles…"
      />
      <template v-if="search.length > 1">
        <ul v-if="searchRes.data.value?.items.length" class="text-sm">
          <li v-for="n in searchRes.data.value.items" :key="n.code">
            <button class="text-left hover:underline" @click="code = n.code">
              <span class="font-mono">{{ n.code }}</span> · {{ n.title }}
            </button>
          </li>
        </ul>
        <p v-else class="text-xs text-slate-500">No matches.</p>
      </template>
      <p v-else-if="root.isLoading.value" class="text-slate-500">Loading chapters…</p>
      <p v-else-if="root.data.value?.items.length === 0" class="text-slate-500 text-sm">
        No HS data yet — run <code class="text-xs">python -m app.refdata.hts.ingest</code>.
      </p>
      <ul v-else class="text-sm">
        <li v-for="n in root.data.value?.items" :key="n.code">
          <button class="text-left hover:underline" @click="code = n.code">
            <span class="font-mono">{{ n.code }}</span> · {{ n.title }}
          </button>
        </li>
      </ul>
    </section>
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm uppercase text-slate-500 mb-2">Detail</h2>
      <p v-if="!code" class="text-slate-500 text-sm">Pick a code from the left.</p>
      <p v-else-if="detail.isLoading.value || !detail.data.value" class="text-slate-500">Loading…</p>
      <div v-else class="text-sm">
        <h3 class="font-semibold">
          <span class="font-mono">{{ detail.data.value.code }}</span> · {{ detail.data.value.title }}
        </h3>
        <p class="text-xs text-slate-500 mt-1">
          Level {{ detail.data.value.level }} · Chapter {{ detail.data.value.chapter }}
        </p>
        <p v-if="detail.data.value.description" class="mt-2">{{ detail.data.value.description }}</p>
        <template v-if="detail.data.value.children && detail.data.value.children.length > 0">
          <h4 class="mt-4 text-xs uppercase text-slate-500">Children</h4>
          <ul>
            <li v-for="c in detail.data.value.children" :key="c.code">
              <button class="text-left hover:underline" @click="code = c.code">
                <span class="font-mono">{{ c.code }}</span> · {{ c.title }}
              </button>
            </li>
          </ul>
        </template>
      </div>
    </section>
  </div>
</template>
