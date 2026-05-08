"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowRight, BarChart3, Boxes, Clock, GitBranch, Maximize2, MessageSquare, RefreshCw, SlidersHorizontal, Tags, Users } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { summarizeLeadLifecycle } from "@/lib/lead-state";

type PipelineTab = "leads" | "knowledge" | "system";
type DistributionMode = "stage" | "date" | "tag";
type DateRangeDays = 1 | 3 | 7;
type ExpandedTable = { title: string; rows: Array<Record<string, any>> } | null;

const STATUS_DOT: Record<string, string> = {
  online: "bg-green-400",
  offline: "bg-red-500",
  degraded: "bg-yellow-400",
  error: "bg-red-500",
  pending: "bg-yellow-400",
  processing: "bg-blue-400 animate-pulse",
  unknown: "bg-brain-muted",
};

const SERVICE_LABELS: Record<string, string> = {
  vault_sync: "Vault Sync",
  knowledge_intake: "Knowledge Intake",
  knowledge_validation: "Knowledge Validation",
  embedding_service: "Embedding Service",
  flow_validator: "Flow Validator",
  n8n_crm_vitoria: "n8n CRM Vitoria",
  supabase: "Supabase",
  whatsapp_webhook: "WhatsApp Webhook",
  mcp_figma: "MCP Figma",
};

const COLUMNS: { label: string; services: string[] }[] = [
  { label: "Entradas", services: ["vault_sync", "knowledge_intake", "whatsapp_webhook", "mcp_figma"] },
  { label: "Processamento", services: ["knowledge_validation", "embedding_service", "flow_validator"] },
  { label: "Saidas", services: ["n8n_crm_vitoria", "supabase"] },
];

