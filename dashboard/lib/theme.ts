export type Theme = "clean" | "dark";

export const THEME_STORAGE = "ai-brain-theme";
export const THEME_EVENT = "ai-brain-theme-change";

export function normalizeTheme(value: unknown): Theme {
  return value === "dark" ? "dark" : "clean";
}

export function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "clean";
  return normalizeTheme(window.localStorage.getItem(THEME_STORAGE));
}

export function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_STORAGE, theme);
    window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { theme } }));
  } catch {}
}
