"""Read-only product-image correlation proposals for Sofia.

The service deliberately returns a versioned CardPatch.  It never writes an
edge or publishes a GraphBundle: an operator must review the evidence first.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from schemas.agent_harness import CardPatch
from services import graph_json_v2_store, supabase_client


def _sha(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata") or {}
    return str(asset.get("content_sha256") or metadata.get("content_sha256") or "").removeprefix("sha256:").lower()


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("data") or node.get("spec") or {}


def _asset_registry_id(node: dict[str, Any]) -> str:
    data = _node_data(node)
    return str(data.get("asset_id") or data.get("registry_asset_id") or "")


def _edge_id(product_id: str, asset_node_id: str) -> str:
    return f"edge:{product_id}:uses_asset:{asset_node_id}"


def propose_asset_product_correlations(_context: dict[str, Any], **args: Any) -> dict[str, Any]:
    """Build correlation candidates and a patch without mutating state."""
    persona_id = str(args["persona_id"])
    persona_slug = str(args["persona_slug"])
    persona = supabase_client.get_persona_by_id(persona_id) or {}
    if str(persona.get("slug") or "") != persona_slug:
        raise HTTPException(422, "persona_id e persona_slug nao identificam a mesma persona.")

    loaded = graph_json_v2_store.load_current(persona_slug)
    if not loaded:
        raise HTTPException(404, "Graph publicado nao encontrado para a persona.")
    version, graph_model = loaded
    graph_hash = graph_json_v2_store.checksum_graph(graph_model)
    if int(version) != int(args["expected_graph_version"]) or graph_hash != args["graph_hash"]:
        raise HTTPException(409, "Graph version/hash mudou; gere um novo preview.")

    graph = graph_model.model_dump(mode="json")
    nodes = {str(node.get("id")): node for node in graph.get("nodes") or []}
    edges = list(graph.get("edges") or [])
    products = {node_id: node for node_id, node in nodes.items() if node.get("node_type") == "product"}
    asset_nodes = [node for node in nodes.values() if node.get("node_type") == "asset"]
    node_by_registry_id = {_asset_registry_id(node): node for node in asset_nodes if _asset_registry_id(node)}

    requested = args.get("correlations") or []
    requested_by_asset = {str(item["asset_id"]): str(item["product_node_id"]) for item in requested}
    wanted_ids = set(args.get("asset_ids") or []) | set(requested_by_asset)
    wanted_hashes = {str(value).removeprefix("sha256:").lower() for value in (args.get("content_sha256") or [])}
    assets = supabase_client.list_assets(persona_id=persona_id, limit=5000)
    if wanted_ids or wanted_hashes:
        assets = [row for row in assets if str(row.get("id")) in wanted_ids or _sha(row) in wanted_hashes]

    sha_seen: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for asset in assets:
        asset_id = str(asset.get("id") or "")
        sha = _sha(asset)
        asset_node = node_by_registry_id.get(asset_id)
        if not asset_node:
            candidates.append({"asset_id": asset_id, "content_sha256": sha, "decision": "needs_human_review", "evidence": ["asset_without_graph_node"]})
            continue
        if sha and sha in sha_seen and sha_seen[sha] != asset_id:
            candidates.append({"asset_id": asset_id, "asset_node_id": asset_node["id"], "content_sha256": sha, "decision": "duplicate", "evidence": ["same_content_sha256"]})
            continue
        if sha:
            sha_seen[sha] = asset_id

        node_data = _node_data(asset_node)
        explicit_product = requested_by_asset.get(asset_id)
        embedded_product = str(node_data.get("product_node_id") or "")
        product_id = explicit_product or embedded_product
        evidence = ["operator_explicit_mapping"] if explicit_product else (["asset_node.product_node_id"] if embedded_product else [])
        if product_id not in products:
            candidates.append({
                "asset_id": asset_id, "asset_node_id": asset_node["id"], "content_sha256": sha,
                "product_node_id": product_id or None, "decision": "conflict" if product_id else "needs_human_review",
                "evidence": evidence or ["filename_or_ocr_is_not_identity_evidence"],
            })
            continue

        direct = [edge for edge in edges if edge.get("source") == product_id and edge.get("target") == asset_node["id"]]
        canonical = next((edge for edge in direct if edge.get("relation_type") == "uses_asset"), None)
        canonical_meta = (canonical or {}).get("metadata") or {}
        slot = str(canonical_meta.get("role") or (canonical_meta.get("page_binding") or {}).get("slot_key") or "")
        if canonical and slot.startswith("product_image"):
            candidates.append({
                "asset_id": asset_id, "asset_node_id": asset_node["id"], "content_sha256": sha,
                "product_node_id": product_id, "decision": "duplicate", "evidence": [*evidence, "canonical_edge_exists"],
            })
            continue

        for edge in direct:
            if edge.get("relation_type") == "contains":
                operations.append({"op": "revoke_edge", "target_id": edge["id"], "value": {}})
                evidence.append("relation_mismatch:contains")
            elif edge.get("relation_type") == "uses_asset" and canonical:
                operations.append({"op": "revoke_edge", "target_id": edge["id"], "value": {}})
                evidence.append("missing_product_image_slot")

        product_slug = str(products[product_id].get("slug") or product_id)
        edge_id = _edge_id(product_id, str(asset_node["id"]))
        operations.append({
            "op": "add_edge", "target_id": edge_id,
            "value": {
                "id": edge_id, "source": product_id, "target": asset_node["id"],
                "relation_type": "uses_asset", "primary_tree": False,
                "lifecycle": {"status": "proposed"},
                "metadata": {
                    "active": True, "role": "product_image", "source": "sofia_asset_product_correlation",
                    "content_sha256": f"sha256:{sha}" if sha else None,
                    "page_binding": {"slot_key": f"product_image:{product_slug}", "target_slug": product_slug},
                },
            },
        })
        candidates.append({
            "asset_id": asset_id, "asset_node_id": asset_node["id"], "content_sha256": sha,
            "product_node_id": product_id, "decision": "exact", "confidence": 1.0,
            "evidence": evidence, "requirements": ["asset_gallery_asset", "product_publication_grant", "asset_publication_grant"],
        })

    patch = None
    if operations:
        patch = CardPatch(
            expected_graph_version=int(version), graph_hash=graph_hash,
            idempotency_key=args["idempotency_key"], reason=args["reason"], operations=operations,
        )
    return {
        "ok": True,
        "summary": f"{len(candidates)} correlacoes analisadas; nenhuma escrita foi feita.",
        "candidates": candidates,
        "patch": patch,
        "automatic_mutation": False,
        "publication_allowed": False,
    }
