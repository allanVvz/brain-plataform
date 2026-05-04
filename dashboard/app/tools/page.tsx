"use client";

import { useEffect, useMemo, useState } from "react";
import { Cpu, ExternalLink, Plug, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import LegacyToolsOverview from "../validacao/tools/page";

type ToolsTab = "overview" | "integrations";

const STATUS_STYLE: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  down: "text-red-400",
  unknown: "text-obs-faint",
};

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-green-400",
  degraded: "bg-yellow-400",
  down: "bg-red-400",
  unknown: "bg-obs-faint",
};

const INPUTS = [
  { key: "supabase", label: "Supabase", desc: "Banco de dados e autenticação" },
  { key: "n8n", label: "n8n", desc: "Automação de fluxos e execuções" },
  { key: "airtable", label: "Airtable", desc: "CRM e dados estruturados" },
  { key: "openai", label: "OpenAI", desc: "Embeddings e modelos auxiliares" },
  { key: "anthropic", label: "Anthropic", desc: "Claude API e classificadores" },
];

const OUTPUTS = [
  { key: "figma_mcp", label: "Figma MCP", desc: "Diagramas e designs" },
  { key: "whatsapp", label: "WhatsApp", desc: "Canal de saída para leads" },
];

const MCP_TOOLS = [
  {
    name: "get_design_context",
    description: "Busca contexto de design a partir de um node Figma",
    example: '{ "fileKey": "abc123", "nodeId": "1:23" }',
  },
  {
    name: "get_screenshot",
    description: "Captura screenshot de um node ou frame do Figma",
    example: '{ "fileKey": "abc123", "nodeId": "1:23" }',
  },
  {
    name: "get_metadata",
    description: "Retorna metadados de um arquivo Figma",
    example: '{ "fileKey": "abc123" }',
  },
  {
    name: "generate_diagram",
    description: "Cria um diagrama em FigJam",
    example: '{ "title": "Arquitetura", "nodes": [] }',
  },
];

function statusOf(data: any) {
  return data?.status || "unknown";
}

