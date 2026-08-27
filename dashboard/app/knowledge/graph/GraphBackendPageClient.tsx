"use client";

import { useSearchParams } from "next/navigation";
import GraphBundlePageClient from "./GraphBundlePageClient";
import GraphPageClient from "./GraphPageClient";

export default function GraphBackendPageClient() {
  const searchParams = useSearchParams();
  return searchParams.get("backend") === "v3" ? <GraphBundlePageClient /> : <GraphPageClient />;
}
