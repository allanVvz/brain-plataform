"use client";

import { useEffect, useState } from "react";
import { Globe2, Keyboard, Moon, Settings, SlidersHorizontal, Sun } from "lucide-react";
import { applyLanguage, getStoredLanguage, LANGUAGE_OPTIONS, type UiLanguage } from "@/lib/language";

const PAN_KEY_STORAGE = "ai-brain-graph-pan-key";
const THEME_STORAGE = "ai-brain-theme";
const GRAPH_NODE_OPACITY_STORAGE = "ai-brain-graph-node-opacity";

type Theme = "clean" | "dark";

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_STORAGE, theme);
  } catch {}
}

export default function SettingsPage() {
  const [panKey, setPanKey] = useState("Control");
  const [theme, setTheme] = useState<Theme>("clean");
  const [language, setLanguage] = useState<UiLanguage>("pt-BR");
  const [graphNodeOpacity, setGraphNodeOpacity] = useState(false);
  const [toggles, setToggles] = useState({
    multiSelect: true,
    advanced: false,
    confirmDelete: true,
  });

  useEffect(() => {
    setPanKey(window.localStorage.getItem(PAN_KEY_STORAGE) || "Control");
    const saved = (window.localStorage.getItem(THEME_STORAGE) as Theme) || "clean";
    setTheme(saved === "dark" ? "dark" : "clean");
    setLanguage(getStoredLanguage());
    setGraphNodeOpacity(window.localStorage.getItem(GRAPH_NODE_OPACITY_STORAGE) === "true");
  }, []);

  function updatePanKey(value: string) {
    setPanKey(value);
    window.localStorage.setItem(PAN_KEY_STORAGE, value);
  }

  function toggleTheme(next: boolean) {
    const t: Theme = next ? "dark" : "clean";
    setTheme(t);
    applyTheme(t);
  }

  function toggleGraphNodeOpacity(next: boolean) {
    setGraphNodeOpacity(next);
    window.localStorage.setItem(GRAPH_NODE_OPACITY_STORAGE, String(next));
    window.dispatchEvent(new CustomEvent("ai-brain-graph-appearance-change", { detail: { graphNodeOpacity: next } }));
  }

  function updateLanguage(next: UiLanguage) {
    setLanguage(next);
    applyLanguage(next);
  }

  const copy = language === "en"
    ? {
        eyebrow: "Settings",
        title: "Settings",
        general: "General",
        darkMode: "Dark mode",
        multiSelect: "Graph multi-select",
        advanced: "Show advanced controls",
        confirmDelete: "Confirm deletions",
        language: "Language",
        languageHint: "Controls fixed UI labels. Dynamic knowledge content keeps its original language.",
        graphAppearance: "Graph appearance",
        graphOpacity: "Use node opacity",
        graphOpacityHint: "Local mock: toggles between glass nodes and filled nodes with stronger contrast.",
        keys: "Keys",
        graphPan: "Move graph canvas",
        graphPanHint: "The canvas only moves while the selected key is pressed.",
      }
    : {
        eyebrow: "Configurações",
        title: "Configurações",
        general: "Configurações",
        darkMode: "Modo escuro",
        multiSelect: "Seleção múltipla no grafo",
        advanced: "Mostrar controles avançados",
        confirmDelete: "Confirmar exclusões",
        language: "Idioma",
        languageHint: "Controla rótulos fixos da interface. Conteúdo dinâmico de conhecimento mantém o idioma original.",
        graphAppearance: "Aparência do grafo",
        graphOpacity: "Usar opacidade nos nodes",
        graphOpacityHint: "Mock local: alterna entre nodes glass/translúcidos e nodes preenchidos com maior contraste.",
        keys: "Teclas",
        graphPan: "Mover tela do grafo",
        graphPanHint: "A tela só se move quando a tecla escolhida estiver pressionada.",
      };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <header className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
          <Settings size={16} />
        </span>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">{copy.eyebrow}</p>
          <h1 className="mt-1 text-xl font-semibold text-obs-text">{copy.title}</h1>
        </div>
      </header>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">{copy.general}</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="flex items-center gap-2 text-obs-text">
              {theme === "dark" ? (
                <Moon size={14} className="text-obs-violet" />
              ) : (
                <Sun size={14} className="text-obs-amber" />
              )}
              {copy.darkMode}
            </span>
            <input
              type="checkbox"
              checked={theme === "dark"}
              onChange={(e) => toggleTheme(e.target.checked)}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">{copy.multiSelect}</span>
            <input
              type="checkbox"
              checked={toggles.multiSelect}
              onChange={(e) => setToggles((t) => ({ ...t, multiSelect: e.target.checked }))}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">{copy.advanced}</span>
            <input
              type="checkbox"
              checked={toggles.advanced}
              onChange={(e) => setToggles((t) => ({ ...t, advanced: e.target.checked }))}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">{copy.confirmDelete}</span>
            <input
              type="checkbox"
              checked={toggles.confirmDelete}
              onChange={(e) => setToggles((t) => ({ ...t, confirmDelete: e.target.checked }))}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Globe2 size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">{copy.language}</h2>
        </div>
        <label className="flex flex-col gap-2 rounded-xl border border-white/10 bg-obs-base/60 p-3 text-sm md:flex-row md:items-center md:justify-between">
          <span>
            <span className="block text-obs-text">{copy.language}</span>
            <span className="mt-0.5 block text-xs text-obs-subtle">{copy.languageHint}</span>
          </span>
          <select
            value={language}
            onChange={(event) => updateLanguage(event.target.value as UiLanguage)}
            className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">{copy.graphAppearance}</h2>
        </div>
        <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
          <span>
            <span className="block text-obs-text">{copy.graphOpacity}</span>
            <span className="mt-0.5 block text-xs text-obs-subtle">
              {copy.graphOpacityHint}
            </span>
          </span>
          <input
            type="checkbox"
            checked={graphNodeOpacity}
            onChange={(e) => toggleGraphNodeOpacity(e.target.checked)}
            className="h-4 w-4 accent-obs-violet"
          />
        </label>
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Keyboard size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">{copy.keys}</h2>
        </div>
        <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-obs-base/60 p-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-medium text-obs-text">{copy.graphPan}</p>
            <p className="mt-0.5 text-xs text-obs-subtle">{copy.graphPanHint}</p>
          </div>
          <select
            value={panKey}
            onChange={(event) => updatePanKey(event.target.value)}
            className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
          >
            <option value="Control">Ctrl</option>
            <option value="Alt">Alt</option>
            <option value="Shift">Shift</option>
          </select>
        </div>
      </section>
    </div>
  );
}
