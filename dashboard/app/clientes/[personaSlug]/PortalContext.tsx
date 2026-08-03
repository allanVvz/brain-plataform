"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  LogOut,
  Megaphone,
  MessageSquare,
  Settings,
  Sparkles,
  UserCircle,
  Users,
} from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError, api } from "@/lib/api";

type Capabilities = {
  view: boolean;
  edit: boolean;
  manage: boolean;
  manage_members: boolean;
};

type PortalContextValue = {
  personaSlug: string;
  persona: any;
  user: any;
  accessProfile: string;
  capabilities: Capabilities;
  channel: { configured: boolean; status: string; provider?: string | null };
};

const PortalContext = createContext<PortalContextValue | null>(null);

// "Configurações" is deliberately not in this list: it already lives in
// the account dropdown below (opens upward, near the user's name), and
// having it here too just duplicates the same destination in two places.
const links = [
  { key: "mensagens", label: "Mensagens", icon: MessageSquare },
  { key: "leads", label: "Leads", icon: Users },
  { key: "pipeline", label: "Pipeline", icon: Activity },
  { key: "disparos", label: "Disparos", icon: Megaphone },
];

// Every route's title, shown in the persistent header instead of each page
// rendering its own — keeps one line of truth instead of two.
const PAGE_TITLES: Record<string, string> = {
  mensagens: "Mensagens",
  leads: "Leads",
  pipeline: "Pipeline",
  disparos: "Disparos",
  configuracoes: "Configurações",
};

export function usePortal() {
  const value = useContext(PortalContext);
  if (!value) throw new Error("usePortal deve ser usado dentro do portal do cliente.");
  return value;
}

export default function PortalProvider({
  personaSlug,
  children,
}: {
  personaSlug: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [state, setState] = useState<PortalContextValue | null>(null);
  const [error, setError] = useState("");
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.me(), api.clientPages()])
      .then(([session, pages]) => {
        const persona = (session?.personas || []).find(
          (item: any) => item.slug === personaSlug,
        );
        const page = pages.find((item) => item.slug === personaSlug);
        if (!persona || !page) throw new Error("403");
        const capabilities = persona.capabilities || page.capabilities || {};
        if (active) {
          setState({
            personaSlug,
            persona,
            user: session.user,
            accessProfile: session.access_profile || "client_viewer",
            capabilities: {
              view: Boolean(capabilities.view),
              edit: Boolean(capabilities.edit),
              manage: Boolean(capabilities.manage),
              manage_members: Boolean(capabilities.manage_members),
            },
            channel: page.channel,
          });
        }
      })
      .catch((reason) => {
        if (reason instanceof ApiError && reason.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        if (active) setError("Acesso negado para esta persona.");
      });
    return () => {
      active = false;
    };
  }, [pathname, personaSlug, router]);

  const base = `/clientes/${personaSlug}`;
  const value = useMemo(() => state, [state]);
  const pageTitle = useMemo(() => {
    const segment = pathname.replace(base, "").split("/").filter(Boolean)[0];
    return (segment && PAGE_TITLES[segment]) || "Mensagens";
  }, [pathname, base]);

  async function logout() {
    await api.logout().catch(() => undefined);
    router.replace("/login");
  }

  if (error) {
    return (
      <main className="portal-theme grid min-h-screen place-items-center bg-[#f4f6fa] p-6">
        <section className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-950">Acesso negado</h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
        </section>
      </main>
    );
  }

  if (!value) {
    return (
      <main
        className="portal-theme grid min-h-screen place-items-center bg-[#f4f6fa]"
        aria-busy="true"
      >
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-violet-600" />
          Validando seu acesso…
        </div>
      </main>
    );
  }

  return (
    <PortalContext.Provider value={value}>
      <div className="portal-theme flex min-h-screen bg-[#f4f6fa] text-slate-950">
        <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
          <div className="border-b border-slate-100 px-6 py-6">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-950 text-white shadow-sm">
                <Sparkles size={17} />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{value.persona.name}</p>
                <p className="text-xs text-slate-500">Portal do cliente</p>
              </div>
            </div>
          </div>
          <nav className="flex-1 space-y-1 p-4" aria-label="Navegação do portal">
            {links.map(({ key, label, icon: Icon }) => {
              const href = `${base}/${key}`;
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <Link
                  key={key}
                  href={href}
                  className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                    active
                      ? "bg-slate-950 text-white shadow-sm"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
                  }`}
                >
                  <Icon size={17} />
                  {label}
                </Link>
              );
            })}
          </nav>
          <div className="relative border-t border-slate-100 p-3">
            {accountMenuOpen && (
              <div className="absolute bottom-full left-3 right-3 mb-2 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
                <Link
                  href={`${base}/configuracoes`}
                  onClick={() => setAccountMenuOpen(false)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-100 hover:text-slate-950"
                >
                  <Settings size={15} /> Configurações
                </Link>
                <button
                  type="button"
                  onClick={logout}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-600 transition hover:bg-slate-100 hover:text-slate-950"
                >
                  <LogOut size={15} /> Sair da conta
                </button>
              </div>
            )}
            <button
              type="button"
              onClick={() => setAccountMenuOpen((open) => !open)}
              className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left transition hover:bg-slate-100"
              aria-label="Abrir menu da conta"
              aria-expanded={accountMenuOpen}
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-950/5 text-slate-600">
                <UserCircle size={17} />
              </span>
              <span className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-slate-700">
                  {value.user?.name || value.user?.email}
                </p>
                <p className="truncate text-[11px] text-slate-500">
                  {value.accessProfile.replaceAll("_", " ")}
                </p>
              </span>
            </button>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur lg:px-8">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-950">{pageTitle}</p>
              <p className="hidden truncate text-xs text-slate-500 lg:block">
                {value.persona.name} · Ambiente seguro · dados exclusivos da sua operação
              </p>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2 text-xs text-slate-500">
              <span
                className={`h-2 w-2 rounded-full ${
                  value.channel.status === "connected" ? "bg-emerald-500" : "bg-amber-400"
                }`}
              />
              {value.channel.configured ? value.channel.status : "Canal não conectado"}
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1500px] p-4 pb-24 lg:p-8">
            {children}
          </main>
        </div>

        <nav
          className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-slate-200 bg-white/95 px-1 pb-[max(.4rem,env(safe-area-inset-bottom))] pt-1.5 backdrop-blur lg:hidden"
          aria-label="Navegação do portal"
        >
          {links.map(({ key, label, icon: Icon }) => {
            const href = `${base}/${key}`;
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={key}
                href={href}
                className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-lg text-[10px] font-medium ${
                  active ? "text-violet-700" : "text-slate-500"
                }`}
              >
                <Icon size={18} />
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
    </PortalContext.Provider>
  );
}
