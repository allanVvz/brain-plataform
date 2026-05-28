from __future__ import annotations

import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, Any

from routes import graph as graph_routes
from routes.process import process as process_route
from schemas.events import LeadEvent
from services import (
    approved_knowledge_snapshots,
    auth_service,
    knowledge_graph,
    knowledge_lifecycle,
    knowledge_taxonomy,
    supabase_client,
)
from utils.env import is_production_runtime

router = APIRouter(tags=["qa-contract"])

QA_PERSONA_ALIASES = {
    "vzlupas": "vz-lupas",
    "vz-lupas": "vz-lupas",
}


def _require_non_production() -> None:
    if is_production_runtime():
        raise HTTPException(403, "QA contract routes are disabled in production")


def _normalise_persona_ref(persona_ref: str) -> str:
    return (persona_ref or "").strip().lower()


def _candidate_persona_refs(persona_ref: str) -> list[str]:
    raw = _normalise_persona_ref(persona_ref)
    if not raw:
        return []
    candidates = [raw]
    alias = QA_PERSONA_ALIASES.get(raw)
    if alias and alias not in candidates:
        candidates.append(alias)
    compact = raw.replace("-", "")
    alias = QA_PERSONA_ALIASES.get(compact)
    if alias and alias not in candidates:
        candidates.append(alias)
    return candidates


def _require_qa_persona(request: Request, persona_ref: str) -> dict:
    candidates = _candidate_persona_refs(persona_ref)
    if not candidates:
        raise HTTPException(400, "persona_ref is required")
    if not any(candidate in QA_PERSONA_ALIASES.values() or candidate in QA_PERSONA_ALIASES for candidate in candidates):
        raise HTTPException(403, "This route is restricted to VZ Lupas QA persona aliases")

    persona = None
    for candidate in candidates:
        persona = supabase_client.get_persona(candidate)
        if persona:
            break
        if len(candidate) >= 32:
            persona = supabase_client.get_persona_by_id(candidate)
            if persona:
                break

    if not persona:
        raise HTTPException(409, "VZ Lupas QA persona not provisioned in this environment")

    canonical_slug = str(persona.get("slug") or candidates[-1]).strip().lower()
    if canonical_slug not in QA_PERSONA_ALIASES.values():
        raise HTTPException(403, "Resolved persona is not an approved VZ Lupas QA alias")
    auth_service.assert_persona_access(request, persona_id=persona.get("id"), persona_slug=canonical_slug)
    return persona


def _persona_ref(persona_slug: Optional[str] = None, persona_ref: Optional[str] = None) -> str:
    return (persona_ref or persona_slug or "").strip()


def _persona_slug(persona: dict) -> str:
    return str(persona.get("slug") or "vz-lupas").strip().lower()


class QaResetBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    confirm: bool = False


class CatalogEntry(BaseModel):
    title: str
    content: str
    content_type: str = "product"
    file_path: Optional[str] = None
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class CatalogIngestBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    entries: list[CatalogEntry]
    source_ref: Optional[str] = None


class GraphGenerateBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None


class GraphValidateBody(BaseModel):
    graph: Optional[dict] = None
    tree_edge_ids: list[str] = []


class FaqApproveBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    knowledge_item_id: str


class EmbedsGenerateBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    faq_node_id: str


class SdrAskBody(BaseModel):
    lead_id: Optional[str] = None
    lead_ref: Optional[int] = None
    nome: Optional[str] = None
    stage: Optional[str] = "novo"
    canal: Optional[str] = "whatsapp"
    mensagem: str
    interesse_produto: Optional[str] = None
    cidade: Optional[str] = None
    cep: Optional[str] = None
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None


class OfficialSeedBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    source_ref: Optional[str] = "qa_official_seed_v1"
    limit_products: int = 9
    run_id: Optional[str] = None


class SofiaGraphCommandContext(BaseModel):
    current_graph_hash: Optional[str] = None
    selected_node_ids: list[str] = []
    client_action: str = "natural_language"
    graph_patch: Optional[dict[str, Any]] = None
    accept_unverified: bool = False


