"use client";
import {
  Wrench, Cpu, Database, Network, MessageSquare, Sparkles,
  Image as ImageIcon, RefreshCw, Activity, CheckSquare, Plug,
  ScrollText, GitBranch, Bot, BookOpen, TestTube2,
} from "lucide-react";

interface Tool {
  name: string;
  where: string;       // arquivo ou rota
  purpose: string;     // 1 linha
  notes?: string;      // detalhe econômico/prático
}

interface Section {
  title: string;
  icon: any; // LucideIcon — forwardRef component, accepts size/className via LucideProps
  tools: Tool[];
}

const SECTIONS: Section[] = [
  {
    title: "Modelos & LLMs",
    icon: Cpu,
    tools: [
      { name: "ModelRouter (cascade)",      where: "services/model_router.py",       purpose: "Chamada de LLM com fallback automático.",
        notes: "OpenAI: gpt-4o-mini → gpt-4o → gpt-3.5-turbo. Anthropic: claude-haiku-4-5 como último recurso." },
      { name: "Anthropic SDK",              where: "anthropic>=0.26.0",              purpose: "Claude direto, usado em /generate (Figma).",
        notes: "Chave em ANTHROPIC_API_KEY." },
      { name: "OpenAI SDK",                 where: "openai>=1.0.0",                  purpose: "GPT chat completions via ModelRouter e /marketing/generate.",
        notes: "Chave em OPENAI_API_KEY." },
    ],
  },
  {
    title: "Persistência & Banco",
    icon: Database,
    tools: [
      { name: "Supabase",                   where: "services/supabase_client.py",    purpose: "Cliente único + helpers seguros (_q, _one, _insert_one).",
        notes: "Tem retry transitório + curto-circuito quando KG não existe (PGRST205)." },
      { name: "Knowledge Graph",            where: "services/knowledge_graph.py",    purpose: "Grafo semântico (008) + curadoria canônica (009) + regras (010).",
        notes: "BFS focus, _detect_terms com prefixo PT (modal/modais), inferência de persona pelo grafo." },
      { name: "Migrations",                 where: "supabase/migrations/*.sql",      purpose: "001-012 — plataforma, KG, curadoria, validation rules, persona routing." },
    ],
  },
  {
    title: "Workers em background",
    icon: Activity,
    tools: [
      { name: "FlowValidatorWorker",        where: "workers/flow_validator_worker.py", purpose: "Roda regras de fluxo periodicamente." },
      { name: "N8nMirrorWorker",            where: "workers/n8n_mirror_worker.py",     purpose: "Espelha execuções do n8n para Supabase." },
      { name: "HealthCheckWorker",          where: "workers/health_check_worker.py",   purpose: "Coleta health score periódico." },
      { name: "KbSyncWorker",               where: "workers/kb_sync_worker.py",        purpose: "Sincroniza vault → knowledge_items → Golden Dataset/grafo." },
    ],
  },
  {
    title: "Rotas FastAPI principais",
    icon: Plug,
    tools: [
      { name: "/process",                   where: "api/routes/process.py",         purpose: "Entrada principal do n8n: classifica + responde + persiste.",
        notes: "Modo internal vs n8n por persona (011)." },
      { name: "/messages",                  where: "api/routes/messages.py",        purpose: "Histórico, conversas, send manual via webhook." },
      { name: "/leads",                     where: "api/routes/leads.py",           purpose: "Listagem com filtro por persona." },
      { name: "/knowledge/*",               where: "api/routes/knowledge.py",       purpose: "Upload, queue, Golden Dataset, chat-context.",
        notes: "Inclui /chat-context com inferência de persona pelo grafo." },
      { name: "/knowledge/graph-data",      where: "api/routes/graph.py",           purpose: "Payload do grafo (focus/depth/filters/registry)." },
      { name: "/marketing/generate",        where: "api/routes/marketing.py",       purpose: "Geração de copy via ModelRouter.",
        notes: "8 modos: copy, cold-email, email-sequence, ad-creative, lead-magnet, social, content-strategy, marketing-psychology." },
      { name: "/generate",                  where: "api/routes/generation.py",       purpose: "Campaign JSON (campanhas Figma)." },
      { name: "/wa-validator/*",            where: "api/routes/wa_validator.py",     purpose: "Geração de scripts E2E e execução." },
      { name: "/personas/*/routing",        where: "api/routes/personas.py",         purpose: "Internal vs n8n + webhook in/out." },
    ],
  },
  {
    title: "Skills / Modos de criação",
    icon: Sparkles,
    tools: [
      { name: "Marketing modes (8)",        where: "/marketing/criacao",             purpose: "Copy, cold-email, sequência, ads, lead magnet, social, estratégia, psicologia.",
        notes: "Distilados das marketing skills (coreyhaines31/marketingskills). System prompt persona-aware." },
      { name: "Criar",                      where: "services/kb_intake_service.py",  purpose: "Conversa curta para classificar conhecimento e salvar no vault." },
      { name: "Skill Creator (staged)",     where: "~/.claude/skills-staging/",      purpose: "7 repos clonados: anthropic, superpowers, pm, designer, marketing, composio.",
        notes: "Staged ainda. Plano de instalação curado em ~95 skills aguardando aprovação." },
    ],
  },
  {
    title: "Integrações externas",
    icon: GitBranch,
    tools: [
      { name: "n8n",                        where: "services/n8n_client.py",         purpose: "Webhook saída + ping + execuções.",
        notes: "Roteamento por persona via personas.outbound_webhook_url." },
      { name: "WhatsApp Web",               where: "services/wa_validator_service.py", purpose: "E2E real via Playwright.",
        notes: "Perfil persistente em .test-browser-profile/<bot>." },
      { name: "Vault local",                where: "services/vault_sync.py",         purpose: "Scan + sync de arquivos markdown para knowledge_items." },
      { name: "Figma plugin",               where: "integrations/figma/",            purpose: "Plugin recebe campaign.json de /generate." },
      { name: "MCP — claude.ai/Figma",      where: "MCP server",                     purpose: "Leitura/escrita Figma via MCP.",
        notes: "Disponível neste workspace via tools mcp__claude_ai_Figma__*." },
    ],
  },
  {
    title: "Frontend — features-chave",
    icon: BookOpen,
    tools: [
      { name: "Sidebar de Conhecimento",    where: "dashboard/app/messages/page.tsx", purpose: "Mostra conhecimento relacionado à conversa, expand inline.",
        notes: "Cards usam chat-context; clique expande; ícone Maximize2 abre /messages/[leadId]." },
      { name: "Grafo de Conhecimento",      where: "dashboard/app/knowledge/graph/", purpose: "3 modos (Camadas/Árvore/Livre) + focus + depth + toggles.",
        notes: "Layout em camadas usa knowledge_node_type_registry.level (009)." },
      { name: "Persona Routing UI",         where: "dashboard/app/persona/page.tsx", purpose: "Internal vs n8n + drawer de webhook URL/secret/token." },
      { name: "Pipeline / Insights / Logs", where: "dashboard/app/{pipeline,insights,logs}/", purpose: "Observabilidade operacional." },
    ],
  },
  {
    title: "Validação / Testes",
    icon: TestTube2,
    tools: [
      { name: "integration_chat_context",   where: "tests/integration_chat_context.py", purpose: "Vault sync + /process + chat-context + graph-data." },
      { name: "integration_prime_bulk_real", where: "tests/integration_prime_bulk_real.py", purpose: "Carga real Prime (5 produtos, 50 FAQs, 10 copies) + mensagens." },
      { name: "integration_moosi_winter26",  where: "tests/integration_moosi_winter26_graph.py", purpose: "Cenário Tock: produto + campanha + relacionados por slug/path." },
      { name: "integration_curation_arch",   where: "tests/integration_knowledge_curation_architecture.py", purpose: "Static + audit das migrations 009/010." },
      { name: "e2e_whatsapp_*",              where: "tests/e2e_whatsapp_*.py",        purpose: "E2E real via WhatsApp Web — Sofia/Tock e variações." },
      { name: "smoke_knowledge_graph",       where: "tests/smoke_knowledge_graph.py", purpose: "Smoke do grafo. Rodar como `python -m tests.smoke_knowledge_graph`." },
    ],
  },
];

