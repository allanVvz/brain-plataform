"use client";
import { useMemo, useState } from "react";
import {
  X,
  AlertTriangle,
  Repeat,
  Ban,
  CircleAlert,
  CheckCircle2,
  Lightbulb,
  RefreshCcw,
  Edit3,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  MessageCircle,
} from "lucide-react";
import type {
  PlanDiagnostic,
  PlanDiagnosticNode,
  PlanDiagnosticNodeStatus,
  PlanDiagnosticRootCause,
  SofiaQuestion,
  SofiaQuestionOption,
} from "./diagnosticTypes";

interface Props {
  diagnostic: PlanDiagnostic;
  onClose: () => void;
  onEdit?: () => void;
  onRegenerate?: () => void;
}

const STATUS_ORDER: PlanDiagnosticNodeStatus[] = [
  "cycle",
  "orphan",
  "error",
  "warning",
  "valid",
];

const STATUS_STYLE: Record<PlanDiagnosticNodeStatus, { label: string; classes: string; chip: string; icon: any }> = {
  valid: {
    label: "valido",
    classes: "border-emerald-300/40 bg-emerald-500/8",
    chip: "bg-emerald-500/15 text-emerald-700 border-emerald-400/40",
    icon: CheckCircle2,
  },
  warning: {
    label: "atencao",
    classes: "border-amber-300/40 bg-amber-500/10",
    chip: "bg-amber-500/15 text-amber-700 border-amber-400/40",
    icon: AlertTriangle,
  },
  error: {
    label: "erro bloqueante",
    classes: "border-red-400/40 bg-red-500/10",
    chip: "bg-red-500/15 text-red-700 border-red-400/40",
    icon: Ban,
  },
  cycle: {
    label: "ciclo",
    classes: "border-purple-400/40 bg-purple-500/10",
    chip: "bg-purple-500/15 text-purple-700 border-purple-400/40",
    icon: Repeat,
  },
  orphan: {
    label: "orfao",
    classes: "border-slate-400/40 bg-slate-500/10",
    chip: "bg-slate-500/15 text-slate-700 border-slate-400/40",
    icon: CircleAlert,
  },
};

const TREE_ORDER = [
  "persona",
  "brand",
  "briefing",
  "campaign",
  "audience",
  "product",
  "offer",
  "copy",
  "faq",
  "asset",
  "rule",
  "tone",
];

