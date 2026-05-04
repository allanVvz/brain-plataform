"use client";

import "./globals.css";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Activity,
  BookOpen,
  CheckSquare,
  Image,
  LayoutDashboard,
  MessageSquare,
  Network,
  RefreshCw,
  ScrollText,
  Settings,
  Sparkles,
  TestTube2,
  UserCircle,
  Users,
  Wrench,
} from "lucide-react";

const nav = [
  { section: null, href: "/", label: "Dashboard", icon: LayoutDashboard },
  { section: null, href: "/pipeline", label: "Pipeline", icon: Activity },
  { section: null, href: "/knowledge/graph", label: "Grafos", icon: Network },
  { section: null, href: "/marketing/criacao", label: "Criar", icon: Sparkles },

  { section: "CRM", href: "/leads", label: "Leads", icon: Users },
  { section: "CRM", href: "/messages", label: "Mensagens", icon: MessageSquare },

  { section: "Marketing", href: "/persona", label: "Persona", icon: UserCircle },
  { section: "Marketing", href: "/marketing/assets", label: "Assets", icon: Image },

  { section: "Knowledge", href: "/knowledge/quality", label: "Curadoria", icon: CheckSquare },
  { section: "Knowledge", href: "/kb", label: "KB Validada", icon: BookOpen },
  { section: "Knowledge", href: "/knowledge/sync", label: "Sync Vault", icon: RefreshCw },

  { section: "Configurações", href: "/tools", label: "Tools", icon: Wrench },
  { section: "Configurações", href: "/wa-validator", label: "WA Validator", icon: TestTube2 },
  { section: "Configurações", href: "/logs", label: "Logs", icon: ScrollText },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [persona, setPersona] = useState("");
  const [personas, setPersonas] = useState<any[]>([]);

  useEffect(() => {
    const saved = window.localStorage.getItem("ai-brain-persona-slug");
    api.personas()
      .then((list) => {
        setPersonas(list);
        const savedExists = saved && list.some((p: any) => p.slug === saved);
        setPersona(savedExists ? saved : "");
      })
      .catch(() => setPersona(saved || ""));
  }, []);

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

  return (
    <html lang="pt-BR">
      <body className="flex min-h-screen bg-obs-base text-obs-text" style={{ background: "#080b12" }}>
        <aside className="flex w-52 shrink-0 flex-col border-r border-white/06 bg-[#0e1118]/95">
          <div className="border-b border-white/06 px-4 py-5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#7c6fff] to-[#a78bfa] text-sm font-black text-[#050709]">
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
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-xs transition-all ${
                      active
                        ? "bg-obs-violet/12 font-medium text-obs-violet"
                        : "text-obs-subtle hover:text-obs-text"
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
          <header className="flex h-11 shrink-0 items-center gap-4 border-b border-white/06 bg-[#0e1118]/90 px-6">
            <div className="flex items-center gap-2 rounded-lg border border-white/08 bg-white/[0.04] px-2 py-1 shadow-sm">
              <Settings size={13} className="text-obs-faint" />
              <span className="hidden text-[10px] font-medium uppercase tracking-[0.16em] text-obs-faint sm:inline">
                Cliente
              </span>
              <select
                className="min-w-36 bg-transparent text-xs font-medium text-obs-text outline-none [color-scheme:dark]"
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
              >
                {personas.length > 0 ? (
                  <>
                    <option className="bg-[#11151f] text-obs-text" value="">Todos</option>
                    {personas.map((p) => (
                      <option className="bg-[#11151f] text-obs-text" key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                  </>
                ) : (
                  <option className="bg-[#11151f] text-obs-text" value="">Carregando clientes...</option>
                )}
              </select>
            </div>
            <div className="ml-auto text-[10px] tracking-wide text-obs-faint">AI Brain Platform</div>
          </header>

          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
