"use client";
import "./globals.css";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import {
  LayoutDashboard, Users, MessageSquare, BookOpen,
  Image, Plug, Cpu, ScrollText, Lightbulb, UserCircle,
  RefreshCw, CheckSquare, Upload, Activity, MessageCircle, TestTube2,
} from "lucide-react";

const nav = [
  { section: null,         href: "/",                    label: "Dashboard",    icon: LayoutDashboard },
  { section: null,         href: "/pipeline",            label: "Pipeline",     icon: Activity },
  { section: null,         href: "/persona",             label: "Persona",      icon: UserCircle },
  { section: null,         href: "/leads",               label: "Leads",        icon: Users },
  { section: null,         href: "/messages",            label: "Mensagens",    icon: MessageSquare },
  { section: "Knowledge",  href: "/kb",                     label: "KB Validada",  icon: BookOpen },
  { section: "Knowledge",  href: "/knowledge/intake",    label: "KB Intake",    icon: MessageCircle },
  { section: "Knowledge",  href: "/knowledge/sync",      label: "Sync Vault",   icon: RefreshCw },
  { section: "Knowledge",  href: "/knowledge/validate",  label: "Validar",      icon: CheckSquare },
  { section: "Knowledge",  href: "/knowledge/upload",    label: "Upload",       icon: Upload },
  { section: "Validação",   href: "/wa-validator",        label: "WA Validator", icon: TestTube2 },
  { section: null,         href: "/assets",              label: "Assets",       icon: Image },
  { section: null,         href: "/integrations",        label: "Integrações",  icon: Plug },
  { section: null,         href: "/mcp",                 label: "MCP",          icon: Cpu },
  { section: null,         href: "/logs",                label: "Logs",         icon: ScrollText },
  { section: null,         href: "/insights",            label: "Insights",     icon: Lightbulb },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [persona, setPersona] = useState("tock-fatal");
  const [personas, setPersonas] = useState<any[]>([]);

  useEffect(() => {
    api.personas().then(setPersonas).catch(() => {});
  }, []);

  return (
    <html lang="pt-BR">
      <body className="bg-brain-bg text-white min-h-screen flex">
        {/* Sidebar */}
        <aside className="w-52 bg-brain-surface border-r border-brain-border flex flex-col shrink-0">
          <div className="px-4 py-5 border-b border-brain-border">
            <span className="font-bold text-brain-accent text-lg tracking-tight">AI Brain</span>
          </div>
          <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
            {nav.map(({ href, label, icon: Icon, section }, idx) => {
              const active = pathname === href || (href !== "/" && pathname.startsWith(href));
              const prevSection = idx > 0 ? nav[idx - 1].section : null;
              const showHeader = section && section !== prevSection;
              return (
                <div key={href}>
                  {showHeader && (
                    <p className="text-[10px] text-brain-muted uppercase tracking-widest px-3 pt-3 pb-1">{section}</p>
                  )}
                  <Link
                    href={href}
                    className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                      active
                        ? "bg-brain-accent/20 text-brain-accent font-medium"
                        : "text-brain-muted hover:text-white hover:bg-white/5"
                    }`}
                  >
                    <Icon size={15} />
                    {label}
                  </Link>
                </div>
              );
            })}
          </nav>
        </aside>

        {/* Main */}
        <div className="flex-1 flex flex-col min-h-screen">
          {/* Topbar */}
          <header className="h-12 border-b border-brain-border bg-brain-surface flex items-center px-6 gap-4 shrink-0">
            <select
              className="bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1"
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
            >
              {personas.length > 0
                ? personas.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)
                : <option value="tock-fatal">Tock Fatal</option>}
            </select>
            <div className="ml-auto text-xs text-brain-muted">AI Brain Platform</div>
          </header>

          {/* Content */}
          <main className="flex-1 p-6 overflow-y-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
