"use client";

import { useMemo, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";

type NoteRow = { key: string; value: string };

// Field keys are graph-driven (whatever the persona's contract declares),
// not a fixed enum — this is a display convenience for the common ones,
// with a readable fallback (snake_case -> Title Case) for anything else,
// never a raw variable name shown as if it were the primary label.
const FIELD_LABELS: Record<string, string> = {
  nome_cliente: "Nome do cliente",
  servico: "Serviço",
  modelo_veiculo: "Modelo do veículo",
  vehicle_year: "Ano do veículo",
  vehicle_color: "Cor do veículo",
  vehicle_size: "Porte do veículo",
  objective: "Objetivo",
  can_visit_in_person: "Pode visitar presencialmente",
  condicao: "Condição do veículo",
  data_desejada: "Data desejada",
  janela_horario: "Janela de horário",
};

function humanizeFieldKey(key: string): string {
  if (!key) return "Novo campo";
  return FIELD_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function noteRowsFromLead(lead: any): NoteRow[] {
  const note = (lead?.metadata?.commercial_note || {}) as Record<string, string>;
  return Object.entries(note)
    .filter(([key]) => key !== "updated_at" && key !== "source")
    .map(([key, value]) => ({ key, value: String(value ?? "") }));
}

export type LeadInfoUpdateBody = {
  nome: string;
  interesse_produto: string;
  commercial_note: Record<string, string>;
};

export function LeadInfoModal({
  lead,
  onClose,
  onSaved,
  onSubmit,
}: {
  lead: any;
  onClose: () => void;
  onSaved: (updatedLead: any) => void | Promise<void>;
  /** Defaults to the admin PATCH /leads/{id} endpoint (api.updateLeadInfo).
   * Pass this to target a different surface, e.g. the client portal's
   * own PATCH /portal/leads/{id} (api.updatePortalLead). */
  onSubmit?: (leadRef: number, body: LeadInfoUpdateBody) => Promise<any>;
}) {
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [nome, setNome] = useState(lead?.nome || "");
  const [interesseProduto, setInteresseProduto] = useState(lead?.interesse_produto || "");
  const [notes, setNotes] = useState<NoteRow[]>(() => noteRowsFromLead(lead));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const viewNotes = useMemo(() => noteRowsFromLead(lead), [lead]);

  const phone = useMemo(() => lead?.telefone || lead?.lead_id || "", [lead]);

  const updateNoteRow = (index: number, patch: Partial<NoteRow>) => {
    setNotes((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeNoteRow = (index: number) => {
    setNotes((prev) => prev.filter((_, i) => i !== index));
  };

  const addNoteRow = () => {
    setNotes((prev) => [...prev, { key: "", value: "" }]);
  };

  const submit = async () => {
    if (submitting) return;
    const trimmedName = nome.trim();
    if (!trimmedName) {
      setError("Nome nao pode ser vazio.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const commercialNote: Record<string, string> = {};
      for (const row of notes) {
        const key = row.key.trim();
        const value = row.value.trim();
        if (key && value) commercialNote[key] = value;
      }
      const body: LeadInfoUpdateBody = {
        nome: trimmedName,
        interesse_produto: interesseProduto.trim(),
        commercial_note: commercialNote,
      };
      const result = onSubmit
        ? await onSubmit(Number(lead.id), body)
        : await api.updateLeadInfo(Number(lead.id), body);
      await onSaved(result?.lead || result);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Falha ao salvar informacoes do lead.");
    } finally {
      setSubmitting(false);
    }
  };

  const startEdit = () => {
    setNome(lead?.nome || "");
    setInteresseProduto(lead?.interesse_produto || "");
    setNotes(noteRowsFromLead(lead));
    setError(null);
    setMode("edit");
  };

  const cancelEdit = () => {
    setError(null);
    setMode("view");
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-5">
      <div className="modal-content flex w-full max-w-lg max-h-[90vh] flex-col gap-5 overflow-y-auto">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">CRM</p>
            <h2 className="mt-1 text-base font-semibold text-obs-text">Informacoes do lead</h2>
            {phone && <p className="mt-1 text-xs text-obs-subtle font-mono">{phone}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle hover:text-obs-text"
            style={{ background: "rgb(var(--glass-solid-bg) / var(--glass-solid-hover))" }}
          >
            <X size={16} />
          </button>
        </div>

        {mode === "view" ? (
          <>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-obs-subtle">Nome</span>
              <p className="text-sm font-medium text-obs-text">{lead?.nome || "—"}</p>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-obs-subtle">Produto de interesse</span>
              <p className="text-sm font-medium text-obs-text">{lead?.interesse_produto || "—"}</p>
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-xs text-obs-subtle">Nota comercial</span>
              {viewNotes.length === 0 ? (
                <p className="text-[11px] text-obs-faint">Nenhuma informação registrada ainda.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {viewNotes.map((row, index) => (
                    <div
                      key={index}
                      className="rounded-xl p-2.5"
                      style={{ border: "1px solid var(--border-glass)" }}
                    >
                      <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-obs-violet">
                        {humanizeFieldKey(row.key)}
                      </span>
                      <p className="mt-1 text-sm font-medium text-obs-text">{row.value || "—"}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2">
              <button type="button" onClick={startEdit} className="lg-btn lg-btn-primary">
                <Pencil size={12} /> Editar
              </button>
            </div>
          </>
        ) : (
          <>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-obs-subtle">Nome</span>
              <input
                className="lg-input"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Nome do cliente"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-obs-subtle">Produto de interesse</span>
              <input
                className="lg-input"
                value={interesseProduto}
                onChange={(e) => setInteresseProduto(e.target.value)}
                placeholder="Ex: chapeacao, vitrificacao..."
              />
            </label>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-obs-subtle">
                  Nota comercial{notes.length > 0 && <span className="text-obs-faint"> · {notes.length}</span>}
                </span>
                <button
                  type="button"
                  onClick={addNoteRow}
                  className="lg-btn lg-btn-secondary text-[11px]"
                >
                  <Plus size={11} /> Campo
                </button>
              </div>
              {notes.length === 0 && (
                <p className="text-[11px] text-obs-faint">
                  Nenhum campo ainda. Adicione o que a IA ja deve considerar como sabido (ex: modelo do veiculo, data desejada).
                </p>
              )}
              <div className="flex flex-col gap-2">
                {notes.map((row, index) => (
                  <div
                    key={index}
                    className="rounded-xl p-2.5"
                    style={{ border: "1px solid var(--border-glass)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-obs-violet">
                        {humanizeFieldKey(row.key)}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeNoteRow(index)}
                        className="shrink-0 rounded p-1 text-obs-faint hover:text-obs-rose"
                        title="Remover campo"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <input
                        className="lg-input w-36 shrink-0 text-[11px] text-obs-subtle"
                        value={row.key}
                        onChange={(e) => updateNoteRow(index, { key: e.target.value })}
                        placeholder="campo (ex: vehicle_model)"
                      />
                      <input
                        className="lg-input flex-1 font-medium"
                        value={row.value}
                        onChange={(e) => updateNoteRow(index, { value: e.target.value })}
                        placeholder="valor"
                      />
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-obs-faint">
                Esses campos ficam vinculados ao lead e a IA passa a tratá-los como já respondidos — não pergunta de novo.
              </p>
            </div>

            {error && <p className="text-xs text-obs-rose">{error}</p>}

            <div className="flex justify-end gap-2">
              <button type="button" onClick={cancelEdit} className="lg-btn lg-btn-secondary">
                Cancelar
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting}
                className="lg-btn lg-btn-primary"
              >
                {submitting ? "Salvando..." : "Salvar"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