const QUICK_FACTS = [
  { label: "Workers ativos", value: "4" },
  { label: "Rotas FastAPI", value: "16" },
  { label: "Migrations aplicadas", value: "012" },
  { label: "Modos de marketing", value: "8" },
  { label: "Personas seedadas", value: "Tock · Prime · Baita · VZ" },
];

export default function ToolsPage() {
  return (
    <div className="space-y-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center"
             style={{ background: "rgba(124,111,255,0.12)" }}>
          <Wrench size={16} className="text-obs-violet" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-white">Tools — ferramentas da plataforma</h1>
          <p className="text-[11px] text-obs-faint">Resumo prático do que está plugado e onde mexer.</p>
        </div>
      </div>

      {/* Quick facts row */}
      <div className="grid grid-cols-5 gap-2">
        {QUICK_FACTS.map((f) => (
          <div key={f.label}
            className="rounded-lg p-3"
            style={{ border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)" }}>
            <p className="text-[9px] uppercase tracking-wider text-obs-faint">{f.label}</p>
            <p className="text-sm font-semibold text-white mt-0.5 truncate">{f.value}</p>
          </div>
        ))}
      </div>

      {/* Sections */}
      <div className="grid grid-cols-2 gap-4">
        {SECTIONS.map((s) => (
          <ToolSectionCard key={s.title} section={s} />
        ))}
      </div>

      <div className="rounded-lg p-3 text-[11px] text-obs-faint"
           style={{ border: "1px dashed rgba(255,255,255,0.10)", background: "rgba(255,255,255,0.02)" }}>
        <p>
          <b className="text-obs-subtle">Atualização:</b> esta lista é estática.
          Ao adicionar nova rota, worker, integração ou modo, edite{" "}
          <code className="text-obs-violet">dashboard/app/validacao/tools/page.tsx</code>.
        </p>
      </div>
    </div>
  );
}

function ToolSectionCard({ section }: { section: Section }) {
  const Icon = section.icon;
  return (
    <div className="rounded-xl overflow-hidden"
         style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}>
      <div className="flex items-center gap-2 px-4 py-2.5"
           style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.02)" }}>
        <Icon size={13} className="text-obs-violet" />
        <span className="text-xs font-semibold text-white">{section.title}</span>
        <span className="ml-auto text-[10px] text-obs-faint">{section.tools.length}</span>
      </div>
      <ul className="divide-y" style={{ borderColor: "rgba(255,255,255,0.04)" }}>
        {section.tools.map((t) => (
          <li key={t.name} className="px-4 py-2.5">
            <div className="flex items-baseline justify-between gap-2 min-w-0">
              <p className="text-xs font-medium text-white truncate">{t.name}</p>
              <code className="text-[10px] text-obs-violet/80 truncate max-w-[55%]">{t.where}</code>
            </div>
            <p className="text-[11px] text-obs-subtle mt-0.5">{t.purpose}</p>
            {t.notes && (
              <p className="text-[10px] text-obs-faint mt-1 leading-snug">{t.notes}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
