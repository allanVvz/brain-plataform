"use client";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { getCatalogUrlForPersona } from "@/utils/env";
import { Building2, ExternalLink, Image as ImageIcon, Megaphone, MessageSquareText, Network, Package, ScrollText, Users } from "lucide-react";

interface Persona { id: string; slug: string; name: string; tone: string; products: string[]; config: any; active: boolean; created_at: string; catalog_url?: string | null; }

interface GraphNodeSummary {
  id: string;
  title: string;
  type: string;
  summary: string;
}

interface PersonaGraphSummary {
  products: GraphNodeSummary[];
  brands: GraphNodeSummary[];
  campaigns: GraphNodeSummary[];
  audiences: GraphNodeSummary[];
  rulesAndTone: GraphNodeSummary[];
  copyFaq: GraphNodeSummary[];
  operationalSummary: string;
  totalConnected: number;
}

const GRAPH_CATEGORY_LABELS: Record<string, string> = {
  persona: "Persona",
  brand: "Brand",
  campaign: "Campanha",
  product: "Produto",
  audience: "Publico",
  faq: "FAQ",
  copy: "Copy",
  asset: "Assets",
  gallery: "Galeria",
  embedded: "Embed",
  background: "Backgrounds",
  texture: "Texturas",
  rule: "Regras",
  tone: "Tom de voz",
  entity: "Entidades",
};

function graphNodeType(node: any): string {
  return String(node?.data?.node_type || node?.data?.content_type || "").toLowerCase();
}

function graphNodeTitle(node: any): string {
  return String(node?.data?.label || node?.data?.title || node?.data?.slug || node?.id || "Node");
}

function graphNodeSummary(node: any): string {
  return String(node?.data?.content_preview || node?.data?.summary || node?.data?.metadata?.summary || "").trim();
}

