<script setup lang="ts">
import { ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../api/client";
import Bar from "../components/Bar.vue";

type Candidate = {
  hs_code: string;
  level: string;
  chapter: string;
  title: string;
  score: number;
  score_components: Record<string, number>;
};

type SanctionMatch = {
  source: string;
  source_record_id: string;
  description: string;
  similarity: number;
  hs_code_overlap: string[];
  restriction_type: string | null;
  provenance_url: string | null;
};

type RuleMatch = {
  rule_id: number;
  rule_name: string;
  phrase: string;
  phrase_similarity: number;
  threshold: number;
  delta_above_threshold: number;
  conditions_satisfied: boolean;
};

type ScreenResponse = {
  shipment_id: string;
  engine_version: string;
  hs_classification: {
    top_candidates: Candidate[];
    chapter_distribution: Record<string, number>;
    confidence_metrics: Record<string, number | boolean | null>;
  };
  sanction_matches: SanctionMatch[];
  rule_matches: RuleMatch[];
  extracted_entities: Record<string, unknown>;
  latency_ms: Record<string, number>;
};

const commodity = ref("");
const cargo = ref("");
const origin = ref("");
const destination = ref("");
const externalRef = ref("");

const result = ref<ScreenResponse | null>(null);
const pending = ref(false);
const error = ref<Error | null>(null);

async function submit() {
  pending.value = true;
  error.value = null;
  try {
    result.value = await api.post<ScreenResponse>("/api/v1/screen", {
      external_ref: externalRef.value || null,
      commodity_text: commodity.value,
      cargo_text: cargo.value || null,
      origin_iso: origin.value || null,
      destination_iso: destination.value || null,
    });
  } catch (e: any) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    pending.value = false;
  }
}

function uppercase(target: "origin" | "destination", value: string) {
  if (target === "origin") origin.value = value.toUpperCase();
  else destination.value = value.toUpperCase();
}
</script>

<template>
  <div class="grid gap-4">
    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">
        Screen a single shipment
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
        <label class="flex flex-col gap-1 md:col-span-2">
          <span class="text-xs text-slate-500">Commodity text *</span>
          <input
            v-model="commodity"
            class="border rounded px-2 py-1"
            placeholder="e.g. stainless steel screws"
          />
        </label>
        <label class="flex flex-col gap-1 md:col-span-2">
          <span class="text-xs text-slate-500">Cargo / packing text (optional)</span>
          <input
            v-model="cargo"
            class="border rounded px-2 py-1"
            placeholder="e.g. wooden crates"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-xs text-slate-500">Origin (ISO-2)</span>
          <input
            :value="origin"
            @input="uppercase('origin', ($event.target as HTMLInputElement).value)"
            maxlength="2"
            class="border rounded px-2 py-1 font-mono uppercase"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-xs text-slate-500">Destination (ISO-2)</span>
          <input
            :value="destination"
            @input="uppercase('destination', ($event.target as HTMLInputElement).value)"
            maxlength="2"
            class="border rounded px-2 py-1 font-mono uppercase"
          />
        </label>
        <label class="flex flex-col gap-1 md:col-span-2">
          <span class="text-xs text-slate-500">External reference (optional)</span>
          <input v-model="externalRef" class="border rounded px-2 py-1" />
        </label>
      </div>
      <div class="mt-3 flex items-center gap-3">
        <button
          class="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
          :disabled="!commodity || pending"
          @click="submit"
        >
          {{ pending ? "Screening…" : "Screen shipment" }}
        </button>
        <span v-if="error" class="text-xs text-red-700">{{ error.message }}</span>
        <RouterLink
          v-if="result"
          :to="`/results/${result.shipment_id}`"
          class="text-xs text-blue-700 hover:underline"
        >
          View permanent result page →
        </RouterLink>
      </div>
    </section>

    <template v-if="result">
      <section class="bg-white border rounded-lg p-4 shadow-sm">
        <h3 class="text-sm uppercase text-slate-500 mb-2">HS Classification (top candidates)</h3>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th>HS Code</th>
              <th>Level</th>
              <th>Title</th>
              <th>Score</th>
              <th>Components</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in result.hs_classification.top_candidates" :key="c.hs_code" class="border-t align-top">
              <td class="py-2 font-mono">{{ c.hs_code }}</td>
              <td>{{ c.level }}</td>
              <td class="max-w-md">{{ c.title }}</td>
              <td class="font-mono">{{ c.score.toFixed(3) }}</td>
              <td>
                <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <div v-for="(v, k) in c.score_components" :key="k" class="flex items-center gap-2">
                    <span class="text-slate-500 w-24">{{ k }}</span>
                    <Bar :value="Number(v)" />
                    <span class="font-mono">{{ Number(v).toFixed(3) }}</span>
                  </div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="bg-white border rounded-lg p-4 shadow-sm">
        <h3 class="text-sm uppercase text-slate-500 mb-2">Sanction matches</h3>
        <p v-if="result.sanction_matches.length === 0" class="text-slate-500 text-sm">No sanction matches.</p>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th>Source</th>
              <th>ID</th>
              <th>Description</th>
              <th>Similarity</th>
              <th>HS overlap</th>
              <th>Provenance</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in result.sanction_matches" :key="m.source_record_id + m.source" class="border-t align-top">
              <td class="py-1 font-mono">{{ m.source }}</td>
              <td class="font-mono text-xs">{{ m.source_record_id }}</td>
              <td class="max-w-md truncate" :title="m.description">{{ m.description }}</td>
              <td class="font-mono">{{ m.similarity.toFixed(3) }}</td>
              <td class="font-mono text-xs">{{ m.hs_code_overlap.join(", ") || "—" }}</td>
              <td>
                <a
                  v-if="m.provenance_url"
                  class="text-blue-700 hover:underline text-xs"
                  :href="m.provenance_url"
                  target="_blank"
                  rel="noreferrer"
                >link</a>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="bg-white border rounded-lg p-4 shadow-sm">
        <h3 class="text-sm uppercase text-slate-500 mb-2">Rule matches</h3>
        <p v-if="result.rule_matches.length === 0" class="text-slate-500 text-sm">No rule matches.</p>
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs uppercase text-slate-500">
              <th>Rule</th>
              <th>Phrase</th>
              <th>Sim.</th>
              <th>Δ</th>
              <th>Conds</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in result.rule_matches" :key="r.rule_id" class="border-t">
              <td class="py-1">{{ r.rule_name }}</td>
              <td class="max-w-md truncate" :title="r.phrase">{{ r.phrase }}</td>
              <td class="font-mono">{{ r.phrase_similarity.toFixed(3) }}</td>
              <td :class="['font-mono', r.delta_above_threshold >= 0 ? 'text-emerald-700' : 'text-slate-500']">
                {{ r.delta_above_threshold.toFixed(3) }}
              </td>
              <td>{{ r.conditions_satisfied ? "✓" : "✗" }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="bg-white border rounded-lg p-4 shadow-sm">
        <h3 class="text-sm uppercase text-slate-500 mb-2">Confidence</h3>
        <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto">{{ JSON.stringify(result.hs_classification.confidence_metrics, null, 2) }}</pre>
      </section>

      <section class="bg-white border rounded-lg p-4 shadow-sm">
        <h3 class="text-sm uppercase text-slate-500 mb-2">Latency (ms)</h3>
        <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto">{{ JSON.stringify(result.latency_ms, null, 2) }}</pre>
      </section>
    </template>
  </div>
</template>
