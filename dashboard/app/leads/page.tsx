"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";

const STAGE_COLOR: Record<string, string> = {
  novo: "text-gray-400",
  "nao qualificado": "text-gray-400",
  contatado: "text-blue-400",
  engajado: "text-yellow-400",
  qualificado: "text-orange-400",
  oportunidade: "text-green-400",
  fechado: "text-green-500 font-semibold",
  perdido: "text-red-400",
};

export default function LeadsPage() {
  const [leads, setLeads] = useState<any[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => { api.leads().then(setLeads).catch(console.error); }, []);

  const filtered = leads.filter((l) => {
    const q = search.toLowerCase();
    return !q || (l.nome || "").toLowerCase().includes(q) || (l.lead_id || "").includes(q);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Leads</h1>
        <span className="text-brain-muted text-sm">{filtered.length} leads</span>
      </div>

      <input
        placeholder="Buscar por nome ou lead_id..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full bg-brain-surface border border-brain-border rounded-lg px-4 py-2 text-sm text-white placeholder-brain-muted focus:outline-none focus:border-brain-accent"
      />

      <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-brain-border text-brain-muted text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Nome</th>
              <th className="px-4 py-3 text-left">Stage</th>
              <th className="px-4 py-3 text-left">Produto</th>
              <th className="px-4 py-3 text-left">Canal</th>
              <th className="px-4 py-3 text-left">Última msg</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brain-border">
            {filtered.map((lead) => (
              <tr key={lead.id || lead.lead_id} className="hover:bg-white/5 transition-colors">
                <td className="px-4 py-3 font-medium">
                  <Link href={`/messages/${lead.lead_id}`} className="hover:text-brain-accent transition-colors">
                    {lead.nome || lead.lead_id || "—"}
                  </Link>
                </td>
                <td className={`px-4 py-3 ${STAGE_COLOR[lead.stage] || "text-white"}`}>
                  {lead.stage || "novo"}
                </td>
                <td className="px-4 py-3 text-brain-muted">{lead.interesse_produto || "—"}</td>
                <td className="px-4 py-3 text-brain-muted">{lead.canal || "whatsapp"}</td>
                <td className="px-4 py-3 text-brain-muted text-xs">
                  {lead.ultima_mensagem?.slice(0, 40) || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