function fmt(ts: string | null) {
  if (!ts) return "--";
  const d = new Date(ts);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function relTime(ts: string | null) {
  if (!ts) return "nunca";
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (diff < 60) return `${diff}s atras`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m atras`;
  return `${Math.floor(diff / 3600)}h atras`;
}

function dayKey(ts: string | null | undefined) {
  if (!ts) return "sem data";
  return new Date(ts).toISOString().slice(0, 10);
}

function normalizeStage(stage: string | null | undefined) {
  return (stage || "novo").toLowerCase().trim() || "novo";
}

function leadTag(lead: any) {
  const tags = lead.tags || lead.metadata?.tags;
  if (Array.isArray(tags) && tags.length > 0) return String(tags[0]);
  return lead.interesse_produto || lead.canal || "sem tag";
}

function isUserMessage(msg: any) {
  const sender = String(msg.sender_type || "").toLowerCase();
  const direction = String(msg.direction || "").toLowerCase();
  return sender === "lead" || sender === "client" || sender === "user" || direction === "inbound";
}

function isAssistantMessage(msg: any) {
  const sender = String(msg.sender_type || "").toLowerCase();
  return sender === "assistant" || sender === "agent" || sender === "ai";
}

function isResponseMessage(msg: any) {
  const sender = String(msg.sender_type || "").toLowerCase();
  const direction = String(msg.direction || "").toLowerCase();
  return isAssistantMessage(msg) || sender === "human" || direction === "outbounding" || direction === "outbound";
}

function averageResponseLatency(messages: any[]) {
  const byLead = new Map<string, any[]>();
  for (const msg of messages) {
    const key = String(msg.lead_ref || msg.nome || "unknown");
    byLead.set(key, [...(byLead.get(key) || []), msg]);
  }
  const latencies: number[] = [];
  for (const rows of byLead.values()) {
    const sorted = [...rows].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    for (let i = 0; i < sorted.length; i++) {
      if (!isUserMessage(sorted[i])) continue;
      const current = new Date(sorted[i].created_at).getTime();
      const response = sorted.slice(i + 1).find(isResponseMessage);
      if (!response) continue;
      const diff = new Date(response.created_at).getTime() - current;
      if (diff > 0 && diff < 24 * 60 * 60 * 1000) latencies.push(diff);
    }
  }
  if (!latencies.length) return 0;
  return Math.round(latencies.reduce((sum, item) => sum + item, 0) / latencies.length);
}

function formatLatency(ms: number) {
  if (!ms) return "--";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.round(minutes / 60)}h`;
}

function countBy<T>(items: T[], keyFn: (item: T) => string) {
  const map = new Map<string, number>();
  for (const item of items) {
    const key = keyFn(item);
    map.set(key, (map.get(key) || 0) + 1);
  }
  return Array.from(map.entries()).map(([name, value]) => ({ name, value }));
}

function inRange(ts: string | null | undefined, days: DateRangeDays) {
  if (!ts) return false;
  return new Date(ts).getTime() >= Date.now() - days * 24 * 60 * 60 * 1000;
}

export default function PipelinePage() {
  const [activeTab, setActiveTab] = useState<PipelineTab>("leads");
  const [distributionMode, setDistributionMode] = useState<DistributionMode>("stage");
  const [dateRangeDays, setDateRangeDays] = useState<DateRangeDays>(7);
  const [includeTags, setIncludeTags] = useState(true);
  const [expanded, setExpanded] = useState<ExpandedTable>(null);
  const [statuses, setStatuses] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any>({});
  const [knowledgeCounts, setKnowledgeCounts] = useState<any>(null);
  const [insights, setInsights] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [messages, setMessages] = useState<any[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [personaFilterId, setPersonaFilterId] = useState("");

  async function load() {
    try {
      const scopedPersonaId = personaFilterId || undefined;
      const [s, m, kc, ins, e, l, msg, conv] = await Promise.all([
        api.pipelineStatus(),
        api.pipelineMetrics(scopedPersonaId),
        api.knowledgeCounts(scopedPersonaId),
        api.insights("open"),
        api.pipelineEvents(30, undefined, scopedPersonaId),
        api.leads(500, 0, scopedPersonaId),
        api.recentMessages(dateRangeDays * 24, scopedPersonaId),
        api.conversations(dateRangeDays * 24, scopedPersonaId),
      ]);
      setStatuses(s);
      setMetrics(m);
      setKnowledgeCounts(kc);
      setInsights(ins.slice(0, 6));
      setEvents(e);
      setLeads(l);
      setMessages(msg);
      setConversations(conv);
    } finally {
      setLoading(false);
    }
  }

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
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, [personaFilterId, dateRangeDays]);

  const filteredLeads = useMemo(
    () => leads.filter((lead) => inRange(lead.created_at || lead.updated_at || lead.last_update, dateRangeDays)),
    [dateRangeDays, leads],
  );
  const lifecycle = useMemo(
    () => summarizeLeadLifecycle(filteredLeads, conversations),
    [filteredLeads, conversations],
  );

  const distributionData = useMemo(() => {
    const mode = !includeTags && distributionMode === "tag" ? "stage" : distributionMode;
    if (mode === "stage") return countBy(filteredLeads, (lead) => normalizeStage(lead.stage));
    if (mode === "date") return countBy(filteredLeads, (lead) => dayKey(lead.created_at || lead.updated_at || lead.last_update));
    return countBy(filteredLeads, leadTag).sort((a, b) => b.value - a.value).slice(0, 12);
  }, [distributionMode, filteredLeads, includeTags]);

  const interactionsData = useMemo(() => {
    const days = new Map<string, { name: string; leads: number; messages: number; usuarios: number; assistente: number }>();
    for (const lead of filteredLeads) {
      const key = dayKey(lead.created_at || lead.updated_at || lead.last_update);
      const row = days.get(key) || { name: key, leads: 0, messages: 0, usuarios: 0, assistente: 0 };
      row.leads += 1;
      days.set(key, row);
    }
    for (const msg of messages) {
      const key = dayKey(msg.created_at);
      const row = days.get(key) || { name: key, leads: 0, messages: 0, usuarios: 0, assistente: 0 };
      row.messages += 1;
      if (isUserMessage(msg)) row.usuarios += 1;
      if (isAssistantMessage(msg)) row.assistente += 1;
      days.set(key, row);
    }
    return Array.from(days.values()).sort((a, b) => a.name.localeCompare(b.name)).slice(-14);
  }, [filteredLeads, messages]);

  const headerMetrics = [
    { label: "Leads totais", value: lifecycle.total, icon: Users },
    { label: "Conversas iniciadas", value: lifecycle.started, icon: MessageSquare },
    { label: "Leads mapeadas", value: lifecycle.mapped, icon: ArrowRight },
    { label: "Conversas", value: conversations.length, icon: MessageSquare },
    { label: "Mensagens totais", value: messages.length, icon: BarChart3 },
    { label: "Mensagens usuario", value: messages.filter(isUserMessage).length, icon: Activity },
    { label: "Mensagens assistente", value: messages.filter(isAssistantMessage).length, icon: Activity },
    { label: "Latencia media", value: formatLatency(averageResponseLatency(messages)), icon: Clock },
  ];

  return (
    <div className="flex h-[calc(100vh-6rem)] min-h-[760px] gap-4 overflow-hidden">
      <main className="min-w-0 flex-1 overflow-y-auto pr-1">
        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Pipeline</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-obs-text">
              {activeTab === "leads"
                ? "Pipeline de Leads"
                : activeTab === "knowledge"
                  ? "Pipeline de Conhecimento"
                  : "Pipeline do Sistema"}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-white/06 bg-white/[0.03] p-1">
              {(["leads", "knowledge", "system"] as PipelineTab[]).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={`rounded-md px-3 py-2 text-xs transition ${
                    activeTab === tab ? "bg-white/10 text-obs-text" : "text-obs-subtle hover:text-obs-text"
                  }`}
                >
                  {tab === "leads" ? "Leads" : tab === "knowledge" ? "Conhecimento" : "Sistema"}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={load}
              className="flex items-center gap-2 rounded-md border border-white/08 px-3 py-2 text-xs text-obs-subtle transition hover:text-obs-text"
            >
              <RefreshCw size={13} />
              Atualizar
            </button>
          </div>
        </div>

        {activeTab === "leads" ? (
          <LeadsPipeline
            headerMetrics={headerMetrics}
            dateRangeDays={dateRangeDays}
            setDateRangeDays={setDateRangeDays}
            includeTags={includeTags}
            setIncludeTags={setIncludeTags}
            distributionMode={distributionMode}
            setDistributionMode={setDistributionMode}
            distributionData={distributionData}
            interactionsData={interactionsData}
            setExpanded={setExpanded}
          />
        ) : activeTab === "knowledge" ? (
          <KnowledgePipeline
            knowledgeCounts={knowledgeCounts}
            metrics={metrics}
          />
        ) : (
          <SystemPipeline
            statuses={statuses}
            metrics={metrics}
            events={events}
            insights={insights}
            loading={loading}
          />
        )}
      </main>

      {expanded && (
        <aside className="hidden w-96 shrink-0 overflow-hidden rounded-xl border border-white/06 bg-white/[0.03] xl:flex xl:flex-col">
          <div className="flex items-center justify-between border-b border-white/06 px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-obs-text">{expanded.title}</p>
              <p className="text-xs text-obs-subtle">{expanded.rows.length} linhas</p>
            </div>
            <button
              type="button"
              onClick={() => setExpanded(null)}
              className="rounded-md border border-white/06 px-2 py-1 text-xs text-obs-subtle hover:text-obs-text"
            >
              Fechar
            </button>
          </div>
          <div className="flex-1 overflow-auto p-3">
            <table className="w-full text-left text-xs">
              <thead className="text-obs-faint">
                <tr>
                  {Object.keys(expanded.rows[0] || { name: "", value: "" }).map((key) => (
                    <th key={key} className="border-b border-white/06 px-2 py-2 font-medium uppercase tracking-[0.12em]">
                      {key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {expanded.rows.map((row, index) => (
                  <tr key={index} className="border-b border-white/06 text-obs-subtle">
                    {Object.values(row).map((value, cell) => (
                      <td key={cell} className="px-2 py-2">
                        {String(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      )}
    </div>
  );
}

function LeadsPipeline({
  headerMetrics,
  dateRangeDays,
  setDateRangeDays,
  includeTags,
  setIncludeTags,
  distributionMode,
  setDistributionMode,
  distributionData,
  interactionsData,
  setExpanded,
}: {
  headerMetrics: Array<{ label: string; value: string | number; icon: any }>;
  dateRangeDays: DateRangeDays;
  setDateRangeDays: (days: DateRangeDays) => void;
  includeTags: boolean;
  setIncludeTags: (value: boolean) => void;
  distributionMode: DistributionMode;
  setDistributionMode: (mode: DistributionMode) => void;
  distributionData: any[];
  interactionsData: any[];
  setExpanded: (value: ExpandedTable) => void;
}) {
  return (
    <section className="space-y-6 animate-fade-in">
      <div className="flex flex-col gap-3 rounded-xl border border-white/06 bg-white/[0.025] p-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-obs-subtle">
          <SlidersHorizontal size={14} />
          Filtros dos gráficos
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-white/06 bg-obs-base p-1">
            {([1, 3, 7] as DateRangeDays[]).map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => setDateRangeDays(days)}
                className={`rounded-md px-3 py-1.5 text-xs transition ${
                  dateRangeDays === days ? "bg-white/10 text-obs-text" : "text-obs-faint hover:text-obs-text"
                }`}
              >
                {days === 1 ? "24h" : `${days} dias`}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setIncludeTags(!includeTags);
              if (includeTags && distributionMode === "tag") setDistributionMode("stage");
            }}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition ${
              includeTags
                ? "border-obs-violet/35 bg-obs-violet/15 text-obs-text"
                : "border-white/06 bg-white/[0.02] text-obs-faint"
            }`}
          >
            <Tags size={13} />
            Tags {includeTags ? "ativas" : "ocultas"}
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        {headerMetrics.map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-obs-faint">
              <Icon size={13} />
              {label}
            </div>
            <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 2xl:grid-cols-2">
        <ChartShell
          title="Distribution by"
          action={() => setExpanded({ title: "Distribution by " + distributionMode, rows: distributionData })}
          right={
            <div className="flex rounded-md border border-white/06 bg-obs-base p-1">
              {(["stage", "date", "tag"] as DistributionMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setDistributionMode(mode)}
                  disabled={mode === "tag" && !includeTags}
                  className={`rounded px-2 py-1 text-[10px] uppercase tracking-[0.12em] ${
                    distributionMode === mode ? "bg-white/10 text-obs-text" : "text-obs-faint hover:text-obs-text"
                  } disabled:cursor-not-allowed disabled:opacity-40`}
                >
                  {mode}
                </button>
              ))}
            </div>
          }
        >
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={distributionData}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#8892a4", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8892a4", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#0e1118", border: "1px solid rgba(255,255,255,0.08)" }} />
              <Bar dataKey="value" fill="#7c6fff" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartShell>

        <ChartShell
          title="Leads and Message interactions overtime"
          action={() => setExpanded({ title: "Interactions overtime", rows: interactionsData })}
        >
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={interactionsData}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#8892a4", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8892a4", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#0e1118", border: "1px solid rgba(255,255,255,0.08)" }} />
              <Line type="monotone" dataKey="leads" stroke="#22c55e" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="messages" stroke="#7c6fff" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="usuarios" stroke="#f59e0b" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="assistente" stroke="#38bdf8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartShell>
      </div>
    </section>
  );
}

function KnowledgePipeline({
  knowledgeCounts,
  metrics,
}: {
  knowledgeCounts: any;
  metrics: any;
}) {
  const byStatus = knowledgeCounts?.by_status || {};
  const byType = knowledgeCounts?.by_type || {};
  const total = Number(knowledgeCounts?.total || 0);
  const attention =
    Number(byStatus.attention || 0) ||
    Number(byStatus.pending || 0) + Number(byStatus.needs_persona || 0) + Number(byStatus.needs_category || 0);
  const classified = Math.max(0, total - Number(byStatus.needs_persona || 0) - Number(byStatus.needs_category || 0));
  const validated =
    Number(byStatus.validated || 0) +
    Number(byStatus.approved || 0) +
    Number(byStatus.embedded || 0) +
    Number(byStatus.ATIVO || 0);
  const kbEntries = Number(metrics?.kb_entries || 0);
  const assets = Number(byType.asset || 0) + Number(byType.maker_material || 0);

  const levels = [
    {
      level: "Nível 1",
      title: "Entrada bruta",
      count: total,
      desc: "Todos os conhecimentos capturados para o escopo atual.",
      tone: "border-sky-400/25 bg-sky-400/10 text-sky-200",
    },
    {
      level: "Nível 2",
      title: "Classificação",
      count: classified,
      desc: "Itens com persona/categoria resolvidas ou prontos para revisão.",
      tone: "border-violet-400/25 bg-violet-400/10 text-violet-200",
    },
    {
      level: "Nível 3",
      title: "Validação",
      count: validated,
      desc: "Conhecimentos aprovados, validados ou incorporados.",
      tone: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
    },
    {
      level: "Nível 4",
      title: "Distribuição",
      count: kbEntries,
      desc: "Entradas ativas disponíveis para agentes, CRM e atendimento.",
      tone: "border-blue-400/25 bg-blue-400/10 text-blue-200",
    },
    {
      level: "Nível 5",
      title: "Uso criativo e pendências",
      count: assets + attention,
      desc: `${assets} assets/maker e ${attention} item(ns) ainda exigindo ação.`,
      tone: "border-amber-400/25 bg-amber-400/10 text-amber-200",
    },
  ];

  return (
    <section className="space-y-6 animate-fade-in">
      <div className="grid gap-3 md:grid-cols-4">
        {[
          { label: "Conhecimentos", value: total, icon: Boxes },
          { label: "Validados", value: validated, icon: Activity },
          { label: "KB ativa", value: kbEntries, icon: BarChart3 },
          { label: "Atenção", value: attention, icon: Clock },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-obs-faint">
              <Icon size={13} />
              {label}
            </div>
            <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-white/06 bg-white/[0.025] p-5">
        <div className="mb-5 flex items-center gap-2">
          <GitBranch size={16} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Árvore de conhecimento por maturidade</h2>
        </div>
        <div className="relative mx-auto flex max-w-5xl flex-col items-center gap-4">
          <div className="absolute bottom-12 top-12 hidden w-px bg-gradient-to-b from-sky-400/30 via-emerald-400/30 to-amber-400/30 md:block" />
          {levels.map((item, index) => (
            <div
              key={item.level}
              className={`relative z-10 grid w-full gap-3 md:grid-cols-[1fr_44px_1fr] ${
                index % 2 === 0 ? "" : "md:[&>*:first-child]:col-start-3"
              }`}
            >
              <div className={`rounded-xl border p-4 shadow-obs-node ${item.tone}`}>
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-70">{item.level}</p>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-white">{item.title}</h3>
                    <p className="mt-1 text-xs leading-relaxed text-obs-subtle">{item.desc}</p>
                  </div>
                  <span className="text-3xl font-semibold text-white">{item.count}</span>
                </div>
              </div>
              <div className="hidden items-center justify-center md:flex">
                <span className="h-3 w-3 rounded-full border border-white/30 bg-obs-violet shadow-obs-node" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ChartShell({
  title,
  children,
  action,
  right,
}: {
  title: string;
  children: React.ReactNode;
  action: () => void;
  right?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-white/06 bg-white/[0.025] p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-obs-text">{title}</h2>
        <div className="flex items-center gap-2">
          {right}
          <button
            type="button"
            onClick={action}
            className="flex items-center gap-1.5 rounded-md border border-white/08 px-2.5 py-1.5 text-xs text-obs-subtle transition hover:text-obs-text"
          >
            <Maximize2 size={12} />
            Tabela
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

function SystemPipeline({
  statuses,
  metrics,
  events,
  insights,
  loading,
}: {
  statuses: any[];
  metrics: any;
  events: any[];
  insights: any[];
  loading: boolean;
}) {
  const byService = Object.fromEntries(statuses.map((s) => [s.service, s]));

  return (
    <section className="space-y-6 animate-fade-in">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          { label: "Atencao necessaria", value: metrics.pending_attention ?? "--", color: "text-yellow-400" },
          { label: "Aprovados hoje", value: metrics.approved_today ?? "--", color: "text-green-400" },
          { label: "Entradas na KB", value: metrics.kb_entries ?? "--", color: "text-blue-400" },
          { label: "Assets pendentes", value: metrics.assets_pending ?? "--", color: "text-orange-400" },
          { label: "Erros 24h", value: metrics.errors_24h ?? "--", color: "text-red-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-xl border border-white/06 bg-white/[0.035] p-4 text-center">
            <div className={`text-2xl font-bold ${color}`}>{value}</div>
            <div className="mt-1 text-[11px] text-obs-subtle">{label}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {COLUMNS.map(({ label, services }, ci) => (
          <div key={label} className="space-y-2">
            <div className="mb-3 flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-widest text-obs-faint">{label}</span>
              {ci < COLUMNS.length - 1 && <span className="ml-auto text-xs text-obs-faint">-&gt;</span>}
            </div>
            {services.map((svc) => {
              const row = byService[svc];
              const status = row?.status ?? "unknown";
              return (
                <div key={svc} className="flex items-center gap-3 rounded-xl border border-white/06 bg-white/[0.035] px-4 py-3">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status] ?? "bg-brain-muted"}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-white">{SERVICE_LABELS[svc] ?? svc}</div>
                    <div className="mt-0.5 text-[11px] text-obs-subtle">
                      {status} | {relTime(row?.last_activity ?? null)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-white/06 bg-white/[0.025] p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Insights do sistema</h2>
            <p className="mt-0.5 text-xs text-obs-subtle">Alertas e recomendações operacionais agora ficam dentro do Pipeline do Sistema.</p>
          </div>
          <a
            href="/insights"
            className="rounded-md border border-white/08 px-3 py-1.5 text-xs text-obs-subtle transition hover:text-obs-text"
          >
            Abrir completo
          </a>
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {insights.length === 0 && (
            <div className="rounded-lg border border-white/06 bg-white/[0.025] p-3 text-sm text-obs-subtle">
              Nenhum insight aberto.
            </div>
          )}
          {insights.map((insight) => (
            <div key={insight.id} className="rounded-lg border border-white/06 bg-white/[0.03] p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-sm font-medium text-white">{insight.title || insight.type || "Insight"}</p>
                <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                  {insight.severity || insight.status || "open"}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-obs-subtle">
                {insight.message || insight.description || insight.recommendation || "Sem descrição."}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-obs-faint">Eventos recentes</h2>
        {loading && <p className="text-sm text-obs-subtle">Carregando...</p>}
        <div className="overflow-hidden rounded-xl border border-white/06 bg-white/[0.025]">
          {events.length === 0 && !loading && (
            <div className="px-4 py-6 text-center text-sm text-obs-subtle">Nenhum evento registrado.</div>
          )}
          {events.map((ev, i) => (
            <div key={ev.id ?? i} className={`flex items-center gap-3 px-4 py-2.5 text-sm ${i < events.length - 1 ? "border-b border-white/06" : ""}`}>
              <span className="w-20 shrink-0 font-mono text-xs text-obs-subtle">{fmt(ev.created_at)}</span>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                ev.event_type?.includes("fail") || ev.event_type?.includes("error")
                  ? "bg-red-500/10 text-red-400"
                  : ev.event_type?.includes("approved") || ev.event_type?.includes("completed")
                    ? "bg-green-500/10 text-green-400"
                    : "bg-white/5 text-obs-subtle"
              }`}>
                {ev.event_type}
              </span>
              <span className="flex-1 truncate text-white">
                {ev.entity_type && <span className="mr-1 text-obs-subtle">{ev.entity_type}</span>}
                {ev.payload && Object.keys(ev.payload).length > 0 && (
                  <span className="text-obs-subtle">
                    {Object.entries(ev.payload)
                      .slice(0, 3)
                      .map(([k, v]) => `${k}: ${String(v).slice(0, 40)}`)
                      .join(" | ")}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
