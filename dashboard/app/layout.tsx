"use client";

import "./globals.css";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
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
  { section: "Marketing", href: "/marketing/assets", label: "Assets", icon: Image },

    { section: "Knowledge", href: "/knowledge/sync", label: "Sync", icon: RefreshCw },
  { section: "Knowledge", href: "/knowledge/quality", label: "Quality", icon: CheckSquare },
  { section: "Knowledge", href: "/kb", label: "Knowledge Base", icon: BookOpen },

  { section: "Configurações", href: "/wa-validator", label: "ChatBot", icon: GitBranch },
  { section: "Configurações", href: "/tools", label: "Tools", icon: Wrench },
  { section: "Configurações", href: "/settings", label: "Settings", icon: Settings },
  { section: "Configurações", href: "/logs", label: "Logs", icon: ScrollText },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [persona, setPersona] = useState("");
  const [personas, setPersonas] = useState<any[]>([]);
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    if (pathname === "/login") return;
    const saved = window.localStorage.getItem("ai-brain-persona-slug");
    api.me()
      .then((session) => {
        const list = session?.personas || [];
        setUser(session?.user || null);
        setPersonas(list);
        const savedExists = saved && list.some((p: any) => p.slug === saved);
        const canSeeAll = session?.user?.role === "admin";
        setPersona(savedExists ? saved : (canSeeAll ? "" : (list[0]?.slug || "")));
      })
      .catch(() => {
        setUser(null);
        setPersonas([]);
        setPersona(saved || "");
      });
  }, [pathname]);

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

  async function handleLogout() {
    try {
      await api.logout();
    } finally {
      window.localStorage.removeItem("ai-brain-persona-slug");
      window.localStorage.removeItem("ai-brain-persona-id");
      router.replace("/login");
      router.refresh();
    }
  }

  if (pathname === "/login") {
    return (
      <html lang="pt-BR" suppressHydrationWarning>
        <body>{children}</body>
      </html>
    );
  }

  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        {/* Apply theme before hydration to avoid FOUC */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('ai-brain-theme');document.documentElement.setAttribute('data-theme',t==='dark'?'dark':'clean');}catch(e){document.documentElement.setAttribute('data-theme','clean');}})();`,
          }}
        />
      </head>
      <body className="flex min-h-screen text-obs-text">
        <aside className="flex w-52 shrink-0 flex-col bg-obs-surface/70 backdrop-blur-glass [border-right:1px_solid_var(--border-glass)]">
          <div className="px-4 py-5 [border-bottom:1px_solid_var(--border-glass-soft)]">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-obs-violet to-[#a78bfa] text-sm font-black text-[#050709]">
                B
              </div>
              <span className="text-sm font-bold tracking-tight text-obs-text">AI Brain</span>
            </div>
          </div>

          <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
            {nav.map(({ href, label, icon: Icon, section }, idx) => {
              const active = pathname === href || (href !== "/" && pathname.startsWith(href));
              const prevSection = idx > 0 ? nav[idx - 1].section : null;
              const showHeader = section && section !== prevSection;
              return (
                <div key={href}>
                  {showHeader && (
                    <p className="px-3 pb-1.5 pt-4 text-[9px] font-semibold uppercase tracking-[0.12em] text-obs-faint">
                      {section}
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
                    {label}
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
                Cliente
              </span>
              <select
                className="min-w-36 bg-transparent text-xs font-medium text-obs-text outline-none"
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
              >
                {personas.length > 0 ? (
                  <>
                    {user?.role === "admin" && <option className="bg-obs-raised text-obs-text" value="">Todos</option>}
                    {personas.map((p) => (
                      <option className="bg-obs-raised text-obs-text" key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                  </>
                ) : (
                  <option className="bg-obs-raised text-obs-text" value="">Carregando clientes...</option>
                )}
              </select>
            </div>
            <div className="ml-auto hidden text-[10px] tracking-wide text-obs-faint sm:block">
              {user?.name || user?.email || "AI Brain Platform"}
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-black/10 bg-white/55 text-obs-subtle shadow-sm transition hover:bg-white hover:text-obs-text"
              aria-label="Sair"
              title="Sair"
            >
              <LogOut size={14} />
            </button>
          </header>

          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
