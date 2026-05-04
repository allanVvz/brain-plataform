import { Suspense } from "react";
import GraphPageClient from "./GraphPageClient";

export default function GraphPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-[calc(100vh-96px)] text-obs-subtle text-sm">
          Carregando grafo...
        </div>
      }
    >
      <GraphPageClient />
    </Suspense>
  );
}
