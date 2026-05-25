<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

type NavItem = { to: string; label: string; icon: string };
type NavGroup = { heading: string; items: NavItem[] };

// Icons are inline SVG path data (Heroicons-style, 24x24, stroke). Keeps the
// shell dependency-free.
const ICONS: Record<string, string> = {
  screen: "M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25",
  upload: "M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5",
  results: "M3.75 12h16.5m-16.5 3.75h16.5M3.75 8.25h16.5M3.75 4.5h16.5",
  hs: "M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 0 0-1.883 2.542l.857 6a2.25 2.25 0 0 0 2.227 1.932H19.05a2.25 2.25 0 0 0 2.227-1.932l.857-6a2.25 2.25 0 0 0-1.883-2.542m-16.5 0V6A2.25 2.25 0 0 1 6 3.75h3.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 0 1.06.44H18A2.25 2.25 0 0 1 20.25 9v.776",
  sanctions: "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z",
  rules: "M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75",
  dashboards: "M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6",
  data: "M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125",
  status: "M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z",
  admin: "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  training: "M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5",
};

const groups: NavGroup[] = [
  {
    heading: "Screening",
    items: [
      { to: "/screen", label: "Screen", icon: "screen" },
      { to: "/upload", label: "Batch upload", icon: "upload" },
      { to: "/results", label: "Results", icon: "results" },
    ],
  },
  {
    heading: "Reference data",
    items: [
      { to: "/hs", label: "HS taxonomy", icon: "hs" },
      { to: "/sanctions", label: "Sanctions", icon: "sanctions" },
      { to: "/rules", label: "Rules", icon: "rules" },
    ],
  },
  {
    heading: "Insights",
    items: [
      { to: "/dashboards", label: "Dashboards", icon: "dashboards" },
      { to: "/data", label: "Data browser", icon: "data" },
    ],
  },
  {
    heading: "System",
    items: [
      { to: "/status", label: "Status", icon: "status" },
      { to: "/admin", label: "Admin", icon: "admin" },
      { to: "/training", label: "Training & Eval", icon: "training" },
    ],
  },
];

const route = useRoute();
const mobileOpen = ref(false);

const allItems = groups.flatMap((g) => g.items);
const currentLabel = computed(() => {
  // Longest matching prefix so /results/:id still resolves to "Results".
  const match = allItems
    .filter((i) => route.path === i.to || route.path.startsWith(i.to + "/"))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return match?.label ?? "";
});
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-800 flex">
    <!-- Sidebar -->
    <aside
      class="fixed inset-y-0 left-0 z-30 w-60 bg-white border-r border-slate-200 flex flex-col transition-transform duration-200 md:translate-x-0"
      :class="mobileOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <RouterLink
        to="/status"
        class="flex items-center gap-2.5 px-5 h-16 border-b border-slate-100 shrink-0"
        @click="mobileOpen = false"
      >
        <span class="grid place-items-center w-8 h-8 rounded-lg bg-indigo-600 text-white text-sm font-bold">
          CS
        </span>
        <span class="font-semibold leading-tight text-slate-900">
          Commodity<br /><span class="text-slate-500 font-normal text-xs">Screening Engine</span>
        </span>
      </RouterLink>

      <nav class="flex-1 overflow-y-auto scrollbar-slim px-3 py-4 space-y-6">
        <div v-for="group in groups" :key="group.heading">
          <p class="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            {{ group.heading }}
          </p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="group flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors"
            active-class="!bg-indigo-50 !text-indigo-700 font-medium"
            @click="mobileOpen = false"
          >
            <svg
              class="w-[18px] h-[18px] shrink-0 text-slate-400 group-hover:text-slate-500"
              :class="route.path === item.to || route.path.startsWith(item.to + '/') ? '!text-indigo-600' : ''"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.6"
              stroke="currentColor"
            >
              <path stroke-linecap="round" stroke-linejoin="round" :d="ICONS[item.icon]" />
            </svg>
            {{ item.label }}
          </RouterLink>
        </div>
      </nav>
    </aside>

    <!-- Mobile backdrop -->
    <div
      v-if="mobileOpen"
      class="fixed inset-0 z-20 bg-slate-900/30 md:hidden"
      @click="mobileOpen = false"
    />

    <!-- Content -->
    <div class="flex-1 flex flex-col min-w-0 md:ml-60">
      <header class="sticky top-0 z-10 h-16 bg-white/80 backdrop-blur border-b border-slate-200 flex items-center gap-3 px-4 sm:px-6">
        <button
          class="md:hidden grid place-items-center w-9 h-9 rounded-lg hover:bg-slate-100"
          aria-label="Toggle navigation"
          @click="mobileOpen = !mobileOpen"
        >
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>
        <h1 class="text-base font-semibold text-slate-900">{{ currentLabel }}</h1>
      </header>

      <main class="flex-1 px-4 sm:px-6 py-6">
        <div class="max-w-6xl mx-auto">
          <RouterView />
        </div>
      </main>
    </div>
  </div>
</template>
