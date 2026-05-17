<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../../api/client";
import { useFetch } from "../../api/useFetch";
import Card from "../Card.vue";

type Row = {
  id: string;
  external_ref: string | null;
  commodity_text: string;
  cargo_text: string | null;
  origin_iso: string | null;
  destination_iso: string | null;
  shipment_value: number | null;
  currency: string | null;
  created_at: string | null;
};

const q = ref("");
const offset = ref(0);
const limit = 50;

const query = useFetch<{ items: Row[]; total: number }>({
  key: computed(() => ["data", "shipments", q.value, offset.value] as const),
  fetcher: () => {
    const sp = new URLSearchParams();
    if (q.value) sp.set("q", q.value);
    sp.set("limit", String(limit));
    sp.set("offset", String(offset.value));
    return api.get(`/api/v1/data/shipments?${sp.toString()}`);
  },
});

function changeQ(v: string) {
  q.value = v;
  offset.value = 0;
}
function prev() {
  offset.value = Math.max(0, offset.value - limit);
}
function next() {
  offset.value = offset.value + limit;
}
</script>

<template>
  <Card title="Shipments">
    <div class="flex items-end gap-2 text-sm mb-3">
      <input
        :value="q"
        class="border rounded px-2 py-1 w-64"
        placeholder="commodity contains…"
        @input="changeQ(($event.target as HTMLInputElement).value)"
      />
      <div v-if="query.data.value" class="ml-auto text-xs text-slate-500">
        total {{ query.data.value.total.toLocaleString() }}
      </div>
    </div>
    <p v-if="query.isLoading.value || !query.data.value" class="text-slate-500">Loading…</p>
    <p v-else-if="query.data.value.items.length === 0" class="text-slate-500 text-sm">No shipments yet.</p>
    <template v-else>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>When</th><th>Ref</th><th>Commodity</th><th>Route</th><th>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in query.data.value.items" :key="r.id" class="border-t">
            <td class="text-slate-600 py-1">{{ r.created_at ? new Date(r.created_at).toLocaleString() : "—" }}</td>
            <td>{{ r.external_ref ?? "—" }}</td>
            <td class="max-w-md truncate" :title="r.commodity_text">{{ r.commodity_text }}</td>
            <td class="font-mono text-xs">{{ r.origin_iso ?? "??" }} → {{ r.destination_iso ?? "??" }}</td>
            <td class="font-mono text-xs">
              {{ r.shipment_value ? `${r.shipment_value} ${r.currency ?? ""}` : "—" }}
            </td>
          </tr>
        </tbody>
      </table>
      <div class="flex items-center gap-2 mt-3 text-sm">
        <button class="px-3 py-1 bg-slate-200 rounded text-xs" :disabled="offset === 0" @click="prev">← Prev</button>
        <button
          class="px-3 py-1 bg-slate-200 rounded text-xs"
          :disabled="offset + limit >= (query.data.value.total ?? 0)"
          @click="next"
        >Next →</button>
      </div>
    </template>
  </Card>
</template>
