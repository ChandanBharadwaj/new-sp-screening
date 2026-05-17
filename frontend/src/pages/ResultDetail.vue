<script setup lang="ts">
import { computed, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { api } from "../api/client";
import { useFetch, invalidateQueries } from "../api/useFetch";
import Bar from "../components/Bar.vue";
import EntityHighlight from "../components/EntityHighlight.vue";

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
  country_pair_applicable: boolean;
  hs_code_overlap: string[];
  restriction_type: string | null;
  provenance_url: string | null;
  score_components: Record<string, number | boolean>;
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

type Detail = {
  result_id: string;
  shipment_id: string;
  engine_version: string;
  shipment: {
    commodity_text: string;
    cargo_text: string | null;
    origin_iso: string | null;
    destination_iso: string | null;
  };
  hs_classification: {
    top_candidates: Candidate[];
    chapter_distribution: Record<string, number>;
    confidence_metrics: Record<string, number | boolean>;
  };
  sanction_matches: SanctionMatch[];
  rule_matches: RuleMatch[];
  // Either the legacy `dict[label, list[str]]` shape or the structured
  // `dict[label, list[{text, start, end, score}]]` shape. EntityHighlight
  // tolerates both — strings render as plain text without overlay.
  extracted_entities: Record<string, Array<string | { text: string; start: number; end: number; score: number }>>;
  latency_ms: Record<string, number>;
};

const route = useRoute();
const id = computed(() => (Array.isArray(route.params.id) ? route.params.id[0] : route.params.id));

const q = useFetch<Detail>({
  key: computed(() => ["result", id.value] as const),
  enabled: computed(() => !!id.value),
  fetcher: () => api.get<Detail>(`/api/v1/results/${id.value}`),
});

const hsCorrection = ref("");
const noteText = ref("");
const feedbackPending = ref(false);

async function postFeedback(body: Record<string, unknown>) {
  feedbackPending.value = true;
  try {
    await api.post("/api/v1/feedback", body);
    invalidateQueries(["result", id.value]);
  } finally {
    feedbackPending.value = false;
  }
}

function submitCorrection() {
  const d = q.data.value;
  if (!d || !hsCorrection.value) return;
  const top1 = d.hs_classification.top_candidates[0];
  void postFeedback({
    result_id: d.result_id,
    event_type: "hs_corrected",
    before_value: { hs_code: top1?.hs_code, score: top1?.score },
    after_value: { hs_code: hsCorrection.value },
  });
}

function dismissSanction(m: SanctionMatch) {
  const d = q.data.value;
  if (!d) return;
  void postFeedback({
    result_id: d.result_id,
    event_type: "sanction_dismissed",
    before_value: { source: m.source, source_record_id: m.source_record_id, similarity: m.similarity },
  });
}

function dismissRule(r: RuleMatch) {
  const d = q.data.value;
  if (!d) return;
  void postFeedback({
    result_id: d.result_id,
    event_type: "rule_dismissed",
    before_value: { rule_id: r.rule_id, phrase_similarity: r.phrase_similarity },
  });
}

function saveNote() {
  const d = q.data.value;
  if (!d || !noteText.value) return;
  void postFeedback({
    result_id: d.result_id,
    event_type: "escalated",
    notes: noteText.value,
  }).then(() => {
    noteText.value = "";
  });
}
</script>

<template>
  <p v-if="q.isLoading.value || !q.data.value" class="text-slate-500">Loading…</p>
  <div v-else class="grid gap-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold">Result <code class="text-sm">{{ q.data.value.result_id }}</code></h2>
      <RouterLink to="/results" class="text-sm text-blue-700 hover:underline">← back</RouterLink>
    </div>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Shipment</h3>
      <div class="mb-1"><strong>Commodity:</strong></div>
      <EntityHighlight
        :text="q.data.value.shipment.commodity_text + (q.data.value.shipment.cargo_text ? ' ' + q.data.value.shipment.cargo_text : '')"
        :entities="q.data.value.extracted_entities"
      />
      <p class="text-sm text-slate-600 mt-2">
        Route: <span class="font-mono">{{ q.data.value.shipment.origin_iso ?? "??" }} → {{ q.data.value.shipment.destination_iso ?? "??" }}</span>
      </p>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">HS Classification (top candidates)</h3>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>HS Code</th><th>Level</th><th>Title</th><th>Score</th><th>Components</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in q.data.value.hs_classification.top_candidates" :key="c.hs_code" class="border-t align-top">
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

      <div class="mt-4 flex items-end gap-2">
        <div>
          <label class="text-xs text-slate-500 block">Correct HS code</label>
          <input
            v-model="hsCorrection"
            class="border rounded px-2 py-1 text-sm font-mono w-32"
            placeholder="620462"
          />
        </div>
        <button
          class="bg-slate-200 px-3 py-1 rounded text-sm"
          :disabled="!hsCorrection || feedbackPending"
          @click="submitCorrection"
        >Submit correction</button>
      </div>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Sanction matches</h3>
      <p v-if="q.data.value.sanction_matches.length === 0" class="text-slate-500 text-sm">No sanction matches.</p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>Source</th><th>ID</th><th>Description</th><th>Similarity</th>
            <th>HS overlap</th><th>Provenance</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in q.data.value.sanction_matches" :key="m.source_record_id + m.source" class="border-t align-top">
            <td class="py-1 font-mono">{{ m.source }}</td>
            <td class="font-mono text-xs">{{ m.source_record_id }}</td>
            <td class="max-w-md truncate" :title="m.description">{{ m.description }}</td>
            <td class="font-mono">{{ m.similarity.toFixed(3) }}</td>
            <td class="font-mono text-xs">{{ m.hs_code_overlap.join(", ") || "—" }}</td>
            <td>
              <a v-if="m.provenance_url" class="text-blue-700 hover:underline text-xs" :href="m.provenance_url" target="_blank" rel="noreferrer">link</a>
              <span v-else>—</span>
            </td>
            <td>
              <button class="text-xs text-red-700 hover:underline" @click="dismissSanction(m)">dismiss</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Rule matches</h3>
      <p v-if="q.data.value.rule_matches.length === 0" class="text-slate-500 text-sm">No rule matches.</p>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs uppercase text-slate-500">
            <th>Rule</th><th>Phrase</th><th>Sim.</th><th>Δ</th><th>Conds</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in q.data.value.rule_matches" :key="r.rule_id" class="border-t">
            <td class="py-1">{{ r.rule_name }}</td>
            <td class="max-w-md truncate" :title="r.phrase">{{ r.phrase }}</td>
            <td class="font-mono">{{ r.phrase_similarity.toFixed(3) }}</td>
            <td :class="['font-mono', r.delta_above_threshold >= 0 ? 'text-emerald-700' : 'text-slate-500']">
              {{ r.delta_above_threshold.toFixed(3) }}
            </td>
            <td>{{ r.conditions_satisfied ? "✓" : "✗" }}</td>
            <td>
              <button class="text-xs text-red-700 hover:underline" @click="dismissRule(r)">dismiss</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Note</h3>
      <textarea
        v-model="noteText"
        class="border rounded px-2 py-1 w-full"
        rows="2"
        placeholder="Free-text analyst note"
      />
      <button
        class="mt-2 bg-slate-200 px-3 py-1 rounded text-sm"
        :disabled="!noteText"
        @click="saveNote"
      >Save note</button>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Confidence</h3>
      <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto">{{ JSON.stringify(q.data.value.hs_classification.confidence_metrics, null, 2) }}</pre>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Extracted entities</h3>
      <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto">{{ JSON.stringify(q.data.value.extracted_entities, null, 2) }}</pre>
    </section>

    <section class="bg-white border rounded-lg p-4 shadow-sm">
      <h3 class="text-sm uppercase text-slate-500 mb-2">Latency (ms)</h3>
      <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto">{{ JSON.stringify(q.data.value.latency_ms, null, 2) }}</pre>
    </section>
  </div>
</template>
