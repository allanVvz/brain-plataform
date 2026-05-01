"use client";
import "./globals.css";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import {
  LayoutDashboard, Users, MessageSquare, BookOpen,
  Image, Plug, Cpu, ScrollText, Lightbulb, UserCircle,
  RefreshCw, CheckSquare, Activity, MessageCircle, TestTube2,
  GitMerge, Folder, Layers, Network,
} from "lucide-react";

const nav = [
  { section: null,          href: "/",                      label: "Dashboard",      icon: LayoutDashboard },
  { section: null,          href: "/pipeline",              label: "Pipeline",        icon: Activity },
  { section: null,          href: "/persona",               label: "Persona",         icon: UserCircle },
  { section: null,          href: "/leads",                 label: "Leads",           icon: Users },
  { section: null,          href: "/messages",              label: "Mensagens",       icon: MessageSquare },

  { section: "Knowledge",   href: "/knowledge/graph",       label: "Grafo",           icon: Network },
  { section: "Knowledge",   href: "/knowledge/capture",     label: "Capturar",        icon: MessageCircle },
  { section: "Knowledge",   href: "/knowledge/quality",     label: "Curadoria",       icon: CheckSquare },
  { section: "Knowledge",   href: "/knowledge/assets",      label: "Assets",          icon: Image },
  { section: "Knowledge",   href: "/kb",                    label: "KB Validada",     icon: BookOpen },
  { section: "Knowledge",   href: "/knowledge/sync",        label: "Sync Vault",      icon: RefreshCw },

  { section: "Validação",   href: "/wa-validator",          label: "WA Validator",    icon: TestTube2 },

  { section: null,          href: "/integrations",          label: "Integrações",     icon: Plug },
  { section: null,          href: "/mcp",                   label: "MCP",             icon: Cpu },
  { section: null,          href: "/logs",                  label: "Logs",            icon: ScrollText },
  { section: null,          href: "/insights",              label: "Insights",        icon: Lightbulb },
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
        setPersona(savedExists ? saved : (list[0]?.slug || "tock-fatal"));
      })
      .catch(() => setPersona(saved || "tock-fatal"));
  }, []);

  useEffect(() => {
    if (!persona) return;
    const selected = personas.find((p) => p.slug === persona);
    window.localStorage.setItem("ai-brain-persona-slug", persona);
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
      <body className="bg-obs-base text-obs-text min-h-screen flex" style={{ background: "#080b12" }}>
        {/* Sidebar */}
        <aside className="w-52 shrink-0 flex flex-col border-r" style={{ background: "rgba(14,17,24,0.95)", borderColor: "rgba(255,255,255,0.06)" }}>
          {/* Logo */}
          <div className="px-4 py-5" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center font-black text-sm"
                style={{ background: "linear-gradient(135deg, #7c6fff, #a78bfa)", color: "#050709" }}>
                B
              </div>
              <span className="font-bold text-obs-text text-sm tracking-tight">AI Brain</span>
            </div>
          </div>

          {/* Nav */}
          <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
            {nav.map(({ href, label, icon: Icon, section }, idx) => {
              const active = pathname === href || (href !== "/" && pathname.startsWith(href));
              const prevSection = idx > 0 ? nav[idx - 1].section : null;
              const showHeader = section && section !== prevSection;
              return (
                <div key={href}>
                  {showHeader && (
                    <p className="text-[9px] text-obs-faint uppercase tracking-[0.12em] px-3 pt-4 pb-1.5 font-semibold">
                      {section}
                    </p>
                  )}
                  <Link href={href}
                    className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-xs transition-all ${
                      active
                        ? "text-obs-violet font-medium"
                        : "text-obs-subtle hover:text-obs-text"
                    }`}
                    style={active ? { background: "rgba(124,111,255,0.12)" } : {}}>
                    <Icon size={13} />
                    {label}
                  </Link>
                </div>
              );
            })}
          </nav>
        </aside>

        {/* Main */}
        <div className="flex-1 flex flex-col min-h-screen overflow-hidden">
          {/* Topbar */}
          <header className="h-11 flex items-center px-6 gap-4 shrink-0"
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(14,17,24,0.90)" }}>
            <select
              className="text-xs text-obs-text rounded-lg px-2 py-1 focus:outline-none"
              style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)" }}
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
            >
              {personas.length > 0
                ? personas.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)
                : <option value="">Carregando clientes...</option>}
            </select>
            <div className="ml-auto text-[10px] text-obs-faint tracking-wide">AI Brain Platform</div>
          </header>

          {/* Content */}
          <main className="flex-1 p-6 overflow-y-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
