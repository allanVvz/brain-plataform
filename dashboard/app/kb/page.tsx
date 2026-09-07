"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, CheckCircle2, GitBranch, Pencil, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useGraphBundleDraft } from "@/lib/GraphBundleDraftProvider";
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
  const [selectedFaqs, setSelectedFaqs] = useState<Set<string>>(new Set());
  const [faqEdits, setFaqEdits] = useState<Record<string, { question: string; answer: string }>>({});
  const [newFaqOpen, setNewFaqOpen] = useState(false);
  const [newFaq, setNewFaq] = useState({ sourceNodeId: "", question: "", answer: "" });
  const drafts = useGraphBundleDraft();

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
  const activeCatalog = catalogs.find((item) => item.persona.slug === globalPersona.slug) || catalogs[0];
  const draftFaqs = useMemo(() => {
    if (!drafts.draft || drafts.draft.persona_slug !== globalPersona.slug) return [];
    return (drafts.draft.bundle?.nodes || []).filter((node: any) => node.node_type === "faq" && node.status !== "archived");
  }, [drafts.draft, globalPersona.slug]);

  const openFaqDraft = async () => {
    if (!globalPersona.slug || !activeCatalog?.graph.checksum) return;
    try { await drafts.ensureDraft(globalPersona.slug, activeCatalog.graph.checksum, { surface: "kb" }); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Falha ao abrir o rascunho."); }
  };
  const editFor = (node: any) => faqEdits[node.id] || { question: String(node.data?.question || node.title || ""), answer: String(node.data?.answer || node.data?.content || node.summary || "") };
  const saveFaq = async (node: any) => {
    const edit = editFor(node);
    await drafts.mutate([{ op: "update_node", node_id: node.id, patch: { title: edit.question.trim(), summary: edit.answer.trim(), "data.question": edit.question.trim(), "data.answer": edit.answer.trim() } }], "FAQ editada no Golden Dataset", { surface: "kb", source_ref: node.id });
  };
  const decideSelected = async (decision: "approve_faq" | "reject_faq") => {
    if (!selectedFaqs.size) return;
    const operations = [...selectedFaqs].flatMap((node_id) => {
      const edit = faqEdits[node_id];
      const save = edit ? [{ op: "update_node", node_id, patch: { title: edit.question.trim(), summary: edit.answer.trim(), "data.question": edit.question.trim(), "data.answer": edit.answer.trim() } } as any] : [];
      return [...save, { op: decision, node_id } as any];
    });
    await drafts.mutate(operations, decision === "approve_faq" ? "FAQs salvas e aprovadas em lote" : "FAQs salvas e rejeitadas em lote", { surface: "kb" });
    setFaqEdits((current) => Object.fromEntries(Object.entries(current).filter(([nodeId]) => !selectedFaqs.has(nodeId))));
    setSelectedFaqs(new Set());
  };
  const reviewOrPublish = async () => {
    if (!drafts.review) await drafts.reviewDraft();
    else await drafts.publishDraft("Publicação confirmada no Golden Dataset");
  };
  const faqSources = useMemo(() => (drafts.draft?.bundle?.nodes || []).filter((node: any) => !["persona", "faq", "embedded", "embed", "gallery", "asset"].includes(node.node_type) && node.status !== "archived"), [drafts.draft]);
  const addFaq = async () => {
    const sourceNode = faqSources.find((node: any) => node.id === newFaq.sourceNodeId);
    const personaNode = (drafts.draft?.bundle?.nodes || []).find((node: any) => node.node_type === "persona");
    if (!sourceNode || !personaNode || !newFaq.question.trim() || !newFaq.answer.trim()) return;
    const id = `faq:${crypto.randomUUID()}`;
    const slug = newFaq.question.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || id.slice(4);
    const source = String(sourceNode.data?.source || sourceNode.source || "pending_source");
    const branchPath = drafts.draft?.bundle?.coordinates?.[sourceNode.id]?.path_node_ids || [personaNode.id, sourceNode.id];
    await drafts.mutate([{ op: "add_faq_proposal", node_id: id, slug, question: newFaq.question.trim(), answer: newFaq.answer.trim(), source, source_node_id: sourceNode.id, source_node_type: sourceNode.node_type, branch_path: branchPath, question_aliases: [], generator: "operator-manual-v1", generation_batch_id: crypto.randomUUID() }], "FAQ criada a partir do conhecimento selecionado", { surface: "kb", source_ref: sourceNode.id });
    setNewFaq({ sourceNodeId: "", question: "", answer: "" }); setNewFaqOpen(false);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Base de conhecimento"
        description="Catálogo canônico publicado pelo grafo. FAQs aparecem primeiro e o seletor global do topo controla o escopo."
        actions={<div className="flex gap-2"><a href="/knowledge/upload" className="rounded-lg border border-obs-violet/30 bg-obs-violet/10 px-3 py-2 text-xs font-medium text-obs-violet">Adicionar conhecimento</a><button type="button" onClick={openFaqDraft} disabled={!activeCatalog?.graph.checksum || drafts.busy} className="flex items-center gap-2 rounded-lg bg-obs-violet px-3 py-2 text-xs font-medium text-white disabled:opacity-50"><Pencil size={13} />Revisar FAQs</button></div>}
      />

      {draftFaqs.length > 0 && (
        <section className="space-y-3 rounded-2xl border border-obs-violet/25 bg-obs-violet/5 p-4">
          <div className="flex flex-wrap items-center gap-2"><div className="mr-auto"><h2 className="text-sm font-semibold text-obs-text">Revisão do mesmo rascunho do Grafo</h2><p className="mt-1 text-xs text-obs-subtle">Edite perguntas e respostas; somente FAQs aprovadas serão projetadas no Embedded.</p></div><button type="button" onClick={() => setNewFaqOpen((value) => !value)} disabled={drafts.busy} className="rounded-lg border border-obs-violet/30 px-3 py-2 text-xs text-obs-violet">Nova FAQ</button><button type="button" disabled={!selectedFaqs.size || drafts.busy} onClick={() => decideSelected("reject_faq")} className="rounded-lg border border-white/10 px-3 py-2 text-xs disabled:opacity-40">Rejeitar</button><button type="button" disabled={!selectedFaqs.size || drafts.busy} onClick={() => decideSelected("approve_faq")} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs text-white disabled:opacity-40">Aprovar selecionadas</button><button type="button" disabled={drafts.busy} onClick={reviewOrPublish} className="rounded-lg bg-obs-violet px-3 py-2 text-xs text-white disabled:opacity-40">{drafts.review ? "Publicar revisão" : "Revisar publicação"}</button></div>
          {newFaqOpen && <div className="grid gap-2 rounded-xl border border-obs-violet/20 bg-obs-base/50 p-3 md:grid-cols-2"><label className="text-[10px] text-obs-faint md:col-span-2">Conhecimento de origem<select className="lg-input mt-1 w-full text-xs" value={newFaq.sourceNodeId} onChange={(event) => setNewFaq((current) => ({ ...current, sourceNodeId: event.target.value }))}><option value="">Selecione um node</option>{faqSources.map((node: any) => <option key={node.id} value={node.id}>{node.node_type} · {node.title}</option>)}</select></label><label className="text-[10px] text-obs-faint">Pergunta<input className="lg-input mt-1 w-full text-xs" value={newFaq.question} onChange={(event) => setNewFaq((current) => ({ ...current, question: event.target.value }))} /></label><label className="text-[10px] text-obs-faint">Resposta<textarea className="lg-input mt-1 w-full text-xs" rows={3} value={newFaq.answer} onChange={(event) => setNewFaq((current) => ({ ...current, answer: event.target.value }))} /></label><div className="md:col-span-2"><button type="button" onClick={addFaq} disabled={!newFaq.sourceNodeId || !newFaq.question.trim() || !newFaq.answer.trim() || drafts.busy} className="rounded-md bg-obs-violet px-3 py-1.5 text-xs text-white disabled:opacity-40">Criar proposta pendente</button></div></div>}
          {(drafts.error || drafts.review?.validation_errors.length) ? <p className="rounded-lg border border-red-400/30 bg-red-500/10 p-2 text-xs text-red-200">{drafts.error || drafts.review?.validation_errors.join(" · ")}</p> : null}
          <div className="grid gap-3 xl:grid-cols-2">
            {draftFaqs.map((node: any) => {
              const edit = editFor(node);
              return <article key={node.id} className="rounded-xl border border-white/10 bg-obs-base/60 p-3"><div className="flex items-start gap-2"><input aria-label={`Selecionar ${node.title}`} type="checkbox" checked={selectedFaqs.has(node.id)} onChange={(event) => setSelectedFaqs((current) => { const next = new Set(current); event.target.checked ? next.add(node.id) : next.delete(node.id); return next; })} /><span className="ml-auto rounded bg-white/5 px-2 py-0.5 text-[10px] text-obs-faint">{node.status}</span></div><label className="mt-2 block text-[10px] text-obs-faint">Pergunta<input className="lg-input mt-1 w-full text-xs" value={edit.question} onChange={(event) => setFaqEdits((current) => ({ ...current, [node.id]: { ...edit, question: event.target.value } }))} /></label><label className="mt-2 block text-[10px] text-obs-faint">Resposta<textarea className="lg-input mt-1 w-full text-xs" rows={4} value={edit.answer} onChange={(event) => setFaqEdits((current) => ({ ...current, [node.id]: { ...edit, answer: event.target.value } }))} /></label><div className="mt-2 flex items-center justify-between"><span className="max-w-[70%] truncate text-[10px] text-obs-faint">{node.data?.source || "pending_source"}</span><button type="button" disabled={drafts.busy || !edit.question.trim() || !edit.answer.trim()} onClick={() => saveFaq(node)} className="rounded-md border border-obs-violet/30 px-2 py-1 text-[10px] text-obs-violet disabled:opacity-40">Salvar</button></div></article>;
            })}
          </div>
        </section>
      )}

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
