"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { getStoredLanguage, UI_LANGUAGE_EVENT, type UiLanguage } from "@/lib/language";
import {
  mandatoryPasswordDestination,
  resolveSessionDestination,
} from "@/lib/session-routing";
import {
  Activity,
  BookOpen,
  CheckSquare,
  GitBranch,
  Image,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Network,
  Package,
  Plus,
  RefreshCw,
  ScrollText,
  Settings,
  Sparkles,
  UserCircle,
  Users,
  Wrench,
} from "lucide-react";

const nav = [
  { section: null, href: "/", label: "Dashboard", icon: LayoutDashboard },
  { section: null, href: "/pipeline", label: "Pipeline", icon: Activity },
  { section: null, href: "/knowledge/graph", label: "Grafos", icon: Network },
  { section: null, href: "/marketing/criacao", label: "Create", icon: Sparkles },
  { section: "CRM", href: "/leads", label: "Leads", icon: Users },
  { section: "CRM", href: "/messages", label: "Messages", icon: MessageSquare },
  { section: "CRM", href: "/leads/import", label: "Import", icon: Plus },
  { section: "Marketing", href: "/persona", label: "Persona", icon: UserCircle },
  { section: "Marketing", href: "/marketing/produtos", label: "Produtos", icon: Package },
  { section: "Marketing", href: "/marketing/assets", label: "Assets", icon: Image },
  { section: "Knowledge", href: "/knowledge/sync", label: "Sync", icon: RefreshCw },
  { section: "Knowledge", href: "/knowledge/import-vault", label: "Importar vault", icon: Plus },
  { section: "Knowledge", href: "/knowledge/quality", label: "Quality", icon: CheckSquare },
  { section: "Knowledge", href: "/kb", label: "Golden Dataset", icon: BookOpen },
  { section: "Configuracoes", href: "/wa-validator", label: "ChatBot", icon: GitBranch },
  { section: "Configuracoes", href: "/tools", label: "Tools", icon: Wrench },
  { section: "Configuracoes", href: "/settings", label: "Settings", icon: Settings },
  { section: "Configuracoes", href: "/logs", label: "Logs", icon: ScrollText },
];

const NAV_TRANSLATIONS: Record<UiLanguage, Record<string, string>> = {
  "pt-BR": {
    Create: "Criar",
    Messages: "Mensagens",
    Import: "Importar",
    Assets: "Assets",
    Knowledge: "Conhecimento",
    Sync: "Sincronizar",
    Quality: "Qualidade",
    Configuracoes: "Configurações",
    Tools: "Ferramentas",
    Settings: "Configurações",
    Logs: "Logs",
  },
  en: {
    Grafos: "Graphs",
    Create: "Create",
    Messages: "Messages",
    Import: "Import",
    Marketing: "Marketing",
    Assets: "Assets",
    Knowledge: "Knowledge",
    Sync: "Sync",
    Quality: "Quality",
    Configuracoes: "Settings",
    Tools: "Tools",
    Settings: "Settings",
    Logs: "Logs",
    Cliente: "Client",
    Todos: "All",
    "Carregando clientes...": "Loading clients...",
    Sair: "Sign out",
  },
};