class SofiaGraphCommandBody(BaseModel):
    persona_slug: str = "vz-lupas"
    persona_ref: Optional[str] = None
    command: str
    context: SofiaGraphCommandContext = SofiaGraphCommandContext()


def _slugify(raw: str) -> str:
    value = "".join(ch.lower() if ch.isalnum() else "-" for ch in (raw or "").strip())
    while "--" in value:
        value = value.replace("--", "-")
    return value.strip("-") or "node"


def _resolve_sofia_graph_patch(command: str, context: SofiaGraphCommandContext) -> dict[str, list[dict]]:
    if (context.client_action or "").strip().lower() == "structured_intent":
        patch = context.graph_patch or {}
        return {
            "nodes_upsert": list(patch.get("nodes_upsert") or []),
            "nodes_delete": list(patch.get("nodes_delete") or []),
            "edges_upsert": list(patch.get("edges_upsert") or []),
            "edges_delete": list(patch.get("edges_delete") or []),
        }

    normalized = (command or "").strip().lower()
    if "reencaixe" in normalized and "vz lupas" in normalized:
        return {
            "nodes_upsert": [
                {
                    "node_type": "brand",
                    "slug": "vz-lupas",
                    "title": "VZ Lupas",
                    "summary": "Brand reencaixada pela Sofia na cadeia canonica.",
                }
            ],
            "nodes_delete": [],
            "edges_upsert": [
                {
                    "source_ref": "persona:self",
                    "target_ref": "slug:vz-lupas",
                    "relation_type": "persona_has_brand",
                    "metadata": {"primary_tree": True, "active": True},
                }
            ],
            "edges_delete": [],
        }
    raise HTTPException(422, "Unable to resolve command into canonical graph operations")


def _persona_graph_nodes(persona_id: str) -> dict[str, dict]:
    rows = supabase_client.list_knowledge_nodes_by_type(
        [
            "persona",
            "brand",
            "briefing",
            "campaign",
            "audience",
            "product_group",
            "product",
            "faq",
            "embedded",
            "copy",
            "gallery",
        ],
        persona_id=persona_id,
        limit=5000,
    )
    by_ref: dict[str, dict] = {}
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if row_id:
            by_ref[f"id:{row_id}"] = row
        slug = str(row.get("slug") or "").strip().lower()
        if slug:
            by_ref[f"slug:{slug}"] = row
    return by_ref


def _canonical_ref(raw: Optional[str], persona_root: dict) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    low = value.lower()
    if low == "persona:self":
        return f"id:{persona_root['id']}"
    if low.startswith("id:") or low.startswith("slug:"):
        return low
    if len(value) >= 32:
        return f"id:{value}"
    return f"slug:{_slugify(value)}"


