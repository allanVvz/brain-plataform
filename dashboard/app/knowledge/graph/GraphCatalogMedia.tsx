"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { GraphBundleViewPayload } from "@/lib/graph-bundle-v3";

export default function GraphCatalogMedia({ view, ownerId, scope }: {
  view: GraphBundleViewPayload; ownerId: string; scope: string;
}) {
  const [bundle, setBundle] = useState<any>(() => ({ ...view.document, bundle_version: "1.0", persona: view.persona }));
  const [media, setMedia] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.graphMediaPreview({ bundle, scope, owner_node_id: ownerId })
      .then(value => { if (!cancelled) setMedia(value); })
      .catch(reason => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [bundle, scope, ownerId]);

  async function change(assetId: string, action: "pin" | "unpin" | "unlink") {
    setBusy(true); setError("");
    try {
      const result = await api.graphMediaPlan({ bundle, operations: [{
        operation_id: crypto.randomUUID(), owner_node_id: ownerId, asset_node_id: assetId,
        action, assigned_at: new Date().toISOString(),
      }] });
      setBundle(result.bundle); setPlan(result.plan);
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  }

  function downloadPlan() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ bundle, plan }, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "catalog-media-publication-plan.json"; link.click();
    URL.revokeObjectURL(url);
  }

  return <section className="space-y-2 rounded-lg border border-white/10 p-3">
    <h3 className="text-sm">Imagens do catálogo</h3>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    {media?.cover_origin && <p className="text-xs">Capa: {media.cover_origin.kind === "pinned" ? "fixada" : media.cover_origin.kind === "inherited" ? "herdada" : "última atribuição"} · {media.cover_origin.owner_node_id}</p>}
    {media?.assets?.map((asset: any) => <div key={asset.asset_node_id} className="space-y-1 border-t border-white/10 py-2">
      {(asset.url || view.ref.startsWith("publication:")) && <img
        src={asset.url || api.graphMediaUrl(asset.asset_node_id, view.persona.slug, view.ref.replace("publication:", ""))}
        alt={asset.alt} className="h-24 w-full object-contain" />}
      <p className="text-xs">{asset.alt || asset.asset_node_id}{media.cover?.asset_node_id === asset.asset_node_id ? " · Capa" : ""}</p>
      {asset.owner_node_id === ownerId && <div className="flex gap-3 text-xs">
        <button disabled={busy} onClick={() => change(asset.asset_node_id, asset.pinned ? "unpin" : "pin")}>{asset.pinned ? "Desfixar" : "Fixar capa"}</button>
        <button disabled={busy} onClick={() => change(asset.asset_node_id, "unlink")}>Desvincular</button>
      </div>}
    </div>)}
    {media && !media.assets.length && <p className="text-xs">Sem imagem atribuída.</p>}
    {plan && <div className="space-y-2 text-xs">
      <p>Alterações preparadas. A publicação ativa continua disponível até a aprovação e ativação.</p>
      {plan.validation_errors?.map((message: string) => <p key={message} className="text-red-300">{message}</p>)}
      <button onClick={downloadPlan}>Baixar plano para publicação</button>
    </div>}
  </section>;
}
