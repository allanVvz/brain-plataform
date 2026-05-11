"use client";

import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bot,
  CheckCircle,
  Code2,
  Circle,
  ClipboardList,
  FileText,
  FolderOpen,
  Link,
  Loader2,
  Network,
  Play,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import { api } from "@/lib/api";

const MODELS = [
  { id: "gpt-4o-mini", label: "GPT-4o Mini - rapido" },
  { id: "gpt-4o", label: "GPT-4o - balanceado" },
  { id: "gpt-3.5-turbo", label: "GPT-3.5 Turbo - legado" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku - fallback" },
];

const TYPE_OPTIONS = [
  { value: "brand", label: "Brand / Identidade" },
  { value: "briefing", label: "Briefing" },
  { value: "product", label: "Produto" },
  { value: "campaign", label: "Campanha" },
  { value: "copy", label: "Copy / Texto" },
  { value: "faq", label: "FAQ / Golden Dataset" },
  { value: "tone", label: "Tom de Voz" },
  { value: "rule", label: "Regra / Padrao" },
  { value: "asset", label: "Asset Visual" },
  { value: "other", label: "Outro" },
];

const DEFAULT_OBJECTIVE =
  "Criar conhecimento de marketing em grafo a partir da fonte informada, com briefing, publico, produto, copy e FAQ.";

const DEFAULT_SOURCE = "";

const KNOWLEDGE_BLOCKS = [
  { id: "brand", label: "Brand", description: "Identidade, proposta, posicionamento e promessas confirmadas." },
  { id: "briefing", label: "Briefing", description: "Contexto bruto, objetivo, fonte e restricoes da captura." },
  { id: "campaign", label: "Campanha", description: "Colecoes, lancamentos, sazonalidade e angulos comerciais." },
  { id: "audience", label: "Publico", description: "Segmentos, dores, desejos, linguagem e objecoes." },
  { id: "product", label: "Produto", description: "Itens, kits, beneficios, precos, disponibilidade e atributos." },
  { id: "offer", label: "Oferta", description: "Preco, quantidade, pacote, kit ou variacao comercial." },
  { id: "entity", label: "Entidades", description: "Cores, materiais, categorias, variantes e termos relacionados." },
  { id: "copy", label: "Copy", description: "Textos comerciais por canal, publico, etapa e oferta." },
  { id: "faq", label: "FAQ", description: "Perguntas e respostas recuperaveis pelo Golden Dataset." },
  { id: "rule", label: "Regras", description: "Politicas comerciais, limites, validacoes e padroes operacionais." },
  { id: "tone", label: "Tom de voz", description: "Estilo, delicadeza, vocabulario e restricoes de linguagem." },
  { id: "asset", label: "Assets", description: "Imagens, referencias visuais, criativos e materiais de apoio." },
];

const DEFAULT_SELECTED_BLOCKS = ["briefing", "audience", "product", "copy", "faq"];

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface Classification {
  persona_slug: string | null;
  content_type: string | null;
  asset_type: string | null;
  asset_function: string | null;
  title: string | null;
}

interface Persona {
  id: string;
  slug: string;
  name: string;
}

interface SessionUpload {
  id: string;
  title: string;
  content_type: string;
  persona_id?: string;
  source: "text" | "file";
  file_name?: string;
  preview: string;
  knowledge_item_id?: string;
}

interface CrawlerRun {
  url: string;
  status_code?: number;
  confidence?: number;
  confidence_label?: string;
  warnings?: string[];
  stages?: Array<{ key: string; label: string; status: string }>;
  product_candidates?: Array<Record<string, any>>;
}

interface CapturePlan {
  personaSlug: string;
  objective: string;
  sourceUrl: string;
  outputFormat: string;
  selectedBlocks: string[];
  variationCounts: Record<string, number>;
  confirmed: boolean;
}

interface MissionState {
  persona?: string;
  objective?: string;
  source?: { type?: string; url?: string };
  knowledge_blocks?: string[];
  requested_outputs?: { models?: Array<{ name?: string; audience?: string; products_requested?: number; fields?: string[] }> };
  format?: string;
  status?: string;
  evidence_items?: Array<Record<string, any>>;
}

interface KnowledgePlanEntry {
  content_type: string;
  title: string;
  slug: string;
  status: string;
  content: string;
  tags: string[];
  metadata: Record<string, any>;
}

interface KnowledgePlanLink {
  source_slug: string;
  target_slug: string;
  relation_type: string;
}

interface KnowledgePlan {
  source: string;
  persona_slug: string;
  validation_policy: string;
  tree_mode?: string;
  branch_policy?: string;
  faq_count_policy?: string;
  entries: KnowledgePlanEntry[];
  links: KnowledgePlanLink[];
  missing_questions?: string[];
}

type BlockCounts = Record<string, number>;

interface PlanState {
  normalized_plan: KnowledgePlan;
  validation: {
    valid: boolean;
    blocking_violations: string[];
    warnings: string[];
  };
  summary: {
    entry_count: number;
    current_block_counts: BlockCounts;
    link_count: number;
    tree_mode: string;
    branch_policy: string;
    faq_count_policy: string;
  };
  plan_hash: string;
}

const COUNTED_BLOCK_IDS = ["brand", "briefing", "campaign", "audience", "product", "offer", "copy", "faq", "rule", "tone", "asset"];
const SIDEBAR_TREE_BLOCKS = [
  { id: "persona", label: "Persona", description: "Raiz da sessao CRIAR." },
  ...KNOWLEDGE_BLOCKS,
  { id: "embedded", label: "Embedded", description: "Destino RAG apos validacao de FAQ." },
  { id: "gallery", label: "Gallery", description: "Destino visual para assets aprovados." },
];

function emptyBlockCounts(): BlockCounts {
  return Object.fromEntries(COUNTED_BLOCK_IDS.map((id) => [id, 0]));
}

function normalizeBlockCounts(value?: Record<string, any> | null): BlockCounts {
  const counts = emptyBlockCounts();
  for (const key of COUNTED_BLOCK_IDS) {
    const n = Number(value?.[key] ?? 0);
    counts[key] = Number.isFinite(n) ? Math.max(0, Math.trunc(n)) : 0;
  }
  return counts;
}

function countBlocksByType(entries?: KnowledgePlanEntry[] | null): BlockCounts {
  const counts = emptyBlockCounts();
  for (const entry of entries || []) {
    const type = normalizeContentTypeAlias(entry.content_type);
    if (type in counts) counts[type] += 1;
  }
  return counts;
}

function normalizeContentTypeAlias(value: any) {
  const type = repairText(String(value || "")).trim().toLowerCase();
  const aliases: Record<string, string> = {
    regras: "rule",
    rules: "rule",
    regra: "rule",
    ofertas: "offer",
    oferta: "offer",
    offers: "offer",
    product_variant: "offer",
    purchase_option: "offer",
    opcao: "offer",
    opção: "offer",
    variacao: "offer",
    variação: "offer",
    pacote: "offer",
    kit: "offer",
  };
  return aliases[type] || type || "other";
}

function isInvalidCriarPersona(slug?: string | null) {
  return ["", "all", "todos", "global"].includes(String(slug || "").trim().toLowerCase());
}

function labelForBlockId(blockId: string) {
  return SIDEBAR_TREE_BLOCKS.find((block) => block.id === blockId)?.label || blockId;
}

function createManualDraftEntry(blockId: string, index: number, personaSlug: string, currentPlan: KnowledgePlan | null): KnowledgePlanEntry {
  const title = `${labelForBlockId(blockId)} ${index}`;
  const slug = `${slugifyPlanValue(blockId)}-manual-${Date.now().toString(36)}-${index}`;
  const entries = currentPlan?.entries || [];
  const latestOf = (type: string) => [...entries].reverse().find((entry) => entry.content_type === type)?.slug;
  const parentByType: Record<string, string | undefined> = {
    briefing: "self",
    campaign: latestOf("briefing"),
    audience: latestOf("campaign") || latestOf("briefing"),
    product: latestOf("audience"),
    offer: latestOf("product"),
    copy: latestOf("offer") || latestOf("product"),
    faq: latestOf("copy") || latestOf("product"),
    rule: latestOf("campaign") || latestOf("briefing") || latestOf("brand"),
    tone: latestOf("brand") || latestOf("briefing"),
    asset: latestOf("product") || latestOf("brand"),
  };
  return {
    content_type: blockId,
    title,
    slug,
    status: "pendente_validacao",
    content: `${title} adicionado manualmente na sidebar para ${personaSlug || "persona"}.`,
    tags: [blockId, "manual"],
    metadata: {
      parent_slug: parentByType[blockId],
      edited_in_sidebar: true,
    },
  };
}

function parseApiErrorBody(message: string): Record<string, unknown> | null {
  // lib/api.ts throws "${status} ${path} - ${jsonBody}". Recover the JSON body.
  const dashIdx = message.indexOf(" - ");
  if (dashIdx < 0) return null;
  const tail = message.slice(dashIdx + 3).trim();
  if (!tail.startsWith("{") && !tail.startsWith("[")) return null;
  try {
    return JSON.parse(tail);
  } catch {
    return null;
  }
}

function formatChatRequestError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  const parsed = parseApiErrorBody(message);
  const bodyMessage = typeof parsed?.message === "string" ? parsed.message : null;
  const bodyDetail = typeof parsed?.detail === "string" ? parsed.detail : null;
  if (bodyMessage) return bodyMessage;
  if (bodyDetail) return bodyDetail;
  if (message.includes("/kb-intake/message")) {
    return "Nao consegui processar sua mensagem agora. Sua configuracao foi mantida.";
  }
  if (message.includes("/kb-intake/start")) {
    return "Nao consegui iniciar a conversa agora. Tente novamente.";
  }
  return "Nao consegui processar agora. Tente novamente.";
}

function formatSaveError(body: Record<string, unknown> | null | undefined): string {
  if (!body) return "Erro ao salvar.";
  const error = (body.error as string) || (body.detail as string) || "Erro ao salvar.";
  const violations = body.violations as string[] | undefined;
  if (Array.isArray(violations) && violations.length > 0) {
    return `Erro: ${error}\n- ${violations.join("\n- ")}`;
  }
  return `Erro: ${error}`;
}

function repairText(value: string) {
  if (!value || !/(Ã|â€|â€œ|â€�|â€˜|â€™|âˆ|â”|�)/.test(value)) return value;
  try {
    return decodeURIComponent(escape(value));
  } catch {
    return value;
  }
}

function slugifyPlanValue(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-") || "item";
}

function normalizePlanEntry(entry: any): KnowledgePlanEntry {
  const contentType = normalizeContentTypeAlias(entry?.content_type || "other");
  return {
    content_type: contentType,
    title: repairText(String(entry?.title || "Conhecimento")).trim() || "Conhecimento",
    slug: slugifyPlanValue(String(entry?.slug || entry?.title || "item")),
    status: repairText(String(entry?.status || "pendente_validacao")).trim() || "pendente_validacao",
    content: repairText(String(entry?.content || entry?.title || "Conhecimento")).trim() || "Conhecimento",
    tags: Array.isArray(entry?.tags) ? entry.tags.map((tag: any) => repairText(String(tag)).trim()).filter(Boolean) : [],
    metadata: entry?.metadata && typeof entry.metadata === "object" ? { ...entry.metadata } : {},
  };
}

