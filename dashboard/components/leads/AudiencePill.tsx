"use client";

import { Pencil, Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export type AudiencePillData = {
  id?: string | null;
  slug: string;
  name: string;
  count?: number;
  isSystem?: boolean;
};

export function AudiencePill({
  data,
  active,
  onActivate,
  onRename,
}: {
  data: AudiencePillData;
  active: boolean;
  onActivate: () => void;
  onRename?: (next: string) => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(data.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(data.name);
  }, [data.name]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const canRename = !!onRename && !data.isSystem && data.id;

  const commit = async () => {
    const next = draft.trim();
    if (!canRename || !next || next === data.name) {
      setEditing(false);
      setDraft(data.name);
      return;
    }
    await onRename!(next);
    setEditing(false);
  };

  if (editing) {
    return (
      <span className="lg-btn lg-btn-secondary !py-1 !pl-3 !pr-1.5 inline-flex items-center gap-1.5">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setEditing(false);
              setDraft(data.name);
            }
          }}
          className="bg-transparent text-xs font-semibold text-obs-text outline-none w-32"
        />
        <button
          type="button"
          onClick={commit}
          className="rounded-full p-1 text-obs-violet hover:bg-obs-violet/15"
          title="Salvar"
        >
          <Check size={11} />
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setDraft(data.name);
          }}
          className="rounded-full p-1 text-obs-faint hover:bg-obs-rose/10 hover:text-obs-rose"
          title="Cancelar"
        >
          <X size={11} />
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onActivate}
      onDoubleClick={() => canRename && setEditing(true)}
      className={`lg-btn ${active ? "lg-btn-primary" : "lg-btn-secondary"} group inline-flex items-center gap-1.5`}
      title={canRename ? "Duplo clique para renomear" : undefined}
    >
      <span>{data.name}</span>
      {typeof data.count === "number" && (
        <span className={`text-[10px] ${active ? "opacity-80" : "text-obs-faint"}`}>{data.count}</span>
      )}
      {canRename && (
        <span
          role="button"
          tabIndex={0}
          aria-label="Renomear"
          onClick={(e) => {
            e.stopPropagation();
            setEditing(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              setEditing(true);
            }
          }}
          className="opacity-0 group-hover:opacity-70 hover:opacity-100 transition cursor-pointer"
        >
          <Pencil size={10} />
        </span>
      )}
    </button>
  );
}
