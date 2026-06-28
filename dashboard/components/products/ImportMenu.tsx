"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Download } from "lucide-react";
import type { ImportProvider } from "./ImportModal";

const OPTIONS: { key: ImportProvider; label: string; subtitle: string }[] = [
  { key: "meta", label: "Importar do Meta", subtitle: "Catalogo WhatsApp Business" },
  { key: "csv", label: "Importar via CSV", subtitle: "Arquivo CSV ou Excel" },
  { key: "shopify", label: "Importar da Shopify", subtitle: "Usar integracao ja existente" },
  { key: "scraper", label: "Scraper (Mock)", subtitle: "Importacao por scraping mockada" },
];

export function ImportMenu({ onSelect }: { onSelect: (provider: ImportProvider) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="lg-btn rounded-lg"
      >
        <Download size={13} /> Adicionar / Importar <ChevronDown size={13} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-lg border border-white/10 bg-obs-base shadow-obs-node">
          {OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onSelect(opt.key);
              }}
              className="block w-full px-4 py-2.5 text-left transition hover:bg-white/[0.05]"
            >
              <p className="text-sm font-medium text-obs-text">{opt.label}</p>
              <p className="text-[11px] text-obs-subtle">{opt.subtitle}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
