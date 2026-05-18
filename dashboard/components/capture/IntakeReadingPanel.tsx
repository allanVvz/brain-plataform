"use client";
import { FileText, Image as ImageIcon, FileBarChart, Video, AlertCircle, ScanLine } from "lucide-react";

export interface IntakeReading {
  filename: string;
  size?: number;
  mime?: string;
  url?: string | null;
  reading: {
    reading_status: string;
    kind: string;
    needs_ocr?: boolean;
    ocr_engine?: string | null;
    ocr_confidence?: number | null;
    needs_ai_fallback?: boolean;
    ai_fallback_used?: boolean;
    ai_fallback_model?: string | null;
    extracted_text?: string;
    visual_summary?: string;
    pdf_pages?: number | null;
    video_reading_mocked?: boolean;
  };
}

interface Props {
  readings: IntakeReading[];
}

function kindIcon(kind: string) {
  if (kind?.startsWith("image")) return <ImageIcon size={11} />;
  if (kind === "pdf") return <FileBarChart size={11} />;
  if (kind === "video") return <Video size={11} />;
  if (kind === "text" || kind === "markdown") return <FileText size={11} />;
  return <ScanLine size={11} />;
}

function statusBadge(reading: IntakeReading["reading"]) {
  if (reading.reading_status === "completed") {
    return { label: "Pronto", cls: "border-emerald-300/30 bg-emerald-500/15 text-emerald-50" };
  }
  if (reading.reading_status === "mocked") {
    return { label: "Mock", cls: "border-obs-amber/30 bg-obs-amber/15 text-obs-amber" };
  }
  if (reading.reading_status === "partial") {
    return { label: "Parcial", cls: "border-obs-amber/30 bg-obs-amber/15 text-obs-amber" };
  }
  if (reading.reading_status === "failed") {
    return { label: "Falhou", cls: "border-red-300/35 bg-red-500/[0.18] text-red-50" };
  }
  return { label: reading.reading_status, cls: "border-white/10 bg-white/[0.04] text-obs-subtle" };
}

function engineBadge(reading: IntakeReading["reading"]): { label: string; cls: string } | null {
  if (reading.kind === "video") return null;
  if (reading.kind === "pdf") return { label: "pypdf", cls: "border-white/10 bg-white/[0.04] text-obs-subtle" };
  const ai = reading.ai_fallback_used ? reading.ai_fallback_model || "ai" : "";
  const ocr = reading.ocr_engine || "";
  if (ai && (!ocr || ocr === "mock")) return { label: `IA ${ai}`, cls: "border-obs-violet/35 bg-obs-violet/15 text-obs-violet" };
  if (ocr === "mock") return { label: "mock", cls: "border-obs-amber/30 bg-obs-amber/15 text-obs-amber" };
  if (ocr) return { label: ocr, cls: "border-white/10 bg-white/[0.04] text-obs-subtle" };
  return null;
}

export default function IntakeReadingPanel({ readings }: Props) {
  if (!readings.length) {
    return (
      <div className="rounded-xl border border-white/[0.05] bg-white/[0.03] backdrop-blur-md px-3 py-2.5">
        <p className="text-[11px] text-obs-subtle">Sem leituras de arquivo nesta sessao.</p>
        <p className="mt-1 text-[10px] text-obs-faint">Solte texto, imagem, PDF ou video no chat para virar contexto da Sofia.</p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {readings.map((entry, idx) => {
        const r = entry.reading;
        const sb = statusBadge(r);
        const eb = engineBadge(r);
        const pendingFallback = r.needs_ai_fallback && !r.ai_fallback_used;
        return (
          <div
            key={`${entry.filename}-${idx}`}
            className="rounded-xl border border-white/[0.05] bg-white/[0.03] backdrop-blur-md px-3 py-2.5 space-y-1.5"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-obs-faint">{kindIcon(r.kind)}</span>
              <span className="text-[11px] font-medium text-obs-text truncate">{entry.filename}</span>
              <span className={`ml-auto shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${sb.cls}`}>{sb.label}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[9px] rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-obs-faint font-mono">{r.kind}</span>
              {eb && <span className={`text-[9px] rounded border px-1.5 py-0.5 font-mono ${eb.cls}`}>{eb.label}</span>}
              {typeof r.ocr_confidence === "number" && r.ocr_engine && r.ocr_engine !== "mock" && (
                <span className="text-[9px] rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-obs-faint font-mono">
                  conf {r.ocr_confidence.toFixed(2)}
                </span>
              )}
              {typeof r.pdf_pages === "number" && (
                <span className="text-[9px] rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-obs-faint font-mono">
                  {r.pdf_pages} pag.
                </span>
              )}
              {r.video_reading_mocked && (
                <span className="text-[9px] rounded border border-obs-amber/30 bg-obs-amber/15 px-1.5 py-0.5 text-obs-amber font-mono">
                  video mock
                </span>
              )}
              {pendingFallback && (
                <span className="inline-flex items-center gap-1 text-[9px] rounded border border-obs-amber/30 bg-obs-amber/15 px-1.5 py-0.5 text-obs-amber">
                  <AlertCircle size={9} /> fallback IA pendente
                </span>
              )}
            </div>
            {r.extracted_text ? (
              <p className="text-[11px] leading-5 text-obs-text line-clamp-3">
                <span className="text-obs-faint">texto:</span> {r.extracted_text}
              </p>
            ) : (
              <p className="text-[10px] text-obs-faint">sem texto detectado</p>
            )}
            {r.visual_summary && (
              <p className="text-[10px] text-obs-subtle line-clamp-2">
                <span className="text-obs-faint">leitura visual:</span> {r.visual_summary}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
