"use client";

import { useEffect, useState } from "react";

export function useGlobalPersona() {
  const [persona, setPersona] = useState({ id: "", slug: "" });

  useEffect(() => {
    const read = () => {
      const urlSlug = new URLSearchParams(window.location.search).get("persona") || "";
      const preferredSlug = window.localStorage.getItem("ai-brain-persona-slug") || "";
      setPersona({
        id: window.localStorage.getItem("ai-brain-persona-id") || "",
        // URL/context is canonical. localStorage is consulted only when the
        // tab was opened without a scoped URL.
        slug: urlSlug || preferredSlug,
      });
    };
    read();
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; slug?: string }>).detail || {};
      setPersona({ id: detail.id || "", slug: detail.slug || "" });
    };
    window.addEventListener("ai-brain-persona-change", onChange as EventListener);
    window.addEventListener("popstate", read);
    return () => {
      window.removeEventListener("ai-brain-persona-change", onChange as EventListener);
      window.removeEventListener("popstate", read);
    };
  }, []);

  return persona;
}
