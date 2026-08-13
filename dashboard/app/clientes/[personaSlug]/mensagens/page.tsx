"use client";

import { PlugZap } from "lucide-react";
import Link from "next/link";
import { MessagesLayout } from "@/app/messages/MessagesLayout";
import { usePortal } from "../PortalContext";

export default function ClientMessagesPage() {
  const { personaSlug, capabilities, channel } = usePortal();
  return (
    <div className="flex h-full flex-col">
      {/* O header sumiu desta rota (título fica na coluna de lista); o
          `main` que envolve esta página também não tem mais padding, então
          este banner cuida do próprio respiro. */}
      {!channel.configured && (
        <section className="mx-4 mt-4 flex flex-col gap-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 sm:flex-row sm:items-center lg:mx-8 lg:mt-8">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white text-amber-700 shadow-sm">
            <PlugZap size={20} />
          </span>
          <div className="flex-1">
            <h2 className="font-semibold text-slate-950">Conecte seu canal para começar</h2>
            <p className="mt-1 text-sm text-slate-600">
              A página de mensagens já está disponível. Novas conversas aparecerão após a conexão.
            </p>
          </div>
          <Link
            href={`/clientes/${personaSlug}/configuracoes`}
            className="rounded-xl bg-slate-950 px-4 py-2.5 text-center text-sm font-medium text-white"
          >
            Abrir configurações
          </Link>
        </section>
      )}
      <MessagesLayout
        portalSlug={personaSlug}
        canEdit={capabilities.edit}
        heightClassName={channel.configured ? undefined : "h-[calc(100vh-11rem)] lg:h-[calc(100vh-9rem)]"}
      />
    </div>
  );
}
