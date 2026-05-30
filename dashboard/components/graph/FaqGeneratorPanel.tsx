"use client";
import { useState } from "react";
import { Sparkles, RefreshCw, Check, X, Loader2, Save } from "lucide-react";
import { api } from "@/lib/api";
import {
  acceptedPayload,
  clampFaqCount,
  defaultFaqCount,
  toEditableSuggestions,
  type FaqSuggestion,
} from "@/lib/faq";

interface FaqGeneratorPanelProps {
  node: any;
  personaSlug?: string;
  sessionId?: string | null;
  onSaved?: () => void | Promise<any>;
}

/**
 * "Gerar" panel. Functional only on FAQ nodes: it asks Sofia's
 * adaptar_faqs_universais_ao_grafo tool (which reads the whole branch markdown)
 * for editable suggestions, then appends the accepted ones to THIS FAQ's own
 * Markdown body — never creating a new node — keeping it pending/draft. Other
 * node types show a disabled placeholder.
 */
export default function FaqGeneratorPanel({ node, personaSlug, sessionId, onSaved }: FaqGeneratorPanelProps) {
  const nodeType = String(node?.data?.node_type || node?.data?.content_type || "").toLowerCase();
  const isFaq = nodeType === "faq";

  const [count, setCount] = useState<number>(defaultFaqCount(node));
  const [suggestions, setSuggestions] = useState<FaqSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const nodeId = String(node?.id || "");
  const hasGenerated = suggestions.length > 0;

  if (!isFaq) {
    return (
      <div className="rounded-xl border border-white/08 bg-white/[0.02] p-3">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles size={13} className="text-obs-faint" />
          <span className="text-[11px] font-semibold uppercase tracking-wide text-obs-faint">Gerar</span>
        </div>
        <p className="text-[10px] text-obs-faint">
          Geração por IA para este tipo de node será ativada em breve.
        </p>
      </div>
    );
  }

  async function generate() {
    setLoading(true);
    setError(null);
    setDone(null);
    try {
      const resp = await api.sofiaFaqGenerate({
        persona_slug: personaSlug,
        session_id: sessionId || null,
        selected_node_id: nodeId || null,
        count: clampFaqCount(count),
      });
      const raw = resp?.faq_suggestions || [];
      if (!raw.length) {
        setError(resp?.sofia_message || "Sofia não conseguiu gerar perguntas para este node.");
        setSuggestions([]);
        return;
      }
      setSuggestions(toEditableSuggestions(raw));
    } catch (e: any) {
      setError(e?.message || "Falha ao gerar FAQs.");
    } finally {
      setLoading(false);
    }
  }

  function patch(index: number, next: Partial<FaqSuggestion>) {
    setSuggestions((prev) => prev.map((s, i) => (i === index ? { ...s, ...next } : s)));
  }

  async function save() {
    const accepted = acceptedPayload(suggestions);
    if (!accepted.length) {
      setError("Aceite ao menos uma sugestão antes de salvar.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.sofiaFaqAppend({
        persona_slug: personaSlug,
        faq_node_id: nodeId,
        suggestions: accepted,
      });
      setDone(`${accepted.length} pergunta(s) adicionadas a este FAQ (rascunho). Aprove para enviar ao Embedded.`);
      setSuggestions([]);
      await onSaved?.();
    } catch (e: any) {
      setError(e?.message || "Falha ao salvar no FAQ.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-obs-violet/25 bg-obs-violet/[0.06] p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles size={13} className="text-obs-violet" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-obs-violet">Gerar</span>
      </div>

      <div className="flex items-center gap-2">
        <label className="text-[10px] text-obs-subtle">Qtd</label>
        <input
          type="number"
          min={1}
          max={20}
          value={count}
          onChange={(e) => setCount(clampFaqCount(e.target.value))}
          className="w-14 bg-obs-base border border-white/10 rounded-md px-2 py-1 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
        />
        <button
          type="button"
          onClick={generate}
          disabled={loading}
          className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-obs-violet/35 bg-obs-violet/15 px-2 py-1.5 text-[11px] font-medium text-obs-text hover:bg-obs-violet/25 disabled:opacity-50"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : hasGenerated ? <RefreshCw size={11} /> : <Sparkles size={11} />}
          {hasGenerated ? "Gerar novamente" : "Gerar"}
        </button>
      </div>

      {error && <p className="text-[10px] text-obs-rose">{error}</p>}
      {done && <p className="text-[10px] text-emerald-400">{done}</p>}

      {hasGenerated && (
        <div className="space-y-2">
          {suggestions.map((s, i) => (
            <div
              key={i}
              className={`rounded-lg border p-2 space-y-1.5 transition-colors ${
                s.accepted ? "border-emerald-400/30 bg-emerald-500/[0.06]" : "border-white/08 bg-white/[0.02] opacity-60"
              }`}
            >
              <div className="flex items-start gap-1.5">
                <textarea
                  value={s.question}
                  onChange={(e) => patch(i, { question: e.target.value })}
                  rows={1}
                  className="flex-1 bg-transparent text-[11px] font-medium text-obs-text resize-y focus:outline-none"
                  placeholder="Pergunta"
                />
                <button
                  type="button"
                  onClick={() => patch(i, { accepted: !s.accepted })}
                  title={s.accepted ? "Rejeitar" : "Aceitar"}
                  className={`shrink-0 rounded-md border p-1 ${
                    s.accepted
                      ? "border-emerald-400/40 text-emerald-400 hover:bg-emerald-500/10"
                      : "border-white/15 text-obs-faint hover:text-obs-text"
                  }`}
                >
                  {s.accepted ? <Check size={11} /> : <X size={11} />}
                </button>
              </div>
              <textarea
                value={s.answer}
                onChange={(e) => patch(i, { answer: e.target.value })}
                rows={2}
                className="w-full bg-obs-base/60 border border-white/08 rounded-md px-2 py-1 text-[10px] text-obs-subtle resize-y focus:outline-none focus:border-obs-violet/40"
                placeholder="Resposta"
              />
            </div>
          ))}
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-300/30 bg-emerald-500/15 px-2 py-1.5 text-[11px] font-medium text-emerald-50 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            Salvar no FAQ (rascunho)
          </button>
        </div>
      )}
    </div>
  );
}
