"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Lock, Mail, Sparkles } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import {
  resolveSessionDestination,
  safeLocalTarget,
} from "@/lib/session-routing";

export function normalizeLoginError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Email/usuário ou senha inválidos.";
    if (error.detail.includes("Usuario inativo")) {
      return "Usuário inativo. Fale com um administrador.";
    }
    if (error.detail.includes("Nenhuma persona")) {
      return "Nenhuma persona foi atribuída a este usuário.";
    }
    if (error.kind === "network" || error.kind === "unavailable") {
      return "O serviço de autenticação está indisponível. Tente novamente em instantes.";
    }
  }
  return "Não foi possível entrar agora. Tente novamente.";
}

export default function LoginPage() {
  const router = useRouter();
  const [safeTarget, setSafeTarget] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const requestedTarget = new URLSearchParams(window.location.search).get("next") || "";
    const target = safeLocalTarget(requestedTarget);
    setSafeTarget(target);
    api.me()
      .then((session) => {
        router.replace(resolveSessionDestination(session, target));
      })
      .catch(() => {});
  }, [router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const session = await api.login({ identifier: identifier.trim(), password, remember });
      const personas = session?.personas || [];
      const firstPersona = personas[0];
      if (firstPersona?.slug) {
        window.localStorage.setItem("ai-brain-persona-slug", firstPersona.slug);
        window.localStorage.setItem("ai-brain-persona-id", firstPersona.id || "");
      } else {
        window.localStorage.removeItem("ai-brain-persona-slug");
        window.localStorage.removeItem("ai-brain-persona-id");
      }
      router.replace(resolveSessionDestination(session, safeTarget));
    } catch (err) {
      setError(normalizeLoginError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-label="Login Brain AI">
        <div className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/50 bg-white/20 text-white shadow-lg backdrop-blur">
              <Sparkles size={20} />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-white/70">Brain AI</p>
              <h1 className="login-title">Login</h1>
            </div>
          </div>
        </div>

        <p className="login-subtitle">Acesse sua conta para operar personas, CRM e conhecimento.</p>

        <form className="mt-9 space-y-5" onSubmit={onSubmit}>
          <label className="block">
            <span className="mb-2 block text-sm font-semibold text-white/86">Email ou usuario</span>
            <span className="relative block">
              <input
                className="login-input pr-12"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                autoComplete="username"
                placeholder="operador@empresa.com"
                autoFocus
                required
              />
              <Mail className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-white/70" size={19} />
            </span>
          </label>

          <label className="block">
            <span className="mb-2 block text-sm font-semibold text-white/86">Senha</span>
            <span className="relative block">
              <input
                className="login-input px-[18px] pr-24"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder="Digite sua senha"
                required
              />
              <Lock className="pointer-events-none absolute right-14 top-1/2 -translate-y-1/2 text-white/70" size={18} />
              <button
                type="button"
                className="absolute right-4 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-white/78 transition hover:bg-white/14 hover:text-white"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </span>
          </label>

          <label className="flex cursor-pointer items-center gap-3 text-sm font-medium text-white/82">
            <input
              type="checkbox"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
              className="login-checkbox"
            />
            lembrar de mim
          </label>

          {error && (
            <div className="login-error" role="alert" aria-live="assertive">
              {error}
            </div>
          )}

          <button className="login-button" type="submit" disabled={loading} aria-busy={loading}>
            {loading ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </section>
    </main>
  );
}
