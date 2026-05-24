"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BookOpenCheck,
  Database,
  Globe2,
  Image,
  Keyboard,
  Moon,
  PlugZap,
  RefreshCw,
  Route,
  Settings,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { api } from "@/lib/api";
import { applyLanguage, getStoredLanguage, LANGUAGE_OPTIONS, type UiLanguage } from "@/lib/language";

const PAN_KEY_STORAGE = "ai-brain-graph-pan-key";
const THEME_STORAGE = "ai-brain-theme";
const GRAPH_NODE_OPACITY_STORAGE = "ai-brain-graph-node-opacity";
// Settings used to hardcode baita-conveniencia + cardapio-baita-v14.
// Now reads the active persona from localStorage; collection_slug stays
// optional so the menu endpoint derives it from persona.config.
const PERSONA_SLUG_STORAGE = "ai-brain-persona-slug";
const PERSONA_ID_STORAGE = "ai-brain-persona-id";

type Theme = "clean" | "dark";

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_STORAGE, theme);
  } catch {}
}

function statusDot(ok: boolean) {
  return ok ? "bg-green-400" : "bg-yellow-400";
}

function formatUpdate(value?: string | number | Date | null) {
  if (!value) return "Sem update";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sem update";
  return date.toLocaleString("pt-BR");
}

