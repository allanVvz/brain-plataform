import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type GraphNode = {
  id?: string;
  type?: string;
  node_type?: string;
  slug?: string;
  data?: {
    node_type?: string;
    slug?: string;
  };
};

type GraphEdge = {
  id?: string;
  source?: string;
  target?: string;
};

function resolveBackendBase(): string {
  const configured = process.env.API_INTERNAL_BASE_URL;
  const isProduction = process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
  return configured || (isProduction ? "http://127.0.0.1:9" : "http://127.0.0.1:8080");
}

function normalizeType(node: GraphNode): string {
  const raw = String(node.node_type || node.data?.node_type || node.type || "").trim().toLowerCase();
  if (raw === "category" || raw === "product_collection") return "product_group";
  return raw;
}

function slugOf(node: GraphNode): string {
  return String(node.slug || node.data?.slug || "").trim().toLowerCase();
}

export async function GET(req: NextRequest) {
  const tenant = req.nextUrl.searchParams.get("tenant")?.trim() || "";
  const personaSlug = req.nextUrl.searchParams.get("personaSlug")?.trim() || "";

  if (!tenant || !personaSlug) {
    return NextResponse.json(
      {
        ok: false,
        error: "missing_required_query",
        required: ["tenant", "personaSlug"],
      },
      { status: 400 },
    );
  }

  const auth = req.headers.get("authorization");
  const adminToken = req.headers.get("x-ai-brain-admin-token");
  if (!auth && !adminToken) {
    return NextResponse.json(
      {
        ok: false,
        error: "missing_authorization",
        required: "Authorization: Bearer <token> or X-AI-BRAIN-ADMIN-TOKEN",
      },
      { status: 401 },
    );
  }

  const backendBase = resolveBackendBase();
  const upstreamUrl = `${backendBase}/graph-documents/current?persona_slug=${encodeURIComponent(personaSlug)}`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: "GET",
      headers: {
        ...(auth ? { Authorization: auth } : {}),
        ...(adminToken ? { "X-AI-BRAIN-ADMIN-TOKEN": adminToken } : {}),
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "backend_unreachable",
        backend: backendBase,
      },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text().catch(() => "");
    return NextResponse.json(
      {
        ok: false,
        error: "backend_error",
        backendStatus: upstream.status,
        detail: text || null,
      },
      { status: upstream.status },
    );
  }

  const payload = await upstream.json().catch(() => ({}));
  const graphJson = payload?.graph_json || payload?.document?.graph_json || payload?.document || payload;
  const nodes: GraphNode[] = Array.isArray(graphJson?.nodes) ? graphJson.nodes : [];
  const edges: GraphEdge[] = Array.isArray(graphJson?.edges) ? graphJson.edges : [];

  const productGroups = new Set<string>();
  const products = new Set<string>();

  for (const node of nodes) {
    const nodeType = normalizeType(node);
    const nodeSlug = slugOf(node) || String(node.id || "");
    if (!nodeSlug) continue;

    if (nodeType === "product_group") productGroups.add(nodeSlug);
    if (nodeType === "product") products.add(nodeSlug);
  }

  const nodeCount = nodes.length;
  const edgeCount = edges.length;
  const visible = nodeCount > 0;

  return NextResponse.json(
    {
      ok: true,
      tenant,
      personaSlug,
      visible,
      graph: {
        nodeCount,
        edgeCount,
      },
      counts: {
        productGroups: productGroups.size,
        products: products.size,
      },
      assertions: {
        nonEmpty: visible,
        expectedProductGroups: productGroups.size === 3,
        expectedProducts: products.size === 9,
      },
      upstream: {
        endpoint: "/graph-documents/current",
        schema: String(graphJson?.schema_version || graphJson?.version || "2.0"),
      },
    },
    { status: 200 },
  );
}