const PREVIEW_TYPE_RANK: Record<string, number> = {
  brand: 1,
  briefing: 2,
  campaign: 3,
  audience: 4,
  product: 5,
  offer: 6,
  copy: 7,
  rule: 8,
  asset: 9,
  tone: 10,
  faq: 11,
};

function sharedPlanTokens(left: string, right: string) {
  const normalize = (value: string) =>
    value
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, " ")
      .toLowerCase()
      .split(/[\s-]+/)
      .filter((token) => token && !["faq", "copy", "product", "audience", "briefing", "campaign"].includes(token));
  const leftTokens = new Set(normalize(left));
  let score = 0;
  for (const token of normalize(right)) {
    if (leftTokens.has(token)) score += 1;
  }
  return score;
}

function bestParentCandidate(entry: KnowledgePlanEntry, candidates: KnowledgePlanEntry[]) {
  let best: KnowledgePlanEntry | null = null;
  let bestScore = -1;
  for (const candidate of candidates) {
    if (candidate.slug === entry.slug) continue;
    const score =
      sharedPlanTokens(`${entry.slug} ${entry.title}`, `${candidate.slug} ${candidate.title}`) +
      (entry.content.includes(candidate.title) ? 2 : 0);
    if (score > bestScore) {
      bestScore = score;
      best = candidate;
    }
  }
  return best || candidates[candidates.length - 1] || null;
}

function normalizePreviewPlan(plan: KnowledgePlan): KnowledgePlan {
  return plan;
}

function normalizeKnowledgePlan(plan: any, personaSlug: string): KnowledgePlan | null {
  if (!plan || !Array.isArray(plan.entries) || plan.entries.length === 0) return null;
  const entries = plan.entries.map(normalizePlanEntry);
  return {
    source: String(plan.source || ""),
    persona_slug: String(plan.persona_slug || personaSlug || "global"),
    validation_policy: String(plan.validation_policy || "human_validation_required"),
    tree_mode: String(plan.tree_mode || "single_branch"),
    branch_policy: String(plan.branch_policy || "single_branch_by_default"),
    faq_count_policy: String(plan.faq_count_policy || "total"),
    entries,
    links: Array.isArray(plan.links)
      ? plan.links
          .map((link: any) => ({
            source_slug: String(link?.source_slug || "").trim(),
            target_slug: String(link?.target_slug || "").trim(),
            relation_type: String(link?.relation_type || "contains").trim() || "contains",
          }))
          .filter((link: KnowledgePlanLink) => link.source_slug && link.target_slug)
      : [],
    missing_questions: Array.isArray(plan.missing_questions)
      ? plan.missing_questions.map((item: any) => repairText(String(item)))
      : [],
  };
}

function buildLocalPlanState(plan: KnowledgePlan | null, fallbackCounts?: Record<string, any> | null): PlanState | null {
  if (!plan) return null;
  const counts = countBlocksByType(plan.entries);
  const summary = {
    entry_count: plan.entries.length,
    current_block_counts: normalizeBlockCounts(fallbackCounts || counts),
    link_count: Array.isArray(plan.links) ? plan.links.length : 0,
    tree_mode: String((plan as any).tree_mode || "single_branch"),
    branch_policy: String((plan as any).branch_policy || "single_branch_by_default"),
    faq_count_policy: String((plan as any).faq_count_policy || "total"),
  };
  return {
    normalized_plan: plan,
    validation: { valid: true, blocking_violations: [], warnings: [] },
    summary,
    plan_hash: String((plan as any).plan_hash || ""),
  };
}

function normalizePlanState(raw: any, personaSlug: string): PlanState | null {
  const source = raw?.plan_state || raw;
  if (!source || typeof source !== "object") return null;
  const rawPlan = source.normalized_plan || raw?.normalized_plan || raw?.knowledge_plan;
  const normalizedPlan = normalizeKnowledgePlan(rawPlan, personaSlug);
  if (!normalizedPlan) return null;
  const summary = source.summary || raw?.plan_summary || {};
  const validation = source.validation || raw?.plan_validation || {};
  return {
    normalized_plan: normalizedPlan,
    validation: {
      valid: validation.valid !== false,
      blocking_violations: Array.isArray(validation.blocking_violations) ? validation.blocking_violations.map((item: any) => String(item)) : [],
      warnings: Array.isArray(validation.warnings) ? validation.warnings.map((item: any) => String(item)) : [],
    },
    summary: {
      entry_count: Number(summary.entry_count ?? normalizedPlan.entries.length),
      current_block_counts: normalizeBlockCounts(summary.current_block_counts || raw?.current_block_counts || countBlocksByType(normalizedPlan.entries)),
      link_count: Number(summary.link_count ?? normalizedPlan.links.length),
      tree_mode: String(summary.tree_mode || (normalizedPlan as any).tree_mode || "single_branch"),
      branch_policy: String(summary.branch_policy || (normalizedPlan as any).branch_policy || "single_branch_by_default"),
      faq_count_policy: String(summary.faq_count_policy || (normalizedPlan as any).faq_count_policy || "total"),
    },
    plan_hash: String(source.plan_hash || raw?.plan_hash || ""),
  };
}

function planStateCountsMatch(planState: PlanState | null) {
  if (!planState) return false;
  const actual = countBlocksByType(planState.normalized_plan.entries);
  const expected = normalizeBlockCounts(planState.summary.current_block_counts);
  return COUNTED_BLOCK_IDS.every((key) => Number(actual[key] || 0) === Number(expected[key] || 0))
    && planState.normalized_plan.entries.length === Number(planState.summary.entry_count || 0);
}

function summarizePlanStateForChat(planState: PlanState): string {
  const counts = normalizeBlockCounts(planState.summary.current_block_counts);
  const lines = [
    `Plano normalizado: ${planState.summary.entry_count} bloco(s).`,
    `Resumo: briefing ${counts.briefing || 0}, campanha ${counts.campaign || 0}, publico ${counts.audience || 0}, produto ${counts.product || 0}, oferta ${counts.offer || 0}, copy ${counts.copy || 0}, FAQ ${counts.faq || 0}, regra ${counts.rule || 0}.`,
    `Politica: ${planState.summary.tree_mode} / ${planState.summary.branch_policy}; FAQ ${planState.summary.faq_count_policy}.`,
  ];
  const violations = planState.validation.blocking_violations || [];
  if (violations.length > 0) {
    lines.push("Plano ainda nao esta pronto para salvar.");
    lines.push("Pendencias bloqueantes:");
    lines.push(...violations.map((violation) => `- ${repairText(violation)}`));
  } else {
    lines.push("Pendencias bloqueantes: nenhuma.");
  }
  return lines.join("\n");
}

function parentSlugOf(entry: KnowledgePlanEntry) {
  const parentSlug = entry.metadata?.parent_slug;
  return typeof parentSlug === "string" && parentSlug.trim() ? parentSlug.trim() : null;
}

function normalizeParentSlug(parentSlug: string | null, personaSlug: string) {
  if (!parentSlug) return null;
  const raw = parentSlug.trim();
  const normalized = slugifyPlanValue(raw);
  if (["global", "root", "persona", "persona-root"].includes(normalized)) return "self";
  if (personaSlug && normalized === slugifyPlanValue(personaSlug)) return "self";
  return raw;
}

function rebuildPlanLinks(plan: KnowledgePlan): KnowledgePlan {
  return plan;
}

function validatePreviewPlan(plan: KnowledgePlan | null | undefined): string[] {
  if (!plan || !Array.isArray(plan.entries) || plan.entries.length === 0) return [];
  const errors: string[] = [];
  const entries = plan.entries;
  const bySlug = new Map(entries.map((entry) => [entry.slug, entry]));
  const slugs = entries.map((entry) => entry.slug).filter(Boolean);
  if (new Set(slugs).size !== slugs.length) errors.push("Plano contem slugs duplicados.");
  const hasOffer = entries.some((entry) => entry.content_type === "offer");
  const hasCopy = entries.some((entry) => entry.content_type === "copy");
  for (const entry of entries) {
    const parentSlug = normalizeParentSlug(parentSlugOf(entry), plan.persona_slug);
    const parentType = parentSlug === "self" ? "persona" : parentSlug ? bySlug.get(parentSlug)?.content_type || "" : "";
    if (entry.content_type === "product" && entry.slug.includes("audience")) {
      errors.push(`Produto ${entry.slug} nao pode embutir audience no slug.`);
    }
    if (entry.content_type === "offer" && parentType !== "product") {
      errors.push(`Oferta ${entry.slug} precisa estar abaixo de product.`);
    }
    if (entry.content_type === "copy") {
      if (hasOffer && parentType !== "offer") errors.push(`Copy ${entry.slug} precisa estar abaixo de offer.`);
      if (!hasOffer && parentType && !["product", "campaign", "briefing", "brand"].includes(parentType)) {
        errors.push(`Copy ${entry.slug} tem parent invalido.`);
      }
    }
    if (entry.content_type === "faq" && hasCopy && parentType !== "copy") {
      errors.push(`FAQ ${entry.slug} precisa estar abaixo de copy.`);
    }
    if (entry.content_type === "rule" && parentType && !["campaign", "briefing", "brand", "persona"].includes(parentType)) {
      errors.push(`Rule ${entry.slug} precisa estar abaixo de campaign/briefing/brand.`);
    }
  }
  return errors;
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g);
  return tokens.filter(Boolean).map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if (token.startsWith("`") && token.endsWith("`")) {
      return <code key={key} className="rounded-md bg-black/30 px-1.5 py-0.5 font-mono text-[0.9em] text-obs-amber">{token.slice(1, -1)}</code>;
    }
    if (token.startsWith("**") && token.endsWith("**")) {
      return <strong key={key} className="font-semibold text-white">{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith("*") && token.endsWith("*")) {
      return <em key={key} className="italic text-obs-text">{token.slice(1, -1)}</em>;
    }
    const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      return (
        <a
          key={key}
          href={linkMatch[2]}
          target="_blank"
          rel="noreferrer"
          className="text-obs-violet underline decoration-obs-violet/40 underline-offset-2 hover:text-white"
        >
          {linkMatch[1]}
        </a>
      );
    }
    return <Fragment key={key}>{token}</Fragment>;
  });
}

