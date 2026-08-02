"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import {
  ChevronDown,
  Globe2,
  Keyboard,
  Link2,
  MessageCircle,
  Moon,
  RefreshCw,
  Route,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  UserPlus,
} from "lucide-react";
import { api } from "@/lib/api";
import { applyLanguage, getStoredLanguage, LANGUAGE_OPTIONS, type UiLanguage } from "@/lib/language";
import { MessagingSettingsPanel } from "@/components/settings/MessagingSettingsPanel";
import { SecuritySettingsPanel } from "@/components/settings/SecuritySettingsPanel";

const panelLoading = () => (
  <p className="rounded-xl border border-white/10 bg-obs-surface p-4 text-sm text-obs-subtle">
    Carregando painel…
  </p>
);
const ToolsSettingsPanel = dynamic(
  () => import("@/app/tools/page"),
  { loading: panelLoading },
);
const LogsSettingsPanel = dynamic(
  () => import("@/app/logs/page"),
  { loading: panelLoading },
);
const AccessSettingsPanel = dynamic(
  () => import("@/app/access/page"),
  { loading: panelLoading },
);

const PAN_KEY_STORAGE = "ai-brain-graph-pan-key";
const THEME_STORAGE = "ai-brain-theme";
const GRAPH_NODE_OPACITY_STORAGE = "ai-brain-graph-node-opacity";
// Settings used to hardcode baita-conveniencia + cardapio-baita-v14.
// Now reads the active persona from localStorage; collection_slug stays
// optional so the menu endpoint derives it from persona.config.
const PERSONA_SLUG_STORAGE = "ai-brain-persona-slug";
const PERSONA_ID_STORAGE = "ai-brain-persona-id";

type Theme = "clean" | "dark";
type PublicSiteDraft = {
  site_slug: string;
  site_name: string;
  format_key: string;
  default_collection_slug: string;
  whatsapp_phone: string;
  whatsapp_message_template: string;
  catalog_url: string;
};

const emptySiteDraft: PublicSiteDraft = {
  site_slug: "",
  site_name: "",
  format_key: "cardapio",
  default_collection_slug: "",
  whatsapp_phone: "",
  whatsapp_message_template: "",
  catalog_url: "",
};

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

