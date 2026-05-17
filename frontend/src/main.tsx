import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, NavLink, Route, Routes, Navigate } from "react-router-dom";
import Status from "./pages/Status";
import Admin from "./pages/Admin";
import Data from "./pages/Data";
import Upload from "./pages/Upload";
import Results from "./pages/Results";
import ResultDetail from "./pages/ResultDetail";
import HsBrowser from "./pages/HsBrowser";
import SanctionsBrowser from "./pages/SanctionsBrowser";
import RuleManager from "./pages/RuleManager";
import Dashboards from "./pages/Dashboards";
import Screen from "./pages/Screen";
import TrainingEval from "./pages/TrainingEval";
import "./index.css";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

function Layout({ children }: { children: React.ReactNode }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    "px-3 py-2 rounded text-sm " +
    (isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200");
  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-4">
          <Link to="/status" className="font-semibold">Commodity Screening</Link>
          <nav className="flex gap-1 ml-4 flex-wrap">
            <NavLink to="/status" className={link}>Status</NavLink>
            <NavLink to="/admin" className={link}>Admin</NavLink>
            <NavLink to="/training" className={link}>Training & Eval</NavLink>
            <NavLink to="/screen" className={link}>Screen</NavLink>
            <NavLink to="/data" className={link}>Data</NavLink>
            <NavLink to="/upload" className={link}>Upload</NavLink>
            <NavLink to="/results" className={link}>Results</NavLink>
            <NavLink to="/hs" className={link}>HS</NavLink>
            <NavLink to="/sanctions" className={link}>Sanctions</NavLink>
            <NavLink to="/rules" className={link}>Rules</NavLink>
            <NavLink to="/dashboards" className={link}>Dashboards</NavLink>
          </nav>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/status" />} />
            <Route path="/status" element={<Status />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/training" element={<TrainingEval />} />
            <Route path="/screen" element={<Screen />} />
            <Route path="/data" element={<Data />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/results" element={<Results />} />
            <Route path="/results/:id" element={<ResultDetail />} />
            <Route path="/hs" element={<HsBrowser />} />
            <Route path="/sanctions" element={<SanctionsBrowser />} />
            <Route path="/rules" element={<RuleManager />} />
            <Route path="/dashboards" element={<Dashboards />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
);