def _validate_sofia_patch(
    *,
    patch: dict[str, list[dict]],
    nodes_after_upsert: dict[str, dict],
    accept_unverified: bool,
) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    recommendations: list[dict] = []
    for edge in patch["edges_upsert"]:
        src = nodes_after_upsert.get(edge["source_ref"])
        dst = nodes_after_upsert.get(edge["target_ref"])
        src_type = knowledge_taxonomy.canonical_node_type(src.get("node_type") if src else None)
        dst_type = knowledge_taxonomy.canonical_node_type(dst.get("node_type") if dst else None)
        rel = str(edge.get("relation_type") or "contains").strip().lower()
        edge_kind = knowledge_taxonomy.edge_kind_for_relation(rel)
        if src_type == "product" and dst_type == "embedded":
            violations.append(
                {
                    "code": "GRAPH_EDGE_FORBIDDEN",
                    "message": "Direct Product -> Embed is not allowed.",
                    "edge": {"from": edge["source_ref"], "to": edge["target_ref"], "relation": rel},
                }
            )
        if src_type == "faq" and dst_type == "embedded":
            src_status = str(src.get("status") or "").lower()
            if src_status not in {"approved", "embedded", "validated"}:
                violations.append(
                    {
                        "code": "FAQ_NOT_APPROVED",
                        "message": "Unapproved FAQ cannot generate embeddings.",
                        "faqRef": edge["source_ref"],
                    }
                )
        if edge_kind == "primary" and not knowledge_taxonomy.is_primary_edge_allowed(src_type, dst_type, rel):
            violations.append(
                {
                    "code": "CANONICAL_CHAIN_VIOLATION",
                    "message": "Primary edge violates canonical chain.",
                    "edge": {"from": edge["source_ref"], "to": edge["target_ref"], "relation": rel},
                    "sourceType": src_type,
                    "targetType": dst_type,
                }
            )
    for node in patch["nodes_upsert"]:
        ctype = knowledge_taxonomy.canonical_node_type(node.get("node_type"))
        if ctype == "audience":
            slug = str(node.get("slug") or "").lower()
            summary = str(node.get("summary") or "").lower()
            forbidden = {"role-sdr", "role-closer", "role-classifier"}
            if any(token in slug or token in summary for token in forbidden):
                violations.append(
                    {
                        "code": "AUDIENCE_ROLE_FORBIDDEN",
                        "message": "Audience cannot be role-sdr, role-closer, or role-classifier.",
                        "slug": slug,
                    }
                )
        if ctype == "product" and not accept_unverified:
            meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            source_url = str(meta.get("source_url") or "").strip()
            if not source_url:
                violations.append(
                    {
                        "code": "PRODUCT_SOURCE_REQUIRED",
                        "message": "Product requires metadata.source_url unless accept_unverified=true.",
                        "slug": str(node.get("slug") or ""),
                    }
                )
        if ctype == "audience" and str(node.get("slug") or "").startswith("audiencia-padrao-"):
            recommendations.append(
                {
                    "type": "audience_default_shared",
                    "reason": "Default audience detected; prefer individualized audience per brand when needed.",
                }
            )
    return violations, recommendations


def _official_products(limit_products: int = 9) -> list[dict]:
    canonical = [
        {"slug": "clip-on-aviator", "title": "Clip-on Aviator"},
        {"slug": "clip-on-classic", "title": "Clip-on Classic"},
        {"slug": "clip-on-sport", "title": "Clip-on Sport"},
        {"slug": "grau-acetato", "title": "Armacao Grau Acetato"},
        {"slug": "grau-metal", "title": "Armacao Grau Metal"},
        {"slug": "grau-titanio", "title": "Armacao Grau Titanio"},
        {"slug": "sol-aviador", "title": "Lupa Sol Aviador"},
        {"slug": "sol-quadrado", "title": "Lupa Sol Quadrado"},
        {"slug": "sol-redondo", "title": "Lupa Sol Redondo"},
    ]
    return canonical[: max(0, min(limit_products, len(canonical)))]


