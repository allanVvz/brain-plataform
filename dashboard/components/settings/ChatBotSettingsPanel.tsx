"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { Bot, CheckCircle2, FlaskConical, MessageSquareText, Route } from "lucide-react";
import { MessagesLayout } from "@/app/messages/MessagesLayout";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

type ChatBotView = "operation" | "validations";
type ConversationMode = "deterministic" | "n8n_agents";

type RoutingConfig = {
  conversation_mode: ConversationMode;
  migration_applied?: boolean;
  model_required?: boolean;
  model_provider?: string | null;
  model_name?: string | null;
};

const ValidatorWorkspace = dynamic(
  () => import("@/app/wa-validator/page"),
  {
    loading: () => (
      <p className="rounded-xl border border-white/10 bg-obs-surface p-4 text-sm text-obs-subtle">
        Carregando testes do ChatBot…
      </p>
    ),
  },
);

function viewFromLocation(): ChatBotView {
  if (typeof window === "undefined") return "operation";
  return new URLSearchParams(window.location.search).get("view") === "validations"
    ? "validations"
    : "operation";
}

export function ChatBotSettingsPanel() {
  const persona = useGlobalPersona();
  const [view, setView] = useState<ChatBotView>("operation");
  const [routing, setRouting] = useState<RoutingConfig | null>(null);
  const [routingBusy, setRoutingBusy] = useState(false);
  const [routingMessage, setRoutingMessage] = useState("");
  const [routingError, setRoutingError] = useState("");

  useEffect(() => {
    setView(viewFromLocation());
  }, []);

  useEffect(() => {
    let active = true;
    setRouting(null);
    setRoutingMessage("");
    setRoutingError("");
    if (!persona.slug) return () => { active = false; };

    api.personaRouting(persona.slug)
      .then((result) => {
        if (active) setRouting(result);
      })
      .catch((error) => {
        if (active) setRoutingError(error?.message || "Não foi possível carregar o fluxo do ChatBot.");
      });

    return () => { active = false; };
  }, [persona.slug]);

  function selectView(next: ChatBotView) {
    setView(next);
    const url = new URL(window.location.href);
    if (next === "validations") url.searchParams.set("view", "validations");
    else url.searchParams.delete("view");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  async function updateConversationMode(mode: ConversationMode) {
    if (!persona.slug || routingBusy || routing?.conversation_mode === mode) return;
    setRoutingBusy(true);
    setRoutingMessage("");
    setRoutingError("");
    try {
      const updated = await api.updatePersonaRouting(persona.slug, {
        conversation_mode: mode,
      });
      setRouting(updated);
      setRoutingMessage(
        mode === "deterministic"
          ? "Fluxo determinístico ativado."
          : "Orquestração n8n com DeepSeek ativada.",
      );
    } catch (error: any) {
      setRoutingError(error?.message || "Falha ao atualizar o fluxo do ChatBot.");
    } finally {
      setRoutingBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-obs-surface p-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            <Bot size={16} />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-obs-text">ChatBot</h2>
            <p className="mt-0.5 text-xs text-obs-subtle">
              Operação e conversas de validação da persona selecionada no cabeçalho.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 rounded-xl border border-white/10 bg-obs-base p-1">
          <button
            type="button"
            onClick={() => selectView("operation")}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${
              view === "operation"
                ? "bg-obs-violet/15 text-obs-violet"
                : "text-obs-subtle hover:text-obs-text"
            }`}
          >
            <FlaskConical size={13} /> Operação
          </button>
          <button
            type="button"
            onClick={() => selectView("validations")}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium ${
              view === "validations"
                ? "bg-obs-violet/15 text-obs-violet"
                : "text-obs-subtle hover:text-obs-text"
            }`}
          >
            <MessageSquareText size={13} /> Validações
          </button>
        </div>
      </div>

      {!persona.id ? (
        <p className="rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm text-amber-200">
          Selecione uma persona no cabeçalho para abrir o ChatBot.
        </p>
      ) : view === "validations" ? (
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-obs-surface">
          <MessagesLayout validationMode />
        </div>
      ) : (
        <div className="space-y-4">
          <section className="rounded-2xl border border-white/10 bg-obs-surface p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
                <Route size={16} />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-obs-text">Fluxo de atendimento</h3>
                <p className="mt-1 text-xs leading-5 text-obs-subtle">
                  Configuração única da persona. O envio permanece direto pelo provider de WhatsApp.
                </p>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {([
                {
                  value: "deterministic",
                  title: "Determinístico",
                  description: "Usa o grafo e as regras publicadas, sem consumir uma chave de modelo.",
                },
                {
                  value: "n8n_agents",
                  title: "n8n + DeepSeek",
                  description: "O n8n extrai campos com DeepSeek e o Brain mantém as decisões comerciais determinísticas.",
                },
              ] as const).map((option) => {
                const selected = routing?.conversation_mode === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => updateConversationMode(option.value)}
                    disabled={routingBusy || !routing?.migration_applied}
                    className={`rounded-xl border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                      selected
                        ? "border-obs-violet/40 bg-obs-violet/10"
                        : "border-white/10 bg-obs-base/60 hover:border-white/20"
                    }`}
                  >
                    <span className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-obs-text">{option.title}</span>
                      {selected && <CheckCircle2 size={15} className="text-obs-violet" />}
                    </span>
                    <span className="mt-2 block text-xs leading-5 text-obs-subtle">
                      {option.description}
                    </span>
                  </button>
                );
              })}
            </div>

            {routing?.conversation_mode === "n8n_agents" && (
              <p className="mt-3 text-xs text-obs-subtle">
                Modelo ativo: {routing.model_name || "DeepSeek configurado na aba Ferramentas"}.
              </p>
            )}
            {routingMessage && <p className="mt-3 text-xs text-green-300">{routingMessage}</p>}
            {routingError && (
              <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {routingError}
              </p>
            )}
          </section>

          <ValidatorWorkspace />
        </div>
      )}
    </div>
  );
}
