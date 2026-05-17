import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/status" },
  { path: "/status", component: () => import("./pages/Status.vue") },
  { path: "/admin", component: () => import("./pages/Admin.vue") },
  { path: "/training", component: () => import("./pages/TrainingEval.vue") },
  { path: "/screen", component: () => import("./pages/Screen.vue") },
  { path: "/data", component: () => import("./pages/Data.vue") },
  { path: "/upload", component: () => import("./pages/Upload.vue") },
  { path: "/results", component: () => import("./pages/Results.vue") },
  { path: "/results/:id", component: () => import("./pages/ResultDetail.vue") },
  { path: "/hs", component: () => import("./pages/HsBrowser.vue") },
  { path: "/sanctions", component: () => import("./pages/SanctionsBrowser.vue") },
  { path: "/rules", component: () => import("./pages/RuleManager.vue") },
  { path: "/dashboards", component: () => import("./pages/Dashboards.vue") },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