@router.post("/qa/reset-destructive")
def qa_reset_destructive(body: QaResetBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    if not body.confirm:
        return {"ok": True, "dry_run": True, "persona_slug": persona_slug, "allowed": True, "message": "Set confirm=true to execute destructive reset in dev/test scope."}

    result = supabase_client.reset_embedded_legacy_publications(persona.get("id"))
    supabase_client.insert_event(
        {
            "event_type": "qa_reset_destructive_executed",
            "entity_type": "persona",
            "entity_id": persona.get("id"),
            "persona_id": persona.get("id"),
            "payload": {"persona_slug": persona_slug, "result": result},
        },
        source="qa_contract.reset_destructive",
    )
    return {"ok": True, "persona_slug": persona_slug, "result": result}


@router.post("/catalog/ingest")
def catalog_ingest(body: CatalogIngestBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    if not body.entries:
        raise HTTPException(400, "entries is required")

    created: list[dict] = []
    rejected_embed_rows = 0
    for entry in body.entries:
        if (entry.content_type or "").strip().lower() == "embed":
            rejected_embed_rows += 1
            continue
        item = knowledge_lifecycle.persist_pending_knowledge_item(
            persona_slug=persona_slug,
            title=entry.title,
            content=entry.content,
            content_type=entry.content_type,
            file_path=entry.file_path,
            metadata={**entry.metadata, "ingest_source": "catalog_contract"},
            tags=entry.tags,
            source_ref=body.source_ref,
        )
        created.append({"id": item.get("id"), "content_type": item.get("content_type"), "status": item.get("status")})

    return {
        "ok": True,
        "persona_slug": persona_slug,
        "drafts_created": len(created),
        "rejected_embed_rows": rejected_embed_rows,
        "items": created,
        "embeddings_generated": 0,
        "catalog_boundary": "catalog ingest creates drafts only; embed generation requires FAQ approval + explicit embeds/generate",
    }


@router.post("/graph/generate")
def graph_generate(body: GraphGenerateBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    counts = knowledge_graph.rebuild_graph_for_persona(persona.get("id"))
    return {"ok": True, "persona_slug": persona_slug, "counts": counts}


@router.post("/graph/validate")
def graph_validate(body: GraphValidateBody, request: Request):
    _require_non_production()
    _require_qa_persona(request, "vz-lupas")
    payload = graph_routes.GraphPreflightBody(graph=body.graph, tree_edge_ids=body.tree_edge_ids)
    return graph_routes.graph_contract_preflight_vzlupas(payload)


@router.post("/faq/approve")
def faq_approve(body: FaqApproveBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    item = supabase_client.get_knowledge_item(body.knowledge_item_id)
    if not item:
        raise HTTPException(422, "knowledge_item_id not found")
    if (item.get("content_type") or "").lower() != "faq":
        raise HTTPException(400, "Only FAQ knowledge items can be approved in this route")

    result = knowledge_lifecycle.promote_knowledge_item(body.knowledge_item_id, promote_to_kb=False)
    supabase_client.insert_event(
        {
            "event_type": "faq_approved_for_embed",
            "entity_type": "knowledge_item",
            "entity_id": body.knowledge_item_id,
            "persona_id": item.get("persona_id"),
            "payload": {"persona_slug": persona_slug, "evidence": result.get("evidence")},
        },
        source="qa_contract.faq_approve",
    )
    return {"ok": True, "item": result.get("item"), "evidence": result.get("evidence")}


@router.post("/embeds/generate")
def embeds_generate(body: EmbedsGenerateBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    node = supabase_client.get_knowledge_node(body.faq_node_id)
    if not node:
        raise HTTPException(422, "faq_node_id not found")
    if (node.get("node_type") or "").lower() != "faq":
        raise HTTPException(400, "Only FAQ nodes can be embedded")
    if (node.get("status") or "").lower() not in {"approved", "embedded", "validated"}:
        raise HTTPException(409, "Unapproved FAQ -> Embed is impossible. Approve FAQ first.")

    publication = approved_knowledge_snapshots.publish_approved_node(
        node.get("id"),
        approved_by=(auth_service.current_user(request) or {}).get("id"),
        require_rag_for_faq=True,
    )
    if not publication.get("embedded_edge_id"):
        raise HTTPException(502, "Embed generation missing embedded_edge_id evidence")
    supabase_client.insert_event(
        {
            "event_type": "embed_generated_from_approved_faq",
            "entity_type": "knowledge_node",
            "entity_id": node.get("id"),
            "persona_id": node.get("persona_id"),
            "payload": {"persona_slug": persona_slug, "publication": publication},
        },
        source="qa_contract.embeds_generate",
    )
    return {"ok": True, "publication": publication}


@router.post("/seed/official-real")
def seed_official_real(body: OfficialSeedBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)

    persona_id = persona.get("id")
    if not persona_id:
        raise HTTPException(409, "Resolved persona has no id")

    # Hard cleanup for deterministic QA seed: remove non-protected legacy nodes/edges
    # so the canonical tree is the single active branch for this persona.
    nodes_before, _edges_before = supabase_client.list_all_knowledge_graph(persona_id)
    for node in nodes_before:
        node_type = (node.get("node_type") or "").lower()
        slug = (node.get("slug") or "").lower()
        metadata = node.get("metadata") or {}
        protected = bool(metadata.get("protected")) or slug in {"self", "gallery-default", "embedded-default"}
        if node_type == "persona" or protected:
            continue
        node_id = node.get("id")
        if node_id:
            supabase_client.delete_knowledge_node(node_id)

    products = _official_products(limit_products=body.limit_products)
    if len(products) < 9:
        raise HTTPException(409, "Official seed fixture is missing required 9 canonical products")

    persona_node = supabase_client.ensure_persona_knowledge_node(persona_id)
    if not persona_node:
        raise HTTPException(502, "Unable to ensure persona root node")

    brand = supabase_client.upsert_knowledge_node(
        {
            "persona_id": persona_id,
            "node_type": "brand",
            "slug": "vz-lupas",
            "title": "VZ Lupas",
            "summary": "Brand principal da persona AllanVvz para oferta de lupas e oculos.",
            "tags": ["brand", "vzlupas", "seed"],
            "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id, "source_ref": body.source_ref},
            "status": "active",
            "level": 20,
            "importance": 0.95,
            "confidence": 1.0,
        }
    )
    briefing = supabase_client.upsert_knowledge_node(
        {
            "persona_id": persona_id,
            "node_type": "briefing",
            "slug": "briefing-vz-lupas-catalogo-oficial",
            "title": "Briefing VZ Lupas Catalogo Oficial",
            "summary": "Briefing canonico para sustentar campanhas comerciais da VZ Lupas.",
            "tags": ["briefing", "vzlupas", "seed"],
            "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id},
            "status": "active",
            "level": 30,
            "importance": 0.9,
            "confidence": 1.0,
        }
    )
    campaign = supabase_client.upsert_knowledge_node(
        {
            "persona_id": persona_id,
            "node_type": "campaign",
            "slug": "campanha-vz-lupas-catalogo-oficial",
            "title": "Campanha VZ Lupas Catalogo Oficial",
            "summary": "Campanha macro para distribuicao dos grupos e produtos oficiais.",
            "tags": ["campaign", "vzlupas", "seed"],
            "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id},
            "status": "active",
            "level": 40,
            "importance": 0.88,
            "confidence": 1.0,
        }
    )
    audience = supabase_client.upsert_knowledge_node(
        {
            "persona_id": persona_id,
            "node_type": "audience",
            "slug": "audiencia-padrao-vz-lupas",
            "title": "Audiencia Padrao VZ Lupas",
            "summary": "Publico comprador final e revenda optica para produtos da VZ Lupas.",
            "tags": ["audience", "vzlupas", "seed"],
            "metadata": {
                "seed_mode": "official_real_qa",
                "run_id": body.run_id,
                "summary_markdown": "Publico principal de compra para catalogo VZ Lupas.",
                "leads_group_id": f"lg-{persona_slug}-audiencia-padrao-vz-lupas",
            },
            "status": "active",
            "level": 50,
            "importance": 0.85,
            "confidence": 1.0,
        }
    )
    if not brand or not briefing or not campaign or not audience:
        raise HTTPException(502, "Failed to create canonical Brand/Briefing/Campaign/Audience nodes")

    def _main(src_id: str, dst_id: str, rel: str = "contains"):
        supabase_client.upsert_knowledge_edge(
            source_node_id=src_id,
            target_node_id=dst_id,
            relation_type=rel,
            persona_id=persona_id,
            weight=1.0,
            metadata={"primary_tree": True, "active": True, "seed_mode": "official_real_qa", "run_id": body.run_id},
        )

    _main(persona_node["id"], brand["id"], "contains")
    _main(brand["id"], briefing["id"], "contains")
    _main(briefing["id"], campaign["id"], "contains")
    _main(campaign["id"], audience["id"], "campaign_has_audience")

    group_by_prefix = {
        "clip-on-": ("grupo-clip-on", "Grupo Clip-on"),
        "grau-": ("grupo-grau", "Grupo Grau"),
        "sol-": ("grupo-sol", "Grupo Sol"),
    }
    groups: dict[str, dict] = {}
    for product in products:
        slug = str(product.get("slug") or "").strip().lower()
        title = str(product.get("title") or slug).strip()
        prefix = next((p for p in group_by_prefix if slug.startswith(p)), None)
        if not prefix:
            continue
        group_slug, group_title = group_by_prefix[prefix]
        if group_slug not in groups:
            group_node = supabase_client.upsert_knowledge_node(
                {
                    "persona_id": persona_id,
                    "node_type": "product_group",
                    "slug": group_slug,
                    "title": group_title,
                    "summary": f"{group_title} oficial VZ Lupas.",
                    "tags": ["product_group", "vzlupas", "seed"],
                    "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id},
                    "status": "active",
                    "level": 60,
                    "importance": 0.84,
                    "confidence": 1.0,
                }
            )
            if not group_node:
                raise HTTPException(502, f"Failed to create product_group {group_slug}")
            groups[group_slug] = group_node
            _main(audience["id"], group_node["id"], "contains")

        product_node = supabase_client.upsert_knowledge_node(
            {
                "persona_id": persona_id,
                "node_type": "product",
                "slug": slug,
                "title": title,
                "summary": f"Produto oficial VZ Lupas: {title}.",
                "tags": ["product", "vzlupas", "seed"],
                "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id},
                "status": "active",
                "level": 70,
                "importance": 0.8,
                "confidence": 1.0,
            }
        )
        if not product_node:
            raise HTTPException(502, f"Failed to create product node for {slug}")
        _main(groups[group_slug]["id"], product_node["id"], "contains")

        faq_node = supabase_client.upsert_knowledge_node(
            {
                "persona_id": persona_id,
                "node_type": "faq",
                "slug": f"faq-{slug}",
                "title": f"FAQ {title}",
                "summary": f"FAQ aprovada para {title}.",
                "tags": ["faq", "vzlupas", "seed"],
                "metadata": {"seed_mode": "official_real_qa", "run_id": body.run_id},
                "status": "approved",
                "level": 80,
                "importance": 0.78,
                "confidence": 1.0,
            }
        )
        if not faq_node:
            raise HTTPException(502, f"Failed to create FAQ for {slug}")
        _main(product_node["id"], faq_node["id"], "contains")

    counts_after_embed: dict[str, Any] = {}
    supabase_client.insert_event(
        {
            "event_type": "qa_official_real_seed_executed",
            "entity_type": "persona",
            "entity_id": persona_id,
            "persona_id": persona_id,
            "payload": {
                "persona_slug": persona_slug,
                "source_ref": body.source_ref,
                "run_id": body.run_id,
                "products_seeded": len(products),
                "product_groups_seeded": len(groups),
                "embedded_publications": 0,
            },
        },
        source="qa_contract.seed_official_real",
    )
    return {
        "ok": True,
        "persona_slug": persona_slug,
        "persona_id": persona_id,
        "source_ref": body.source_ref,
        "run_id": body.run_id,
        "draft_items_created": 0,
        "faqs_approved": len(products),
        "embeds_generated": 0,
        "graph_counts_before_embed": {},
        "graph_counts_after_embed": counts_after_embed,
        "publications": [],
    }


@router.post("/sdr/ask")
async def sdr_ask(body: SdrAskBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_slug = _persona_slug(persona)
    event = LeadEvent(
        lead_id=body.lead_id,
        lead_ref=body.lead_ref,
        nome=body.nome,
        stage=body.stage,
        canal=body.canal,
        mensagem=body.mensagem,
        interesse_produto=body.interesse_produto,
        cidade=body.cidade,
        cep=body.cep,
        persona_slug=persona_slug,
    )
    result = await process_route(event=event, x_webhook_token=None)
    return {
        "ok": True,
        "persona_slug": persona_slug,
        "result": result,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sofia/graph-command")
def sofia_graph_command(body: SofiaGraphCommandBody, request: Request):
    _require_non_production()
    persona = _require_qa_persona(request, _persona_ref(body.persona_slug, body.persona_ref))
    persona_id = persona.get("id")
    if not persona_id:
        raise HTTPException(409, "Resolved persona has no id")
    persona_slug = _persona_slug(persona)

    patch = _resolve_sofia_graph_patch(body.command, body.context)
    persona_node = supabase_client.ensure_persona_knowledge_node(persona_id)
    if not persona_node:
        raise HTTPException(502, "Unable to ensure persona root node")
    known = _persona_graph_nodes(persona_id)
    known[f"id:{persona_node['id']}"] = persona_node
    known["persona:self"] = persona_node
    known["slug:self"] = persona_node

    persisted_nodes: list[dict] = []
    patch_nodes: list[dict] = []
    for raw_node in patch["nodes_upsert"]:
        node_type = knowledge_taxonomy.canonical_node_type(raw_node.get("node_type"))
        if not node_type:
            raise HTTPException(422, f"Unknown node_type in nodes_upsert: {raw_node.get('node_type')}")
        node_payload = {
            "persona_id": persona_id,
            "node_type": node_type,
            "slug": str(raw_node.get("slug") or _slugify(raw_node.get("title") or node_type)),
            "title": str(raw_node.get("title") or node_type),
            "summary": str(raw_node.get("summary") or ""),
            "metadata": raw_node.get("metadata") if isinstance(raw_node.get("metadata"), dict) else {},
            "status": str(raw_node.get("status") or "active"),
            "tags": raw_node.get("tags") if isinstance(raw_node.get("tags"), list) else [],
        }
        row = supabase_client.upsert_knowledge_node(node_payload)
        if not row:
            raise HTTPException(502, f"Failed to upsert node slug={node_payload['slug']}")
        persisted_nodes.append(row)
        patch_nodes.append(node_payload)
        known[f"id:{row['id']}"] = row
        known[f"slug:{str(row.get('slug') or '').lower()}"] = row

    edges_to_persist: list[dict] = []
    for raw_edge in patch["edges_upsert"]:
        src_ref = _canonical_ref(raw_edge.get("source_ref"), persona_node)
        dst_ref = _canonical_ref(raw_edge.get("target_ref"), persona_node)
        if not src_ref or not dst_ref:
            raise HTTPException(422, "edges_upsert requires source_ref and target_ref")
        src = known.get(src_ref)
        dst = known.get(dst_ref)
        if not src or not dst:
            raise HTTPException(422, f"edge reference not found: source={src_ref} target={dst_ref}")
        edges_to_persist.append(
            {
                "source_ref": src_ref,
                "target_ref": dst_ref,
                "source_node_id": src["id"],
                "target_node_id": dst["id"],
                "relation_type": str(raw_edge.get("relation_type") or "contains").strip().lower(),
                "metadata": raw_edge.get("metadata") if isinstance(raw_edge.get("metadata"), dict) else {},
            }
        )

    violations, recommendations = _validate_sofia_patch(
        patch={"nodes_upsert": patch_nodes, "nodes_delete": patch["nodes_delete"], "edges_upsert": edges_to_persist, "edges_delete": patch["edges_delete"]},
        nodes_after_upsert=known,
        accept_unverified=bool(body.context.accept_unverified),
    )
    if violations:
        supabase_client.insert_event(
            {
                "event_type": "sofia_graph_command_rejected",
                "entity_type": "persona",
                "entity_id": persona_id,
                "persona_id": persona_id,
                "payload": {"persona_slug": persona_slug, "command": body.command, "violations": violations},
            },
            source="qa_contract.sofia_graph_command",
        )
        raise HTTPException(
            422,
            {
                "ok": False,
                "code": "GRAPH_VALIDATION_FAILED",
                "message": "Command violates canonical graph constraints.",
                "violations": violations,
            },
        )

    for edge in edges_to_persist:
        supabase_client.upsert_knowledge_edge(
            source_node_id=edge["source_node_id"],
            target_node_id=edge["target_node_id"],
            relation_type=edge["relation_type"],
            persona_id=persona_id,
            weight=1.0,
            metadata=edge["metadata"] or {"primary_tree": True, "active": True},
        )
    supabase_client.insert_event(
        {
            "event_type": "sofia_graph_command_applied",
            "entity_type": "persona",
            "entity_id": persona_id,
            "persona_id": persona_id,
            "payload": {
                "persona_slug": persona_slug,
                "command": body.command,
                "nodes_upsert": len(persisted_nodes),
                "edges_upsert": len(edges_to_persist),
                "recommendations": recommendations,
            },
        },
        source="qa_contract.sofia_graph_command",
    )
    return {
        "ok": True,
        "sofia_message": "Comando aplicado com cadeia canonica validada.",
        "graph_patch": patch,
        "persisted": True,
        "recommendations": recommendations,
        "validation": {"canonical_chain_respected": True, "violations": []},
    }
