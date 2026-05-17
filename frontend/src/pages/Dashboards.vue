<script setup lang="ts">
import { computed } from "vue";
import VChart from "vue-echarts";
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { api } from "../api/client";
import { useFetch } from "../api/useFetch";
import Card from "../components/Card.vue";

use([CanvasRenderer, BarChart, LineChart, GridComponent, TooltipComponent]);

const chap = useFetch<{ items: { chapter: string; count: number }[] }>({
  key: ["dash", "chapter-volume"],
  fetcher: () => api.get("/api/v1/dashboards/chapter-volume"),
});
const sanctions = useFetch<{ items: { source: string; count: number }[] }>({
  key: ["dash", "sanction-hits"],
  fetcher: () => api.get("/api/v1/dashboards/sanction-hits-by-source"),
});
const heat = useFetch<{ cells: { origin_iso: string; destination_iso: string; count: number }[] }>({
  key: ["dash", "country-heatmap"],
  fetcher: () => api.get("/api/v1/dashboards/country-pair-heatmap"),
});
const hist = useFetch<{ top1_score: { bucket: number; count: number }[] }>({
  key: ["dash", "histograms"],
  fetcher: () => api.get("/api/v1/dashboards/score-histograms"),
});
const trend = useFetch<{ items: { chapter: string; rate: number; corrections: number; total: number }[] }>({
  key: ["dash", "override-trend"],
  fetcher: () => api.get("/api/v1/dashboards/override-rate-trend"),
});

function barOption(items: { name: string; value: number }[], color: string) {
  return {
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: items.map((i) => i.name) },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: items.map((i) => i.value), itemStyle: { color } }],
  };
}

function lineOption(items: { name: string; value: number }[], color: string) {
  return {
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: items.map((i) => i.name) },
    yAxis: { type: "value" },
    series: [
      {
        type: "line",
        smooth: true,
        data: items.map((i) => i.value),
        lineStyle: { color },
        itemStyle: { color },
      },
    ],
  };
}

const chapOption = computed(() =>
  barOption(
    (chap.data.value?.items ?? []).slice(0, 20).map((i) => ({ name: i.chapter, value: i.count })),
    "#0f172a"
  )
);
const sanctionsOption = computed(() =>
  barOption(
    (sanctions.data.value?.items ?? []).map((i) => ({ name: i.source, value: i.count })),
    "#b91c1c"
  )
);
const histOption = computed(() =>
  barOption(
    (hist.data.value?.top1_score ?? []).map((i) => ({ name: String(i.bucket), value: i.count })),
    "#0369a1"
  )
);
const trendOption = computed(() =>
  lineOption(
    (trend.data.value?.items ?? []).map((i) => ({ name: i.chapter, value: i.rate })),
    "#16a34a"
  )
);
</script>

<template>
  <div class="grid gap-4">
    <Card title="Volume by HS chapter">
      <VChart
        v-if="chap.data.value && chap.data.value.items.length > 0"
        :option="chapOption"
        autoresize
        style="height: 240px"
      />
      <p v-else class="text-slate-500 text-sm">No screening results yet.</p>
    </Card>

    <Card title="Sanction hits by source">
      <VChart
        v-if="sanctions.data.value && sanctions.data.value.items.length > 0"
        :option="sanctionsOption"
        autoresize
        style="height: 240px"
      />
      <p v-else class="text-slate-500 text-sm">No sanction hits yet.</p>
    </Card>

    <Card title="Country-pair heatmap">
      <table v-if="heat.data.value && heat.data.value.cells.length > 0" class="text-xs">
        <tbody>
          <tr v-for="(c, i) in heat.data.value.cells.slice(0, 100)" :key="i">
            <td class="px-2 py-1 font-mono">{{ c.origin_iso }}</td>
            <td class="px-2 py-1">→</td>
            <td class="px-2 py-1 font-mono">{{ c.destination_iso }}</td>
            <td class="px-2 py-1 font-mono">{{ c.count }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="text-slate-500 text-sm">No shipment routes seen yet.</p>
    </Card>

    <Card title="Top-1 score distribution">
      <VChart
        v-if="hist.data.value && hist.data.value.top1_score.length > 0"
        :option="histOption"
        autoresize
        style="height: 240px"
      />
      <p v-else class="text-slate-500 text-sm">No score data yet.</p>
    </Card>

    <Card title="Override rate by chapter">
      <VChart
        v-if="trend.data.value && trend.data.value.items.length > 0"
        :option="trendOption"
        autoresize
        style="height: 240px"
      />
      <p v-else class="text-slate-500 text-sm">No feedback yet.</p>
    </Card>
  </div>
</template>
