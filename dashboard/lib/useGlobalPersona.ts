"use client";

import { useEffect, useState } from "react";

export function useGlobalPersona() {
  const [persona, setPersona] = useState({ id: "", slug: "" });

  useEffect(() => {
    const read = () => setPersona({
      id: window.localStorage.getItem("ai-brain-persona-id") || "",
      slug: window.localStorage.getItem("ai-brain-persona-slug") || "",
    });
    read();
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; slug?: string }>).detail || {};
      setPersona({ id: detail.id || "", slug: detail.slug || "" });
    };
    window.addEventListener("ai-brain-persona-change", onChange as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", onChange as EventListener);
  }, []);

  return persona;
}
