"use client";

import { useMemo, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";

type NoteRow = { key: string; value: string };

function noteRowsFromLead(lead: any): NoteRow[] {
  const note = (lead?.metadata?.commercial_note || {}) as Record<string, string>;
  return Object.entries(note)
    .filter(([key]) => key !== "updated_at" && key !== "source")
    .map(([key, value]) => ({ key, value: String(value ?? "") }));
}

export function LeadInfoModal({
  lead,
  onClose,
  onSaved,
}: {
  lead: any;
  onClose: () => void;
  onSaved: (updatedLead: any) => void | Promise<void>;
}) {
  const [nome, setNome] = useState(lead?.nome || "");
  const [interesseProduto, setInteresseProduto] = useState(lead?.interesse_produto || "");
  const [notes, setNotes] = useState<NoteRow[]>(() => noteRowsFromLead(lead));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      const result = await api.updateLeadInfo(Number(lead.id), {
        nome: trimmedName,
        interesse_produto: interesseProduto.trim(),
        commercial_note: commercialNote,
      });
      await onSaved(result?.lead || result);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Falha ao salvar informacoes do lead.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-5">
      <div className="modal-content flex w-full max-w-lg flex-col gap-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">CRM</p>
            <h2 className="mt-1 text-base font-semibold text-obs-text">Informacoes do lead</h2>
            {phone && <p className="mt-1 text-xs text-obs-subtle font-mono">{phone}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle hover:text-obs-text"
            style={{ background: "rgba(255,255,255,0.55)" }}
          >
            <X size={16} />
          </button>
        </div>

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
            <span className="text-xs text-obs-subtle">Nota comercial</span>
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
          {notes.map((row, index) => (
            <div key={index} className="flex items-center gap-2">
              <input
                className="lg-input flex-1"
                value={row.key}
                onChange={(e) => updateNoteRow(index, { key: e.target.value })}
                placeholder="campo (ex: vehicle_model)"
              />
              <input
                className="lg-input flex-[1.5]"
                value={row.value}
                onChange={(e) => updateNoteRow(index, { value: e.target.value })}
                placeholder="valor"
              />
              <button
                type="button"
                onClick={() => removeNoteRow(index)}
                className="rounded-lg p-1.5 text-obs-faint hover:text-obs-rose"
                title="Remover campo"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          <p className="text-[10px] text-obs-faint">
            Esses campos ficam vinculados ao lead e a IA passa a tratá-los como já respondidos — não pergunta de novo.
          </p>
        </div>

        {error && <p className="text-xs text-obs-rose">{error}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="lg-btn lg-btn-secondary">
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
      </div>
    </div>
  );
}
