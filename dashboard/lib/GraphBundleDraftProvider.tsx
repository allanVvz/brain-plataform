"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { GraphBundleDraftOperation, GraphBundleDraftSnapshot } from "@/lib/graph-bundle-v3";

type Surface = "graph" | "kb" | "messages" | "api" | "import";
type Source = { surface: Surface; response_message_id?: string; source_ref?: string };

interface ReviewEvidence {
  plan_ref: string;
  validation_ref: string;
  runtime_checksum: string;
  validation_errors: string[];
  plan: Record<string, any>;
  diff: Record<string, any>;
  previews: Record<string, any>;
  publish_key: string;
}

interface DraftContextValue {
  draft: GraphBundleDraftSnapshot | null;
  busy: boolean;
  error: string;
  review: ReviewEvidence | null;
  ensureDraft: (personaSlug: string, activeChecksum: string, source: Source) => Promise<GraphBundleDraftSnapshot>;
  mutate: (operations: GraphBundleDraftOperation[], reason: string, source: Source) => Promise<GraphBundleDraftSnapshot>;
  reviewDraft: () => Promise<ReviewEvidence>;
  publishDraft: (reason: string) => Promise<any>;
  clearDraft: () => void;
}

const DraftContext = createContext<DraftContextValue | null>(null);
const storageKey = (personaSlug: string) => `ai-brain-graph-draft-v3:${personaSlug}`;

export function GraphBundleDraftProvider({ children }: { children: React.ReactNode }) {
  const [draft, setDraft] = useState<GraphBundleDraftSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<ReviewEvidence | null>(null);
  const draftRef = useRef<GraphBundleDraftSnapshot | null>(null);

  const remember = useCallback((next: GraphBundleDraftSnapshot | null) => {
    draftRef.current = next;
    setDraft(next);
    setReview(null);
    if (next && typeof window !== "undefined") sessionStorage.setItem(storageKey(next.persona_slug), next.draft_ref);
  }, []);

  const ensureDraft = useCallback(async (personaSlug: string, activeChecksum: string, source: Source) => {
    if (draftRef.current?.persona_slug === personaSlug && draftRef.current.state !== "published") return draftRef.current;
    setBusy(true); setError("");
    try {
      const savedRef = typeof window !== "undefined" ? sessionStorage.getItem(storageKey(personaSlug)) : null;
      if (savedRef) {
        try {
          const saved = await api.graphBundleDraft(savedRef);
          if (saved.persona_slug === personaSlug && saved.state !== "published") {
            remember(saved);
            return saved;
          }
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 404) throw caught;
          sessionStorage.removeItem(storageKey(personaSlug));
        }
      }
      const created = await api.graphBundleCreateDraft({
        persona_slug: personaSlug,
        expected_active_checksum: activeChecksum,
        reuse_open: true,
        reason: "Edição unificada pelo dashboard",
        source,
        idempotency_key: crypto.randomUUID(),
      });
      remember(created);
      return created;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Não foi possível abrir o rascunho.";
      setError(message);
      throw caught;
    } finally { setBusy(false); }
  }, [remember]);

  const mutate = useCallback(async (operations: GraphBundleDraftOperation[], reason: string, source: Source) => {
    const current = draftRef.current;
    if (!current) throw new Error("Abra um rascunho antes de editar.");
    setBusy(true); setError("");
    try {
      const updated = await api.graphBundlePatchDraft(current.draft_ref, {
        expected_revision: current.revision,
        expected_draft_checksum: current.draft_checksum,
        operations, reason, source,
        idempotency_key: crypto.randomUUID(),
      });
      remember(updated);
      return updated;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        const latest = await api.graphBundleDraft(current.draft_ref);
        remember(latest);
        setError("O rascunho mudou em outra tela. Recarregamos a revisão atual; confira e tente novamente.");
      } else setError(caught instanceof Error ? caught.message : "Falha ao salvar o rascunho.");
      throw caught;
    } finally { setBusy(false); }
  }, [remember]);

  const reviewDraft = useCallback(async () => {
    const current = draftRef.current;
    if (!current) throw new Error("Abra um rascunho antes de revisar.");
    setBusy(true); setError("");
    try {
      const seal = { expected_revision: current.revision, expected_draft_checksum: current.draft_checksum };
      const [plan, validation, diff, agent, catalog, site] = await Promise.all([
        api.graphBundleDraftPlan(current.draft_ref, { ...seal, idempotency_key: crypto.randomUUID() }),
        api.graphBundleDraftValidate(current.draft_ref, { ...seal, idempotency_key: crypto.randomUUID() }),
        api.graphBundleDraftDiff(current.draft_ref),
        api.graphBundleDraftPreview(current.draft_ref, "agent"),
        api.graphBundleDraftPreview(current.draft_ref, "catalog"),
        api.graphBundleDraftPreview(current.draft_ref, "site"),
      ]);
      const next = {
        plan_ref: plan.plan_ref,
        validation_ref: validation.validation_ref,
        runtime_checksum: validation.runtime_checksum || plan.runtime_checksum,
        validation_errors: validation.validation_errors || [],
        plan,
        diff,
        previews: { agent, catalog, site },
        publish_key: crypto.randomUUID(),
      };
      setReview(next);
      return next;
    } finally { setBusy(false); }
  }, []);

  const publishDraft = useCallback(async (reason: string) => {
    const current = draftRef.current;
    if (!current || !review) throw new Error("Revise o rascunho antes de publicar.");
    if (review.validation_errors.length) throw new Error("Corrija os erros antes de publicar.");
    setBusy(true); setError("");
    try {
      const result = await api.graphBundleDraftPublish(current.draft_ref, {
        expected_revision: current.revision,
        expected_draft_checksum: current.draft_checksum,
        plan_ref: review.plan_ref,
        validation_ref: review.validation_ref,
        approved_runtime_checksum: review.runtime_checksum,
        confirmation: true,
        reason,
        idempotency_key: review.publish_key,
      });
      remember({ ...current, state: "published" });
      sessionStorage.removeItem(storageKey(current.persona_slug));
      return result;
    } finally { setBusy(false); }
  }, [remember, review]);

  const value = useMemo(() => ({ draft, busy, error, review, ensureDraft, mutate, reviewDraft, publishDraft, clearDraft: () => remember(null) }), [draft, busy, error, review, ensureDraft, mutate, reviewDraft, publishDraft, remember]);
  return <DraftContext.Provider value={value}>{children}</DraftContext.Provider>;
}

export function useGraphBundleDraft() {
  const value = useContext(DraftContext);
  if (!value) throw new Error("useGraphBundleDraft must be used inside GraphBundleDraftProvider");
  return value;
}
