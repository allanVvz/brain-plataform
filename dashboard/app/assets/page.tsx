"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/utils/supabase/client";

interface Asset {
  id: string;
  name: string;
  type: string;
  url: string | null;
  source: string;
  created_at: string;
  metadata: Record<string, any>;
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = createClient();
    async function load() {
      try {
        const { data } = await supabase.from("assets").select("*").order("created_at", { ascending: false }).limit(100);
        if (data) setAssets(data);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const filtered = filter ? assets.filter((a) => a.type === filter) : assets;
  const types = ["image", "copy", "campaign", "template"];

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Assets</h1>

      <div className="flex gap-2">
        <button onClick={() => setFilter("")}
          className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${!filter ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
          Todos
        </button>
        {types.map((t) => (
          <button key={t} onClick={() => setFilter(t)}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${filter === t ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            {t}
          </button>
        ))}
      </div>

      {loading && <p className="text-brain-muted text-sm">Carregando...</p>}
      {!loading && filtered.length === 0 && (
        <p className="text-brain-muted text-sm">Nenhum asset encontrado.</p>
      )}

      <div className="grid grid-cols-3 gap-4">
        {filtered.map((asset) => (
          <div key={asset.id} className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-2">
            {asset.url && asset.type === "image" ? (
              <img src={asset.url} alt={asset.name} className="w-full h-32 object-cover rounded-lg bg-brain-bg" />
            ) : (
              <div className="w-full h-32 bg-brain-bg rounded-lg flex items-center justify-center text-brain-muted text-xs uppercase">
                {asset.type}
              </div>
            )}
            <p className="text-sm font-medium truncate">{asset.name}</p>
            <div className="flex items-center justify-between">
              <span className="text-xs text-brain-muted">{asset.source}</span>
              <span className="text-xs text-brain-muted">{new Date(asset.created_at).toLocaleDateString("pt-BR")}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
