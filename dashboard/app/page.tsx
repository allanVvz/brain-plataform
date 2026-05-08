"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, BrainCircuit, Gauge } from "lucide-react";
import { api } from "@/lib/api";
import { SystemDashboardTab } from "@/components/dashboard/SystemDashboardTab";
import { LeadsDashboardTab } from "@/components/dashboard/LeadsDashboardTab";
import { KnowledgeDashboardTab } from "@/components/dashboard/KnowledgeDashboardTab";

type DashboardTab = "leads" | "system" | "knowledge";

const tabs: Array<{ id: DashboardTab; label: string; icon: any }> = [
  { id: "knowledge", label: "Dashboard de Conhecimento", icon: BrainCircuit },
  { id: "leads", label: "Dashboard de Leads", icon: Gauge },
  { id: "system", label: "Dashboard do Sistema", icon: Activity },
];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<DashboardTab>("knowledge");
  const [health, setHealth] = useState<any>(null);
  const [insights, setInsights] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [knowledgeCounts, setKnowledgeCounts] = useState<any>(null);
  const [pipelineMetrics, setPipelineMetrics] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [personaFilterId, setPersonaFilterId] = useState("");

  useEffect(() => {
    setPersonaFilterId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      setPersonaFilterId(detail?.id || window.localStorage.getItem("ai-brain-persona-id") || "");
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(console.error);
    api.insights("open").then((d) => setInsights(d.slice(0, 6))).catch(console.error);
  }, []);

  useEffect(() => {
    const scopedPersonaId = personaFilterId || undefined;
    api.leads(1000, 0, scopedPersonaId).then(setLeads).catch(console.error);
    api.conversations(720, scopedPersonaId).then(setConversations).catch(() => setConversations([]));
    api.knowledgeCounts(scopedPersonaId).then(setKnowledgeCounts).catch(() => setKnowledgeCounts(null));
    api.pipelineMetrics(scopedPersonaId).then(setPipelineMetrics).catch(() => setPipelineMetrics(null));
  }, [personaFilterId]);

  async function triggerValidator() {
    setRunning(true);
    try {
      const result = await api.runValidator();
      setHealth(result);
      const fresh = await api.insights("open");
      setInsights(fresh.slice(0, 6));
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(false);
    }
  }

  const activeLabel = useMemo(
    () => tabs.find((tab) => tab.id === activeTab)?.label || "Dashboard",
    [activeTab],
  );

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Brain AI
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-obs-text">
            {activeLabel}
          </h1>
        </div>

        <div className="flex w-full gap-1 rounded-lg border border-white/06 bg-white/[0.03] p-1 lg:w-auto">
          {tabs.map(({ id, label, icon: Icon }) => {
            const active = id === activeTab;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={`flex min-h-9 flex-1 items-center justify-center gap-2 rounded-md px-3 text-xs font-medium transition lg:flex-none ${
                  active
                    ? "bg-white/10 text-obs-text shadow-obs-node"
                    : "text-obs-subtle hover:bg-white/[0.04] hover:text-obs-text"
                }`}
              >
                <Icon size={14} />
                <span className="whitespace-nowrap">{label}</span>
              </button>
            );
          })}
        </div>
      </header>

      {activeTab === "leads" && (
        <LeadsDashboardTab
          leads={leads}
          conversations={conversations}
        />
      )}

      {activeTab === "system" && (
        <SystemDashboardTab
          health={health}
          insights={insights}
          running={running}
          onRunValidator={triggerValidator}
        />
      )}

      {activeTab === "knowledge" && (
        <KnowledgeDashboardTab
          leads={leads}
          knowledgeCounts={knowledgeCounts}
          pipelineMetrics={pipelineMetrics}
        />
      )}
    </div>
  );
}
