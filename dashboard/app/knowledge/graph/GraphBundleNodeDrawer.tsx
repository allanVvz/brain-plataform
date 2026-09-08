"use client";

import { useEffect, useMemo, useState } from "react";
import { Archive, Bot, Save, X } from "lucide-react";
import { api } from "@/lib/api";
import { branchMembershipsForNode, GraphBundleViewPayload } from "@/lib/graph-bundle-v3";

interface Props {
  node: any | null;
  view: GraphBundleViewPayload | null;
  edges: any[];
  editable?: boolean;
  busy?: boolean;
  onSave?: (nodeId: string, patch: Record<string, any>) => Promise<void>;
  onArchive?: (nodeId: string) => Promise<void>;
  onClose: () => void;
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><p className="mb-1 text-[9px] uppercase tracking-wider text-obs-faint">{label}</p><div className="text-xs text-obs-text">{children}</div></div>;
}

export default function GraphBundleNodeDrawer({ node, view, edges, editable = false, busy = false, onSave, onArchive, onClose }: Props) {
  const raw = node?.data?.bundle_node || {};
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [content, setContent] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [routing, setRouting] = useState<any>(null);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setTitle(String(raw.title || ""));
    setSummary(String(raw.summary || ""));
    setContent(String(raw.data?.answer || raw.data?.content || raw.content || ""));
    setSource(String(raw.data?.source || raw.source || "pending_source"));
    setStatus(String(raw.status || raw.data?.status || "pending_validation"));
    setLocalError("");
  }, [node?.id]);

  const isAgent = ["agent", "action"].includes(String(raw.node_type || "").toLowerCase()) || Boolean(raw.data?.agent_slug || raw.data?.agent_kind);
  useEffect(() => {
    let active = true;
    setRouting(null);
    if (isAgent && view?.persona.slug) api.personaRouting(view.persona.slug).then((value) => active && setRouting(value)).catch(() => undefined);
    return () => { active = false; };
  }, [isAgent, view?.persona.slug]);

  const relations = useMemo(() => (edges || []).filter((edge) => edge.source === node?.id || edge.target === node?.id).map((edge) => ({
    id: edge.id, direction: edge.source === node?.id ? "saída" : "entrada",
    other: edge.source === node?.id ? edge.target : edge.source,
    relation: edge.data?.relation_type || "contains",
  })), [edges, node?.id]);
  if (!node || !view) return null;
  const memberships = branchMembershipsForNode(view, node.id);
  const protectedNode = ["persona", "embedded", "gallery"].includes(String(raw.node_type || "").toLowerCase());

  const save = async () => {
    if (!onSave) return;
    setLocalError("");
    const patch: Record<string, any> = { title: title.trim(), summary, status };
    if (!protectedNode) {
      patch[raw.node_type === "faq" ? "data.answer" : "data.content"] = content;
      if (raw.node_type === "faq") patch["data.question"] = title.trim();
      patch["data.source"] = source || "pending_source";
    }
    try { await onSave(String(raw.id || node.id), patch); }
    catch (caught) { setLocalError(caught instanceof Error ? caught.message : "Falha ao salvar."); }
  };

  return (
    <aside className="absolute inset-y-3 right-3 z-50 w-[410px] overflow-y-auto rounded-xl border border-white/10 bg-obs-raised/95 p-4 shadow-2xl backdrop-blur-xl">
      <div className="mb-4 flex items-start gap-3">
        <div className="min-w-0 flex-1"><p className="text-[10px] uppercase tracking-wider text-obs-violet">GraphBundle v3 · {editable ? "rascunho editável" : "publicação ativa"}</p><h2 className="mt-1 text-base font-semibold text-obs-text">{raw.title || raw.slug || raw.id}</h2><p className="mt-1 font-mono text-[10px] text-obs-faint">{raw.id}</p></div>
        <button type="button" onClick={onClose} className="rounded-md p-1.5 text-obs-subtle hover:bg-white/5 hover:text-white" aria-label="Fechar detalhes"><X size={15} /></button>
      </div>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3"><Detail label="Tipo">{raw.node_type || "—"}</Detail><Detail label="Estado">{view.state}</Detail></div>
        {editable ? (
          <section className="space-y-3 rounded-xl border border-obs-violet/25 bg-obs-violet/5 p-3">
            <label className="block text-[10px] text-obs-faint">Título<input className="lg-input mt-1 w-full text-xs" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
            <label className="block text-[10px] text-obs-faint">Resumo<textarea className="lg-input mt-1 w-full text-xs" rows={3} value={summary} onChange={(event) => setSummary(event.target.value)} /></label>
            {!protectedNode && <><label className="block text-[10px] text-obs-faint">{raw.node_type === "faq" ? "Resposta" : "Conteúdo"}<textarea className="lg-input mt-1 w-full text-xs" rows={6} value={content} onChange={(event) => setContent(event.target.value)} /></label><label className="block text-[10px] text-obs-faint">Fonte<input className="lg-input mt-1 w-full text-xs" value={source} onChange={(event) => setSource(event.target.value)} /></label></>}
            <label className="block text-[10px] text-obs-faint">Status<select className="lg-input mt-1 w-full text-xs" value={status} onChange={(event) => setStatus(event.target.value)}><option value="pending_validation">Pendente</option>{raw.node_type !== "faq" && <><option value="validated">Validado</option><option value="approved">Aprovado</option></>}<option value="rejected">Rejeitado</option></select></label>
            {localError && <p className="text-xs text-red-300">{localError}</p>}
            <div className="flex gap-2"><button type="button" onClick={save} disabled={busy || !title.trim()} className="flex items-center gap-2 rounded-lg bg-obs-violet px-3 py-2 text-xs font-medium text-white disabled:opacity-50"><Save size={13} />{busy ? "Salvando…" : "Salvar no rascunho"}</button>{!protectedNode && onArchive ? <button type="button" onClick={() => onArchive(String(raw.id || node.id))} disabled={busy} className="flex items-center gap-2 rounded-lg border border-amber-400/30 px-3 py-2 text-xs text-amber-200 disabled:opacity-50"><Archive size={13} />Arquivar</button> : null}</div>
          </section>
        ) : <Detail label="Conteúdo"><p className="whitespace-pre-wrap leading-relaxed text-obs-subtle">{String(raw.data?.answer || raw.data?.content || raw.summary || "Sem conteúdo textual.")}</p></Detail>}
        {isAgent && <section className="rounded-xl border border-sky-400/25 bg-sky-500/5 p-3"><div className="flex items-center gap-2"><Bot size={14} className="text-sky-300" /><h3 className="text-xs font-semibold text-obs-text">Agente {raw.data?.agent_kind || raw.data?.agent_slug || raw.title || "configurável"}</h3></div><div className="mt-3 grid grid-cols-2 gap-3 text-xs"><Detail label="Executor">{routing?.conversation_mode || raw.data?.executor || "carregando"}</Detail><Detail label="Workflow">{raw.data?.workflow_name || raw.data?.workflow_ref || "herdado da persona"}</Detail><Detail label="Estado">{routing?.readiness?.operational_state || "indisponível"}</Detail><Detail label="Modelo">{routing?.field_extractor || raw.data?.model || "herdado"}</Detail><Detail label="Skills">{(raw.data?.skills || []).join(", ") || "—"}</Detail><Detail label="Plugins">{(raw.data?.plugins || []).join(", ") || "—"}</Detail><Detail label="Credencial">{routing?.model_required ? "configurada no cofre (mascarada)" : "não exigida"}</Detail></div>{raw.data?.prompt && <div className="mt-3"><Detail label="Prompt"><pre className="max-h-36 overflow-auto whitespace-pre-wrap text-[10px]">{raw.data.prompt}</pre></Detail></div>}<p className="mt-3 text-[10px] text-obs-faint">A chave nunca é carregada no grafo ou no navegador; apenas a referência mascarada é exibida.</p></section>}
        <Detail label="Relações"><div className="space-y-1">{relations.length ? relations.map((relation) => <div key={relation.id} className="rounded border border-white/8 bg-white/[0.025] px-2 py-1.5 text-[10px]"><span className="text-obs-faint">{relation.direction}</span> · {relation.relation} · <span className="font-mono">{relation.other}</span></div>) : "—"}</div></Detail>
        <Detail label="Branch memberships"><div className="flex flex-wrap gap-1">{memberships.length ? memberships.map((branch) => <span key={branch} className="rounded bg-obs-violet/10 px-1.5 py-0.5 font-mono text-[10px] text-obs-violet">{branch}</span>) : "—"}</div></Detail>
        <Detail label="Validações">{view.validation_errors.length ? <ul className="space-y-1 text-[10px] text-red-200">{view.validation_errors.map((item) => <li key={item}>{item}</li>)}</ul> : <span className="text-emerald-300">Sem erros conhecidos.</span>}</Detail>
      </div>
    </aside>
  );
}
