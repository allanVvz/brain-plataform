"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BookOpenCheck,
  ChevronDown,
  Globe2,
  Image,
  KeyRound,
  Keyboard,
  Moon,
  RefreshCw,
  Route,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  Trash2,
  UserPlus,
  X,
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

function slugifyPersona(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
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
  const [newPersonaName, setNewPersonaName] = useState("");
  const [newPersonaSlug, setNewPersonaSlug] = useState("");
  const [creatingPersona, setCreatingPersona] = useState(false);
  const [createPersonaError, setCreatePersonaError] = useState("");
  const [createPersonaSuccess, setCreatePersonaSuccess] = useState("");
  const [apiKeyModal, setApiKeyModal] = useState<null | "selector" | "openai" | "anthropic">(null);
  const [apiKeyValue, setApiKeyValue] = useState("");
  const [apiKeyBusy, setApiKeyBusy] = useState(false);
  const [apiKeyError, setApiKeyError] = useState("");
  const [apiKeySuccess, setApiKeySuccess] = useState("");

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

  function handlePersonaNameChange(value: string) {
    setNewPersonaName(value);
    setCreatePersonaError("");
    setCreatePersonaSuccess("");
    if (!newPersonaSlug.trim()) {
      setNewPersonaSlug(slugifyPersona(value));
    }
  }

  async function handleCreatePersona() {
    const name = newPersonaName.trim();
    const slug = slugifyPersona(newPersonaSlug.trim());
    setCreatePersonaError("");
    setCreatePersonaSuccess("");
    if (!name) {
      setCreatePersonaError("Informe o nome da persona.");
      return;
    }
    if (!slug) {
      setCreatePersonaError("Informe um slug valido (letras, numeros e hifen).");
      return;
    }
    setCreatingPersona(true);
    try {
      await api.createPersona({ name, slug, products: [], prompts: {}, config: {} });
      setCreatePersonaSuccess(`Persona ${name} criada.`);
      setNewPersonaName("");
      setNewPersonaSlug("");
      setPersonaSlug(slug);
      window.localStorage.setItem(PERSONA_SLUG_STORAGE, slug);
      await refreshIntegrationState();
    } catch (error: any) {
      setCreatePersonaError(error?.message || "Falha ao criar persona.");
    } finally {
      setCreatingPersona(false);
    }
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

  function openApiKeyForm(service: "openai" | "anthropic") {
    setApiKeyValue("");
    setApiKeyError("");
    setApiKeySuccess("");
    setApiKeyModal(service);
  }

  async function saveApiKey(service: "openai" | "anthropic") {
    const key = apiKeyValue.trim();
    setApiKeyError("");
    setApiKeySuccess("");
    if (!key) {
      setApiKeyError("Informe a chave de API.");
      return;
    }
    setApiKeyBusy(true);
    try {
      await api.updateUserIntegration(service, { enabled: true, api_key: key });
      setApiKeySuccess(`${service === "openai" ? "OpenAI" : "Anthropic"} configurado para este usuario.`);
      setApiKeyValue("");
      setApiKeyModal(null);
      await refreshIntegrationState();
    } catch (error: any) {
      setApiKeyError(error?.message || "Falha ao salvar a chave.");
    } finally {
      setApiKeyBusy(false);
    }
  }

  async function removeApiKey(service: "openai" | "anthropic") {
    setApiKeyError("");
    setApiKeySuccess("");
    setApiKeyBusy(true);
    try {
      await api.deleteUserIntegrationCredentials(service);
      setApiKeySuccess(`${service === "openai" ? "OpenAI" : "Anthropic"} removido deste usuario.`);
      await refreshIntegrationState();
    } catch (error: any) {
      setApiKeyError(error?.message || "Falha ao remover a chave.");
    } finally {
      setApiKeyBusy(false);
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
          Atualizar
        </button>
      </header>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-4 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatusTile label="API" value={apiOnline ? "conectada" : "pendente"} ok={apiOnline} detail={formatUpdate(lastUpdate)} />
          <StatusTile label="Menu" value={menuConnected ? "ativo" : "erro"} ok={menuConnected} detail={menuError || `/api/menu/${personaSlug || "persona"}`} />
          <StatusTile label="Produtos" value={String(countItems(products))} ok={countItems(products) > 0} detail={`${countItems(categories)} categorias`} />
          <StatusTile label="Assets" value={String(countItems(galleryAssets))} ok={galleryConnected} detail="Gallery aprovada" />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <UserPlus size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Persona</h2>
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <input
              value={newPersonaName}
              onChange={(event) => handlePersonaNameChange(event.target.value)}
              placeholder="Nome da persona"
              className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
            />
            <input
              value={newPersonaSlug}
              onChange={(event) => {
                setNewPersonaSlug(slugifyPersona(event.target.value));
                setCreatePersonaError("");
                setCreatePersonaSuccess("");
              }}
              placeholder="slug-da-persona"
              className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
            />
            <button
              type="button"
              onClick={handleCreatePersona}
              disabled={creatingPersona}
              className="inline-flex min-h-10 items-center justify-center rounded-xl border border-obs-violet/30 bg-obs-violet/15 px-4 text-sm font-medium text-obs-violet transition hover:bg-obs-violet/20 disabled:opacity-50"
            >
              {creatingPersona ? "Criando..." : "Criar"}
            </button>
          </div>
          {createPersonaError && (
            <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {createPersonaError}
            </p>
          )}
          {createPersonaSuccess && (
            <p className="mt-3 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs text-green-200">
              {createPersonaSuccess}
            </p>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Route size={15} className="text-obs-violet" />
            <h2 className="text-sm font-semibold text-obs-text">Catalogo API</h2>
          </div>
          <div className="grid gap-3">
            <StatusTile label="Endpoint" value={`/api/menu/${personaSlug || "persona"}`} ok={menuConnected} detail="landing page" />
            <StatusTile label="Colecao" value={menuPayload?.persona?.collections?.[0]?.slug || "auto"} ok={countItems(collections) > 0} detail={menuPayload?.collection?.slug || "config da persona"} />
          </div>
        </div>
      </section>

      <SettingsDropdown
        icon={<KeyRound size={15} />}
        title="Chaves de API"
        status={`${apiKeyStatus(byService.openai).label} / ${apiKeyStatus(byService.anthropic).label}`}
        defaultOpen
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="text-xs leading-5 text-obs-subtle">
            Vault por usuario para OpenAI e Anthropic. O frontend exibe apenas status.
          </div>
          <button
            type="button"
            onClick={() => {
              setApiKeyError("");
              setApiKeySuccess("");
              setApiKeyModal("selector");
            }}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-obs-violet/30 bg-obs-violet/15 px-3 text-xs font-medium text-obs-violet transition hover:bg-obs-violet/20"
          >
            <KeyRound size={13} />
            Abrir seletor
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <ApiKeyStatusCard
            label="OpenAI"
            description="Sofia, marketing, assets e embeddings."
            item={byService.openai}
            busy={apiKeyBusy}
            onConfigure={() => openApiKeyForm("openai")}
            onRemove={() => removeApiKey("openai")}
          />
          <ApiKeyStatusCard
            label="Anthropic"
            description="Claude e fallback de modelo."
            item={byService.anthropic}
            busy={apiKeyBusy}
            onConfigure={() => openApiKeyForm("anthropic")}
            onRemove={() => removeApiKey("anthropic")}
          />
        </div>
        {apiKeyError && (
          <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {apiKeyError}
          </p>
        )}
        {apiKeySuccess && (
          <p className="mt-3 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs text-green-200">
            {apiKeySuccess}
          </p>
        )}
      </SettingsDropdown>

      <SettingsDropdown
        icon={<Keyboard size={15} />}
        title="Configuracao do grafo"
        status={`Pan ${panKey}`}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-2 rounded-xl border border-white/10 bg-obs-base/60 px-3 py-3 text-sm">
            <span className="text-xs font-medium text-obs-subtle">Tecla de pan</span>
            <select
              value={panKey}
              onChange={(event) => updatePanKey(event.target.value)}
              className="rounded-lg border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
            >
              <option value="Control">Ctrl</option>
              <option value="Alt">Alt</option>
              <option value="Shift">Shift</option>
            </select>
          </label>
          <Toggle label="Usar opacidade nos nodes" checked={graphNodeOpacity} onChange={toggleGraphNodeOpacity} />
          <Toggle label="Selecao multipla no grafo" checked={toggles.multiSelect} onChange={(checked) => setToggles((t) => ({ ...t, multiSelect: checked }))} />
          <Toggle label="Mostrar controles avancados" checked={toggles.advanced} onChange={(checked) => setToggles((t) => ({ ...t, advanced: checked }))} />
          <Toggle label="Confirmar exclusoes" checked={toggles.confirmDelete} onChange={(checked) => setToggles((t) => ({ ...t, confirmDelete: checked }))} />
        </div>
      </SettingsDropdown>

      <SettingsDropdown
        icon={<SlidersHorizontal size={15} />}
        title="Interface"
        status={theme === "dark" ? "escuro" : "claro"}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
            <span className="flex items-center gap-2 text-obs-text">
              {theme === "dark" ? <Moon size={14} className="text-obs-violet" /> : <Sun size={14} className="text-obs-amber" />}
              Modo escuro
            </span>
            <input type="checkbox" checked={theme === "dark"} onChange={(e) => toggleTheme(e.target.checked)} className="h-4 w-4 accent-obs-violet" />
          </label>
          <label className="grid gap-2 rounded-xl border border-white/10 bg-obs-base/60 px-3 py-3 text-sm">
            <span className="flex items-center gap-2 text-obs-text">
              <Globe2 size={14} className="text-obs-violet" />
              Idioma
            </span>
            <select
              value={language}
              onChange={(event) => updateLanguage(event.target.value as UiLanguage)}
              className="rounded-lg border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
            >
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </SettingsDropdown>

      <section className="grid gap-4 lg:grid-cols-2">
        <OutputBox
          icon={<Image size={15} className="text-obs-amber" />}
          title="Saida - Assets"
          status={galleryConnected ? "conectada" : "sem assets"}
          ok={galleryConnected}
          lines={[
            `${countItems(galleryAssets)} assets em Gallery`,
            "Assets aprovados alimentam MCP e API.",
            "Capas seguem a conexao vigente no grafo.",
          ]}
        />
        <OutputBox
          icon={<BookOpenCheck size={15} className="text-green-300" />}
          title="Saida - FAQ"
          status={tockFatalConnected ? "conectada" : "pendente"}
          ok={tockFatalConnected}
          lines={[
            tockFatalConnected ? "Tock Fatal validado para FAQ." : "FAQ depende de contexto aprovado.",
            "Publicacao segue o Golden Dataset.",
            "Aba Persona controla o roteamento detalhado.",
          ]}
        />
      </section>

      {apiKeyModal && (
        <ApiKeyModal
          mode={apiKeyModal}
          value={apiKeyValue}
          busy={apiKeyBusy}
          error={apiKeyError}
          onChange={setApiKeyValue}
          onClose={() => {
            setApiKeyModal(null);
            setApiKeyValue("");
            setApiKeyError("");
          }}
          onBack={() => {
            setApiKeyModal("selector");
            setApiKeyValue("");
            setApiKeyError("");
          }}
          onSelect={openApiKeyForm}
          onSave={saveApiKey}
        />
      )}
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

function SettingsDropdown({
  icon,
  title,
  status,
  defaultOpen = false,
  children,
}: {
  icon: ReactNode;
  title: string;
  status: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <details
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      className="group rounded-2xl border border-white/10 bg-obs-surface shadow-sm"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
        <span className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            {icon}
          </span>
          <span className="truncate text-sm font-semibold text-obs-text">{title}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <span className="max-w-[160px] truncate rounded-full border border-white/10 bg-obs-base/60 px-2 py-1 text-[11px] text-obs-subtle">
            {status}
          </span>
          <ChevronDown size={15} className="text-obs-faint transition group-open:rotate-180" />
        </span>
      </summary>
      <div className="border-t border-white/10 px-5 py-4">{children}</div>
    </details>
  );
}

function apiKeyStatus(item: any) {
  if (!item) return { label: "carregando", ok: false };
  if (item.configured && item.enabled && ["connected", "healthy"].includes(String(item.status))) return { label: "ativa", ok: true };
  if (item.configured) return { label: item.enabled ? String(item.status || "configurada") : "desativada", ok: false };
  return { label: "nao configurada", ok: false };
}

function ApiKeyStatusCard({
  label,
  description,
  item,
  busy,
  onConfigure,
  onRemove,
}: {
  label: string;
  description: string;
  item: any;
  busy: boolean;
  onConfigure: () => void;
  onRemove: () => void;
}) {
  const status = apiKeyStatus(item);
  return (
    <article className="rounded-xl border border-white/10 bg-obs-base/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${statusDot(status.ok)}`} />
            <h3 className="text-sm font-semibold text-obs-text">{label}</h3>
          </div>
          <p className="mt-2 text-xs leading-5 text-obs-subtle">{description}</p>
        </div>
        <span className="rounded-full border border-white/10 bg-obs-raised px-2 py-1 text-[11px] text-obs-subtle">
          {status.label}
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfigure}
          disabled={busy}
          className="inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-white/10 bg-obs-raised px-3 text-xs font-medium text-obs-text transition hover:bg-white/[0.06] disabled:opacity-50"
        >
          <KeyRound size={12} />
          {item?.configured ? "Substituir" : "Adicionar"}
        </button>
        {item?.configured && (
          <button
            type="button"
            onClick={onRemove}
            disabled={busy}
            className="inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 text-xs font-medium text-rose-200 transition hover:bg-rose-500/15 disabled:opacity-50"
          >
            <Trash2 size={12} />
            Remover
          </button>
        )}
      </div>
      <p className="mt-3 flex items-center gap-2 text-[11px] text-obs-faint">
        <ShieldCheck size={12} />
        Valor mascarado por contrato: esta tela mostra apenas status, nunca a chave.
      </p>
    </article>
  );
}

function ApiKeyModal({
  mode,
  value,
  busy,
  error,
  onChange,
  onClose,
  onBack,
  onSelect,
  onSave,
}: {
  mode: "selector" | "openai" | "anthropic";
  value: string;
  busy: boolean;
  error: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onBack: () => void;
  onSelect: (service: "openai" | "anthropic") => void;
  onSave: (service: "openai" | "anthropic") => void;
}) {
  const serviceLabel = mode === "openai" ? "OpenAI" : "Anthropic";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Vault de API</p>
            <h3 className="mt-1 text-lg font-semibold text-obs-text">
              {mode === "selector" ? "Escolha a chave para configurar" : `Configurar ${serviceLabel}`}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/10 bg-obs-raised p-2 text-obs-subtle transition hover:text-obs-text"
            aria-label="Fechar"
          >
            <X size={14} />
          </button>
        </div>

        {mode === "selector" ? (
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => onSelect("openai")}
              className="rounded-xl border border-white/10 bg-obs-base/60 p-4 text-left transition hover:border-obs-violet/40 hover:bg-obs-violet/10"
            >
              <KeyRound size={16} className="text-obs-violet" />
              <p className="mt-3 text-sm font-semibold text-obs-text">OpenAI</p>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">GPT, embeddings, assets e Sofia.</p>
            </button>
            <button
              type="button"
              onClick={() => onSelect("anthropic")}
              className="rounded-xl border border-white/10 bg-obs-base/60 p-4 text-left transition hover:border-obs-violet/40 hover:bg-obs-violet/10"
            >
              <KeyRound size={16} className="text-obs-violet" />
              <p className="mt-3 text-sm font-semibold text-obs-text">Anthropic</p>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">Claude e fallback de modelo.</p>
            </button>
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            <label className="block space-y-2">
              <span className="text-sm text-obs-text">Chave de API {serviceLabel}</span>
              <input
                type="password"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={mode === "openai" ? "sk-..." : "sk-ant-..."}
                autoComplete="off"
                className="w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
              />
            </label>
            <div className="rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-xs leading-5 text-obs-subtle">
              A chave sera enviada somente para o backend autenticado, criptografada no banco e usada apenas nas chamadas do usuario atual.
            </div>
            {error && (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onBack}
                className="rounded-lg border border-white/10 bg-obs-raised px-3 py-2 text-xs text-obs-subtle transition hover:text-obs-text"
              >
                Voltar
              </button>
              <button
                type="button"
                onClick={() => onSave(mode)}
                disabled={busy}
                className="rounded-lg border border-obs-violet/30 bg-obs-violet/15 px-3 py-2 text-xs font-medium text-obs-violet transition hover:bg-obs-violet/20 disabled:opacity-50"
              >
                {busy ? "Salvando..." : "Salvar chave"}
              </button>
            </div>
          </div>
        )}
      </div>
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
