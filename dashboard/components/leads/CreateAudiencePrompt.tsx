"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";

export function CreateAudiencePrompt({
  personaId,
  onClose,
  onCreated,
}: {
  personaId: string;
  onClose: () => void;
  onCreated: (audience: any) => void;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.createAudience({
        persona_id: personaId,
        name: trimmed,
        source_type: "manual",
      });
      onCreated(result.audience || result);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Falha ao criar audiencia.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-5">
      <div className="modal-content flex w-full max-w-md flex-col gap-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">CRM</p>
            <h2 className="mt-1 text-base font-semibold text-obs-text">Nova audiencia</h2>
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
          <span className="text-xs text-obs-subtle">Nome da audiencia</span>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") onClose();
            }}
            placeholder="Ex: VIP, Reativacao Outubro, Lista quente..."
            className="lg-input"
          />
        </label>

        {error && <p className="text-xs text-obs-rose">{error}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="lg-btn lg-btn-secondary">
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!name.trim() || submitting}
            className="lg-btn lg-btn-primary"
          >
            {submitting ? "Criando..." : "Criar audiencia"}
          </button>
        </div>
      </div>
    </div>
  );
}