function GeneralSettingsPanel() {
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
  const [personas, setPersonas] = useState<any[]>([]);
  const [personaSlug, setPersonaSlug] = useState("");
  const [storedPersonaId, setStoredPersonaId] = useState("");
  const [collections, setCollections] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [products, setProducts] = useState<any[]>([]);
  const [galleryAssets, setGalleryAssets] = useState<any[]>([]);
  const [menuPayload, setMenuPayload] = useState<any>(null);
  const [menuError, setMenuError] = useState("");
  const [siteFormats, setSiteFormats] = useState<any[]>([]);
  const [publicSite, setPublicSite] = useState<any>(null);
  const [siteDraft, setSiteDraft] = useState<PublicSiteDraft>(emptySiteDraft);
  const [savingSite, setSavingSite] = useState(false);
  const [siteError, setSiteError] = useState("");
  const [siteSuccess, setSiteSuccess] = useState("");
  const [newPersonaName, setNewPersonaName] = useState("");
  const [newPersonaSlug, setNewPersonaSlug] = useState("");
  const [creatingPersona, setCreatingPersona] = useState(false);
  const [createPersonaError, setCreatePersonaError] = useState("");
  const [createPersonaSuccess, setCreatePersonaSuccess] = useState("");

  useEffect(() => {
    setPanKey(window.localStorage.getItem(PAN_KEY_STORAGE) || "Control");
    const savedTheme = (window.localStorage.getItem(THEME_STORAGE) as Theme) || "clean";
    setTheme(savedTheme === "dark" ? "dark" : "clean");
    setLanguage(getStoredLanguage());
    setGraphNodeOpacity(window.localStorage.getItem(GRAPH_NODE_OPACITY_STORAGE) === "true");
    const syncPersona = (event?: Event) => {
      const detail = (event as CustomEvent<{ id?: string; slug?: string }> | undefined)?.detail;
      setPersonaSlug(detail?.slug ?? window.localStorage.getItem(PERSONA_SLUG_STORAGE) ?? "");
      setStoredPersonaId(detail?.id ?? window.localStorage.getItem(PERSONA_ID_STORAGE) ?? "");
    };
    syncPersona();
    window.addEventListener("ai-brain-persona-change", syncPersona as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", syncPersona as EventListener);
  }, []);

  useEffect(() => {
    refreshIntegrationState();
  }, [personaSlug]);

  const activePersonaId = personas.find((persona) => persona.slug === personaSlug)?.id || storedPersonaId;
  const galleryConnected = countItems(galleryAssets) > 0;
  const menuConnected = !menuError && Boolean(menuPayload?.ok);
  const siteConnected = Boolean(publicSite?.site?.slug || menuPayload?.site?.slug);
  const activeSiteFormat = useMemo(
    () => siteFormats.find((format) => format.key === siteDraft.format_key),
    [siteFormats, siteDraft.format_key],
  );

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
      const [session, healthData, formatsData, publicSiteData, collectionsData, categoriesData, productsData, menuData] =
        await Promise.all([
          api.me().catch(() => null),
          api.health().catch(() => null),
          api.publicSiteFormats().catch(() => []),
          personaSlug ? api.personaPublicSite(personaSlug).catch(() => null) : Promise.resolve(null),
          api.productCollections({ persona_slug: personaSlug }).catch(() => []),
          api.productCategories({ persona_slug: personaSlug }).catch(() => []),
          api.products({ persona_slug: personaSlug }).catch(() => []),
          personaSlug ? api.menuPayload(personaSlug).catch((error) => {
            setMenuError(error?.message || "Menu API indisponivel");
            return null;
          }) : Promise.resolve(null),
        ]);
      const list = session?.personas || [];
      setPersonas(list);
      setApiOnline(Boolean(healthData));
      setSiteFormats(formatsData || []);
      setPublicSite(publicSiteData);
      if (publicSiteData?.config) {
        setSiteDraft({
          site_slug: publicSiteData.config.site_slug || "",
          site_name: publicSiteData.config.site_name || "",
          format_key: publicSiteData.config.format_key || "cardapio",
          default_collection_slug: publicSiteData.config.default_collection_slug || "",
          whatsapp_phone: publicSiteData.config.whatsapp_phone || "",
          whatsapp_message_template: publicSiteData.config.whatsapp_message_template || "",
          catalog_url: publicSiteData.catalog_url || publicSiteData.site?.catalog_url || "",
        });
      }
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

  function updateSiteDraft<K extends keyof PublicSiteDraft>(key: K, value: PublicSiteDraft[K]) {
    setSiteDraft((draft) => ({ ...draft, [key]: value }));
    setSiteError("");
    setSiteSuccess("");
  }

  async function savePublicSite() {
    setSiteError("");
    setSiteSuccess("");
    if (!personaSlug) {
      setSiteError("Selecione ou crie uma persona antes de configurar o site.");
      return;
    }
    if (!siteDraft.site_name.trim()) {
      setSiteError("Informe o nome do site.");
      return;
    }
    if (!siteDraft.site_slug.trim()) {
      setSiteError("Informe o slug do site.");
      return;
    }
    setSavingSite(true);
    try {
      const updated = await api.updatePersonaPublicSite(personaSlug, {
        site_name: siteDraft.site_name.trim(),
        site_slug: slugifyPersona(siteDraft.site_slug),
        format_key: siteDraft.format_key || "cardapio",
        default_collection_slug: slugifyPersona(siteDraft.default_collection_slug || `cardapio-${personaSlug}-v1`),
        whatsapp_phone: siteDraft.whatsapp_phone,
        whatsapp_message_template: siteDraft.whatsapp_message_template,
        catalog_url: siteDraft.catalog_url.trim() || null,
      });
      setPublicSite(updated);
      if (updated?.config) {
        setSiteDraft({
          site_slug: updated.config.site_slug || "",
          site_name: updated.config.site_name || "",
          format_key: updated.config.format_key || "cardapio",
          default_collection_slug: updated.config.default_collection_slug || "",
          whatsapp_phone: updated.config.whatsapp_phone || "",
          whatsapp_message_template: updated.config.whatsapp_message_template || "",
          catalog_url: updated.catalog_url || updated.site?.catalog_url || "",
        });
      }
      setSiteSuccess("Configuracao do site salva.");
      await refreshIntegrationState();
    } catch (error: any) {
      setSiteError(error?.message || "Falha ao salvar o site.");
    } finally {
      setSavingSite(false);
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
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <StatusTile label="API" value={apiOnline ? "conectada" : "pendente"} ok={apiOnline} detail={formatUpdate(lastUpdate)} />
          <StatusTile label="Menu" value={menuConnected ? "ativo" : "erro"} ok={menuConnected} detail={menuError || `/api/menu/${personaSlug || "persona"}`} />
          <StatusTile label="Site" value={siteConnected ? siteDraft.site_slug || "configurado" : "pendente"} ok={siteConnected} detail={activeSiteFormat?.label || "formato"} />
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
        icon={<Globe2 size={15} />}
        title="Output do site"
        status={siteConnected ? `${activeSiteFormat?.label || siteDraft.format_key} · ${siteDraft.site_slug || "sem slug"}` : "pendente"}
        defaultOpen
      >
        <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="grid gap-3">
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">Nome do site</span>
                <input
                  value={siteDraft.site_name}
                  onChange={(event) => updateSiteDraft("site_name", event.target.value)}
                  placeholder="Baita Cardapio"
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                />
              </label>
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">Slug publico</span>
                <input
                  value={siteDraft.site_slug}
                  onChange={(event) => updateSiteDraft("site_slug", slugifyPersona(event.target.value))}
                  placeholder="baita-cardapio"
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 font-mono text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                />
              </label>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">Formato</span>
                <select
                  value={siteDraft.format_key}
                  onChange={(event) => updateSiteDraft("format_key", event.target.value)}
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                >
                  {(siteFormats.length ? siteFormats : [{ key: "cardapio", label: "Cardapio" }]).map((format) => (
                    <option key={format.key} value={format.key}>
                      {format.label || format.key}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">Colecao padrao</span>
                <input
                  value={siteDraft.default_collection_slug}
                  onChange={(event) => updateSiteDraft("default_collection_slug", slugifyPersona(event.target.value))}
                  placeholder={`cardapio-${personaSlug || "persona"}-v1`}
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 font-mono text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                />
              </label>
            </div>
            <label className="grid gap-2 text-sm">
              <span className="text-xs font-medium text-obs-subtle">URL publicada</span>
              <input
                value={siteDraft.catalog_url}
                onChange={(event) => updateSiteDraft("catalog_url", event.target.value)}
                placeholder="https://site-publico.vercel.app/cardapio/baita-cardapio"
                className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
              />
            </label>
            <div className="grid gap-3 md:grid-cols-[0.75fr_1.25fr]">
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">WhatsApp publico</span>
                <input
                  value={siteDraft.whatsapp_phone}
                  onChange={(event) => updateSiteDraft("whatsapp_phone", event.target.value)}
                  placeholder="5511999999999"
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 font-mono text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                />
              </label>
              <label className="grid gap-2 text-sm">
                <span className="text-xs font-medium text-obs-subtle">Mensagem automatica</span>
                <input
                  value={siteDraft.whatsapp_message_template}
                  onChange={(event) => updateSiteDraft("whatsapp_message_template", event.target.value)}
                  placeholder="Ola, vim pelo site e quero mais informacoes."
                  className="rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet focus:ring-4 focus:ring-obs-violet/15"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={savePublicSite}
                disabled={savingSite || !personaSlug}
                className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-obs-violet/30 bg-obs-violet/15 px-3 text-xs font-medium text-obs-violet transition hover:bg-obs-violet/20 disabled:opacity-50"
              >
                <Save size={13} />
                {savingSite ? "Salvando..." : "Salvar output"}
              </button>
              {siteSuccess && <span className="text-xs text-green-300">{siteSuccess}</span>}
              {siteError && <span className="text-xs text-rose-200">{siteError}</span>}
            </div>
          </div>

          <div className="grid gap-3">
            <StatusTile label="Formato ativo" value={activeSiteFormat?.label || siteDraft.format_key || "cardapio"} ok={Boolean(siteDraft.format_key)} detail="registry do banco" />
            <StatusTile label="Rota sugerida" value={publicSite?.site?.route_path || `/${siteDraft.format_key || "site"}/${siteDraft.site_slug || "slug"}`} ok={Boolean(siteDraft.site_slug)} detail="consumida pelo repo publico" />
            <div className="rounded-xl border border-white/10 bg-obs-base/60 p-3">
              <div className="flex items-center gap-2 text-xs font-medium text-obs-subtle">
                <MessageCircle size={13} className="text-green-300" />
                Preview WhatsApp
              </div>
              {publicSite?.site?.whatsapp?.href ? (
                <a
                  href={publicSite.site.whatsapp.href}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex max-w-full items-center gap-2 truncate rounded-lg border border-green-400/20 bg-green-400/10 px-3 py-2 text-xs text-green-200"
                >
                  <Link2 size={12} />
                  {publicSite.site.whatsapp.href}
                </a>
              ) : (
                <p className="mt-3 text-xs leading-5 text-obs-subtle">
                  Salve um telefone publico para gerar o link wa.me. Tokens Meta/n8n nao aparecem neste payload.
                </p>
              )}
            </div>
          </div>
        </div>
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

    </div>
  );
}

type SettingsTab =
  | "general"
  | "messaging"
  | "tools"
  | "logs"
  | "access"
  | "security";

const SETTINGS_TABS: Array<{
  key: SettingsTab;
  label: string;
  icon: typeof Settings;
}> = [
  { key: "general", label: "Geral", icon: Settings },
  { key: "messaging", label: "Mensageria", icon: MessageCircle },
  { key: "tools", label: "Ferramentas", icon: SlidersHorizontal },
  { key: "logs", label: "Logs", icon: RefreshCw },
  { key: "access", label: "Acessos", icon: UserPlus },
  { key: "security", label: "Segurança", icon: ShieldCheck },
];

function tabFromLocation(): SettingsTab {
  if (typeof window === "undefined") return "general";
  const candidate = new URLSearchParams(window.location.search).get("tab") || "";
  return SETTINGS_TABS.some((tab) => tab.key === candidate)
    ? candidate as SettingsTab
    : "general";
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  useEffect(() => {
    // ChatBot merged into Mensageria > Agentes — redirect old links/bookmarks
    // instead of silently falling back to Geral.
    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "chatbot") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", "messaging");
      url.searchParams.set("sub", params.get("view") === "validations" ? "validacoes" : "agentes");
      url.searchParams.delete("view");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
    const sync = () => setActiveTab(tabFromLocation());
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  function selectTab(tab: SettingsTab) {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    if (tab === "general") {
      url.searchParams.delete("tab");
    } else {
      url.searchParams.set("tab", tab);
    }
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
          Central administrativa
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-obs-text">Configurações</h1>
        <p className="mt-1 text-sm text-obs-subtle">
          Operação, mensageria, ferramentas, auditoria e segurança em um único lugar.
        </p>
      </header>

      <nav
        aria-label="Abas de configurações"
        className="flex gap-1 overflow-x-auto rounded-2xl border border-white/10 bg-obs-surface p-1.5"
      >
        {SETTINGS_TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => selectTab(key)}
            aria-selected={activeTab === key}
            className={`flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition ${
              activeTab === key
                ? "bg-obs-violet/15 text-obs-violet ring-1 ring-obs-violet/25"
                : "text-obs-subtle hover:bg-white/[0.05] hover:text-obs-text"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      <section data-settings-tab={activeTab}>
        {activeTab === "general" && <GeneralSettingsPanel />}
        {activeTab === "messaging" && <MessagingSettingsPanel />}
        {activeTab === "tools" && <ToolsSettingsPanel />}
        {activeTab === "logs" && <LogsSettingsPanel />}
        {activeTab === "access" && <AccessSettingsPanel />}
        {activeTab === "security" && <SecuritySettingsPanel />}
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

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-center justify-between rounded-xl border border-white/10 bg-obs-base/60 px-3 py-2 text-sm">
      <span className="text-obs-text">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-obs-violet" />
    </label>
  );
}
