"""Regression coverage for FAQ edge direction.

FAQ is the terminal node for commercial vectors. Product/offer/copy point into
FAQ; FAQ only points out to Embedded.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))


def _assert(condition: bool, message: str, detail=None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")
    print(f"ok {message}")


def test_bootstrap_faq_references_point_into_faq() -> None:
    from services import knowledge_graph, supabase_client

    nodes: dict[tuple[str, str], dict] = {}
    edges: list[dict] = []

    def upsert_knowledge_node(data: dict) -> dict:
        node_type = str(data.get("node_type") or "node")
        slug = str(data.get("slug") or "node")
        node = {
            **deepcopy(data),
            "id": f"n-{node_type}-{slug}",
            "node_type": node_type,
            "slug": slug,
            "metadata": deepcopy(data.get("metadata") or {}),
        }
        nodes[(node_type, slug)] = node
        return deepcopy(node)

    def upsert_knowledge_edge(source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        edge = {
            "id": f"e-{len(edges) + 1}",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": deepcopy(metadata or {}),
        }
        edges.append(edge)
        return deepcopy(edge)

    patched = {
        "upsert_knowledge_node": upsert_knowledge_node,
        "upsert_knowledge_edge": upsert_knowledge_edge,
        "get_knowledge_node": lambda _node_id: None,
        "get_knowledge_node_by_slug": lambda slug, persona_id=None, node_type=None: None,
    }
    originals = {name: getattr(supabase_client, name) for name in patched}
    try:
        for name, fn in patched.items():
            setattr(supabase_client, name, fn)
        mirror = knowledge_graph.bootstrap_from_item(
            {
                "id": "item-faq",
                "persona_id": "persona-1",
                "content_type": "faq",
                "title": "FAQ Kit Modal",
                "content": "Pergunta: preco?\nResposta: validar.",
                "tags": ["product:kit-modal"],
                "status": "pending",
            },
            frontmatter={
                "product": "Kit Modal",
                "offer": "Oferta Kit Modal",
                "copy": "Copy Kit Modal",
            },
            body="",
            persona_id="persona-1",
        )
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)

    _assert(mirror and mirror["node_type"] == "faq", "FAQ mirror node is created")
    faq_id = mirror["id"]
    inbound_answer_edges = [
        edge for edge in edges
        if edge["target_node_id"] == faq_id and edge["relation_type"] == "answers_question"
    ]
    outbound_answer_edges = [
        edge for edge in edges
        if edge["source_node_id"] == faq_id and edge["relation_type"] == "answers_question"
    ]
    inbound_types = {
        edge["source_node_id"].split("-", 2)[1]
        for edge in inbound_answer_edges
    }
    _assert({"product", "offer", "copy"}.issubset(inbound_types), "product/offer/copy point into FAQ", inbound_types)
    _assert(not outbound_answer_edges, "bootstrap never creates FAQ -> commercial answers_question edges", outbound_answer_edges)


def test_graph_edge_api_blocks_faq_outgoing_except_embedded() -> None:
    from fastapi import HTTPException
    from routes import graph as graph_route
    from services import auth_service, supabase_client, approved_knowledge_snapshots

    faq_node = {
        "id": "n-faq",
        "node_type": "faq",
        "persona_id": "persona-1",
        "source_table": "knowledge_items",
        "source_id": "item-faq",
        "metadata": {},
    }
    offer_node = {"id": "n-offer", "node_type": "offer", "persona_id": "persona-1", "metadata": {}}
    embedded_node = {"id": "n-embedded", "node_type": "embedded", "persona_id": "persona-1", "metadata": {}}

    def resolve(value: str, persona_id=None):
        return {"faq": faq_node, "offer": offer_node, "embedded": embedded_node}.get(value)

    published_edge = {
            "id": "edge-1",
            "source_node_id": "n-faq",
            "target_node_id": "n-embedded",
            "relation_type": "manual",
            "persona_id": "persona-1",
            "metadata": {"active": True, "primary_tree": False},
    }

    patched = [
        (graph_route, "_resolve_graph_node_ref", resolve),
        (graph_route, "_knowledge_item_for_graph_node", lambda _node: {"id": "item-faq", "status": "approved"}),
        (graph_route, "_prepare_faq_for_embedded", lambda node: (faq_node, {"id": "item-faq", "status": "approved"})),
        (auth_service, "assert_persona_access", lambda *args, **kwargs: None),
        (auth_service, "current_user", lambda _request: {"id": "user-1"}),
        (supabase_client, "get_knowledge_edge", lambda edge_id: published_edge if edge_id == "edge-1" else None),
        (supabase_client, "insert_event", lambda *args, **kwargs: None),
        (approved_knowledge_snapshots, "publish_approved_node", lambda *args, **kwargs: {
            "approved_snapshot_id": "snapshot-1",
            "rag_entry_id": "rag-1",
            "rag_chunk_ids": ["chunk-1"],
            "status": "active",
        }),
    ]
    originals = [(obj, name, getattr(obj, name)) for obj, name, _ in patched]
    try:
        for obj, name, fn in patched:
            setattr(obj, name, fn)

        try:
            graph_route.create_graph_edge(
                graph_route.GraphEdgeCreateBody(source_node_id="faq", target_node_id="offer", relation_type="answers_question", persona_id="persona-1"),
                SimpleNamespace(),
            )
        except HTTPException as exc:
            _assert(exc.status_code == 400, "API rejects FAQ -> offer")
        else:
            raise AssertionError("API accepted invalid FAQ -> offer edge")

        result = graph_route.create_graph_edge(
            graph_route.GraphEdgeCreateBody(source_node_id="faq", target_node_id="embedded", relation_type="manual", persona_id="persona-1"),
            SimpleNamespace(),
        )
    finally:
        for obj, name, fn in originals:
            setattr(obj, name, fn)

    _assert(result["success"] is True, "API allows FAQ -> embedded publication")
    _assert(result["edge"]["source_node_id"] == "n-faq" and result["edge"]["target_node_id"] == "n-embedded", "embedded edge keeps FAQ as source")


def test_frontend_layout_treats_answers_question_as_inbound_to_faq() -> None:
    layout = (ROOT / "dashboard" / "components" / "graph" / "knowledgeGraphLayout.ts").read_text(encoding="utf-8")
    faq_parent_line = next((line for line in layout.splitlines() if line.strip().startswith("faq: [")), "")
    for parent_type in ['"copy"', '"offer"', '"product"']:
        _assert(parent_type in faq_parent_line, f"frontend expected FAQ parent includes {parent_type}")
    child_to_parent_block = layout.split("if (edge.source === childId && edge.target === parentId)", 1)[1].split("if (edge.source === parentId && edge.target === childId)", 1)[0]
    parent_to_child_block = layout.split("if (edge.source === parentId && edge.target === childId)", 1)[1].split("return 0;", 1)[0]
    _assert('"answers_question"' not in child_to_parent_block, "answers_question is not accepted as FAQ -> parent")
    _assert('"answers_question"' in parent_to_child_block, "answers_question is accepted as parent -> FAQ")


def test_migration_repairs_inverted_faq_edges() -> None:
    migration = (ROOT / "supabase" / "migrations" / "034_repair_faq_edge_direction.sql").read_text(encoding="utf-8")
    _assert("src.node_type = 'faq'" in migration, "migration finds FAQ-sourced invalid edges")
    _assert("tgt.node_type IN ('product', 'offer', 'copy', 'campaign', 'audience')" in migration, "migration targets commercial parent types")
    _assert("invalid_edges.parent_node_id" in migration and "invalid_edges.faq_node_id" in migration, "migration inserts reversed parent -> FAQ edge")
    _assert("'active', false" in migration and "'visual_hidden', true" in migration, "migration soft-deletes invalid edge")


def test_graph_payload_filters_inactive_edges() -> None:
    graph_route = (ROOT / "api" / "routes" / "graph.py").read_text(encoding="utf-8")
    _assert('get("active") is not False' in graph_route, "graph-data filters soft-deleted edges before tree rendering")


def test_reparented_primary_edges_stop_being_visual_primary() -> None:
    client = (ROOT / "api" / "services" / "supabase_client.py").read_text(encoding="utf-8")
    block = client.split('def deactivate_primary_paths_for_target', 1)[1].split('def delete_knowledge_edge', 1)[0]
    _assert('"active": False' in block, "reparent soft-deletes previous primary edge")
    _assert('"primary_tree": False' in block, "reparented edge is no longer a primary tree edge")
    _assert('"visual_hidden": True' in block, "reparented edge is hidden from graph visuals")


def main() -> None:
    test_bootstrap_faq_references_point_into_faq()
    test_graph_edge_api_blocks_faq_outgoing_except_embedded()
    test_frontend_layout_treats_answers_question_as_inbound_to_faq()
    test_migration_repairs_inverted_faq_edges()
    test_graph_payload_filters_inactive_edges()
    test_reparented_primary_edges_stop_being_visual_primary()
    print("PASS integration_faq_edge_direction_contract")


if __name__ == "__main__":
    main()