function NodeCard({ node }: { node: PlanDiagnosticNode }) {
  const style = STATUS_STYLE[node.status] || STATUS_STYLE.warning;
  const Icon = style.icon;
  return (
    <div className={`rounded-lg border p-2.5 ${style.classes}`}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[10px] font-mono text-obs-faint">
          entry[{node.entry_index}]
        </span>
        <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${style.chip}`}>
          <Icon size={10} />
          {style.label}
        </span>
      </div>
      <div className="flex items-center gap-2 mb-1">
        <span className="rounded border border-white/15 bg-obs-base px-1.5 py-0.5 text-[10px] font-semibold text-obs-text">
          {node.type || "?"}
        </span>
        <p className="text-[11px] font-semibold text-obs-text truncate flex-1">
          {node.title || node.slug || "(sem titulo)"}
        </p>
      </div>
      <p className="text-[10px] font-mono text-obs-faint truncate">slug: {node.slug || "(sem slug)"}</p>
      {node.parent_slug ? (
        <p className="text-[10px] text-obs-subtle mt-1">
          parent atual: <span className="font-mono">{node.parent_slug}</span>
          {node.parent_type ? <span className="text-obs-faint"> ({node.parent_type})</span> : <span className="text-red-600"> (nao encontrado)</span>}
        </p>
      ) : (
        <p className="text-[10px] text-obs-faint mt-1">sem parent declarado</p>
      )}
      {node.expected_parent_types.length > 0 && node.status !== "valid" && (
        <p className="text-[10px] text-obs-subtle">
          parent esperado: <span className="font-mono">{node.expected_parent_types.join(" | ")}</span>
        </p>
      )}
      {node.issues.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {node.issues.slice(0, 3).map((issue, idx) => (
            <li key={`${node.entry_index}-issue-${idx}`} className="text-[10px] text-red-700">- {issue}</li>
          ))}
        </ul>
      )}
      {node.suggested_action && (
        <p className="mt-1.5 inline-flex items-center gap-1 rounded border border-blue-400/40 bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-700">
          <Lightbulb size={10} />
          {node.suggested_action}
        </p>
      )}
    </div>
  );
}

function SofiaQuestionCard({
  question,
  index,
  onOptionSelect,
}: {
  question: SofiaQuestion;
  index: number;
  onOptionSelect?: (q: SofiaQuestion, opt: SofiaQuestionOption) => void;
}) {
  const [showTech, setShowTech] = useState(false);
  return (
    <div className="rounded-lg border border-blue-300/40 bg-blue-500/8 p-3">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-start gap-1.5">
          <span className="inline-flex items-center justify-center rounded-full bg-blue-500/15 border border-blue-400/40 text-blue-700 text-[10px] font-mono font-semibold w-5 h-5 shrink-0">
            {index}
          </span>
          <h4 className="text-[12px] font-semibold text-obs-text leading-snug">
            {question.human_summary}
          </h4>
        </div>
        {question.affected_type && (
          <span className="shrink-0 rounded border border-white/15 bg-obs-base px-1.5 py-0.5 text-[10px] font-semibold text-obs-text">
            {question.affected_type}
          </span>
        )}
      </div>
      {question.probable_cause && (
        <p className="text-[11px] text-obs-subtle mb-2 leading-snug">
          {question.probable_cause}
        </p>
      )}
      {question.question && (
        <p className="text-[12px] font-medium text-obs-text mb-2 inline-flex items-start gap-1">
          <HelpCircle size={12} className="mt-0.5 shrink-0 text-blue-700" />
          <span>{question.question}</span>
        </p>
      )}
      {question.options.length > 0 && (
        <ul className="space-y-1 mb-2">
          {question.options.map((opt, idx) => (
            <li key={`${question.kind}-opt-${idx}`}>
              <button
                type="button"
                onClick={() => onOptionSelect?.(question, opt)}
                className="w-full text-left rounded border border-white/20 bg-obs-base px-2 py-1 text-[11px] text-obs-text hover:bg-blue-500/10 hover:border-blue-400/40 transition"
              >
                <span className="font-mono text-obs-faint mr-1.5">{String.fromCharCode(65 + idx)}.</span>
                {opt.label}
              </button>
            </li>
          ))}
        </ul>
      )}
      {question.technical_error && (
        <div className="mt-1">
          <button
            type="button"
            onClick={() => setShowTech((v) => !v)}
            className="inline-flex items-center gap-1 text-[10px] text-obs-faint hover:text-obs-text"
          >
            {showTech ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            detalhes tecnicos
          </button>
          {showTech && (
            <pre className="mt-1 whitespace-pre-wrap font-mono text-[10px] text-obs-faint bg-obs-base/60 border border-white/10 rounded px-2 py-1">
              {question.technical_error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function RootCauseCard({ cause }: { cause: PlanDiagnosticRootCause }) {
  return (
    <div className="rounded-lg border border-red-400/30 bg-red-500/8 p-3">
      <div className="flex items-center justify-between gap-2 mb-1">
        <h4 className="text-[12px] font-semibold text-red-800">{cause.title}</h4>
        <span className="text-[10px] rounded border border-red-400/40 bg-red-500/15 px-1.5 py-0.5 text-red-700 font-mono">
          {cause.affected_entry_indexes.length || cause.raw_messages.length} afetada(s)
        </span>
      </div>
      {cause.description && (
        <p className="text-[11px] text-obs-subtle mb-1.5">{cause.description}</p>
      )}
      {cause.affected_entry_indexes.length > 0 && (
        <p className="text-[10px] font-mono text-obs-faint mb-1.5">
          entries: {cause.affected_entry_indexes.slice(0, 12).map((i) => `[${i}]`).join(" ")}
          {cause.affected_entry_indexes.length > 12 ? ` ... (+${cause.affected_entry_indexes.length - 12})` : ""}
        </p>
      )}
      {cause.suggested_repair && (
        <p className="inline-flex items-start gap-1 rounded border border-blue-400/40 bg-blue-500/10 px-1.5 py-1 text-[10px] text-blue-700">
          <Lightbulb size={10} className="mt-0.5 shrink-0" />
          <span>{cause.suggested_repair}</span>
        </p>
      )}
    </div>
  );
}

export default function BlockedPlanDiagnosticModal({ diagnostic, onClose, onEdit, onRegenerate }: Props) {
  const grouped = useMemo(() => {
    const byStatus: Record<PlanDiagnosticNodeStatus, PlanDiagnosticNode[]> = {
      valid: [],
      warning: [],
      error: [],
      cycle: [],
      orphan: [],
    };
    for (const node of diagnostic.nodes) {
      (byStatus[node.status] || byStatus.warning).push(node);
    }
    for (const key of Object.keys(byStatus) as PlanDiagnosticNodeStatus[]) {
      byStatus[key].sort((a, b) => {
        const ai = TREE_ORDER.indexOf(a.type);
        const bi = TREE_ORDER.indexOf(b.type);
        const ax = ai === -1 ? 999 : ai;
        const bx = bi === -1 ? 999 : bi;
        if (ax !== bx) return ax - bx;
        return a.entry_index - b.entry_index;
      });
    }
    return byStatus;
  }, [diagnostic.nodes]);

  const summary = diagnostic.summary;
  const summaryChips: Array<{ label: string; value: number; cls: string }> = [
    { label: "entradas", value: summary.entry_count, cls: "border-white/15 bg-obs-base text-obs-text" },
    { label: "validas", value: summary.valid_count, cls: "border-emerald-400/40 bg-emerald-500/10 text-emerald-700" },
    { label: "erros", value: summary.error_count, cls: "border-red-400/40 bg-red-500/10 text-red-700" },
    { label: "ciclos", value: summary.cycle_count, cls: "border-purple-400/40 bg-purple-500/10 text-purple-700" },
    { label: "orfas", value: summary.orphan_count, cls: "border-slate-400/40 bg-slate-500/10 text-slate-700" },
    { label: "warnings", value: summary.warning_count, cls: "border-amber-400/40 bg-amber-500/10 text-amber-700" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-6xl max-h-[92vh] flex flex-col rounded-2xl border border-white/15 shadow-xl"
        style={{ background: "rgba(255,255,255,0.96)" }}
      >
        <header className="flex items-center justify-between gap-3 border-b border-white/15 px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-obs-text flex items-center gap-2">
              <Ban size={14} className="text-red-600" />
              Plano precisa de decisoes da Sofia
            </h2>
            <p className="text-[11px] text-obs-subtle">
              Cada bloqueio virou uma pergunta com opcoes. Detalhes tecnicos ficam disponiveis ao expandir.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/20 bg-obs-base px-2 py-1 text-obs-text hover:bg-white/10"
            aria-label="Fechar"
          >
            <X size={14} />
          </button>
        </header>

        <div className="flex flex-wrap gap-1.5 px-5 py-3 border-b border-white/10">
          {summaryChips.map((chip) => (
            <span
              key={chip.label}
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] ${chip.cls}`}
            >
              <span className="font-mono font-semibold">{chip.value}</span>
              <span>{chip.label}</span>
            </span>
          ))}
          <span className="ml-auto text-[10px] text-obs-faint self-center">
            {summary.root_cause_count} grupo(s) de causa raiz / {summary.blocked_count} violacao(oes) brutas
          </span>
        </div>

        <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 lg:grid-cols-[1fr,1.2fr] gap-4">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-obs-text">Grafo do plano (estado por entry)</h3>
              <p className="text-[10px] text-obs-faint">{diagnostic.repair_suggestion}</p>
            </div>
            <div className="space-y-3">
              {STATUS_ORDER.map((status) => {
                const list = grouped[status];
                if (!list.length) return null;
                const style = STATUS_STYLE[status];
                return (
                  <div key={status}>
                    <div className="mb-1 flex items-center justify-between">
                      <p className={`text-[11px] font-semibold uppercase tracking-wider inline-flex items-center gap-1 px-1.5 py-0.5 rounded border ${style.chip}`}>
                        <style.icon size={10} />
                        {style.label}
                      </p>
                      <span className="text-[10px] text-obs-faint font-mono">{list.length}</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {list.map((node) => (
                        <NodeCard key={`${status}-${node.entry_index}`} node={node} />
                      ))}
                    </div>
                  </div>
                );
              })}
              {diagnostic.nodes.length === 0 && (
                <p className="text-xs text-obs-faint italic">
                  Nenhuma entrada para classificar (o plano pode estar vazio).
                </p>
              )}
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-obs-text inline-flex items-center gap-1">
                <MessageCircle size={12} className="text-blue-700" />
                Sofia precisa de {diagnostic.sofia_questions.length || diagnostic.root_causes.length} decisao(oes)
              </h3>
              <span className="text-[10px] text-obs-faint">
                {diagnostic.sofia_questions.length} pergunta(s)
              </span>
            </div>
            <div className="space-y-2">
              {diagnostic.sofia_questions.map((q, idx) => (
                <SofiaQuestionCard
                  key={`${q.kind}-${q.affected_entry_index ?? "k"}-${idx}`}
                  question={q}
                  index={idx + 1}
                />
              ))}
              {diagnostic.sofia_questions.length === 0 && (
                <p className="text-xs text-obs-faint italic">
                  Sem perguntas pendentes - confira os detalhes tecnicos abaixo.
                </p>
              )}
            </div>

            <details className="mt-4 rounded-lg border border-white/10 bg-obs-base/60">
              <summary className="cursor-pointer select-none px-3 py-2 text-[11px] text-obs-subtle hover:text-obs-text">
                Detalhes tecnicos ({diagnostic.root_causes.length} causa(s) raiz / {diagnostic.summary.blocked_count} violacao(oes))
              </summary>
              <div className="p-3 pt-0 space-y-2">
                {diagnostic.root_causes.map((cause) => (
                  <RootCauseCard key={cause.kind} cause={cause} />
                ))}
                {diagnostic.root_causes.length === 0 && (
                  <p className="text-xs text-obs-faint italic">Sem causas raiz identificadas.</p>
                )}
                {diagnostic.questions_markdown && diagnostic.sofia_questions.length === 0 && (
                  <div className="mt-2 rounded-lg border border-white/15 bg-obs-base p-3">
                    <h4 className="text-[12px] font-semibold text-obs-text mb-1.5">Perguntas para reparar o plano</h4>
                    <pre className="whitespace-pre-wrap font-sans text-[11px] text-obs-subtle leading-snug">
                      {diagnostic.questions_markdown}
                    </pre>
                  </div>
                )}
              </div>
            </details>
          </section>
        </div>

        <footer className="border-t border-white/15 px-5 py-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/20 px-3 py-1.5 text-[12px] text-obs-text hover:bg-white/10"
          >
            Fechar
          </button>
          {onEdit && (
            <button
              type="button"
              onClick={() => { onEdit(); onClose(); }}
              className="inline-flex items-center gap-1 rounded-md border border-white/20 bg-obs-base px-3 py-1.5 text-[12px] text-obs-text hover:bg-white/10"
            >
              <Edit3 size={12} />
              Editar plano
            </button>
          )}
          {onRegenerate && (
            <button
              type="button"
              onClick={() => { onRegenerate(); onClose(); }}
              className="inline-flex items-center gap-1 rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1.5 text-[12px] text-blue-800 hover:bg-blue-500/20"
            >
              <RefreshCcw size={12} />
              Regerar estrutura
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
