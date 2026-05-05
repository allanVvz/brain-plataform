import type { Config } from "tailwindcss";

const rgbVar = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Neutral foreground scrim ─────────────────────────────────
        // `text-white`, `bg-white/X`, `border-white/X` resolve to a
        // theme-aware foreground (white on dark, near-black on clean).
        white: rgbVar("--scrim-fg"),

        // ── Legacy tokens (maintained for backwards compat) ──────────
        brain: {
          bg:      rgbVar("--obs-base"),
          surface: rgbVar("--obs-surface"),
          border:  rgbVar("--scrim-fg"),
          accent:  rgbVar("--obs-violet"),
          muted:   rgbVar("--obs-subtle"),
        },
        // ── Obsidiana Design System (theme-aware via CSS vars) ──────
        obs: {
          deep:    rgbVar("--obs-deep"),
          base:    rgbVar("--obs-base"),
          surface: rgbVar("--obs-surface"),
          raised:  rgbVar("--obs-raised"),

          line:        "var(--border-glass-soft)",
          "line-soft": "var(--border-glass-soft)",
          "line-strong": "var(--border-glass-strong)",
          glow:    "rgb(var(--obs-violet) / 0.30)",

          violet:        rgbVar("--obs-violet"),
          "violet-soft": "rgb(var(--obs-violet) / 0.15)",
          "violet-glow": "rgb(var(--obs-violet) / 0.08)",

          slate:        rgbVar("--obs-slate"),
          "slate-soft": "rgb(var(--obs-slate) / 0.12)",

          amber:        rgbVar("--obs-amber"),
          "amber-soft": "rgb(var(--obs-amber) / 0.12)",

          rose:        rgbVar("--obs-rose"),
          "rose-soft": "rgb(var(--obs-rose) / 0.10)",

          text:    rgbVar("--obs-text"),
          subtle:  rgbVar("--obs-subtle"),
          faint:   rgbVar("--obs-faint"),
        },
      },
      backdropBlur: {
        glass: "16px",
      },
      boxShadow: {
        "obs-node":   "0 0 0 1px rgb(var(--scrim-fg) / 0.06), 0 4px 24px rgba(0,0,0,0.30)",
        "obs-violet": "0 0 20px rgb(var(--obs-violet) / 0.25), 0 0 0 1px rgb(var(--obs-violet) / 0.35)",
        "obs-amber":  "0 0 16px rgb(var(--obs-amber) / 0.20), 0 0 0 1px rgb(var(--obs-amber) / 0.30)",
        "obs-glow":   "0 0 40px rgb(var(--obs-violet) / 0.15)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      animation: {
        "pulse-slow":  "pulse 3s cubic-bezier(0.4,0,0.6,1) infinite",
        "fade-in":     "fadeIn 0.2s ease-out",
        "slide-in-r":  "slideInRight 0.25s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%":   { opacity: "0", transform: "translateX(12px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
