"use client";

import { useEffect, useMemo, useState } from "react";
import { Settings2, X } from "lucide-react";
import { api } from "@/lib/api";

type Persona = { id: string; slug: string; name: string };
type Audience = { id: string; slug: string; name: string; persona_id: string; is_system?: boolean; source_type?: string };
type Membership = { id?: string; audience_id?: string; membership_type?: string; audience?: Audience };

export function ManageGroupModal({
  leadRef,
  leadName,
  currentPersonaId,
  currentMemberships,
  onClose,
  onDone,
}: {
  leadRef: number;
  leadName: string;
  currentPersonaId: string | null;
  currentMemberships: Membership[];
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [targetPersonaId, setTargetPersonaId] = useState<string>(currentPersonaId || "");
  const [audiences, setAudiences] = useState<Audience[]>([]);
  const [targetAudienceId, setTargetAudienceId] = useState<string>("");
  const [loadingAudiences, setLoadingAudiences] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me()
      .then((session) => {
        setPersonas((session?.personas || []) as Persona[]);
        setIsAdmin(session?.user?.role === "admin");
      })
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
        const current = currentMemberships.find(
          (membership) => membership.audience?.persona_id === targetPersonaId,
        )?.audience;
        const defaultPick = list.find((audience) => audience.id === current?.id) || list[0];
        setTargetAudienceId(defaultPick?.id || "");
      })
      .catch(() => setAudiences([]))
      .finally(() => setLoadingAudiences(false));
  }, [currentMemberships, targetPersonaId]);

  const sourceAudience = useMemo(() => {
    return currentMemberships.find((membership) => {
      const audience = membership.audience;
      return audience && audience.slug !== "import" && audience.source_type !== "import";
    })?.audience || null;
  }, [currentMemberships]);

  const targetAudience = audiences.find((a) => a.id === targetAudienceId) || null;
  const targetPersona = personas.find((p) => p.id === targetPersonaId) || null;

  const sameTarget =
    !!sourceAudience && !!targetAudience && sourceAudience.id === targetAudience.id;

  const submit = async () => {
    if (!targetAudience || !targetPersonaId || submitting) return;
    if (sameTarget) {
      setError("O lead ja esta nesse grupo.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.setLeadGroup(leadRef, {
        persona_id: targetPersonaId,
        audience_id: targetAudience.id,
        idempotency_key: `lead-group:${leadRef}:${crypto.randomUUID()}`,
        reason: "Grupo alterado pela interface de leads",
      });
      await onDone();
      onClose();
    } catch (e: any) {
      setError(e?.message || "Falha ao gerenciar grupo.");
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
            <h2 className="mt-1 text-base font-semibold text-obs-text">Gerenciar grupo</h2>
            <p className="mt-1 text-xs text-obs-subtle">{leadName}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar gerenciamento de grupo"
            className="rounded-lg p-1.5 text-obs-subtle hover:text-obs-text"
            style={{ background: "rgb(var(--glass-bg) / var(--glass-solid-hover))" }}
          >
            <X size={16} />
          </button>
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs text-obs-subtle">Persona destino</span>
          <select
            className="lg-input"
            value={targetPersonaId}
            onChange={(e) => setTargetPersonaId(e.target.value)}
            disabled={!isAdmin}
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
          <span className="text-xs text-obs-subtle">Grupo semantico</span>
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
            Alterar o grupo de <strong>{leadName}</strong>
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
            <Settings2 size={12} /> {submitting ? "Aplicando..." : "Confirmar grupo"}
          </button>
        </div>
      </div>
    </div>
  );
}
