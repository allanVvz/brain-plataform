"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, CheckCircle2, GitBranch, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";
import {
  PageHeader,
  SafeMarkdown,
  SearchBar,
  StatePanel,
} from "@/components/operations/Shared";

type CatalogDocument = {
  id: string;
  node_type: string;
  title: string;
  markdown: string;
  status: string;
  source: string;
  path_label: string;
  faq_count: number;
  embedded: boolean;
};

type CatalogCategory = {
  key: string;
  label: string;
  count: number;
  items: CatalogDocument[];
};

type Catalog = {
  persona: { id: string; slug: string; name: string };
  graph: { version: number; checksum: string; document_count: number };
  categories: CatalogCategory[];
  embedded: { faq_count: number; status: string };
};

export default function KbPage() {
  const globalPersona = useGlobalPersona();
  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [activeCategory, setActiveCategory] = useState("faqs");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api.knowledgeCatalog({
      personaId: globalPersona.id || undefined,
      personaSlug: globalPersona.slug || undefined,
    })
      .then((result) => {
        if (!cancelled) setCatalogs(result.catalogs || []);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Falha ao carregar o catálogo.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [globalPersona.id, globalPersona.slug]);

  const categories = useMemo(() => {
    const ordered = catalogs[0]?.categories || [];
    return ordered.map((category) => ({
      key: category.key,
      label: category.label,
      count: catalogs.reduce(
        (total, catalog) => total + (catalog.categories.find((item) => item.key === category.key)?.count || 0),
        0,
      ),
    }));
  }, [catalogs]);

  const documents = useMemo(() => {
    const term = query.trim().toLocaleLowerCase("pt-BR");
    return catalogs.flatMap((catalog) => {
      const category = catalog.categories.find((item) => item.key === activeCategory);
      return (category?.items || []).map((item) => ({ ...item, persona: catalog.persona, graph: catalog.graph }));
    }).filter((item) => !term || [
      item.title, item.markdown, item.source, item.path_label, item.persona.name,
    ].some((value) => String(value || "").toLocaleLowerCase("pt-BR").includes(term)));
  }, [activeCategory, catalogs, query]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Base de conhecimento"
        description="Catálogo canônico publicado pelo grafo. FAQs aparecem primeiro e o seletor global do topo controla o escopo."
        actions={
          <a href="/knowledge/upload" className="rounded-lg border border-obs-violet/30 bg-obs-violet/10 px-3 py-2 text-xs font-medium text-obs-violet">
            Adicionar conhecimento
          </a>
        }
      />

      <SearchBar value={query} onChange={setQuery} placeholder="Buscar por título, conteúdo, fonte ou caminho">
        <div className="flex flex-wrap gap-1.5">
          {categories.map((category) => (
            <button
              key={category.key}
              onClick={() => setActiveCategory(category.key)}
              className={`rounded-lg px-2.5 py-2 text-xs transition ${
                activeCategory === category.key ? "bg-obs-violet/15 text-obs-violet" : "text-obs-subtle hover:bg-white/5"
              }`}
            >
              {category.label} <span className="opacity-60">{category.count}</span>
            </button>
          ))}
        </div>
      </SearchBar>

      {loading && <StatePanel state="loading" title="Carregando catálogo canônico" />}
      {!loading && error && <StatePanel state="error" title="Não foi possível carregar a base" description={error} />}
      {!loading && !error && catalogs.length === 0 && (
        <StatePanel
          state="empty"
          title="Nenhum grafo publicado neste escopo"
          description="Publique uma versão válida do grafo para materializar os documentos Markdown na base."
        />
      )}
      {!loading && !error && catalogs.length > 0 && documents.length === 0 && (
        <StatePanel state="empty" title="Nenhum documento corresponde à busca" description="Ajuste a categoria ou os termos pesquisados." />
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {documents.map((item) => (
          <article key={`${item.persona.slug}:${item.id}`} className="min-w-0 rounded-xl border border-white/06 bg-white/[0.025] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                  <span>{item.node_type}</span>
                  {catalogs.length > 1 && <span>{item.persona.name}</span>}
                  <span>v{item.graph.version}</span>
                </div>
                <h2 className="mt-1 text-sm font-semibold text-obs-text">{item.title}</h2>
              </div>
              <div className="flex items-center gap-1.5">
                {item.embedded && <span title="Publicado no Embedded"><ShieldCheck size={14} className="text-emerald-400" /></span>}
                <span className="rounded-full bg-white/5 px-2 py-1 text-[10px] text-obs-subtle">{item.status}</span>
              </div>
            </div>
            <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-white/05 bg-obs-base/50 p-3">
              <SafeMarkdown markdown={item.markdown} />
            </div>
            <footer className="mt-3 grid gap-2 text-[10px] text-obs-faint sm:grid-cols-2">
              <span className="flex min-w-0 items-center gap-1.5"><GitBranch size={11} /><span className="truncate">{item.path_label}</span></span>
              <span className="flex min-w-0 items-center gap-1.5 sm:justify-end"><BookOpen size={11} /><span className="truncate">{item.source}</span></span>
              {item.node_type === "faq" && (
                <span className="flex items-center gap-1.5"><CheckCircle2 size={11} />{item.faq_count} pergunta{item.faq_count === 1 ? "" : "s"}</span>
              )}
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}
