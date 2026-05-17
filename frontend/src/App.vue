<script setup lang="ts">
const navItems: { to: string; label: string }[] = [
  { to: "/status", label: "Status" },
  { to: "/admin", label: "Admin" },
  { to: "/training", label: "Training & Eval" },
  { to: "/screen", label: "Screen" },
  { to: "/data", label: "Data" },
  { to: "/upload", label: "Upload" },
  { to: "/results", label: "Results" },
  { to: "/hs", label: "HS" },
  { to: "/sanctions", label: "Sanctions" },
  { to: "/rules", label: "Rules" },
  { to: "/dashboards", label: "Dashboards" },
];
</script>

<template>
  <div class="min-h-screen">
    <header class="border-b bg-white">
      <div class="max-w-6xl mx-auto px-4 py-3 flex items-center gap-4">
        <RouterLink to="/status" class="font-semibold">Commodity Screening</RouterLink>
        <nav class="flex gap-1 ml-4 flex-wrap">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="px-3 py-2 rounded text-sm text-slate-700 hover:bg-slate-200"
            active-class="!bg-slate-900 !text-white hover:!bg-slate-900"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
      </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