function ServiceCard({
  service,
  data,
  compact = false,
}: {
  service: { key: string; label: string; desc: string };
  data: any;
  compact?: boolean;
}) {
  const status = statusOf(data);
  return (
    <div className={`flex items-center gap-3 rounded-xl border border-white/06 bg-white/[0.03] ${compact ? "min-w-44 px-3 py-2" : "p-4"}`}>
      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${STATUS_DOT[status] ?? STATUS_DOT.unknown}`} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-white">{service.label}</p>
        {!compact && <p className="mt-0.5 text-xs text-obs-subtle">{service.desc}</p>}
        {data?.error_message && !compact && (
          <p className="mt-0.5 text-xs text-red-400">{data.error_message}</p>
        )}
      </div>
      <div className="text-right">
        <p className={`text-xs font-medium ${STATUS_STYLE[status] ?? STATUS_STYLE.unknown}`}>{status}</p>
        {data?.response_ms > 0 && !compact && (
          <p className="text-xs text-obs-faint">{data.response_ms}ms</p>
        )}
      </div>
    </div>
  );
}

function IntegrationsSummary({ byService }: { byService: Record<string, any> }) {
  const services = [...INPUTS, ...OUTPUTS];
  const counts = services.reduce(
    (acc, service) => {
      const status = statusOf(byService[service.key]);
      if (status === "healthy") acc.healthy += 1;
      else if (status === "down") acc.down += 1;
      else acc.other += 1;
      return acc;
    },
    { healthy: 0, down: 0, other: 0 },
  );

  return (
    <section className="rounded-xl border border-white/06 bg-white/[0.025] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Plug size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Resumo de integrações</h2>
        </div>
        <div className="flex gap-2 text-[11px]">
          <span className="rounded-full bg-green-400/10 px-2 py-1 text-green-300">{counts.healthy} saudáveis</span>
          <span className="rounded-full bg-red-400/10 px-2 py-1 text-red-300">{counts.down} down</span>
          <span className="rounded-full bg-white/5 px-2 py-1 text-obs-subtle">{counts.other} outros</span>
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {services.map((service) => (
          <ServiceCard key={service.key} service={service} data={byService[service.key]} compact />
        ))}
      </div>
    </section>
  );
}

function FullIntegrations({ byService }: { byService: Record<string, any> }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(380px,0.75fr)]">
      <div className="space-y-5">
        <section>
          <p className="mb-3 text-[10px] uppercase tracking-widest text-obs-faint">Entradas - fontes de dados</p>
          <div className="grid gap-3">
            {INPUTS.map((service) => (
              <ServiceCard key={service.key} service={service} data={byService[service.key]} />
            ))}
          </div>
        </section>

        <section>
          <p className="mb-3 text-[10px] uppercase tracking-widest text-obs-faint">Saídas - destinos e canais</p>
          <div className="grid gap-3">
            {OUTPUTS.map((service) => (
              <ServiceCard key={service.key} service={service} data={byService[service.key]} />
            ))}
          </div>
        </section>
      </div>

      <McpPanel />
    </div>
  );
}

function McpPanel() {
  const [selected, setSelected] = useState(MCP_TOOLS[0].name);
  const [input, setInput] = useState(MCP_TOOLS[0].example);
  const [result, setResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const tool = MCP_TOOLS.find((item) => item.name === selected) || MCP_TOOLS[0];

  function selectTool(name: string) {
    const next = MCP_TOOLS.find((item) => item.name === name);
    if (!next) return;
    setSelected(next.name);
    setInput(next.example);
    setResult(null);
  }

  async function runTool() {
    setRunning(true);
    setResult(null);
    try {
      const parsed = JSON.parse(input);
      setResult(JSON.stringify(parsed, null, 2) + "\n\n// Ferramenta MCP simulada via integração Figma");
    } catch {
      setResult("Erro: JSON inválido");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="rounded-xl border border-white/06 bg-white/[0.025] p-4">
      <div className="mb-4 flex items-center gap-2">
        <Cpu size={15} className="text-obs-violet" />
        <div>
          <h2 className="text-sm font-semibold text-obs-text">MCP</h2>
          <p className="text-xs text-obs-subtle">Ferramentas Figma disponíveis dentro de Integrações.</p>
        </div>
      </div>

      <div className="space-y-2">
        {MCP_TOOLS.map((item) => (
          <button
            key={item.name}
            type="button"
            onClick={() => selectTool(item.name)}
            className={`w-full rounded-lg border p-3 text-left transition ${
              selected === item.name
                ? "border-obs-violet/40 bg-obs-violet/10"
                : "border-white/06 bg-white/[0.02] hover:border-white/12"
            }`}
          >
            <p className="font-mono text-xs font-medium text-obs-violet">{item.name}</p>
            <p className="mt-1 text-xs text-obs-subtle">{item.description}</p>
          </button>
        ))}
      </div>

      <div className="mt-4">
        <p className="mb-1 text-xs text-obs-faint">Parâmetros JSON</p>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={6}
          className="w-full resize-none rounded-lg border border-white/08 bg-obs-base p-3 font-mono text-xs text-white outline-none transition focus:border-obs-violet/50"
        />
      </div>
      <button
        type="button"
        onClick={runTool}
        disabled={running}
        className="mt-3 inline-flex items-center gap-2 rounded-md border border-obs-violet/35 bg-obs-violet/15 px-3 py-2 text-xs font-medium text-obs-text transition hover:bg-obs-violet/25 disabled:opacity-50"
      >
        <ExternalLink size={13} />
        {running ? "Executando..." : `Executar ${tool.name}`}
      </button>
      {result && (
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-lg border border-white/08 bg-obs-base p-3 font-mono text-xs text-green-300">
          {result}
        </pre>
      )}
    </section>
  );
}

export default function ToolsPage() {
  const [activeTab, setActiveTab] = useState<ToolsTab>("overview");
  const [integrations, setIntegrations] = useState<any[]>([]);

  useEffect(() => {
    api.integrations().then(setIntegrations).catch(console.error);
  }, []);

  const byService = useMemo(
    () => Object.fromEntries(integrations.map((item) => [item.service, item])),
    [integrations],
  );

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            <Wrench size={16} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Configurações</p>
            <h1 className="mt-1 text-xl font-semibold text-white">Tools</h1>
          </div>
        </div>

        <div className="flex w-full gap-1 rounded-lg border border-white/06 bg-white/[0.03] p-1 lg:w-auto">
          {[
            { id: "overview", label: "Overview" },
            { id: "integrations", label: "Integrações" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id as ToolsTab)}
              className={`min-h-9 flex-1 rounded-md px-4 text-xs font-medium transition lg:flex-none ${
                activeTab === tab.id
                  ? "bg-white/10 text-obs-text shadow-obs-node"
                  : "text-obs-subtle hover:bg-white/[0.04] hover:text-obs-text"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      {activeTab === "overview" ? (
        <>
          <IntegrationsSummary byService={byService} />
          <LegacyToolsOverview />
        </>
      ) : (
        <FullIntegrations byService={byService} />
      )}
    </div>
  );
}
