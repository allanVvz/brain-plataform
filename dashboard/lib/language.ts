export type UiLanguage = "pt-BR" | "en";

export const UI_LANGUAGE_STORAGE = "ai-brain-ui-language";
export const UI_LANGUAGE_EVENT = "ai-brain-language-change";

export const LANGUAGE_OPTIONS: Array<{ value: UiLanguage; label: string }> = [
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "en", label: "English" },
];

export function normalizeLanguage(value: unknown): UiLanguage {
  return value === "en" ? "en" : "pt-BR";
}

export function getStoredLanguage(): UiLanguage {
  if (typeof window === "undefined") return "pt-BR";
  return normalizeLanguage(window.localStorage.getItem(UI_LANGUAGE_STORAGE));
}

export function applyLanguage(language: UiLanguage) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = language;
  try {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE, language);
    window.dispatchEvent(new CustomEvent(UI_LANGUAGE_EVENT, { detail: { language } }));
  } catch {}
}
