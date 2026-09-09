"use client";

import { useEffect, useState } from "react";
import { ListChecks, Megaphone } from "lucide-react";
import { CampaignsPanel } from "@/components/disparos/CampaignsPanel";
import { ReleaseQueuePanel } from "@/components/disparos/ReleaseQueuePanel";

type DisparosTab = "campanhas" | "fila";

const DISPAROS_TABS: Array<{ key: DisparosTab; label: string; icon: typeof Megaphone }> = [
  { key: "campanhas", label: "Campanhas", icon: Megaphone },
  { key: "fila", label: "Fila de liberacao", icon: ListChecks },
];

function tabFromLocation(): DisparosTab {
  if (typeof window === "undefined") return "campanhas";
  const candidate = new URLSearchParams(window.location.search).get("tab") || "";
  return DISPAROS_TABS.some((tab) => tab.key === candidate) ? (candidate as DisparosTab) : "campanhas";
}

export default function DisparosPage() {
  const [activeTab, setActiveTab] = useState<DisparosTab>("campanhas");

  useEffect(() => {
    const sync = () => setActiveTab(tabFromLocation());
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  function selectTab(tab: DisparosTab) {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    if (tab === "campanhas") url.searchParams.delete("tab");
    else url.searchParams.set("tab", tab);
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return (
    <div className="lg-page-narrow flex flex-col gap-5 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-obs-violet/10 text-obs-violet [border:1px_solid_var(--border-glass)]">
            <Megaphone size={16} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Mensageria</p>
            <h1 className="mt-1 text-xl font-semibold text-obs-text">Disparos</h1>
          </div>
        </div>
      </header>

      <nav
        aria-label="Abas de disparos"
        className="flex gap-1 overflow-x-auto rounded-2xl border border-white/10 bg-obs-surface p-1.5"
      >
        {DISPAROS_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => selectTab(key)}
            aria-selected={activeTab === key}
            className={`flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition ${
              activeTab === key
                ? "bg-obs-violet/15 text-obs-violet ring-1 ring-obs-violet/25"
                : "text-obs-subtle hover:bg-white/[0.05] hover:text-obs-text"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      <section data-disparos-tab={activeTab}>
        {activeTab === "campanhas" && <CampaignsPanel />}
        {activeTab === "fila" && <ReleaseQueuePanel />}
      </section>
    </div>
  );
}
