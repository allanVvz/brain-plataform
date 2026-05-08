"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Share2, X } from "lucide-react";
import { api } from "@/lib/api";

type Persona = { id: string; slug: string; name: string };
type Audience = { id: string; slug: string; name: string; persona_id: string; is_system?: boolean };
type Membership = { id?: string; audience_id?: string; membership_type?: string; audience?: Audience };

export type MoveShareMode = "move" | "share";

export function MoveShareModal({
  leadRef,
  leadName,
  initialMode,
  currentPersonaId,
  currentMemberships,
  onClose,
  onDone,
}: {
  leadRef: number;
  leadName: string;
  initialMode: MoveShareMode;
  currentPersonaId: string | null;
  currentMemberships: Membership[];
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [mode, setMode] = useState<MoveShareMode>(initialMode);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [targetPersonaId, setTargetPersonaId] = useState<string>(currentPersonaId || "");
  const [audiences, setAudiences] = useState<Audience[]>([]);
  const [targetAudienceId, setTargetAudienceId] = useState<string>("");
  const [loadingAudiences, setLoadingAudiences] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me()
      .then((session) => setPersonas((session?.personas || []) as Persona[]))
      .catch(() => setPersonas([]));
  }, []);

  useEffect(() => {
    if (!targetPersonaId) {
      setAudiences([]);
      setTargetAudienceId("");
      return;
    }
    setLoadingAudiences(true);
    api.audiences(targetPersonaId)
      .then((rows) => {
        const list = (rows || []) as Audience[];
        setAudiences(list);
        const defaultPick = list.find((a) => a.slug === "import") || list[0];
        if (defaultPick) setTargetAudienceId(defaultPick.id);
      })
      .catch(() => setAudiences([]))
      .finally(() => setLoadingAudiences(false));
  }, [targetPersonaId]);

  const sourceAudience = useMemo(() => {
    const primary = currentMemberships.find((m) => m.membership_type === "primary");
    return primary?.audience || currentMemberships[0]?.audience || null;
  }, [currentMemberships]);

  const targetAudience = audiences.find((a) => a.id === targetAudienceId) || null;
  const targetPersona = personas.find((p) => p.id === targetPersonaId) || null;

  const sameTarget =
    !!sourceAudience && !!targetAudience && sourceAudience.id === targetAudience.id;

  const submit = async () => {
    if (!targetAudience || !targetPersonaId || submitting) return;
    if (sameTarget && mode === "move") {
      setError("O lead ja esta nessa audiencia.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        target_persona_id: targetPersonaId,
        target_audience_id: targetAudience.id,
        ...(sourceAudience?.id ? { source_audience_id: sourceAudience.id } : {}),
      };
      if (mode === "move") await api.moveLead(leadRef, body);
      else await api.shareLead(leadRef, body);
      await onDone();
      onClose();
    } catch (e: any) {
      setError(e?.message || "Falha ao mover/compartilhar.");
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
            <h2 className="mt-1 text-base font-semibold text-obs-text">
              {mode === "move" ? "Mover lead" : "Compartilhar lead"}
            </h2>
            <p className="mt-1 text-xs text-obs-subtle">{leadName}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle hover:text-obs-text"
            style={{ background: "rgba(255,255,255,0.55)" }}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setMode("move")}
            className={`lg-btn ${mode === "move" ? "lg-btn-primary" : "lg-btn-secondary"}`}
          >
            <ArrowRight size={12} /> Mover
          </button>
          <button
            type="button"
            onClick={() => setMode("share")}
            className={`lg-btn ${mode === "share" ? "lg-btn-primary" : "lg-btn-secondary"}`}
          >
            <Share2 size={12} /> Compartilhar
          </button>
          <span className="ml-auto text-[11px] text-obs-faint">
            {mode === "move" ? "remove da audiencia atual" : "mantem nas audiencias atuais"}
          </span>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs text-obs-subtle">Persona destino</span>
          <select
            className="lg-input"
            value={targetPersonaId}
            onChange={(e) => setTargetPersonaId(e.target.value)}
          >
            <option value="">Selecione uma persona</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs text-obs-subtle">Audiencia destino</span>
          <select
            className="lg-input"
            value={targetAudienceId}
            onChange={(e) => setTargetAudienceId(e.target.value)}
            disabled={!targetPersonaId || loadingAudiences}
          >
            {!targetPersonaId && <option value="">Selecione uma persona primeiro</option>}
            {loadingAudiences && <option>Carregando audiencias...</option>}
            {!loadingAudiences &&
              audiences.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.is_system ? " (system)" : ""}
                </option>
              ))}
          </select>
        </label>

        <div className="rounded-xl bg-obs-violet/8 px-3 py-2.5 text-xs text-obs-text [border:1px_solid_var(--border-glass)]">
          <p>
            {mode === "move" ? "Mover " : "Compartilhar "} <strong>{leadName}</strong>
            {sourceAudience && (
              <>
                {" de "}
                <strong>{sourceAudience.name}</strong>
              </>
            )}
            {targetAudience && targetPersona && (
              <>
                {" para "}
                <strong>{targetAudience.name}</strong> em <strong>{targetPersona.name}</strong>.
              </>
            )}
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
            disabled={!targetAudienceId || submitting}
            className="lg-btn lg-btn-primary"
          >
            {submitting ? "Aplicando..." : mode === "move" ? "Confirmar mover" : "Confirmar compartilhar"}
          </button>
        </div>
      </div>
    </div>
  );
}
