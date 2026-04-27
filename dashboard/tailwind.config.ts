import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Legacy tokens (maintained for backwards compat) ──────────
        brain: {
          bg:      "#080b12",
          surface: "#0e1118",
          border:  "#1e2130",
          accent:  "#7c6fff",
          muted:   "#4a5068",
        },
        // ── Obsidiana Design System ───────────────────────────────────
        obs: {
          // Backgrounds
          deep:    "#050709",
          base:    "#080b12",
          surface: "#0e1118",
          raised:  "#141724",
          // Borders
          line:    "rgba(255,255,255,0.06)",
          glow:    "rgba(124,111,255,0.30)",
          // Accent / Primary (Persona root)
          violet:  "#7c6fff",
          "violet-soft": "rgba(124,111,255,0.15)",
          "violet-glow": "rgba(124,111,255,0.08)",
          // Validated nodes
          slate:   "#64748b",
          "slate-soft": "rgba(100,116,139,0.12)",
          // Pending / Alert nodes
          amber:   "#f59e0b",
          "amber-soft": "rgba(245,158,11,0.12)",
          // Rejected
          rose:    "#f43f5e",
          "rose-soft":  "rgba(244,63,94,0.10)",
          // Text
          text:    "#e2e8f0",
          subtle:  "#8892a4",
          faint:   "#3d4559",
        },
      },
      backdropBlur: {
        glass: "16px",
      },
      boxShadow: {
        "obs-node":   "0 0 0 1px rgba(255,255,255,0.06), 0 4px 24px rgba(0,0,0,0.6)",
        "obs-violet": "0 0 20px rgba(124,111,255,0.25), 0 0 0 1px rgba(124,111,255,0.35)",
        "obs-amber":  "0 0 16px rgba(245,158,11,0.20), 0 0 0 1px rgba(245,158,11,0.30)",
        "obs-glow":   "0 0 40px rgba(124,111,255,0.15)",
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
