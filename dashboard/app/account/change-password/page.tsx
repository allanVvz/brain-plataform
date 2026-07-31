"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function ChangePasswordLegacyRedirect() {
  const router = useRouter();

  useEffect(() => {
    api.me()
      .then((session) => {
        if ((session?.account_type || session?.user?.account_type) === "client") {
          const slug = (session?.personas || [])[0]?.slug;
          router.replace(
            slug
              ? `/clientes/${encodeURIComponent(slug)}/configuracoes?section=security`
              : "/login",
          );
          return;
        }
        router.replace("/settings?tab=security");
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  return <p className="text-sm text-obs-subtle">Redirecionando para Segurança…</p>;
}
