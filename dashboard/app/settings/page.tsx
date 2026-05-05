"use client";

import { useEffect, useState } from "react";
import { Keyboard, Moon, Settings, SlidersHorizontal, Sun } from "lucide-react";

const PAN_KEY_STORAGE = "ai-brain-graph-pan-key";
const THEME_STORAGE = "ai-brain-theme";

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
  const [toggles, setToggles] = useState({
    multiSelect: true,
    advanced: false,
    confirmDelete: true,
  });

  useEffect(() => {
    setPanKey(window.localStorage.getItem(PAN_KEY_STORAGE) || "Control");
    const saved = (window.localStorage.getItem(THEME_STORAGE) as Theme) || "clean";
    setTheme(saved === "dark" ? "dark" : "clean");
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

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <header className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
          <Settings size={16} />
        </span>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Configuracoes</p>
          <h1 className="mt-1 text-xl font-semibold text-obs-text">Settings</h1>
        </div>
      </header>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Configuracoes</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="flex items-center gap-2 text-obs-text">
              {theme === "dark" ? (
                <Moon size={14} className="text-obs-violet" />
              ) : (
                <Sun size={14} className="text-obs-amber" />
              )}
              Modo escuro
            </span>
            <input
              type="checkbox"
              checked={theme === "dark"}
              onChange={(e) => toggleTheme(e.target.checked)}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">Selecao multipla no grafo</span>
            <input
              type="checkbox"
              checked={toggles.multiSelect}
              onChange={(e) => setToggles((t) => ({ ...t, multiSelect: e.target.checked }))}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">Mostrar controles avancados</span>
            <input
              type="checkbox"
              checked={toggles.advanced}
              onChange={(e) => setToggles((t) => ({ ...t, advanced: e.target.checked }))}
              className="h-4 w-4 accent-obs-violet"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="text-obs-text">Confirmar exclusoes</span>
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
          <Keyboard size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Teclas</h2>
        </div>
        <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-obs-base/60 p-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-medium text-obs-text">Mover tela do grafo</p>
            <p className="mt-0.5 text-xs text-obs-subtle">A tela so se move quando a tecla escolhida estiver pressionada.</p>
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