function compactSummary(text: string, max = 150): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trim()}...` : clean;
}

function toSummary(node: any): GraphNodeSummary {
  const type = graphNodeType(node);
  return {
    id: node.id,
    title: graphNodeTitle(node),
    type: GRAPH_CATEGORY_LABELS[type] || type || "Node",
    summary: compactSummary(graphNodeSummary(node)),
  };
}

function summarizePersonaGraph(graph: any, fallbackProducts: string[] = []): PersonaGraphSummary {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const connectedIds = new Set<string>();
  for (const edge of edges) {
    if (edge?.source) connectedIds.add(edge.source);
    if (edge?.target) connectedIds.add(edge.target);
  }
  const scopedNodes = nodes.filter((node: any) => {
    const type = graphNodeType(node);
    if (!type || ["persona", "tag", "mention", "knowledge_item", "kb_entry"].includes(type)) return false;
    return connectedIds.size === 0 || connectedIds.has(node.id);
  });

  const byType = (types: string[]) => scopedNodes.filter((node: any) => types.includes(graphNodeType(node))).map(toSummary);
  const productNodes = byType(["product"]);
  const products = productNodes.length > 0
    ? productNodes
    : fallbackProducts.map((title) => ({ id: `fallback-product:${title}`, title, type: "Produto", summary: "" }));

  const highlights = [
    ...byType(["brand"]).slice(0, 1),
    ...byType(["campaign"]).slice(0, 1),
    ...products.slice(0, 2),
    ...byType(["audience"]).slice(0, 1),
    ...byType(["rule", "tone"]).slice(0, 2),
  ].filter((item) => item.summary || item.title);

  const operationalSummary = highlights.length > 0
    ? highlights
        .map((item) => item.summary ? `${item.title}: ${item.summary}` : item.title)
        .join(" ")
    : "Sem conexoes principais suficientes no grafo para gerar um resumo operacional.";

  return {
    products,
    brands: byType(["brand"]),
    campaigns: byType(["campaign"]),
    audiences: byType(["audience"]),
    rulesAndTone: byType(["rule", "tone"]),
    copyFaq: byType(["copy", "faq"]),
    operationalSummary: compactSummary(operationalSummary, 420),
    totalConnected: scopedNodes.length,
  };
}

export default function PersonaPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selected, setSelected] = useState<Persona | null>(null);
  const [brand, setBrand] = useState<any>(null);
  const [bindings, setBindings] = useState<any[]>([]);
  const [kbCount, setKbCount] = useState<number | null>(null);
  const [graphSummary, setGraphSummary] = useState<PersonaGraphSummary | null>(null);
  const [galleryAssetCount, setGalleryAssetCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.personas().then((list) => {
      setPersonas(list);
      if (list.length === 0) return;
      const stored = (typeof window !== "undefined"
        ? window.localStorage.getItem("ai-brain-persona-slug")
        : "") || "";
      const match = stored ? list.find((p) => p.slug === stored) : null;
      selectPersona(match || list[0]);
    }).finally(() => setLoading(false));
  }, []);

  // Top-bar Cliente filter and the persona page must stay in sync.
  // Header dispatches `ai-brain-persona-change`; we react to it and adopt the slug.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ slug?: string; id?: string }>).detail;
      const slug = detail?.slug || "";
      if (!slug) return;
      if (selected?.slug === slug) return;
      const next = personas.find((p) => p.slug === slug);
      if (next) selectPersona(next);
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, [personas, selected?.slug]);

  async function selectPersona(p: Persona) {
    setSelected(p);
    // Mirror Cliente=Persona business rule: any in-page persona switch
    // must propagate to the top-bar via the same channel AppShell uses.
    if (typeof window !== "undefined") {
      const currentSlug = window.localStorage.getItem("ai-brain-persona-slug");
      const currentId = window.localStorage.getItem("ai-brain-persona-id");
      if (currentSlug !== p.slug || currentId !== p.id) {
        window.localStorage.setItem("ai-brain-persona-slug", p.slug);
        window.localStorage.setItem("ai-brain-persona-id", p.id);
        window.dispatchEvent(new CustomEvent("ai-brain-persona-change", {
          detail: { slug: p.slug, id: p.id },
        }));
      }
    }
    setBrand(null);
    setBindings([]);
    setKbCount(null);
    setGraphSummary(null);
    setGalleryAssetCount(null);
    const [brandData, bindingsData, kbData, graphData, galleryData] = await Promise.all([
      api.brandProfile(p.id).catch(() => null),
      api.workflowBindings(p.id).catch(() => []),
      api.kb(p.id).catch(() => []),
      api.graphData(p.slug, { include_embedded: true, mode: "semantic_tree", max_depth: 6 }).catch(() => null),
      api.galleryAssets(p.id).catch(() => []),
    ]);
    setBrand(brandData);
    setBindings(bindingsData);
    setKbCount(Array.isArray(kbData) ? kbData.length : 0);
    setGraphSummary(summarizePersonaGraph(graphData, p.products || []));
    setGalleryAssetCount(Array.isArray(galleryData) ? galleryData.length : 0);
  }

  if (loading) return <p className="text-obs-subtle text-sm">Carregando...</p>;

  return (
    <div className="lg-page-narrow space-y-5">
      <h1 className="text-xl font-semibold text-obs-text">Personas / Clientes</h1>

      {/* Client tabs */}
      <div className="flex gap-2 flex-wrap">
        {personas.map((p) => (
          <button key={p.id} onClick={() => selectPersona(p)}
            className={`lg-btn ${
              selected?.id === p.id
                ? "lg-btn-primary"
                : "lg-btn-secondary"
            }`}>
            {p.name}
          </button>
        ))}
      </div>

      {selected && (
        <div className="grid grid-cols-3 gap-4">
          {/* Main info */}
          <div className="col-span-2 space-y-4">
            <div className="panel space-y-5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-obs-violet/10 flex items-center justify-center text-obs-violet font-bold text-lg [border:1px_solid_var(--border-glass)]">
                  {selected.name[0]}
                </div>
                <div>
                  <p className="font-semibold text-lg text-obs-text">Persona: {selected.name}</p>
                  <p className="text-xs text-obs-faint font-mono">{selected.slug}</p>
                </div>
                <span className={`ml-auto lg-badge ${selected.active ? "lg-badge-success" : "lg-badge-error"}`}>
                  {selected.active ? "ativo" : "inativo"}
                </span>
              </div>

              <div>
                <p className="text-xs text-obs-faint uppercase tracking-wide mb-1">Tom de voz</p>
                <p className="text-sm text-obs-text">{selected.tone || "—"}</p>
              </div>

              <div>
                <p className="text-xs text-obs-faint uppercase tracking-wide mb-1">Produtos cadastrados</p>
                <div className="flex flex-wrap gap-1.5">
                  {(selected.products || []).map((p) => (
                    <span key={p} className="lg-badge">{p}</span>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <GraphSummarySection icon={<Package size={14} />} title="Produtos conectados" items={graphSummary?.products || []} />
                <GraphSummarySection icon={<Building2 size={14} />} title="Brands conectadas" items={graphSummary?.brands || []} />
                <GraphSummarySection icon={<Megaphone size={14} />} title="Campanhas conectadas" items={graphSummary?.campaigns || []} />
                <GraphSummarySection icon={<Users size={14} />} title="Publicos conectados" items={graphSummary?.audiences || []} />
                <GraphSummarySection icon={<ScrollText size={14} />} title="Regras e tom de voz" items={graphSummary?.rulesAndTone || []} />
                <GraphSummarySection icon={<MessageSquareText size={14} />} title="Copy e FAQ" items={graphSummary?.copyFaq || []} />
              </div>

              <div className="lg-card space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-obs-faint">
                    <Network size={14} className="text-obs-violet" />
                    Resumo operacional
                  </p>
                  <span className="lg-badge">{graphSummary?.totalConnected ?? 0} nodes conectados</span>
                </div>
                <p className="text-sm leading-relaxed text-obs-text">
                  {graphSummary?.operationalSummary || "Carregando resumo do grafo..."}
                </p>
              </div>

              {selected.config && Object.keys(selected.config).length > 0 && (
                <div>
                  <p className="text-xs text-obs-faint uppercase tracking-wide mb-1">Config</p>
                  <pre className="text-xs rounded-lg p-3 overflow-x-auto text-obs-text [background:rgba(255,255,255,0.58)] [border:1px_solid_var(--border-glass)]">
                    {JSON.stringify(selected.config, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <PersonaCatalogCard
              persona={selected}
              productCount={graphSummary?.products.length ?? 0}
              galleryCount={galleryAssetCount}
              onCatalogUrlSaved={(url) => {
                setSelected((current) => current && current.slug === selected.slug
                  ? { ...current, catalog_url: url } : current);
                setPersonas((list) => list.map((p) => p.slug === selected.slug
                  ? { ...p, catalog_url: url } : p));
              }}
            />

            {/* Brand Profile */}
            {brand && Object.keys(brand).length > 0 && (
              <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-3">
                <p className="text-sm font-semibold">Brand Profile</p>
                {brand.tagline && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Tagline</p>
                    <p className="text-sm italic">"{brand.tagline}"</p>
                  </div>
                )}
                {brand.positioning && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Posicionamento</p>
                    <p className="text-sm">{brand.positioning}</p>
                  </div>
                )}
                {brand.tone_pillars?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Pilares de tom</p>
                    <div className="flex gap-2 flex-wrap">
                      {brand.tone_pillars.map((t: string) => (
                        <span key={t} className="text-xs bg-brain-accent/10 border border-brain-accent/30 text-brain-accent rounded px-2 py-0.5">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {brand.differentials?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Diferenciais</p>
                    <ul className="text-sm space-y-0.5">
                      {brand.differentials.map((d: string, i: number) => (
                        <li key={i} className="flex gap-2"><span className="text-brain-accent">·</span>{d}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {brand.palette?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Paleta</p>
                    <div className="flex gap-2">
                      {brand.palette.map((c: string) => (
                        <div key={c} className="flex items-center gap-1.5">
                          <div className="w-5 h-5 rounded border border-brain-border" style={{ backgroundColor: c }} />
                          <span className="text-xs font-mono text-brain-muted">{c}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {!brand && (
              <div className="bg-brain-surface border border-dashed border-brain-border rounded-xl p-4 text-center text-sm text-brain-muted">
                Sem brand profile. Sincronize o vault ou adicione via{" "}
                <a href="/knowledge/upload" className="text-brain-accent hover:underline">Upload</a>.
              </div>
            )}

          </div>

          {/* Right column: stats + bindings */}
          <div className="space-y-4">
            {/* Quick stats */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
              <p className="text-xs text-brain-muted uppercase tracking-wide">Resumo</p>
              <Stat label="Entradas no Golden Dataset" value={kbCount ?? "—"} />
              <Stat label="Fluxos n8n" value={bindings.length} />
            </div>

            {/* n8n bindings */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-2">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Fluxos n8n</p>
              {bindings.length === 0 && (
                <p className="text-xs text-brain-muted">Nenhum fluxo vinculado.</p>
              )}
              {bindings.map((b) => (
                <div key={b.id} className="flex items-center gap-2 text-xs">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${b.active ? "bg-green-400" : "bg-brain-muted"}`} />
                  <span className="text-white truncate">{b.workflow_name}</span>
                  {b.whatsapp_number && <span className="text-brain-muted shrink-0">{b.whatsapp_number}</span>}
                </div>
              ))}
            </div>

            {/* Quick links */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-1">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Ações rápidas</p>
              <a href={`/kb?persona_id=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Ver Golden Dataset</a>
              <a href="/knowledge/sync" className="block text-xs text-brain-accent hover:underline py-0.5">→ Sincronizar Vault</a>
              <a href={`/knowledge/validate?persona=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Validar itens pendentes</a>
              <a href="/knowledge/upload" className="block text-xs text-brain-accent hover:underline py-0.5">→ Upload de conhecimento</a>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function PersonaCatalogCard({
  persona,
  productCount,
  galleryCount,
  onCatalogUrlSaved,
}: {
  persona: Persona;
  productCount: number;
  galleryCount: number | null;
  onCatalogUrlSaved: (url: string | null) => void;
}) {
  // The persisted URL (personas.catalog_url) wins over the env fallback so each
  // persona can point at its own cardapio deploy. Empty string saves clear the
  // column and the env fallback is used again.
  const fallbackUrl = getCatalogUrlForPersona(persona.slug);
  const effectiveUrl = (persona.catalog_url && persona.catalog_url.trim()) || fallbackUrl || "";
  const [draft, setDraft] = useState<string>(persona.catalog_url || "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Reset draft when persona switches.
  useEffect(() => {
    setDraft(persona.catalog_url || "");
    setMessage(null);
  }, [persona.slug]);

  const productsLinked = productCount > 0;
  const galleryLinked = (galleryCount ?? 0) > 0;
  const dirty = (persona.catalog_url || "") !== draft;

  async function save() {
    if (saving) return;
    setSaving(true);
    setMessage(null);
    const trimmed = draft.trim();
    const payload = trimmed ? trimmed : null;
    try {
      await api.updatePersonaCatalogUrl(persona.slug, payload);
      onCatalogUrlSaved(payload);
      setMessage(payload ? "URL do catalogo salva." : "URL limpa; usando fallback do env.");
    } catch (e: any) {
      setMessage(e?.message || "Falha ao salvar URL do catalogo.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            <ExternalLink size={14} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-obs-faint">
              Catalogo publico
            </p>
            <p className="text-sm font-semibold text-obs-text">
              Cardapio de {persona.name}
            </p>
          </div>
        </div>
        {effectiveUrl ? (
          <a
            href={effectiveUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md bg-obs-violet px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-obs-violet/90"
          >
            Abrir catalogo
            <ExternalLink size={12} />
          </a>
        ) : (
          <span className="lg-badge lg-badge-warning">URL nao configurada</span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <div className="lg-card flex items-center justify-between gap-2 px-3 py-2">
          <span className="flex items-center gap-2 text-xs text-obs-subtle">
            <Package size={13} className="text-obs-violet" />
            Produtos vinculados
          </span>
          <span className={`lg-badge ${productsLinked ? "lg-badge-success" : "lg-badge-warning"}`}>
            {productCount}
          </span>
        </div>
        <div className="lg-card flex items-center justify-between gap-2 px-3 py-2">
          <span className="flex items-center gap-2 text-xs text-obs-subtle">
            <ImageIcon size={13} className="text-obs-violet" />
            Assets em Gallery
          </span>
          <span className={`lg-badge ${galleryLinked ? "lg-badge-success" : "lg-badge-warning"}`}>
            {galleryCount === null ? "-" : galleryCount}
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] font-semibold uppercase tracking-[0.18em] text-obs-faint block">
          URL persistida (sobrescreve o fallback do env)
        </label>
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={fallbackUrl || "https://meu-cardapio.com/minha-persona"}
            className="flex-1 rounded-md px-3 py-2 text-xs font-mono text-obs-text [background:rgba(255,255,255,0.58)] [border:1px_solid_var(--border-glass)] focus:outline-none focus:[border-color:var(--obs-violet)]"
            disabled={saving}
          />
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="rounded-md bg-obs-violet px-3 py-2 text-xs font-medium text-white shadow-sm transition hover:bg-obs-violet/90 disabled:opacity-50"
          >
            {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
        {message && (
          <p className="text-[11px] text-obs-faint">{message}</p>
        )}
        {!persona.catalog_url && fallbackUrl && (
          <p className="text-[11px] text-obs-faint">
            Usando fallback <code className="text-obs-violet">NEXT_PUBLIC_CARDAPIO_BASE_URL</code> -&gt; {fallbackUrl}
          </p>
        )}
        {!persona.catalog_url && !fallbackUrl && (
          <p className="text-[11px] text-obs-faint">
            Sem URL persistida e sem fallback do env. Defina aqui ou em <code className="text-obs-violet">NEXT_PUBLIC_CARDAPIO_BASE_URL</code>.
          </p>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-obs-subtle">{label}</span>
      <span className="text-sm font-semibold text-obs-text">{value}</span>
    </div>
  );
}

function GraphSummarySection({
  icon,
  title,
  items,
}: {
  icon: ReactNode;
  title: string;
  items: GraphNodeSummary[];
}) {
  const visible = items.slice(0, 5);
  return (
    <section className="lg-card space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-obs-faint">
          <span className="text-obs-violet">{icon}</span>
          {title}
        </p>
        <span className="text-[11px] text-obs-faint">{items.length}</span>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-obs-faint">Nenhum node conectado.</p>
      ) : (
        <ul className="space-y-1.5">
          {visible.map((item) => (
            <li key={item.id} className="rounded-lg px-2 py-1.5 [background:rgba(255,255,255,0.48)] [border:1px_solid_var(--border-glass-soft)]">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-obs-text">{item.title}</span>
                <span className="lg-badge shrink-0">{item.type}</span>
              </div>
              {item.summary && (
                <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-obs-subtle">{item.summary}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
