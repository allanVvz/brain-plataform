"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-yellow-400",
  down: "text-red-400",
  unknown: "text-brain-muted",
};

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-green-400",
  degraded: "bg-yellow-400",
  down: "bg-red-400",
  unknown: "bg-brain-muted",
};

const INPUTS = [
  { key: "supabase",  label: "Supabase",  desc: "Banco de dados e autenticação" },
  { key: "n8n",       label: "n8n",       desc: "Automação de fluxos e execuções" },
  { key: "airtable",  label: "Airtable",  desc: "CRM e dados estruturados" },
  { key: "openai",    label: "OpenAI",    desc: "Embeddings e modelos auxiliares" },
  { key: "anthropic", label: "Anthropic", desc: "Claude API — agentes e classificadores" },
];

const OUTPUTS = [
  { key: "figma_mcp", label: "Figma MCP", desc: "Gera diagramas e exporta designs" },
  { key: "whatsapp",  label: "WhatsApp",  desc: "Canal de saída para leads via Z-API / Evolution" },
];

function ServiceRow({ service, data }: { service: { key: string; label: string; desc: string }; data: any }) {
  const status = data?.status || "unknown";
  return (
    <div className="bg-brain-surface border border-brain-border rounded-xl p-4 flex items-center gap-4">
      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${STATUS_DOT[status]}`} />
      <div className="flex-1">
        <p className="font-medium text-sm">{service.label}</p>
        <p className="text-xs text-brain-muted mt-0.5">{service.desc}</p>
        {data?.error_message && (
          <p className="text-xs text-red-400 mt-0.5">{data.error_message}</p>
        )}
      </div>
      <div className="text-right">
        <p className={`text-sm font-medium ${STATUS_STYLE[status]}`}>{status}</p>
        {data?.response_ms > 0 && (
          <p className="text-xs text-brain-muted">{data.response_ms}ms</p>
        )}
        {data?.last_check && (
          <p className="text-xs text-brain-muted">
            {new Date(data.last_check).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
          </p>
        )}
      </div>
    </div>
  );
}

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<any[]>([]);

  useEffect(() => { api.integrations().then(setIntegrations).catch(console.error); }, []);

  const byService = Object.fromEntries(integrations.map((i) => [i.service, i]));

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Integrações</h1>

      <div>
        <p className="text-[10px] uppercase tracking-widest text-brain-muted mb-3">Entradas — fontes de dados</p>
        <div className="grid grid-cols-1 gap-3">
          {INPUTS.map((s) => (
            <ServiceRow key={s.key} service={s} data={byService[s.key]} />
          ))}
        </div>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-widest text-brain-muted mb-3">Saídas — destinos e canais</p>
        <div className="grid grid-cols-1 gap-3">
          {OUTPUTS.map((s) => (
            <ServiceRow key={s.key} service={s} data={byService[s.key]} />
          ))}
        </div>
      </div>
    </div>
  );
}
