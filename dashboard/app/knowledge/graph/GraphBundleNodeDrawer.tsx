"use client";

import { X } from "lucide-react";
import { branchMembershipsForNode, GraphBundleViewPayload } from "@/lib/graph-bundle-v3";

interface Props {
  node: any | null;
  view: GraphBundleViewPayload | null;
  edges: any[];
  onClose: () => void;
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[9px] uppercase tracking-wider text-obs-faint">{label}</p>
      <div className="text-xs text-obs-text">{children}</div>
    </div>
  );
}

export default function GraphBundleNodeDrawer({ node, view, edges, onClose }: Props) {
  if (!node || !view) return null;
  const raw = node.data?.bundle_node || {};
  const relations = (edges || [])
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => ({
      id: edge.id,
      direction: edge.source === node.id ? "saída" : "entrada",
      other: edge.source === node.id ? edge.target : edge.source,
      relation: edge.data?.relation_type || "contains",
    }));
  const memberships = branchMembershipsForNode(view, node.id);
  const source = raw.data?.source || raw.source || view.origin;
  const content = raw.data?.content || raw.content || raw.summary || "Sem conteúdo textual.";

  return (
    <aside className="absolute inset-y-3 right-3 z-50 w-[390px] overflow-y-auto rounded-xl border border-white/10 bg-obs-raised/95 p-4 shadow-2xl backdrop-blur-xl">
      <div className="mb-4 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wider text-obs-violet">GraphBundle v3 · somente leitura</p>
          <h2 className="mt-1 text-base font-semibold text-obs-text">{raw.title || raw.slug || raw.id}</h2>
          <p className="mt-1 font-mono text-[10px] text-obs-faint">{raw.id}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded-md p-1.5 text-obs-subtle hover:bg-white/5 hover:text-white" aria-label="Fechar detalhes">
          <X size={15} />
        </button>
      </div>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Detail label="Tipo">{raw.node_type || "—"}</Detail>
          <Detail label="Status">{raw.status || raw.data?.status || "—"}</Detail>
          <Detail label="Versão">{view.version ?? "draft"}</Detail>
          <Detail label="Estado">{view.state}</Detail>
        </div>
        <Detail label="Fonte"><span className="break-all">{String(source || "pending_source")}</span></Detail>
        <Detail label="Resumo / conteúdo"><p className="whitespace-pre-wrap leading-relaxed text-obs-subtle">{String(content)}</p></Detail>
        <Detail label="Tags">
          <div className="flex flex-wrap gap-1">
            {(raw.tags || []).length ? raw.tags.map((tag: string) => <span key={tag} className="rounded border border-white/10 px-1.5 py-0.5 text-[10px]">{tag}</span>) : "—"}
          </div>
        </Detail>
        <Detail label="Relações">
          <div className="space-y-1">
            {relations.length ? relations.map((relation) => (
              <div key={relation.id} className="rounded border border-white/8 bg-white/[0.025] px-2 py-1.5 text-[10px]">
                <span className="text-obs-faint">{relation.direction}</span> · {relation.relation} · <span className="font-mono">{relation.other}</span>
              </div>
            )) : "—"}
          </div>
        </Detail>
        <Detail label="Branch memberships">
          <div className="flex flex-wrap gap-1">
            {memberships.length ? memberships.map((branch) => <span key={branch} className="rounded bg-obs-violet/10 px-1.5 py-0.5 font-mono text-[10px] text-obs-violet">{branch}</span>) : "—"}
          </div>
        </Detail>
        <Detail label="Validações">
          {view.validation_errors.length ? (
            <ul className="space-y-1 text-[10px] text-red-200">
              {view.validation_errors.map((error) => <li key={error} className="rounded border border-red-400/20 bg-red-500/10 px-2 py-1">{error}</li>)}
            </ul>
          ) : <span className="text-emerald-300">Sem erros de validação.</span>}
        </Detail>
        <Detail label="Data específica do node">
          <pre className="max-h-64 overflow-auto rounded-lg border border-white/8 bg-black/20 p-2 text-[10px] text-obs-subtle">{JSON.stringify(raw.data || {}, null, 2)}</pre>
        </Detail>
      </div>
    </aside>
  );
}