function navText(language: UiLanguage, value: string) {
  return NAV_TRANSLATIONS[language][value] || value;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [persona, setPersona] = useState("");
  const [personas, setPersonas] = useState<any[]>([]);
  const [user, setUser] = useState<any>(null);
  const [language, setLanguage] = useState<UiLanguage>("pt-BR");
  const [sessionPhase, setSessionPhase] = useState<"resolving" | "internal" | "redirecting" | "error">("resolving");
  const [sessionRetry, setSessionRetry] = useState(0);

  useEffect(() => {
    if (
      pathname === "/login"
      || pathname.startsWith("/clientes/")
      || pathname === "/account/change-password"
    ) return;
    if (user && (user.account_type || "internal") !== "client") {
      setSessionPhase("internal");
      return;
    }
    let active = true;
    setSessionPhase("resolving");
    setLanguage(getStoredLanguage());
    const saved = window.localStorage.getItem("ai-brain-persona-slug");
    api.me()
      .then((session) => {
        if (!active) return;
        const list = session?.personas || [];
        const sessionUser = session?.user || null;
        setUser(sessionUser);
        setPersonas(list);
        const savedExists = saved && list.some((p: any) => p.slug === saved);
        const mustSelect = (session?.account_type || sessionUser?.account_type) === "client";
        setPersona(savedExists ? saved : mustSelect ? list[0]?.slug || "" : "");
        if (sessionUser?.must_change_password && pathname !== "/account/change-password") {
          setSessionPhase("redirecting");
          router.replace(mandatoryPasswordDestination(session, pathname));
        } else if (mustSelect) {
          setSessionPhase("redirecting");
          router.replace(resolveSessionDestination(session, pathname));
        } else {
          setSessionPhase("internal");
        }
      })
      .catch((error) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          const next = pathname === "/" ? "/" : pathname;
          router.replace(`/login?next=${encodeURIComponent(next)}`);
          return;
        }
        setSessionPhase("error");
        setUser(null);
        setPersonas([]);
        setPersona(saved || "");
      });
    return () => {
      active = false;
    };
  }, [pathname, router, sessionRetry]);

  useEffect(() => {
    function handleLanguageChange(event: Event) {
      const nextLanguage = (event as CustomEvent<{ language?: UiLanguage }>).detail?.language;
      setLanguage(nextLanguage === "en" ? "en" : "pt-BR");
    }
    window.addEventListener(UI_LANGUAGE_EVENT, handleLanguageChange as EventListener);
    return () => window.removeEventListener(UI_LANGUAGE_EVENT, handleLanguageChange as EventListener);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    const selected = personas.find((p) => p.slug === persona);
    if (persona) {
      window.localStorage.setItem("ai-brain-persona-slug", persona);
    } else {
      window.localStorage.removeItem("ai-brain-persona-slug");
    }
    if (selected?.id) {
      window.localStorage.setItem("ai-brain-persona-id", selected.id);
    } else {
      window.localStorage.removeItem("ai-brain-persona-id");
    }
    window.dispatchEvent(new CustomEvent("ai-brain-persona-change", {
      detail: { slug: persona, id: selected?.id || "" },
    }));
  }, [persona, personas]);

  useEffect(() => {
    function handlePersonaChange(event: Event) {
      const nextSlug = (event as CustomEvent<{ slug?: string }>).detail?.slug || "";
      setPersona((current) => (current === nextSlug ? current : nextSlug));
    }
    window.addEventListener("ai-brain-persona-change", handlePersonaChange as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", handlePersonaChange as EventListener);
  }, []);

  async function handleLogout() {
    try {
      await api.logout();
    } finally {
      window.localStorage.removeItem("ai-brain-persona-slug");
      window.localStorage.removeItem("ai-brain-persona-id");
      router.replace("/login");
    }
  }

  if (
    pathname === "/login"
    || pathname.startsWith("/clientes/")
    || pathname === "/account/change-password"
  ) {
    return <>{children}</>;
  }

  if (sessionPhase === "resolving" || sessionPhase === "redirecting") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-obs-bg text-obs-subtle">
        <div className="rounded-xl border border-black/10 bg-white/70 px-5 py-4 text-sm shadow-sm">
          Validando acesso...
        </div>
      </main>
    );
  }

  if (sessionPhase === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-obs-bg px-6 text-obs-text">
        <section className="max-w-md rounded-2xl border border-black/10 bg-white/75 p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold">Nao foi possivel validar sua sessao</h1>
          <p className="mt-2 text-sm text-obs-subtle">
            Confirme o backend e tente novamente. Nenhuma tela administrativa foi carregada.
          </p>
          <button
            type="button"
            className="mt-5 rounded-lg bg-obs-violet px-4 py-2 text-sm font-medium text-white"
            onClick={() => setSessionRetry((value) => value + 1)}
          >
            Tentar novamente
          </button>
        </section>
      </main>
    );
  }

  const isAgency = user?.account_type === "agency";
  const visibleNav = isAgency
    ? [...nav, { section: "Configuracoes", href: "/access", label: "Acessos", icon: Users }]
    : user?.role === "admin"
      ? [...nav, { section: "Configuracoes", href: "/access", label: "Acessos", icon: Users }]
      : nav;

  return (
    <div className="flex min-h-screen text-obs-text">
      <aside className="flex w-52 shrink-0 flex-col bg-obs-surface/70 backdrop-blur-glass [border-right:1px_solid_var(--border-glass)]">
        <div className="px-4 py-5 [border-bottom:1px_solid_var(--border-glass-soft)]">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-obs-violet to-[#a78bfa] text-sm font-black text-[#050709]">
              B
            </div>
            <span className="text-sm font-bold tracking-tight text-obs-text">Brain AI</span>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
          {visibleNav.map(({ href, label, icon: Icon, section }, idx) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            const prevSection = idx > 0 ? visibleNav[idx - 1].section : null;
            const showHeader = section && section !== prevSection;
            return (
              <div key={href}>
                {showHeader && (
                  <p className="px-3 pb-1.5 pt-4 text-[9px] font-semibold uppercase tracking-[0.12em] text-obs-faint">
                    {navText(language, section)}
                  </p>
                )}
                <Link
                  href={href}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-all ${
                    active
                      ? "bg-obs-violet/10 font-medium text-obs-violet ring-1 ring-obs-violet/15"
                      : "text-obs-subtle hover:bg-white/[0.05] hover:text-obs-text"
                  }`}
                >
                  <Icon size={13} />
                  {navText(language, label)}
                </Link>
              </div>
            );
          })}
        </nav>
      </aside>

      <div className="flex min-h-screen flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-4 bg-obs-surface/55 backdrop-blur-glass px-6 [border-bottom:1px_solid_var(--border-glass)]">
          <div className="flex items-center gap-2 rounded-full bg-white/[0.05] px-3 py-1.5 [border:1px_solid_var(--border-glass)]">
            <Settings size={13} className="text-obs-faint" />
            <span className="hidden text-[10px] font-medium uppercase tracking-[0.16em] text-obs-faint sm:inline">
              {navText(language, "Cliente")}
            </span>
            <select
              className="min-w-36 bg-transparent text-xs font-medium text-obs-text outline-none"
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
            >
              {personas.length > 0 ? (
                <>
                  <option className="bg-obs-raised text-obs-text" value="">{navText(language, "Todos")}</option>
                  {personas.map((p) => (
                    <option className="bg-obs-raised text-obs-text" key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </>
              ) : (
                <option className="bg-obs-raised text-obs-text" value="">{navText(language, "Carregando clientes...")}</option>
              )}
            </select>
          </div>
          <div className="ml-auto hidden text-[10px] tracking-wide text-obs-faint sm:block">
            {user?.name || user?.email || "Brain AI Platform"}
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-black/10 bg-white/55 text-obs-subtle shadow-sm transition hover:bg-white hover:text-obs-text"
            aria-label={navText(language, "Sair")}
            title={navText(language, "Sair")}
          >
            <LogOut size={14} />
          </button>
        </header>

        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
