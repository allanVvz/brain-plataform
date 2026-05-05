"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, ChevronDown, ChevronRight, FileUp, Loader2, Plus, Table2, X } from "lucide-react";
import { api } from "@/lib/api";

export default function LeadImportPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [imports, setImports] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [modal, setModal] = useState<any | null>(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [lastCreated, setLastCreated] = useState<number | null>(null);
  const [personaId, setPersonaId] = useState("");
  const [personaName, setPersonaName] = useState("");

  async function load() {
    const scoped = window.localStorage.getItem("ai-brain-persona-id") || "";
    const scopedName = window.localStorage.getItem("ai-brain-persona-slug") || "";
    setPersonaId(scoped);
    setPersonaName(scopedName);
    const items = await api.leadImports(scoped || undefined);
    setImports(items);
    const open = new URLSearchParams(window.location.search).get("open");
    if (open) {
      const detail = await api.leadImport(open);
      setModal(detail);
      setExpanded(open);
    }
  }

  useEffect(() => {
    load().catch(console.error);
    const onPersonaChange = () => load().catch(console.error);
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  async function upload(file?: File) {
    if (!file) return;
    if (!personaId) {
      setNotice("Selecione uma persona no filtro Cliente antes de importar. Imports em 'Todos' nao sao permitidos.");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setUploading(true);
    setNotice("");
    setLastCreated(null);
    try {
      const result = await api.uploadLeadImport(file, personaId || undefined);
      await load();
      const stats = result?.batch?.stats || {};
      const created = Number(stats.created || 0);
      const updated = Number(stats.updated || 0);
      setLastCreated(created + updated);
      setNotice(
        `Importado: ${stats.valid || 0} validos · ${stats.with_phone || 0} com celular · ${created} criados · ${updated} atualizados · ${stats.email_only || 0} somente email · ${stats.invalid || 0} invalidos.`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Nao foi possivel importar o CSV.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const totals = imports.reduce(
    (acc, item) => {
      const stats = item.stats || {};
      acc.imports += 1;
      acc.total += Number(stats.valid || stats.total || 0);
      acc.withPhone += Number(stats.with_phone || 0);
      acc.emailOnly += Number(stats.email_only || 0);
      return acc;
    },
    { imports: 0, total: 0, withPhone: 0, emailOnly: 0 },
  );

  async function openFull(batchId: string) {
    const detail = await api.leadImport(batchId);
    setModal(detail);
  }

  async function deleteImport(batchId: string) {
    if (!batchId) return;
    if (!window.confirm("Excluir este grupo de leads da lista e do grafo?")) return;
    await api.deleteLeadImport(batchId);
    if (modal?.batch?.batch_id === batchId) setModal(null);
    if (new URLSearchParams(window.location.search).get("open") === batchId) {
      window.history.replaceState(null, "", "/leads/import");
    }
    await load();
  }

  return (
    <div className="lg-page-narrow relative flex min-h-[calc(100vh-132px)] flex-col gap-5 pb-20">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-obs-violet/10 text-obs-violet [border:1px_solid_var(--border-glass)]">
            <Table2 size={16} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">CRM</p>
            <h1 className="mt-1 text-xl font-semibold text-obs-text">Importar leads</h1>
          </div>
        </div>
        <span className="text-xs text-obs-subtle">{personaName ? `Persona: ${personaName}` : "Selecione uma persona"}</span>
      </header>

      {!personaId && (
        <div className="flex items-center gap-2 rounded-xl bg-obs-amber/10 px-3 py-2 text-sm text-obs-amber [border:1px_solid_rgb(var(--obs-amber)/0.3)]">
          <AlertCircle size={15} />
          Selecione um cliente/persona no topo da plataforma antes de importar leads.
        </div>
      )}

      <section className="grid gap-3 md:grid-cols-4">
        <Metric label="Imports" value={totals.imports} />
        <Metric label="Total de leads" value={totals.total} />
        <Metric label="Com celular" value={totals.withPhone} />
        <Metric label="Somente email" value={totals.emailOnly} />
      </section>

      {notice && (
        <div className="lg-card flex flex-col gap-1 text-sm text-obs-text">
          <span>{notice}</span>
          {!!lastCreated && (
            <span className="text-xs text-obs-subtle">
              {lastCreated} {lastCreated === 1 ? "lead criado/atualizado aparece" : "leads criados/atualizados aparecem"} agora em{" "}
              <Link href="/leads" className="text-obs-violet hover:underline">Leads</Link>.
            </span>
          )}
        </div>
      )}

      <div className="lg-table-shell overflow-hidden">
        {imports.length ? imports.map((item) => {
          const batchId = item.batch_id || item.event_id;
          const stats = item.stats || {};
          const open = expanded === batchId;
          return (
            <div key={batchId} className="[border-bottom:1px_solid_var(--border-glass-soft)] last:[border-bottom:0]">
              <div className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.04]">
                <button type="button" onClick={() => setExpanded(open ? null : batchId)} className="rounded p-1 text-obs-subtle hover:bg-white/5 hover:text-obs-text">
                  {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </button>
                <button type="button" onClick={() => setExpanded(open ? null : batchId)} className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-medium text-obs-text">{item.filename || "CSV importado"}</p>
                  <p className="mt-0.5 text-xs text-obs-faint">{item.created_at || item.finished_at || ""}</p>
                </button>
                <span className="text-xs text-obs-subtle">{stats.valid || 0} leads</span>
                <span className="lg-badge lg-badge-info">{stats.with_phone || 0} celular</span>
                <span className="lg-badge lg-badge-success">{(stats.created || 0) + (stats.updated || 0)} ok</span>
                {!!stats.invalid && <span className="lg-badge lg-badge-error">{stats.invalid} invalidas</span>}
                <button
                  type="button"
                  onClick={() => deleteImport(batchId)}
                  className="lg-btn lg-btn-danger"
                  title="Excluir grupo de leads"
                >
                  <X size={12} />
                </button>
              </div>
              {open && (
                <div className="px-4 py-3 [border-top:1px_solid_var(--border-glass-soft)]">
                  <ImportPreview rows={item.preview || []} />
                  <button
                    type="button"
                    onClick={() => openFull(batchId)}
                    className="lg-btn lg-btn-secondary mt-3"
                  >
                    Expandir todos os leads
                  </button>
                </div>
              )}
            </div>
          );
        }) : (
          <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
            <FileUp size={28} className="text-obs-faint" />
            <p className="text-sm text-obs-subtle">Nenhuma importacao encontrada.</p>
          </div>
        )}
      </div>

      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => upload(event.target.files?.[0])}
      />

      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={uploading || !personaId}
        className="fixed bottom-6 left-1/2 z-40 flex h-14 w-14 -translate-x-1/2 items-center justify-center rounded-full bg-obs-violet/25 text-obs-violet shadow-obs-node transition hover:bg-obs-violet/35 disabled:opacity-50 [border:1px_solid_rgb(var(--obs-violet)/0.45)]"
        title="Importar CSV"
      >
        {uploading ? <Loader2 size={22} className="animate-spin" /> : <Plus size={25} />}
      </button>

      {modal && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 p-5">
          <div className="modal-content drawer-right flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden">
            <div className="-mx-[22px] -mt-[22px] flex items-center justify-between px-5 py-4 [border-bottom:1px_solid_var(--border-glass-soft)]">
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">Importacao</p>
                <h2 className="mt-1 text-lg font-semibold text-obs-text">{modal.batch?.filename || "Leads importados"}</h2>
              </div>
              <button onClick={() => setModal(null)} className="rounded-lg p-2 text-obs-subtle hover:bg-white/5 hover:text-obs-text">
                <X size={18} />
              </button>
            </div>
            <div className="-mx-[22px] flex-1 overflow-y-auto px-5 py-5">
              <ImportPreview rows={modal.rows || []} full />
            </div>
            <div className="-mx-[22px] -mb-[22px] flex justify-end px-5 py-4 [border-top:1px_solid_var(--border-glass-soft)]">
              <button
                type="button"
                onClick={() => deleteImport(modal.batch?.batch_id)}
                className="lg-btn lg-btn-danger"
              >
                Excluir grupo de leads
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="lg-card">
      <p className="text-[10px] uppercase tracking-[0.16em] text-obs-faint">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-obs-text">{value}</p>
    </div>
  );
}

function ImportPreview({ rows, full = false }: { rows: any[]; full?: boolean }) {
  const visible = full ? rows : rows.filter((row) => row.status !== "invalid").slice(0, 5);
  return (
    <div className="lg-table-shell">
      <table className="lg-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Nome</th>
            <th>Celular</th>
            <th>Email</th>
            <th>Cidade</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={`${row.row_index}-${row.parsed?.lead_id || ""}`}>
              <td className="text-xs text-obs-faint">{row.row_index}</td>
              <td>{row.parsed?.nome || "-"}</td>
              <td className="font-mono text-xs text-obs-subtle">{row.parsed?.lead_id || "-"}</td>
              <td className="text-obs-subtle">{row.parsed?.email || "-"}</td>
              <td className="text-obs-subtle">{row.parsed?.cidade || "-"}</td>
              <td>
                <RowStatusBadge status={row.status} />
              </td>
            </tr>
          ))}
          {!visible.length && (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-sm text-obs-faint">Sem linhas validas para mostrar.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function RowStatusBadge({ status }: { status?: string }) {
  if (status === "invalid")     return <span className="lg-badge lg-badge-error">invalid</span>;
  if (status === "email_only")  return <span className="lg-badge lg-badge-warning">email_only</span>;
  if (status === "updated")     return <span className="lg-badge lg-badge-info">updated</span>;
  return <span className="lg-badge lg-badge-success">{status || "created"}</span>;
}