function renderMarkdownContent(content: string): ReactNode {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;

  const isBlockStart = (line: string) =>
    /^```/.test(line) ||
    /^#{1,6}\s+/.test(line) ||
    /^>\s?/.test(line) ||
    /^[-*]\s+/.test(line) ||
    /^\d+\.\s+/.test(line) ||
    /^---+$/.test(line);

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim();
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push(
        <div key={`code-${blocks.length}`} className="overflow-hidden rounded-xl border border-white/8 bg-[#0f1117]">
          {lang && <div className="border-b border-white/8 px-3 py-1.5 text-[10px] uppercase tracking-[0.18em] text-obs-faint">{lang}</div>}
          <pre className="overflow-x-auto px-3.5 py-3 text-[12px] leading-6 text-obs-amber"><code>{codeLines.join("\n")}</code></pre>
        </div>,
      );
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      const match = line.match(/^(#{1,6})\s+(.*)$/);
      const level = match?.[1].length || 1;
      const text = match?.[2] || line;
      const Tag = `h${Math.min(level + 1, 6)}` as keyof JSX.IntrinsicElements;
      const className = {
        1: "text-xl font-semibold text-white",
        2: "text-lg font-semibold text-white",
        3: "text-base font-semibold text-white",
        4: "text-sm font-semibold text-white",
        5: "text-sm font-medium text-obs-text",
        6: "text-xs font-medium uppercase tracking-[0.18em] text-obs-faint",
      }[level];
      blocks.push(<Tag key={`h-${blocks.length}`} className={className}>{renderInlineMarkdown(text, `h-${blocks.length}`)}</Tag>);
      i += 1;
      continue;
    }
    if (/^---+$/.test(line.trim())) {
      blocks.push(<div key={`hr-${blocks.length}`} className="my-1 border-t border-white/8" />);
      i += 1;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push(
        <blockquote key={`q-${blocks.length}`} className="border-l-2 border-obs-violet/40 bg-white/[0.03] px-3 py-2 text-sm italic text-obs-subtle">
          {quoteLines.map((quoteLine, idx) => <div key={idx}>{renderInlineMarkdown(quoteLine, `q-${blocks.length}-${idx}`)}</div>)}
        </blockquote>,
      );
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="space-y-1.5 pl-5 text-sm text-obs-text">
          {items.map((item, idx) => <li key={idx} className="list-disc marker:text-obs-violet">{renderInlineMarkdown(item, `ul-${blocks.length}-${idx}`)}</li>)}
        </ul>,
      );
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`} className="space-y-1.5 pl-5 text-sm text-obs-text">
          {items.map((item, idx) => <li key={idx} className="list-decimal marker:text-obs-violet">{renderInlineMarkdown(item, `ol-${blocks.length}-${idx}`)}</li>)}
        </ol>,
      );
      continue;
    }

    const paragraphLines: string[] = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      paragraphLines.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p key={`p-${blocks.length}`} className="text-sm leading-7 text-obs-text">
        {paragraphLines.map((paragraphLine, idx) => (
          <Fragment key={idx}>
            {idx > 0 && <br />}
            {renderInlineMarkdown(paragraphLine, `p-${blocks.length}-${idx}`)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="space-y-3">{blocks}</div>;
}

function MessageBody({ content, raw, role }: { content: string; raw: boolean; role: Message["role"] }) {
  const safeContent = repairText(content);
  if (raw) {
    return (
      <pre className={`whitespace-pre-wrap break-words ${role === "system" ? "font-mono text-xs" : "font-mono text-[12px] leading-6"}`}>
        {safeContent}
      </pre>
    );
  }
  return <div className={role === "system" ? "text-xs leading-6" : ""}>{renderMarkdownContent(safeContent)}</div>;
}

const DEFAULT_VARIATION_COUNTS = KNOWLEDGE_BLOCKS.reduce<Record<string, number>>((acc, block) => {
  if (DEFAULT_SELECTED_BLOCKS.includes(block.id)) {
    acc[block.id] = block.id === "faq" ? 2 : 1;
  } else {
    acc[block.id] = 0;
  }
  return acc;
}, {});

function StepDot({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {done ? (
        <CheckCircle size={12} className="text-green-400 shrink-0" />
      ) : (
        <Circle size={12} className="text-obs-faint shrink-0" />
      )}
      <span className={`text-xs ${done ? "text-green-400" : "text-obs-subtle"}`}>{label}</span>
    </div>
  );
}

function buildInitialContext(plan: CapturePlan, uploads: SessionUpload[]) {
  const selectedBlockText = plan.selectedBlocks.length
    ? plan.selectedBlocks
        .map((id) => {
          const block = KNOWLEDGE_BLOCKS.find((item) => item.id === id);
          return block ? `- ${block.id}: ${block.label} - ${block.description}` : `- ${id}`;
        })
        .join("\n")
    : "- nenhum bloco selecionado; pergunte ao operador quais blocos deseja capturar.";

  const uploadBlock = uploads.length
    ? uploads
        .map((u, i) => {
          return [
            `### Upload ${i + 1}: ${u.title}`,
            `- source: ${u.source}${u.file_name ? ` (${u.file_name})` : ""}`,
            `- content_type: ${u.content_type}`,
            `- knowledge_item_id: ${u.knowledge_item_id || "pending"}`,
            "",
            u.preview,
          ].join("\n");
        })
        .join("\n\n")
    : "Nenhum upload manual nesta sessao.";

  const variationBlock = KNOWLEDGE_BLOCKS
    .filter((block) => plan.selectedBlocks.includes(block.id))
    .map((block) => `- ${block.id}: ${Math.max(1, Number(plan.variationCounts[block.id] || 1))} variacao(oes) por ramo`)
    .join("\n");

  return [
    "# Plano confirmado pelo operador",
    `persona_slug: ${plan.personaSlug}`,
    `objetivo: ${plan.objective}`,
    `fonte principal: ${plan.sourceUrl}`,
    `saida esperada: ${plan.outputFormat}`,
    "",
    "## Blocos de conhecimento solicitados",
    selectedBlockText,
    "",
    "## Variacoes por atributo",
    variationBlock || "- usar 1 variacao por bloco; FAQ padrao 2.",
    "",
    "## Uploads manuais da sessao",
    uploadBlock,
    "",
    "## Regras de execucao",
    "- Se o operador pedir para ler/coletar o site, acionar captura bruta/crawler quando disponivel e tratar resultado como evidencia com confianca, nao como verdade perfeita.",
    "- Antes de gerar ou salvar, confirmar fontes e entries.",
    "- Se faltar qualquer informacao, perguntar ao operador antes de propor ou salvar.",
    "- Fazer no maximo 3 perguntas objetivas por rodada.",
    "- Os blocos selecionados sao a intencao inicial; se a conversa mudar, aceitar novos blocos e perguntar lacunas especificas.",
    "- Ao gerar, produzir diversos conhecimentos: uma proposta por bloco selecionado e uma entry por produto/FAQ/copy quando houver dados suficientes.",
    "- O plano inicial e apenas ponto de partida; se o operador expandir para 2 publicos, 4 produtos e 8 FAQs, manter esse plano vivo.",
    "- Sempre usar o knowledge_plan atual como fonte para salvar; nunca voltar ao plano inicial apos expansao.",
    "- Sempre criar uma estrutura de conhecimento baseada em grafo hierarquizado.",
    "- Gerar conhecimento hierarquizado como grafo quando houver relacoes entre brand, campanha, publico, produto, entidades, copy, FAQ, regra ou tom.",
    "- Respeitar as quantidades de variacao por bloco; FAQ deve se multiplicar por conhecimento quando configurado.",
    "- Nao inventar precos, cores, disponibilidade ou URLs.",
    "- CRIAR exige persona especifica; nao usar Todos/global para criar conhecimento.",
  ].join("\n");
}

function PreflightPanel({
  plan,
  setPlan,
  model,
  setModel,
  onStart,
  loading,
  uploads,
  personas,
  onPersonaChange,
}: {
  plan: CapturePlan;
  setPlan: (next: CapturePlan) => void;
  model: string;
  setModel: (value: string) => void;
  onStart: () => void;
  loading: boolean;
  uploads: SessionUpload[];
  personas: Persona[];
  onPersonaChange: (slug: string) => void;
}) {
  const selectedBlocks = new Set(plan.selectedBlocks);
  const blockCount = (id: string) => Math.max(0, Number(plan.variationCounts[id] ?? 0));
  const defaultCountFor = (id: string) => (id === "faq" ? 2 : 1);

  const setBlockCount = (blockId: string, next: number) => {
    const value = Math.max(0, next);
    const nextSelected = value > 0
      ? Array.from(new Set([...plan.selectedBlocks, blockId]))
      : plan.selectedBlocks.filter((id) => id !== blockId);
    setPlan({
      ...plan,
      selectedBlocks: nextSelected,
      variationCounts: { ...plan.variationCounts, [blockId]: value },
    });
  };

  const adjust = (blockId: string, delta: number) => {
    const current = blockCount(blockId);
    if (delta > 0 && current === 0) {
      setBlockCount(blockId, defaultCountFor(blockId));
    } else {
      setBlockCount(blockId, current + delta);
    }
  };

  const selectedCount = plan.selectedBlocks.length;
  const personaMissing = isInvalidCriarPersona(plan.personaSlug);

  return (
    <div className="panel flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="-mx-[22px] -mt-[22px] flex items-center justify-between px-5 py-4 [border-bottom:1px_solid_var(--border-glass-soft)]">
        <div className="flex items-center gap-2">
          <ClipboardList size={15} className="text-obs-violet" />
          <span className="text-sm font-semibold text-obs-text">Pre-confirmacao</span>
        </div>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="lg-input py-1 text-xs"
        >
          {MODELS.map((m) => (
            <option key={m.id} value={m.id} className="bg-obs-raised">{m.label}</option>
          ))}
        </select>
      </div>

      {/* Body */}
      <div className="-mx-[22px] flex-1 overflow-y-auto px-5 py-5 space-y-4">
        {/* Plan summary */}
        <div className="grid gap-2 md:grid-cols-2">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Persona</label>
            <select
              value={plan.personaSlug}
              onChange={(e) => onPersonaChange(e.target.value)}
              className="lg-input w-full text-sm"
            >
              <option value="">Selecione uma persona</option>
              {personas.map((persona) => (
                <option key={persona.slug} value={persona.slug}>
                  {persona.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Fonte principal</label>
            <input
              value={plan.sourceUrl}
              onChange={(e) => setPlan({ ...plan, sourceUrl: e.target.value })}
              className="lg-input w-full text-sm"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Objetivo</label>
            <textarea
              value={plan.objective}
              onChange={(e) => setPlan({ ...plan, objective: e.target.value })}
              rows={2}
              className="lg-input w-full text-sm resize-none"
            />
          </div>
        </div>

        {/* Knowledge blocks (single unified list) */}
        <div>
          <div className="mb-2 flex items-baseline justify-between">
            <label className="text-[10px] uppercase tracking-wider text-obs-faint">Blocos de conhecimento</label>
            <span className="text-[10px] text-obs-faint">{selectedCount} no plano</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {KNOWLEDGE_BLOCKS.map((block) => {
              const count = blockCount(block.id);
              const selected = count > 0;
              return (
                <div
                  key={block.id}
                  className={`flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors ${
                    selected
                      ? "bg-obs-violet/10 [border:1px_solid_rgb(var(--obs-violet)/0.28)]"
                      : "bg-white/[0.025] [border:1px_solid_var(--border-glass)]"
                  }`}
                >
                  <Stepper
                    value={count}
                    onDec={() => adjust(block.id, -1)}
                    onInc={() => adjust(block.id, +1)}
                    blockId={block.id}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      {selected
                        ? <CheckCircle size={11} className="text-obs-violet shrink-0" />
                        : <Circle size={11} className="text-obs-faint shrink-0" />}
                      <span className="text-xs font-semibold text-obs-text">{block.label}</span>
                    </div>
                    <p className="mt-0.5 text-[11px] leading-snug text-obs-subtle">{block.description}</p>
                    <p className="mt-1 text-[10px] text-obs-faint">
                      {selected ? "Selecionado no plano atual" : "Fora do plano atual"}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-obs-faint">
            A selecao e ponto de partida. Durante a conversa o agente pode adicionar, remover ou trocar blocos conforme o pedido mudar.
          </p>
          {personaMissing && (
            <p className="mt-2 text-[11px] text-obs-amber">
              Selecione uma persona antes de criar conhecimento.
            </p>
          )}
        </div>

        {/* Confirmation */}
        <label className="flex items-start gap-2 rounded-xl bg-white/[0.04] px-3 py-2 text-xs text-obs-subtle [border:1px_solid_var(--border-glass)]">
          <input
            type="checkbox"
            checked={plan.confirmed}
            onChange={(e) => setPlan({ ...plan, confirmed: e.target.checked })}
            className="mt-0.5 accent-obs-violet"
          />
          <span>
            {!uploads.some((upload) => upload.source === "file")
              ? "Sessao pronta para iniciar. Sem uploads adicionais, o plano ja entra confirmado por padrao."
              : `Confirmo que o modelo deve usar este plano e os ${uploads.length} upload(s) da sessao como contexto. Se faltar dado, ele deve perguntar antes de propor entradas, copys ou salvar.`}
          </span>
        </label>
      </div>

      {/* Footer */}
      <div className="-mx-[22px] -mb-[22px] px-5 py-4 [border-top:1px_solid_var(--border-glass-soft)]">
        <button
          onClick={onStart}
          disabled={loading || !plan.confirmed || plan.selectedBlocks.length === 0 || personaMissing}
          className="lg-btn lg-btn-primary w-full justify-center"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          Inicializar criacao de conhecimento
        </button>
      </div>
    </div>
  );
}

function Stepper({
  value,
  onDec,
  onInc,
  blockId,
}: {
  value: number;
  onDec: () => void;
  onInc: () => void;
  blockId: string;
}) {
  return (
    <div className="flex items-center gap-0.5 rounded-full bg-white/[0.05] p-0.5 [border:1px_solid_var(--border-glass)]">
      <button
        type="button"
        onClick={onDec}
        disabled={value <= 0}
        className="h-6 w-6 rounded-full text-xs text-obs-subtle hover:bg-white/[0.08] hover:text-obs-text disabled:opacity-40 disabled:hover:bg-transparent"
        aria-label={`reduzir-${blockId}`}
        data-testid={`reduzir-${blockId}`}
      >
        −
      </button>
      <span className="w-6 text-center text-xs font-semibold text-obs-text tabular-nums">{value}</span>
      <button
        type="button"
        onClick={onInc}
        className="h-6 w-6 rounded-full text-xs text-obs-subtle hover:bg-white/[0.08] hover:text-obs-text"
        aria-label={`aumentar-${blockId}`}
        data-testid={`aumentar-${blockId}`}
      >
        +
      </button>
    </div>
  );
}

function ChatPanel({
  plan,
  setPlan,
  uploads,
  onCrawlerRun,
  personas,
  onPersonaChange,
  currentKnowledgePlan,
  setCurrentKnowledgePlan,
  currentBlockCounts,
  setCurrentBlockCounts,
  planState,
  setPlanState,
  confirmedPlanHash,
  setConfirmedPlanHash,
  sessionId,
  setSessionId,
  sessionStatus,
  setSessionStatus,
}: {
  plan: CapturePlan;
  setPlan: (next: CapturePlan) => void;
  uploads: SessionUpload[];
  onCrawlerRun: (run: CrawlerRun) => void;
  personas: Persona[];
  onPersonaChange: (slug: string) => void;
  currentKnowledgePlan: KnowledgePlan | null;
  setCurrentKnowledgePlan: (plan: KnowledgePlan | null) => void;
  currentBlockCounts: BlockCounts;
  setCurrentBlockCounts: (counts: BlockCounts) => void;
  planState: PlanState | null;
  setPlanState: (state: PlanState | null) => void;
  confirmedPlanHash: string | null;
  setConfirmedPlanHash: (hash: string | null) => void;
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  sessionStatus: string;
  setSessionStatus: (status: string) => void;
}) {
  const router = useRouter();
  const [model, setModel] = useState("gpt-4o-mini");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState("idle");
  const [cls, setCls] = useState<Classification>({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
  const [loading, setLoading] = useState(false);
  const [contentText, setContentText] = useState("");
  const [showContent, setShowContent] = useState(false);
  const [friendlyError, setFriendlyError] = useState<string | null>(null);
  const [lastAttempt, setLastAttempt] = useState<string>("");
  const [missionState, setMissionState] = useState<MissionState | null>(null);
  const [resumeSummary, setResumeSummary] = useState<string | null>(null);
  const [showRawMarkdown, setShowRawMarkdown] = useState(false);
  const [planConfirmed, setPlanConfirmed] = useState(false);
  const [selectedFaqSlug, setSelectedFaqSlug] = useState<string | null>(null);
  const [selectedProductSlug, setSelectedProductSlug] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const draftPlan = planState?.normalized_plan || currentKnowledgePlan;
  const blockingViolations = planState?.validation?.blocking_violations || [];
  const planStateValid = Boolean(planState && planState.validation.valid && blockingViolations.length === 0 && planStateCountsMatch(planState));
  const previewViolations = planState
    ? [...blockingViolations, ...(!planStateCountsMatch(planState) ? ["Plan summary/counts divergem do normalizedPlan."] : [])]
    : validatePreviewPlan(draftPlan);
  const currentEntryCount = Number(planState?.summary?.entry_count ?? Object.values(currentBlockCounts || {}).reduce((sum, value) => sum + Number(value || 0), 0));

  function applyPlanState(nextState: PlanState | null) {
    setPlanState(nextState);
    setCurrentKnowledgePlan(nextState?.normalized_plan || null);
    setCurrentBlockCounts(normalizeBlockCounts(nextState?.summary?.current_block_counts || undefined));
    setPlanConfirmed(false);
    setConfirmedPlanHash(null);
    setSelectedFaqSlug(null);
    setSelectedProductSlug(null);
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!sessionId || stage !== "idle") return;
    setStage(sessionStatus === "saved" ? "done" : sessionStatus || "chatting");
    setCls((prev) => ({ ...prev, persona_slug: prev.persona_slug || plan.personaSlug || null }));
    setMessages([{ role: "system", content: "Sessao CRIAR restaurada com o plano atual da Sofia." }]);
  }, [sessionId, sessionStatus, stage, plan.personaSlug]);

  useEffect(() => {
    if (planState?.plan_hash && confirmedPlanHash === planState.plan_hash && planStateValid) {
      setPlanConfirmed(true);
    }
  }, [confirmedPlanHash, planState?.plan_hash, planStateValid]);

  async function start() {
    if (isInvalidCriarPersona(plan.personaSlug)) {
      setFriendlyError("Selecione uma persona antes de criar conhecimento.");
      return;
    }
    setLoading(true);
    try {
      const d = await api.kbIntakeStart(model, buildInitialContext(plan, uploads), {
        mode: "criar",
        persona_slug: plan.personaSlug,
        source_url: plan.sourceUrl,
        initial_block_counts: normalizeBlockCounts(plan.variationCounts),
        knowledge_plan: planState?.normalized_plan,
      });
      if (d?.ok === false) {
        setFriendlyError(d?.message || "Nao consegui iniciar a conversa agora.");
        return;
      }
      setSessionId(d.session_id);
      window.localStorage.setItem("active_criar_session_id", d.session_id);
      setMessages(d.bootstrap_message ? [{ role: "assistant", content: d.bootstrap_message }] : []);
      setStage(d.stage || "chatting");
      setSessionStatus(d.status || d.stage || "chatting");
      setCls(d.classification || { persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
      setMissionState(d.state || null);
      setResumeSummary(d.resume_summary || null);
      const nextState = normalizePlanState(d, d.persona_slug || plan.personaSlug);
      if (nextState) {
        applyPlanState(nextState);
      } else {
        setCurrentBlockCounts(normalizeBlockCounts(d.current_block_counts || plan.variationCounts));
      }
      setFriendlyError(null);
    } catch (e: any) {
      setFriendlyError(formatChatRequestError(e));
    } finally {
      setLoading(false);
    }
  }

  async function send() {
    if (!sessionId || (!input.trim() && !file)) return;
    setLoading(true);
    const userMsg = input.trim();
    setLastAttempt(userMsg);
    setInput("");
    setFriendlyError(null);
    setMessages((p) => [...p, { role: "user", content: file ? `[arquivo] ${file.name}${userMsg ? `\n${userMsg}` : ""}` : userMsg }]);
    try {
      let d: any;
      if (file) {
        const form = new FormData();
        form.append("session_id", sessionId);
        form.append("message", userMsg);
        form.append("file", file);
        d = await api.kbIntakeMessage(sessionId, userMsg, file || undefined);
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
      } else {
        d = await api.kbIntakeMessage(sessionId, userMsg);
      }
      if (d?.state) {
        setMissionState(d.state);
        setPlan({
          ...plan,
          personaSlug: d.state.persona || plan.personaSlug,
          objective: d.state.objective || plan.objective,
          sourceUrl: d.state?.source?.url || plan.sourceUrl,
          selectedBlocks: (d.state.knowledge_blocks && d.state.knowledge_blocks.length > 0) ? d.state.knowledge_blocks : plan.selectedBlocks,
        });
      }
      if (d?.ok === false) {
        setFriendlyError(d?.message || "Nao consegui processar agora. Tente novamente.");
        return;
      }
      setStage(d.stage);
      setSessionStatus(d.status || d.stage || sessionStatus);
      setCls(d.classification);
      const nextState = normalizePlanState(d, d.classification?.persona_slug || plan.personaSlug);
      if (d.crawler) onCrawlerRun(d.crawler);
      if (nextState) {
        setMessages((p) => [...p, { role: "assistant", content: summarizePlanStateForChat(nextState) }]);
      } else if ((d.message || "").trim()) {
        setMessages((p) => [...p, { role: "assistant", content: d.message }]);
      }
      if (Array.isArray(d.plan_violations) && d.plan_violations.length > 0) {
        setFriendlyError(`Plano bloqueado antes da preview:\n- ${d.plan_violations.join("\n- ")}`);
      }
      if (nextState) {
        applyPlanState(nextState);
        if (!nextState.validation.valid || nextState.validation.blocking_violations.length > 0) {
          setFriendlyError(`Plano bloqueado antes da preview:\n- ${nextState.validation.blocking_violations.join("\n- ")}`);
        }
      } else if (d.current_block_counts) {
        setCurrentBlockCounts(normalizeBlockCounts(d.current_block_counts));
      }
    } catch (e: any) {
      setFriendlyError(formatChatRequestError(e));
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!sessionId || !planState || !planConfirmed) return;
    if (!planStateValid || confirmedPlanHash !== planState.plan_hash) {
      setFriendlyError(
        "Plano ainda não pode ser salvo. Corrija as pendências bloqueantes primeiro."
        + (previewViolations.length ? `\n- ${previewViolations.join("\n- ")}` : "")
        + (confirmedPlanHash !== planState.plan_hash ? "\n- Plano confirmado difere do normalizedPlan atual." : "")
      );
      return;
    }
    setLoading(true);
    try {
      const d = await api.kbIntakeSave(sessionId, contentText, {
        plan_hash: planState.plan_hash,
        normalized_plan: planState.normalized_plan,
      });
      setStage("done");
      setMessages((p) => [...p, {
        role: "system",
        content: d.ok
          ? `Salvo${d.status === "saved_with_warnings" ? " com avisos" : ""}.\nArquivo: ${d.file_path}\nGit: ${d.git?.commit_ok ? "ok" : "falhou"} | Push: ${d.git?.push_ok ? "ok" : "falhou"}\n${Array.isArray(d.warnings) && d.warnings.length ? `Avisos: ${d.warnings.map((w: any) => w.message || w.stage).join("; ")}\n` : ""}Supabase: ${d.sync?.new ?? 0} novos`
          : formatSaveError(d),
      }]);
      // After a successful save, silently open the knowledge graph focused
      // on the persona/campaign just created so the operator immediately
      // sees the hierarchical tree. Falls back to /knowledge/graph when no
      // persona is known yet.
      if (d?.ok) {
        window.localStorage.removeItem("active_criar_session_id");
        setSessionStatus("saved");
        const personaSlug = (cls?.persona_slug || plan.personaSlug || "").trim();
        const target = personaSlug
          ? `/knowledge/graph?persona=${encodeURIComponent(personaSlug)}&mode=semantic_tree&depth=5`
          : "/knowledge/graph";
        // Small delay so the success message is briefly visible before redirect.
        setTimeout(() => router.push(target), 700);
      }
    } catch (e: any) {
      const parsed = parseApiErrorBody(e?.message || "");
      setMessages((p) => [...p, {
        role: "system",
        content: formatSaveError(parsed ?? { error: e?.message || "falha ao salvar" }),
      }]);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setSessionId(null);
    setMessages([]);
    setInput("");
    setFile(null);
    setStage("idle");
    setCls({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
    setContentText("");
    setShowContent(false);
    setFriendlyError(null);
    setMissionState(null);
    setResumeSummary(null);
    setPlanState(null);
    setCurrentKnowledgePlan(null);
    setCurrentBlockCounts(normalizeBlockCounts(plan.variationCounts));
    setSessionStatus("collecting");
    window.localStorage.removeItem("active_criar_session_id");
    setPlanConfirmed(false);
    setConfirmedPlanHash(null);
    setSelectedFaqSlug(null);
    setSelectedProductSlug(null);
  }

  function updateDraftPlan(mutator: (current: KnowledgePlan) => KnowledgePlan) {
    if (!draftPlan) return;
    const nextPlan = mutator(draftPlan);
    setCurrentKnowledgePlan(nextPlan);
    setCurrentBlockCounts(countBlocksByType(nextPlan.entries));
    if (sessionId) {
      api.kbIntakeUpdatePlan(sessionId, {
        knowledge_plan: nextPlan,
        last_change: "edicao manual da previa",
      }).then((result: any) => {
        const nextState = normalizePlanState(result, plan.personaSlug);
        if (nextState) applyPlanState(nextState);
      }).catch(() => {});
    }
    setPlanConfirmed(false);
    setConfirmedPlanHash(null);
  }

  function modifySelectedFaq() {
    if (!draftPlan || !selectedFaqSlug) return;
    const current = draftPlan.entries.find((entry) => entry.slug === selectedFaqSlug);
    if (!current) return;
    const title = window.prompt("Novo titulo da FAQ", current.title);
    if (!title) return;
    const content = window.prompt("Novo conteudo/resposta da FAQ", current.content);
    if (!content) return;
    updateDraftPlan((planValue) => ({
      ...planValue,
      entries: planValue.entries.map((entry) =>
        entry.slug === selectedFaqSlug
          ? { ...entry, title: title.trim(), content: content.trim() }
          : entry,
      ),
    }));
  }

  function deleteSelectedFaq() {
    if (!draftPlan || !selectedFaqSlug) return;
    if (!window.confirm("Excluir esta FAQ cria uma excecao manual para esse ramo. Deseja continuar?")) return;
    updateDraftPlan((planValue) => ({
      ...planValue,
      entries: planValue.entries.filter((entry) => entry.slug !== selectedFaqSlug),
      links: (planValue.links || []).filter((link) => link.target_slug !== selectedFaqSlug && link.source_slug !== selectedFaqSlug),
    }));
    setSelectedFaqSlug(null);
  }

  function addFaq() {
    if (!draftPlan) return;
    const title = window.prompt("Titulo da nova FAQ");
    if (!title) return;
    const content = window.prompt("Resposta ou conteudo da nova FAQ");
    if (!content) return;
    const targetProductSlugs = selectedProductSlug
      ? [selectedProductSlug]
      : draftPlan.entries.filter((entry) => entry.content_type === "product").map((entry) => entry.slug);
    if (targetProductSlugs.length === 0) return;
    updateDraftPlan((planValue) => {
      const nextEntries = [...planValue.entries];
      for (const productSlug of targetProductSlugs) {
        const faqSlug = `${slugifyPlanValue(title)}-${productSlug}-${Date.now().toString(36).slice(-4)}`;
        nextEntries.push({
          content_type: "faq",
          title: title.trim(),
          slug: faqSlug,
          status: "pendente_validacao",
          content: content.trim(),
          tags: ["faq", "manual"],
          metadata: {
            parent_slug: productSlug,
            manual_exception: !!selectedProductSlug,
            edited_in_preview: true,
          },
        });
      }
      return { ...planValue, entries: nextEntries };
    });
  }

  if (stage === "idle") {
    return (
      <PreflightPanel
        plan={plan}
        setPlan={setPlan}
        model={model}
        setModel={setModel}
        onStart={start}
        loading={loading}
        uploads={uploads}
        personas={personas}
        onPersonaChange={onPersonaChange}
      />
    );
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 sep">
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-obs-violet" />
          <span className="text-sm font-semibold">Criar</span>
          {sessionId && <span className="text-[10px] text-obs-subtle font-mono">{sessionId.slice(0, 8)}</span>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowRawMarkdown((value) => !value)}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 transition-colors ${
              showRawMarkdown
                ? "border-obs-violet/40 bg-obs-violet/12 text-obs-violet"
                : "border-white/06 text-obs-subtle hover:text-obs-text hover:bg-white/[0.04]"
            }`}
            title={showRawMarkdown ? "Mostrar markdown formatado" : "Mostrar raw markdown"}
            aria-label={showRawMarkdown ? "Mostrar markdown formatado" : "Mostrar raw markdown"}
          >
            <Code2 size={13} />
          </button>
          <button onClick={reset} className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded-md transition-colors">
            Nova sessao
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {missionState && (
          <div className="border border-white/08 bg-obs-base rounded-lg p-3 text-xs">
            <p className="text-obs-subtle">
              Missao: <span className="text-obs-text">{repairText(missionState.persona || "—")}</span> | Fonte: <span className="text-obs-text">{repairText(missionState.source?.url || "—")}</span>
            </p>
            <p className="text-obs-faint mt-1">
              Blocos: {(missionState.knowledge_blocks || []).map((item) => repairText(String(item))).join(", ") || "—"} | Status: {repairText(missionState.status || "collecting")}
            </p>
          </div>
        )}
        {resumeSummary && (
          <div className="border border-obs-violet/20 bg-obs-violet/10 rounded-lg p-3 text-xs text-obs-text whitespace-pre-wrap">
            <p className="text-obs-violet font-medium mb-1">Retomada automatica da Sofia</p>
            {resumeSummary}
          </div>
        )}
        {friendlyError && (
          <div className="border border-obs-amber/30 bg-obs-amber/10 rounded-lg p-3 text-xs text-obs-amber flex items-center justify-between gap-3">
            <span>{friendlyError}</span>
            <button
              onClick={() => {
                if (lastAttempt) setInput(lastAttempt);
              }}
              className="border border-white/10 rounded px-2 py-1 text-obs-text hover:bg-white/5"
            >
              tentar novamente
            </button>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2.5 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${
              msg.role === "assistant" ? "bg-obs-violet/20 text-obs-violet"
              : msg.role === "system" ? "bg-green-500/20 text-green-400"
              : "bg-white/10 text-obs-text"}`}>
              {msg.role === "user" ? <User size={11} /> : <Bot size={11} />}
            </div>
            <div className={`max-w-[82%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
              msg.role === "user" ? "bg-obs-violet/15 text-obs-text"
              : msg.role === "system" ? "bg-green-500/8 border border-green-500/20 text-green-300 font-mono text-xs"
              : "bg-obs-raised border border-white/06 text-obs-text"}`}>
              <MessageBody content={msg.content} raw={showRawMarkdown} role={msg.role} />
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-2.5">
            <div className="w-6 h-6 rounded-full bg-obs-violet/20 flex items-center justify-center">
              <Bot size={11} className="text-obs-violet" />
            </div>
            <div className="glass border border-white/06 rounded-xl px-3.5 py-2.5">
              <Loader2 size={13} className="animate-spin text-obs-subtle" />
            </div>
          </div>
        )}
        {stage === "ready_to_save" && draftPlan && !planStateValid && previewViolations.length > 0 && (
          <div className="rounded-2xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-100">
            <p className="font-semibold">Plano bloqueado antes da preview</p>
            <div className="mt-2 space-y-1">
              {previewViolations.map((violation, index) => (
                <p key={`${violation}-${index}`} className="text-xs">- {violation}</p>
              ))}
            </div>
          </div>
        )}
        {stage === "ready_to_save" && draftPlan && planStateValid && (
          <GraphPreviewPanel
            plan={draftPlan}
            confirmed={planConfirmed}
            selectedFaqSlug={selectedFaqSlug}
            selectedProductSlug={selectedProductSlug}
            onSelectFaq={(slug) => {
              setSelectedFaqSlug(slug);
              setSelectedProductSlug(null);
            }}
            onSelectProduct={(slug) => {
              setSelectedProductSlug(slug);
              setSelectedFaqSlug(null);
            }}
            onModifyFaq={modifySelectedFaq}
            onDeleteFaq={deleteSelectedFaq}
            onAddFaq={addFaq}
            onConfirmStructure={async () => {
              if (!sessionId || !planStateValid || !planState) {
                setFriendlyError("Plano ainda nao pode ser confirmado. Corrija as pendencias bloqueantes primeiro.");
                return;
              }
              try {
                const result = await api.kbIntakeUpdatePlan(sessionId, {
                  knowledge_plan: planState.normalized_plan,
                  status: "ready_to_save",
                  last_change: "estrutura confirmada pelo operador",
                });
                const nextState = normalizePlanState(result, plan.personaSlug);
                if (!nextState || !nextState.validation.valid || !planStateCountsMatch(nextState)) {
                  setFriendlyError("Plano ainda nao pode ser confirmado. Corrija as pendencias bloqueantes primeiro.");
                  setPlanConfirmed(false);
                  setConfirmedPlanHash(null);
                  return;
                }
                setPlanState(nextState);
                setCurrentKnowledgePlan(nextState.normalized_plan);
                setCurrentBlockCounts(normalizeBlockCounts(nextState.summary.current_block_counts));
                setConfirmedPlanHash(nextState.plan_hash);
                setPlanConfirmed(true);
                setSessionStatus(result.status || "ready_to_save");
                setFriendlyError(null);
              } catch (error: any) {
                setFriendlyError(formatChatRequestError(error));
                setPlanConfirmed(false);
                setConfirmedPlanHash(null);
              }
            }}
            onSaveKnowledge={save}
            loading={loading}
          />
        )}
        <div ref={bottomRef} />
      </div>

      {stage === "ready_to_save" && showContent && (
        <div className="px-4 pb-2">
          <textarea
            value={contentText}
            onChange={(e) => setContentText(e.target.value)}
            rows={4}
            placeholder="Conteudo completo para salvar no vault..."
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none"
          />
        </div>
      )}

      {stage !== "done" && (
        <div className="sep px-3 py-2.5 space-y-2">
          {file && (
            <div className="flex items-center gap-2 bg-obs-base border border-white/06 rounded-lg px-3 py-1.5 text-xs text-obs-text">
              <Upload size={11} className="text-obs-violet" />
              <span className="flex-1 truncate">{file.name}</span>
              <button onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }} className="text-obs-subtle hover:text-obs-text">
                remover
              </button>
            </div>
          )}
          <div className="flex gap-2 items-end">
            <label className="cursor-pointer text-obs-subtle hover:text-obs-text transition-colors shrink-0">
              <Upload size={15} />
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              rows={1}
              placeholder="Mensagem..."
              className="flex-1 bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none min-h-[36px] max-h-[100px]"
            />
            <button onClick={send} disabled={loading || (!input.trim() && !file)} className="shrink-0 bg-obs-violet hover:bg-obs-violet/80 disabled:opacity-40 text-white p-2 rounded-lg transition-colors">
              <Send size={13} />
            </button>
          </div>
        </div>
      )}

      {stage === "ready_to_save" && (
        <div className={`sep px-4 py-2.5 flex items-center gap-3 ${planStateValid ? "bg-green-500/5" : "bg-red-500/5"}`}>
          <CheckCircle size={13} className={`${planStateValid ? "text-green-400" : "text-red-300"} shrink-0`} />
          <span className={`text-xs flex-1 ${planStateValid ? "text-green-400" : "text-red-200"}`}>
            {draftPlan
              ? planStateValid
                ? `Estrutura pronta para revisao visual (${currentEntryCount} blocos no plano atual)`
                : `Plano ainda nao esta pronto para salvar (${currentEntryCount} blocos no plano atual)`
              : "Estrutura ainda nao gerada. Continue a conversa para montar a arvore antes de salvar."}
          </span>
          <button onClick={() => setShowContent((v) => !v)} className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded transition-colors">
            {showContent ? "Ocultar" : "+ Conteudo"}
          </button>
        </div>
      )}

      <div className="sep px-4 py-3 shrink-0">
        <div className="flex gap-4 flex-wrap">
          <StepDot done={!!cls.persona_slug} label="Cliente" />
          <StepDot done={!!cls.content_type} label="Tipo" />
          <StepDot done={!!cls.title} label="Titulo" />
          <StepDot done={(stage === "ready_to_save" && planStateValid) || stage === "done"} label="Pronto" />
        </div>
      </div>
    </div>
  );
}

function UploadPanel({
  uploads,
  onUploaded,
  onRemoveUpload,
}: {
  uploads: SessionUpload[];
  onUploaded: (upload: SessionUpload) => void;
  onRemoveUpload: (id: string) => void;
}) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [mode, setMode] = useState<"text" | "file">("file");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [contentType, setContentType] = useState("other");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.personas()
      .then((rows: any) => {
        setPersonas(rows);
      })
      .catch(() => {});
  }, []);

  function chooseFile(f: File | null) {
    setFile(f);
    if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      let row: any;
      let preview = "";
      if (mode === "text") {
        row = await api.uploadText({ title, content, persona_id: personaId || undefined, content_type: contentType });
        preview = content.slice(0, 1200);
      } else if (file) {
        preview = await file.text().catch(() => `[arquivo ${file.name}]`);
        row = await api.uploadFile(file, personaId || undefined, contentType);
      }
      if (row) {
        onUploaded({
          id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          title: row.title || row.titulo || title || file?.name || "upload",
          content_type: row.content_type || contentType,
          persona_id: personaId || undefined,
          source: mode,
          file_name: file?.name,
          preview: preview.slice(0, 1600),
          knowledge_item_id: row.id,
        });
      }
      setTitle("");
      setContent("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 sep">
        <FolderOpen size={15} className="text-obs-amber" />
        <span className="text-sm font-semibold">Upload manual</span>
      </div>

      <div className="overflow-y-auto p-4">
        <form onSubmit={submit} className="space-y-3">
          <div className="flex gap-1.5">
            {(["file", "text"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  mode === m ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "border-white/06 text-obs-subtle hover:text-obs-text"
                }`}
              >
                {m === "file" ? "Arquivo" : "Texto"}
              </button>
            ))}
          </div>

          {mode === "file" ? (
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); chooseFile(e.dataTransfer.files[0] || null); }}
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-5 text-center transition-colors cursor-pointer ${
                file ? "border-obs-violet/50 bg-obs-violet/5" : "border-white/10 hover:border-white/20"
              }`}
            >
              <FileText size={20} className="mx-auto text-obs-violet mb-2" />
              <p className="text-xs text-obs-subtle truncate">{file ? file.name : "Arraste ou clique"}</p>
              <input ref={fileRef} type="file" className="hidden" accept=".md,.txt,.json" onChange={(e) => chooseFile(e.target.files?.[0] || null)} />
            </div>
          ) : (
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={6}
              placeholder="Cole o conhecimento aqui..."
              className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40 resize-none"
            />
          )}

          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Titulo"
            className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40"
          />
          <div className="grid grid-cols-2 gap-2">
            <select value={personaId} onChange={(e) => setPersonaId(e.target.value)} className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-xs text-obs-text focus:outline-none">
              <option value="">Sem persona</option>
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select value={contentType} onChange={(e) => setContentType(e.target.value)} className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-xs text-obs-text focus:outline-none">
              {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting || (mode === "text" ? !title || !content : !title || !file)}
            className="w-full bg-obs-amber/90 hover:bg-obs-amber disabled:opacity-40 text-obs-base text-sm font-semibold py-2.5 rounded-xl transition-colors"
          >
            {submitting ? "Enviando..." : "Enviar para validacao"}
          </button>
        </form>

        <div className="mt-4 pt-4 border-t border-white/06">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-obs-text">Uploads da sessao</span>
            <span className="text-[10px] text-obs-faint">{uploads.length}</span>
          </div>
          <div className="space-y-2">
            {uploads.length === 0 && <p className="text-xs text-obs-faint">Uploads feitos aqui aparecem nesta lista e entram no contexto do agente.</p>}
            {uploads.map((u) => (
              <div key={u.id} className="border border-white/06 bg-obs-base rounded-lg p-2">
                <div className="flex items-start gap-2">
                  <FileText size={13} className="text-obs-violet mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-obs-text truncate">{u.title}</p>
                    <p className="text-[10px] text-obs-faint truncate">{u.content_type} | {u.knowledge_item_id || "sem id"}</p>
                  </div>
                  <button onClick={() => onRemoveUpload(u.id)} className="text-obs-faint hover:text-obs-text">
                    <Trash2 size={12} />
                  </button>
                </div>
                {u.preview && <p className="text-[10px] text-obs-subtle mt-1 line-clamp-2">{u.preview}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function GraphPreviewPanel({
  plan,
  confirmed,
  selectedFaqSlug,
  selectedProductSlug,
  onSelectFaq,
  onSelectProduct,
  onModifyFaq,
  onDeleteFaq,
  onAddFaq,
  onConfirmStructure,
  onSaveKnowledge,
  loading,
}: {
  plan: KnowledgePlan;
  confirmed: boolean;
  selectedFaqSlug: string | null;
  selectedProductSlug: string | null;
  onSelectFaq: (slug: string) => void;
  onSelectProduct: (slug: string) => void;
  onModifyFaq: () => void;
  onDeleteFaq: () => void;
  onAddFaq: () => void;
  onConfirmStructure: () => void;
  onSaveKnowledge: () => void;
  loading: boolean;
}) {
  const previewPlan = plan;
  const entries = previewPlan.entries || [];
  const childrenByParent = new Map<string, KnowledgePlanEntry[]>();
  for (const entry of entries) {
    const parentKeyRaw = normalizeParentSlug(parentSlugOf(entry), previewPlan.persona_slug);
    const parentKey = !parentKeyRaw || parentKeyRaw === "self" ? "__root__" : parentKeyRaw;
    const bucket = childrenByParent.get(parentKey) || [];
    bucket.push(entry);
    childrenByParent.set(parentKey, bucket);
  }
  for (const [key, bucket] of childrenByParent.entries()) {
    childrenByParent.set(
      key,
      bucket.sort((a, b) => (PREVIEW_TYPE_RANK[a.content_type] || 99) - (PREVIEW_TYPE_RANK[b.content_type] || 99) || a.title.localeCompare(b.title)),
    );
  }

  const roots = childrenByParent.get("__root__") || [];
  const selectedLabel = selectedFaqSlug
    ? entries.find((entry) => entry.slug === selectedFaqSlug)?.title
    : selectedProductSlug
      ? entries.find((entry) => entry.slug === selectedProductSlug)?.title
      : null;

  const renderEntry = (entry: KnowledgePlanEntry, depth = 0): ReactNode => {
    const children = childrenByParent.get(entry.slug) || [];
    const isFaq = entry.content_type === "faq";
    const isProduct = entry.content_type === "product";
    const isSelected = selectedFaqSlug === entry.slug || selectedProductSlug === entry.slug;
    const toneClass =
      entry.content_type === "briefing" || entry.content_type === "campaign"
        ? "node-briefing border-sky-400/25 bg-sky-400/10"
        : entry.content_type === "audience"
          ? "node-audience border-emerald-400/25 bg-emerald-400/10"
          : entry.content_type === "product"
            ? "node-product border-amber-400/25 bg-amber-400/10"
            : entry.content_type === "faq"
              ? "node-faq border-violet-400/25 bg-violet-400/10"
              : "border-white/10 bg-white/[0.03]";

    return (
      <div key={String(entry.metadata?.plan_entry_id || entry.metadata?.client_id || `${entry.content_type}-${parentSlugOf(entry) || "root"}-${entry.slug}`)} className={depth > 0 ? "ml-5 border-l border-white/10 pl-4" : ""}>
        <button
          type="button"
          onClick={() => {
            if (isFaq) onSelectFaq(entry.slug);
            if (isProduct) onSelectProduct(entry.slug);
          }}
          className={`node-card w-full rounded-xl border px-3 py-3 text-left transition-colors ${toneClass} ${
            isSelected ? "ring-1 ring-obs-violet/60" : "hover:border-white/20"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">{entry.content_type}</p>
              <p className="mt-1 text-sm font-semibold text-white">{repairText(entry.title)}</p>
            </div>
            <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-obs-subtle">
              {repairText(entry.status)}
            </span>
          </div>
          <p className="mt-2 line-clamp-3 text-xs leading-6 text-obs-subtle">{repairText(entry.content)}</p>
        </button>
        {!!children.length && (
          <div className="mt-2 space-y-2">
            {children.map((child) => renderEntry(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="graph-preview rounded-2xl border border-white/08 bg-obs-base/70 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-obs-faint">Previa visual</p>
          <p className="text-sm font-semibold text-white">Estrutura fractal antes do save</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[10px] border ${confirmed ? "border-green-400/30 text-green-300 bg-green-500/10" : "border-obs-amber/25 text-obs-amber bg-obs-amber/10"}`}>
          {confirmed ? "estrutura confirmada" : "aguardando confirmacao"}
        </span>
      </div>

      <div className="node-actions flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onModifyFaq}
          disabled={!selectedFaqSlug}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-obs-text disabled:opacity-40"
        >
          Modificar FAQ
        </button>
        <button
          type="button"
          onClick={onDeleteFaq}
          disabled={!selectedFaqSlug}
          className="rounded-lg border border-red-400/20 px-3 py-1.5 text-xs text-red-200 disabled:opacity-40"
        >
          Excluir FAQ
        </button>
        <button
          type="button"
          onClick={onAddFaq}
          className="rounded-lg border border-obs-violet/25 px-3 py-1.5 text-xs text-obs-violet"
        >
          Adicionar FAQ
        </button>
        <button
          type="button"
          onClick={onConfirmStructure}
          className="rounded-lg border border-green-400/25 px-3 py-1.5 text-xs text-green-300"
        >
          Confirmar estrutura
        </button>
        <button
          type="button"
          onClick={onSaveKnowledge}
          disabled={!confirmed || loading}
          className="rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          Salvar conhecimento
        </button>
      </div>

      {selectedLabel && (
        <p className="text-[11px] text-obs-subtle">
          Selecionado: <span className="text-white">{repairText(selectedLabel)}</span>
        </p>
      )}

      <div className="space-y-3">
        <div className="node-card node-persona rounded-xl border border-white/10 bg-white/[0.04] px-3 py-3">
          <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">persona</p>
          <p className="mt-1 text-sm font-semibold text-white">{repairText(previewPlan.persona_slug || "persona")}</p>
        </div>
        <div className="ml-5 border-l border-white/10 pl-4 space-y-2">
          {roots.map((entry) => renderEntry(entry))}
        </div>
      </div>

      {!!plan.missing_questions?.length && (
        <div className="rounded-xl border border-obs-amber/20 bg-obs-amber/10 px-3 py-3">
          <p className="text-[10px] uppercase tracking-[0.18em] text-obs-amber mb-1">Pendencias</p>
          <div className="space-y-1">
            {plan.missing_questions.map((item, index) => (
              <p key={`${item}-${index}`} className="text-xs text-obs-text">{repairText(item)}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CaptureSidebar({
  plan,
  uploads,
  crawlerRuns,
  planState,
  currentKnowledgePlan,
  currentBlockCounts,
  sessionStatus,
  onAdjustBlock,
}: {
  plan: CapturePlan;
  uploads: SessionUpload[];
  crawlerRuns: CrawlerRun[];
  planState: PlanState | null;
  currentKnowledgePlan: KnowledgePlan | null;
  currentBlockCounts: BlockCounts;
  sessionStatus: string;
  onAdjustBlock: (blockId: string, delta: number) => void;
}) {
  const selectedBlocks = useMemo(
    () => KNOWLEDGE_BLOCKS.filter((block) => plan.selectedBlocks.includes(block.id)),
    [plan.selectedBlocks],
  );
  const latestCrawler = crawlerRuns[0];
  const initialCounts = normalizeBlockCounts(plan.variationCounts);
  const blockingViolations = planState?.validation?.blocking_violations || [];
  const liveCounts = planState
    ? normalizeBlockCounts(planState.summary.current_block_counts)
    : currentKnowledgePlan?.entries?.length
      ? countBlocksByType(currentKnowledgePlan.entries)
      : normalizeBlockCounts(currentBlockCounts);
  const displayCounts = planState || currentKnowledgePlan?.entries?.length ? liveCounts : initialCounts;
  const totalInitial = Object.values(initialCounts).reduce((sum, value) => sum + value, 0);
  const totalCurrent = Number(planState?.summary?.entry_count ?? Object.values(displayCounts).reduce((sum, value) => sum + value, 0));
  const planLabel =
    sessionStatus === "saved" ? "Plano salvo" :
    sessionStatus === "ready_to_save" && planState?.validation?.valid ? "Plano final confirmado" :
    blockingViolations.length ? "Plano bloqueado" :
    planState || currentKnowledgePlan?.entries?.length ? "Plano em construcao" :
    "Plano inicial";
  const createdCountFor = (id: string) => {
    if (id === "persona") return plan.personaSlug ? 1 : 0;
    if (id === "embedded" || id === "gallery") {
      return (planState?.normalized_plan.entries || currentKnowledgePlan?.entries || [])
        .filter((entry) => normalizeContentTypeAlias(entry.content_type) === id).length;
    }
    return displayCounts[id] || 0;
  };
  const expectedCountFor = (id: string) => {
    if (id === "persona") return plan.personaSlug ? 1 : 0;
    if (id === "offer" || id === "embedded" || id === "gallery") return initialCounts[id] || 0;
    return initialCounts[id] || 0;
  };
  const statusFor = (id: string) => {
    const expected = expectedCountFor(id);
    const created = createdCountFor(id);
    if (expected === 0 && created === 0) return "idle";
    if (expected === 0 && created > 0) return "extra";
    if (created <= 0 && expected > 0) return "missing";
    if (created < expected) return "partial";
    return "done";
  };
  const rowClassFor = (status: string) => {
    if (status === "done") return "border-green-400/20 bg-green-500/8";
    if (status === "partial") return "border-obs-amber/25 bg-obs-amber/10";
    if (status === "missing") return "border-red-400/20 bg-red-500/10";
    if (status === "extra") return "border-obs-violet/25 bg-obs-violet/10";
    return "border-white/06 bg-obs-base";
  };
  const statusLabelFor = (status: string) => {
    if (status === "done") return "criado";
    if (status === "partial") return "parcial";
    if (status === "missing") return "pendente";
    if (status === "extra") return "novo/extra";
    return "fora do plano";
  };

  return (
    <aside className="w-80 shrink-0 flex flex-col glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 sep flex items-center gap-2">
        <Network size={15} className="text-obs-violet" />
        <span className="text-sm font-semibold">Contexto do agente</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <section>
          <div className="flex items-center gap-2 mb-2">
            <Link size={12} className="text-obs-amber" />
            <span className="text-xs font-semibold text-obs-text">Fonte</span>
          </div>
          <p className="text-[11px] text-obs-violet break-all">{plan.sourceUrl}</p>
        </section>
        <section>
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={12} className="text-obs-amber" />
            <span className="text-xs font-semibold text-obs-text">Pipeline</span>
          </div>
          <div className="space-y-1.5">
            {["crawler bruto", "parsing + confianca", "perguntar lacunas", "propor arvore", "gerar conhecimentos", "validacao humana", "salvar draft"].map((step, i) => (
              <div key={step} className="flex items-center gap-2 text-xs text-obs-subtle">
                <span className="w-5 h-5 rounded-full border border-white/08 bg-obs-base flex items-center justify-center text-[10px]">{i + 1}</span>
                {step}
              </div>
            ))}
          </div>
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Crawler da fonte</p>
          {!latestCrawler && (
            <div className="border border-white/06 bg-obs-base rounded-lg p-2">
              <p className="text-[11px] text-obs-subtle">Aguardando pedido para ler/coletar a fonte.</p>
              <p className="text-[10px] text-obs-faint mt-1">O resultado sera tratado como captura bruta com validacao humana.</p>
            </div>
          )}
          {latestCrawler && (
            <div className="border border-white/06 bg-obs-base rounded-lg p-2 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-obs-subtle">Confianca</span>
                <span className="text-[11px] text-obs-violet">
                  {latestCrawler.confidence_label || "pendente"} {typeof latestCrawler.confidence === "number" ? `(${latestCrawler.confidence})` : ""}
                </span>
              </div>
              <div className="space-y-1">
                {(latestCrawler.stages || []).map((stage) => (
                  <div key={stage.key || stage.label} className="flex items-center justify-between gap-2 text-[10px]">
                    <span className="text-obs-faint truncate">{stage.label}</span>
                    <span className={
                      stage.status === "done" ? "text-green-400" :
                      stage.status === "error" ? "text-red-400" :
                      stage.status === "warning" ? "text-obs-amber" :
                      "text-obs-subtle"
                    }>
                      {stage.status}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-obs-faint">
                {(latestCrawler.product_candidates || []).length} candidato(s) de produto. Nao salva como ativo sem validacao.
              </p>
              {(latestCrawler.warnings || []).slice(0, 2).map((warning) => (
                <p key={warning} className="text-[10px] text-obs-amber line-clamp-2">{warning}</p>
              ))}
            </div>
          )}
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Plano inicial</p>
          <div className="rounded-lg border border-white/06 bg-obs-base p-2">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] text-obs-subtle">Pre-confirmacao</span>
              <span className="text-[10px] text-obs-faint">{totalInitial} bloco(s)</span>
            </div>
            <div className="space-y-1">
              {SIDEBAR_TREE_BLOCKS.map((block) => (
                <div key={`initial-${block.id}`} className="flex items-center justify-between text-[11px]">
                  <span className="text-obs-faint">{block.label}</span>
                  <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-obs-subtle">{expectedCountFor(block.id)}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold text-obs-text">{planLabel}</p>
            <span className="text-[10px] text-obs-violet">{totalCurrent} bloco(s)</span>
          </div>
          <div className="space-y-1.5">
            {SIDEBAR_TREE_BLOCKS.map((block) => {
              const status = statusFor(block.id);
              const expected = expectedCountFor(block.id);
              const created = createdCountFor(block.id);
              const adjustable = KNOWLEDGE_BLOCKS.some((candidate) => candidate.id === block.id);
              return (
              <div key={block.id} className={`flex items-center gap-2 rounded border px-2 py-1.5 ${rowClassFor(status)}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] font-semibold text-obs-subtle truncate">{block.label}</p>
                    <span className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] font-mono text-obs-text">{expected}/{created}</span>
                  </div>
                  <p className="text-[10px] text-obs-faint line-clamp-1">{statusLabelFor(status)} - {block.description}</p>
                </div>
                {adjustable && (
                  <Stepper
                    value={created}
                    onDec={() => onAdjustBlock(block.id, -1)}
                    onInc={() => onAdjustBlock(block.id, +1)}
                    blockId={`sidebar-${block.id}`}
                  />
                )}
              </div>
            )})}
            {!planState && !currentKnowledgePlan && <p className="text-xs text-obs-faint">Estrutura ainda nao gerada.</p>}
          </div>
          {blockingViolations.length > 0 && (
            <div className="mt-3 rounded-lg border border-red-400/20 bg-red-500/10 p-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-red-200">Pendencias bloqueantes</p>
              <div className="mt-1 space-y-1">
                {blockingViolations.slice(0, 4).map((violation, index) => (
                  <p key={`${violation}-${index}`} className="text-[10px] text-red-100">- {repairText(violation)}</p>
                ))}
              </div>
            </div>
          )}
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Uploads legiveis pelo agente</p>
          <div className="space-y-1">
            {uploads.map((u) => (
              <div key={u.id} className="text-[11px] border border-white/06 bg-obs-base rounded px-2 py-1 text-obs-subtle truncate">
                {u.title}
              </div>
            ))}
            {uploads.length === 0 && <p className="text-xs text-obs-faint">Nenhum upload na sessao.</p>}
          </div>
        </section>
      </div>
    </aside>
  );
}

export function CaptureWorkspace({ embedded = false }: { embedded?: boolean }) {
  const [uploads, setUploads] = useState<SessionUpload[]>([]);
  const [crawlerRuns, setCrawlerRuns] = useState<CrawlerRun[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [planState, setPlanState] = useState<PlanState | null>(null);
  const [confirmedPlanHash, setConfirmedPlanHash] = useState<string | null>(null);
  const [currentKnowledgePlan, setCurrentKnowledgePlan] = useState<KnowledgePlan | null>(null);
  const [currentBlockCounts, setCurrentBlockCounts] = useState<BlockCounts>(normalizeBlockCounts(DEFAULT_VARIATION_COUNTS));
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState("collecting");
  const [plan, setPlan] = useState<CapturePlan>({
    personaSlug: "",
    objective: DEFAULT_OBJECTIVE,
    sourceUrl: DEFAULT_SOURCE,
    outputFormat: "raw markdown com copys em niveis de marketing hierarquizados como grafo",
    selectedBlocks: DEFAULT_SELECTED_BLOCKS,
    variationCounts: DEFAULT_VARIATION_COUNTS,
    confirmed: true,
  });

  useEffect(() => {
    const persisted = window.localStorage.getItem("ai-brain-persona-slug") || "";
    if (persisted) {
      setPlan((prev) => (prev.personaSlug === persisted ? prev : { ...prev, personaSlug: persisted }));
    }

    api.me()
      .then((session) => {
        setPersonas(session?.personas || []);
        const latest = window.localStorage.getItem("ai-brain-persona-slug") || "";
        if (latest) {
          setPlan((prev) => (prev.personaSlug === latest ? prev : { ...prev, personaSlug: latest }));
        }
      })
      .catch(() => setPersonas([]));

    function handlePersonaChange(event: Event) {
      const nextSlug = (event as CustomEvent<{ slug?: string }>).detail?.slug || "";
      setPlan((prev) => (prev.personaSlug === nextSlug ? prev : { ...prev, personaSlug: nextSlug }));
    }

    window.addEventListener("ai-brain-persona-change", handlePersonaChange as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", handlePersonaChange as EventListener);
  }, []);

  useEffect(() => {
    const sessionId = window.localStorage.getItem("active_criar_session_id");
    if (!sessionId) return;
    api.kbIntakeSession(sessionId)
      .then((session: any) => {
        setActiveSessionId(session.id || sessionId);
        setSessionStatus(session.status || session.stage || "collecting");
        const personaSlug = session.persona_slug || session.classification?.persona_slug || "";
        const sourceUrl = session.source_url || "";
        setPlan((prev) => ({
          ...prev,
          personaSlug: personaSlug || prev.personaSlug,
          sourceUrl: sourceUrl || prev.sourceUrl,
          variationCounts: normalizeBlockCounts(session.initial_block_counts || prev.variationCounts),
        }));
        const restoredState = normalizePlanState(session, personaSlug || plan.personaSlug);
        const restoredPlan = restoredState?.normalized_plan || normalizeKnowledgePlan(session.knowledge_plan, personaSlug || plan.personaSlug);
        setPlanState(restoredState);
        setConfirmedPlanHash(session.confirmed_plan_hash || null);
        setCurrentKnowledgePlan(restoredPlan);
        setCurrentBlockCounts(normalizeBlockCounts(
          restoredState?.summary?.current_block_counts
          || session.current_block_counts
          || (restoredPlan ? countBlocksByType(restoredPlan.entries) : undefined),
        ));
      })
      .catch(() => {
        window.localStorage.removeItem("active_criar_session_id");
      });
  // Restore once on mount; persona fallback is intentionally best-effort.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function syncPersonaSlug(nextSlug: string) {
    const selected = personas.find((persona) => persona.slug === nextSlug);
    setPlan((prev) => (prev.personaSlug === nextSlug ? prev : { ...prev, personaSlug: nextSlug }));
    if (nextSlug) {
      window.localStorage.setItem("ai-brain-persona-slug", nextSlug);
    } else {
      window.localStorage.removeItem("ai-brain-persona-slug");
    }
    if (selected?.id) {
      window.localStorage.setItem("ai-brain-persona-id", selected.id);
    } else {
      window.localStorage.removeItem("ai-brain-persona-id");
    }
    window.dispatchEvent(new CustomEvent("ai-brain-persona-change", {
      detail: { slug: nextSlug, id: selected?.id || "" },
    }));
  }

  useEffect(() => {
    setPlan((prev) => {
      const nextConfirmed = !uploads.some((upload) => upload.source === "file");
      if (prev.confirmed === nextConfirmed) return prev;
      return { ...prev, confirmed: nextConfirmed };
    });
  }, [uploads]);

  function syncCurrentPlan(nextPlan: KnowledgePlan, lastChange: string, status?: string) {
    setCurrentKnowledgePlan(nextPlan);
    setCurrentBlockCounts(countBlocksByType(nextPlan.entries));
    setConfirmedPlanHash(null);
    if (activeSessionId) {
      api.kbIntakeUpdatePlan(activeSessionId, {
        knowledge_plan: nextPlan,
        status,
        last_change: lastChange,
      }).then((result: any) => {
        const nextState = normalizePlanState(result, plan.personaSlug);
        if (!nextState) return;
        setPlanState(nextState);
        setCurrentKnowledgePlan(nextState.normalized_plan);
        setCurrentBlockCounts(normalizeBlockCounts(nextState.summary.current_block_counts));
        if (status && nextState.validation.valid) {
          setSessionStatus(result.status || status);
          setConfirmedPlanHash(result.confirmed_plan_hash || null);
        }
      }).catch(() => {});
    } else if (status) {
      setSessionStatus(status);
    }
  }

  function adjustSidebarBlock(blockId: string, delta: number) {
    const activePlan = planState?.normalized_plan || currentKnowledgePlan;
    if (!activeSessionId || !activePlan) {
      const current = Math.max(0, Number(plan.variationCounts[blockId] || 0));
      const next = Math.max(0, current + delta);
      const nextSelected = next > 0
        ? Array.from(new Set([...plan.selectedBlocks, blockId]))
        : plan.selectedBlocks.filter((id) => id !== blockId);
      setPlan({
        ...plan,
        selectedBlocks: nextSelected,
        variationCounts: { ...plan.variationCounts, [blockId]: next },
      });
      setCurrentBlockCounts(normalizeBlockCounts({ ...plan.variationCounts, [blockId]: next }));
      return;
    }
    const existing = countBlocksByType(activePlan.entries)[blockId] || 0;
    if (delta < 0 && existing <= 0) return;
    if (delta < 0) {
      const removeIndex = [...activePlan.entries].map((entry, index) => ({ entry, index })).reverse().find((item) => item.entry.content_type === blockId)?.index;
      if (removeIndex == null) return;
      const removedSlug = activePlan.entries[removeIndex].slug;
      syncCurrentPlan({
        ...activePlan,
        entries: activePlan.entries.filter((_, index) => index !== removeIndex),
        links: (activePlan.links || []).filter((link) => link.source_slug !== removedSlug && link.target_slug !== removedSlug),
      }, `sidebar removeu ${blockId}`);
      return;
    }
    const nextEntry = createManualDraftEntry(blockId, existing + 1, plan.personaSlug, activePlan);
    syncCurrentPlan({
      ...activePlan,
      entries: [...activePlan.entries, nextEntry],
    }, `sidebar adicionou ${blockId}`);
  }

  return (
    <div className={`flex gap-5 min-h-0 ${embedded ? "h-full" : "h-[calc(100vh-7rem)]"}`}>
      <div className="w-80 shrink-0">
        <UploadPanel
          uploads={uploads}
          onUploaded={(upload) => setUploads((prev) => [upload, ...prev])}
          onRemoveUpload={(id) => setUploads((prev) => prev.filter((u) => u.id !== id))}
        />
      </div>
      <div className="flex-1 min-w-0">
        <ChatPanel
          plan={plan}
          setPlan={setPlan}
          uploads={uploads}
          onCrawlerRun={(run) => setCrawlerRuns((prev) => [run, ...prev].slice(0, 5))}
          personas={personas}
          onPersonaChange={syncPersonaSlug}
          currentKnowledgePlan={currentKnowledgePlan}
          setCurrentKnowledgePlan={setCurrentKnowledgePlan}
          currentBlockCounts={currentBlockCounts}
          setCurrentBlockCounts={setCurrentBlockCounts}
          planState={planState}
          setPlanState={setPlanState}
          confirmedPlanHash={confirmedPlanHash}
          setConfirmedPlanHash={setConfirmedPlanHash}
          sessionId={activeSessionId}
          setSessionId={setActiveSessionId}
          sessionStatus={sessionStatus}
          setSessionStatus={setSessionStatus}
        />
      </div>
      <CaptureSidebar
        plan={plan}
        uploads={uploads}
        crawlerRuns={crawlerRuns}
        planState={planState}
        currentKnowledgePlan={currentKnowledgePlan}
        currentBlockCounts={currentBlockCounts}
        sessionStatus={sessionStatus}
        onAdjustBlock={adjustSidebarBlock}
      />
    </div>
  );
}

export default function CapturePage() {
  return <CaptureWorkspace />;
}