function countItems(value: any) {
  return Array.isArray(value) ? value.length : 0;
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

  const [loadingIntegrations, setLoadingIntegrations] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [personas, setPersonas] = useState<any[]>([]);
  const [personaSlug, setPersonaSlug] = useState("");
  const [storedPersonaId, setStoredPersonaId] = useState("");
  const [collections, setCollections] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [products, setProducts] = useState<any[]>([]);
  const [galleryAssets, setGalleryAssets] = useState<any[]>([]);
  const [menuPayload, setMenuPayload] = useState<any>(null);
  const [menuError, setMenuError] = useState("");

  useEffect(() => {
    setPanKey(window.localStorage.getItem(PAN_KEY_STORAGE) || "Control");
    const savedTheme = (window.localStorage.getItem(THEME_STORAGE) as Theme) || "clean";
    setTheme(savedTheme === "dark" ? "dark" : "clean");
    setLanguage(getStoredLanguage());
    setGraphNodeOpacity(window.localStorage.getItem(GRAPH_NODE_OPACITY_STORAGE) === "true");
    setPersonaSlug(window.localStorage.getItem(PERSONA_SLUG_STORAGE) || "");
    setStoredPersonaId(window.localStorage.getItem(PERSONA_ID_STORAGE) || "");
  }, []);

  useEffect(() => {
    refreshIntegrationState();
  }, [personaSlug]);

  const activePersonaId = personas.find((persona) => persona.slug === personaSlug)?.id || storedPersonaId;
  const byService = useMemo(
    () => Object.fromEntries(integrations.map((item) => [item.service, item])),
    [integrations],
  );
  const tockFatalConnected = personaSlug === "tock-fatal";
  const galleryConnected = countItems(galleryAssets) > 0;
  const menuConnected = !menuError && Boolean(menuPayload?.ok);

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

  async function refreshIntegrationState() {
    setLoadingIntegrations(true);
    setMenuError("");
    try {
      const [session, healthData, integrationsData, collectionsData, categoriesData, productsData, menuData] =
        await Promise.all([
          api.me().catch(() => null),
          api.health().catch(() => null),
          api.integrations().catch(() => []),
          api.productCollections({ persona_slug: personaSlug }).catch(() => []),
          api.productCategories({ persona_slug: personaSlug }).catch(() => []),
          api.products({ persona_slug: personaSlug }).catch(() => []),
          api.menuPayload(personaSlug).catch((error) => {
            setMenuError(error?.message || "Menu API indisponivel");
            return null;
          }),
        ]);
      const list = session?.personas || [];
      setPersonas(list);
      setApiOnline(Boolean(healthData));
      setIntegrations(integrationsData || []);
      setCollections(collectionsData || []);
      setCategories(categoriesData || []);
      setProducts(productsData || []);
      setMenuPayload(menuData);
      const personaId = list.find((persona: any) => persona.slug === personaSlug)?.id || activePersonaId;
      const assets = personaId ? await api.galleryAssets(personaId).catch(() => []) : [];
      setGalleryAssets(assets || []);
      setLastUpdate(new Date());
    } finally {
      setLoadingIntegrations(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            <Settings size={16} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Ajustes</p>
            <h1 className="mt-1 text-xl font-semibold text-obs-text">Configuracoes</h1>
          </div>
        </div>
        <button
          type="button"
          onClick={refreshIntegrationState}
          disabled={loadingIntegrations}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-white/10 bg-obs-surface px-3 text-xs font-medium text-obs-text transition hover:bg-white/[0.06] disabled:opacity-50"
        >
          <RefreshCw size={14} className={loadingIntegrations ? "animate-spin" : ""} />
          Atualizar conexoes
        </button>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <PlugZap size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Tools - integracoes</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <StatusTile label="API" value={apiOnline ? "conectada" : "pendente"} ok={apiOnline} detail={formatUpdate(lastUpdate)} />
            <StatusTile label="Supabase" value={byService.supabase?.status || "unknown"} ok={byService.supabase?.status === "healthy"} detail={byService.supabase?.response_ms ? `${byService.supabase.response_ms}ms` : "sem metrica"} />
            <StatusTile label="Colecao" value={String(countItems(collections))} ok={countItems(collections) > 0} detail={menuPayload?.persona?.collections?.[0]?.slug || "auto (config da persona)"} />
            <StatusTile label="Menu API" value={menuConnected ? "ativa" : "erro"} ok={menuConnected} detail={menuError || `/api/menu/${personaSlug}`} />
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Database size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Cardapio - landing page</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatusTile label="Categorias" value={String(countItems(categories))} ok={countItems(categories) > 0} detail="category + entity" />
            <StatusTile label="Produtos" value={String(countItems(products))} ok={countItems(products) > 0} detail="copy + category + asset" />
            <StatusTile label="Payload" value={menuPayload?.collection?.slug || "sem payload"} ok={menuConnected} detail={formatUpdate(menuPayload?.generated_at)} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <OutputBox
          icon={<Image size={15} className="text-obs-amber" />}
          title="Saida - Assets"
          status={galleryConnected ? "conectada" : "sem assets"}
          ok={galleryConnected}
          lines={[
            `${countItems(galleryAssets)} assets em Gallery`,
            "Aprovado + vinculado em Gallery fica disponivel para MCP e API.",
            "Capas mudam quando a conexao do asset no grafo muda.",
          ]}
        />
        <OutputBox
          icon={<BookOpenCheck size={15} className="text-green-300" />}
          title="Saida - FAQ"
          status={tockFatalConnected ? "conectada" : "pendente"}
          ok={tockFatalConnected}
          lines={[
            tockFatalConnected ? "Tock Fatal validado para FAQ." : "Somente Tock Fatal esta validado hoje.",
            "FAQ fica visivel como saida conectada quando a persona possui contexto aprovado.",
            "A configuracao detalhada da persona permanece na aba Persona.",
          ]}
        />
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Route size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Integracao Catalogo API</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <StatusTile label="Endpoint" value={`/api/menu/${personaSlug}`} ok={menuConnected} detail="publico para landing page" />
          <StatusTile label="Branch do produto" value={menuConnected ? "resolvido" : "pendente"} ok={menuConnected} detail="copy, category, asset" />
          <StatusTile label="Assets aprovados" value={String(countItems(galleryAssets))} ok={galleryConnected} detail="fonte das capas" />
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <SlidersHorizontal size={15} className="text-obs-violet" />
          <h2 className="text-sm font-semibold text-obs-text">Geral</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="flex items-center gap-2 text-obs-text">
              {theme === "dark" ? <Moon size={14} className="text-obs-violet" /> : <Sun size={14} className="text-obs-amber" />}
              Modo escuro
            </span>
            <input type="checkbox" checked={theme === "dark"} onChange={(e) => toggleTheme(e.target.checked)} className="h-4 w-4 accent-obs-violet" />
          </label>
          <Toggle label="Selecao multipla no grafo" checked={toggles.multiSelect} onChange={(checked) => setToggles((t) => ({ ...t, multiSelect: checked }))} />
          <Toggle label="Mostrar controles avancados" checked={toggles.advanced} onChange={(checked) => setToggles((t) => ({ ...t, advanced: checked }))} />
          <Toggle label="Confirmar exclusoes" checked={toggles.confirmDelete} onChange={(checked) => setToggles((t) => ({ ...t, confirmDelete: checked }))} />
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Globe2 size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Idioma</h2>
          </div>
          <select
            value={language}
            onChange={(event) => updateLanguage(event.target.value as UiLanguage)}
            className="w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Keyboard size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Grafo</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <select
              value={panKey}
              onChange={(event) => updatePanKey(event.target.value)}
              className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
            >
              <option value="Control">Ctrl</option>
              <option value="Alt">Alt</option>
              <option value="Shift">Shift</option>
            </select>
            <Toggle label="Usar opacidade nos nodes" checked={graphNodeOpacity} onChange={toggleGraphNodeOpacity} />
          </div>
        </div>
      </section>
    </div>
  );
}

function StatusTile({ label, value, detail, ok }: { label: string; value: string; detail: string; ok: boolean }) {
  return (
    <div className="min-w-0 rounded-xl border border-white/10 bg-obs-base/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-obs-subtle">{label}</p>
        <span className={`h-2.5 w-2.5 rounded-full ${statusDot(ok)}`} />
      </div>
      <p className="mt-2 truncate text-sm font-semibold text-obs-text">{value}</p>
      <p className="mt-1 truncate text-[11px] text-obs-faint">{detail}</p>
    </div>
  );
}

function OutputBox({
  icon,
  title,
  status,
  ok,
  lines,
}: {
  icon: ReactNode;
  title: string;
  status: string;
  ok: boolean;
  lines: string[];
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-sm font-semibold text-obs-text">{title}</h2>
        </div>
        <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${ok ? "bg-green-400/10 text-green-300" : "bg-yellow-400/10 text-yellow-300"}`}>
          {status}
        </span>
      </div>
      <div className="space-y-2">
        {lines.map((line) => (
          <p key={line} className="rounded-lg border border-white/10 bg-obs-base/60 px-3 py-2 text-xs text-obs-subtle">
            {line}
          </p>
        ))}
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
      <span className="text-obs-text">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-obs-violet" />
    </label>
  );
}
