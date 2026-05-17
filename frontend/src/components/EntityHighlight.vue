<script setup lang="ts">
import { computed } from "vue";

type EntitySpan = {
  text: string;
  start: number;
  end: number;
  score: number;
};

// Tolerates the legacy `{label: ["surface_form", ...]}` shape (persisted results
// from before NER span preservation) — those render as plain text, no overlay.
type EntitiesInput =
  | Record<string, Array<EntitySpan | string>>
  | null
  | undefined;

const props = defineProps<{ text: string; entities: EntitiesInput }>();

// Per-label background colors. Stable across labels we know about; unknown
// labels cycle through the same palette.
const LABEL_COLORS: Record<string, string> = {
  material: "bg-amber-100 border-amber-300",
  form: "bg-sky-100 border-sky-300",
  end_use: "bg-emerald-100 border-emerald-300",
  processing_state: "bg-violet-100 border-violet-300",
  composition_percentages: "bg-pink-100 border-pink-300",
  dimensions: "bg-slate-100 border-slate-300",
};
const FALLBACK_COLORS = [
  "bg-amber-100 border-amber-300",
  "bg-sky-100 border-sky-300",
  "bg-emerald-100 border-emerald-300",
  "bg-violet-100 border-violet-300",
];

function colorFor(label: string): string {
  return (
    LABEL_COLORS[label] ??
    FALLBACK_COLORS[
      Math.abs(
        Array.from(label).reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7)
      ) % FALLBACK_COLORS.length
    ]
  );
}

type Span = { label: string; start: number; end: number; score: number };

const segments = computed(() => {
  const text = props.text ?? "";
  if (!text) return [{ kind: "plain" as const, text: "" }];

  const spans: Span[] = [];
  for (const [label, items] of Object.entries(props.entities ?? {})) {
    for (const item of items ?? []) {
      if (typeof item === "string") continue; // legacy shape — skip overlay
      if (
        typeof item.start !== "number" ||
        typeof item.end !== "number" ||
        item.end <= item.start
      ) {
        continue;
      }
      spans.push({
        label,
        start: Math.max(0, item.start),
        end: Math.min(text.length, item.end),
        score: item.score ?? 0,
      });
    }
  }

  // Overlap resolution: longer span wins; on tie, higher score wins.
  spans.sort((a, b) => {
    const lenDelta = b.end - b.start - (a.end - a.start);
    if (lenDelta !== 0) return lenDelta;
    return (b.score ?? 0) - (a.score ?? 0);
  });

  const taken = new Array<boolean>(text.length).fill(false);
  const kept: Span[] = [];
  for (const s of spans) {
    let conflict = false;
    for (let i = s.start; i < s.end; i++) {
      if (taken[i]) {
        conflict = true;
        break;
      }
    }
    if (conflict) continue;
    for (let i = s.start; i < s.end; i++) taken[i] = true;
    kept.push(s);
  }

  kept.sort((a, b) => a.start - b.start);

  const out: Array<{ kind: "plain" | "marked"; text: string; label?: string; score?: number }> = [];
  let cursor = 0;
  for (const s of kept) {
    if (s.start > cursor) {
      out.push({ kind: "plain", text: text.slice(cursor, s.start) });
    }
    out.push({
      kind: "marked",
      text: text.slice(s.start, s.end),
      label: s.label,
      score: s.score,
    });
    cursor = s.end;
  }
  if (cursor < text.length) {
    out.push({ kind: "plain", text: text.slice(cursor) });
  }
  return out;
});

const legend = computed(() => {
  const seen = new Set<string>();
  for (const [label, items] of Object.entries(props.entities ?? {})) {
    if ((items ?? []).some((i) => typeof i !== "string")) seen.add(label);
  }
  return Array.from(seen).sort();
});
</script>

<template>
  <div>
    <p class="leading-relaxed">
      <template v-for="(seg, i) in segments" :key="i">
        <mark
          v-if="seg.kind === 'marked'"
          :class="['rounded px-0.5 border', colorFor(seg.label!)]"
          :title="`${seg.label} (${seg.score?.toFixed(2)})`"
        >{{ seg.text }}</mark>
        <span v-else>{{ seg.text }}</span>
      </template>
    </p>
    <div v-if="legend.length" class="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
      <span v-for="l in legend" :key="l" :class="['rounded px-1.5 py-0.5 border', colorFor(l)]">
        {{ l }}
      </span>
    </div>
  </div>
</template>
