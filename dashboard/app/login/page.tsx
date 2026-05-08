"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Lock, Mail, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

function normalizeError(message: string) {
  if (message.includes("Usuario inativo")) return "Usuario inativo. Fale com um administrador.";
  if (message.includes("Nenhuma persona")) return "Nenhuma persona foi atribuida a este usuario.";
  if (message.includes("401")) return "Email/usuario ou senha invalidos.";
  return "Nao foi possivel entrar agora. Tente novamente.";
}

export default function LoginPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me()
      .then(() => router.replace("/"))
      .catch(() => {});
  }, [router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const session = await api.login({ identifier, password, remember });
      const personas = session?.personas || [];
      const firstPersona = personas[0];
      if (firstPersona?.slug) {
        window.localStorage.setItem("ai-brain-persona-slug", firstPersona.slug);
        window.localStorage.setItem("ai-brain-persona-id", firstPersona.id || "");
      } else {
        window.localStorage.removeItem("ai-brain-persona-slug");
        window.localStorage.removeItem("ai-brain-persona-id");
      }
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(normalizeError(err instanceof Error ? err.message : String(err)));
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
            <div className="login-error" role="alert">
              {error}
            </div>
          )}

          <button className="login-button" type="submit" disabled={loading}>
            {loading ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </section>
    </main>
  );
}
