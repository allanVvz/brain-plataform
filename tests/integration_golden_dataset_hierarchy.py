# -*- coding: utf-8 -*-
"""
Offline checks for Golden Dataset hierarchy:
PLAN parent_slug -> graph hierarchy -> approved snapshot -> contextual FAQ chunk.

Run:
  python tests/integration_golden_dataset_hierarchy.py
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok {message}")


def test_plan_without_brand_parent_slugs() -> None:
    from services import kb_intake_service

    plan = {
        "entries": [
            {"content_type": "briefing", "slug": "briefing-tock-fatal", "title": "Briefing Tock Fatal", "content": "Campanha de inverno."},
            {"content_type": "audience", "slug": "publico-tock-fatal", "title": "Publico Tock Fatal", "content": "Empreendedoras."},
            {"content_type": "product", "slug": "kit-roupas-tock-fatal", "title": "Kit Roupas Tock Fatal", "content": "Kit contendo 5 pecas."},
            {"content_type": "copy", "slug": "copy-campanha-tock-fatal", "title": "Copy Campanha", "content": "Copy comercial."},
            {"content_type": "faq", "slug": "faq-tock-fatal", "title": "FAQ Tock Fatal", "content": "Pergunta: Preco?\nResposta: R$ 59,90."},
        ]
    }
    normalized = kb_intake_service._normalize_sofia_knowledge_plan(
        plan,
        {"classification": {"persona_slug": "tock-fatal"}, "context": "- faq: 1 variacao"},
    )
    by_slug = {entry["slug"]: entry for entry in normalized["entries"]}
    parent = lambda slug: (by_slug[slug].get("metadata") or {}).get("parent_slug")

    _assert(parent("briefing-tock-fatal") == "self", "briefing without brand is direct child of persona")
    _assert(parent("publico-tock-fatal") == "briefing-tock-fatal", "audience stays under briefing")
    _assert(parent("kit-roupas-tock-fatal") == "publico-tock-fatal", "product stays under audience")
    offer_entries = [entry for entry in normalized["entries"] if entry.get("content_type") == "offer"]
    _assert(bool(offer_entries), "offer is created when product/FAQ contains quantity or price")
    offer_slug = offer_entries[0]["slug"]
    _assert(parent(offer_slug) == "kit-roupas-tock-fatal", "offer stays under product")
    copy_entries = [entry for entry in normalized["entries"] if entry.get("content_type") == "copy"]
    _assert(bool(copy_entries), "PLAN contains copy entries after offer normalization")
    _assert(
        all((entry.get("metadata") or {}).get("parent_slug") == offer_slug for entry in copy_entries),
        "copy stays under offer when commercial offer exists",
    )
    faq_entries = [entry for entry in normalized["entries"] if entry.get("content_type") == "faq"]
    _assert(bool(faq_entries), "PLAN contains FAQ entries after normalization")
    _assert(
        all((entry.get("metadata") or {}).get("parent_slug") in {entry["slug"] for entry in copy_entries} for entry in faq_entries),
        "faq stays under copy in pyramidal marketing flow",
    )
    _assert(
        not any((entry.get("metadata") or {}).get("single_branch_parent_rewritten") is True for entry in faq_entries),
        "pyramidal planner does not need parent rewrite",
    )
    _assert(not normalized.get("warnings"), "pyramidal planner does not emit rewrite warnings")
    _assert(normalized.get("tree_mode") == "pyramidal", "PLAN defaults to pyramidal")
    _assert(normalized.get("branch_policy") == "top_down_pyramidal", "PLAN defaults to top_down_pyramidal")
    links = {(link["source_slug"], link["target_slug"]) for link in normalized.get("links") or []}
    _assert(("self", "briefing-tock-fatal") in links, "PLAN emits persona -> briefing link")
    _assert(("briefing-tock-fatal", "publico-tock-fatal") in links, "PLAN emits briefing -> audience link")
    _assert(("publico-tock-fatal", "kit-roupas-tock-fatal") in links, "PLAN emits audience -> product link")
    _assert(("kit-roupas-tock-fatal", offer_slug) in links, "PLAN emits product -> offer link")
    _assert(any(source == offer_slug and target in {entry["slug"] for entry in copy_entries} for source, target in links), "PLAN emits offer -> copy link")
    _assert(
        any(source in {entry["slug"] for entry in copy_entries} and by_slug.get(target, {}).get("content_type") == "faq" for source, target in links),
        "PLAN emits copy -> faq link",
    )


class FakeHierarchyStore:
    def __init__(self) -> None:
        self.persona = {"id": "persona-tock", "slug": "tock-fatal", "name": "Tock Fatal"}
        self.nodes = [
            self.node("n-persona", "persona", "self", "Persona"),
            self.node("n-briefing", "briefing", "briefing-tock-fatal", "Briefing Tock Fatal", "Campanha de inverno com kits."),
            self.node("n-audience", "audience", "publico-tock-fatal", "Publico Tock Fatal", "Empreendedoras.", metadata={"resolved_parent_node_id": "n-briefing"}),
            self.node("n-product", "product", "kit-roupas-tock-fatal", "Kit Roupas Tock Fatal", "Kit contendo 5 pecas.", metadata={"resolved_parent_node_id": "n-audience"}),
            self.node("n-copy", "copy", "copy-campanha-tock-fatal", "Copy Campanha", "Oferta do kit para revenda.", metadata={"resolved_parent_node_id": "n-product"}),
            self.node("n-faq", "faq", "faq-tock-fatal", "FAQ Tock Fatal", "Pergunta: Qual o preco?\nResposta: R$ 59,90.", source_table="knowledge_items", source_id="item-faq", metadata={"resolved_parent_node_id": "n-copy"}),
            self.node("n-mention", "mention", "publico-tock-fatal-publico-tock-fatal", "Mention duplicada"),
        ]
        self.edges = [
            self.edge("e-bad-persona-product", "n-persona", "n-product", "belongs_to_persona", {"primary_tree": True, "active": True}),
            self.edge("e-bad-product-persona", "n-product", "n-persona", "belongs_to_persona", {"primary_tree": True, "active": True}),
            self.edge("e-briefing-audience-deleted", "n-briefing", "n-audience", "contains", {"primary_tree": True, "active": False, "deleted_from": "graph_ui_reparent"}),
            self.edge("e-audience-product-deleted", "n-audience", "n-product", "offers_product", {"primary_tree": True, "active": False, "deleted_from": "graph_ui_reparent"}),
            self.edge("e-product-copy", "n-product", "n-copy", "supports_copy", {"primary_tree": True, "active": True}),
            self.edge("e-copy-faq", "n-copy", "n-faq", "answers_question", {"primary_tree": True, "active": True}),
            self.edge("e-persona-mention", "n-persona", "n-mention", "belongs_to_persona", {"primary_tree": True, "active": True}),
        ]
        self.item = {
            "id": "item-faq",
            "persona_id": self.persona["id"],
            "content_type": "faq",
            "title": "FAQ Tock Fatal",
            "content": "Pergunta: Qual o preco?\nResposta: R$ 59,90.",
            "metadata": {"classification": {"content_type": "faq"}},
            "tags": ["kit-roupas-tock-fatal"],
            "status": "approved",
        }
        self.snapshots: list[dict] = []
        self.rag_entries: list[dict] = []
        self.chunks: list[dict] = []
        self.embedded_edges: list[dict] = []

    def node(self, node_id, node_type, slug, title, summary="", source_table=None, source_id=None, metadata=None):
        return {
            "id": node_id,
            "persona_id": self.persona["id"],
            "node_type": node_type,
            "slug": slug,
            "title": title,
            "summary": summary,
            "source_table": source_table,
            "source_id": source_id,
            "tags": [slug],
            "metadata": metadata or {},
            "status": "validated",
            "level": 75 if node_type == "faq" else 40,
            "importance": 0.8,
            "confidence": 0.9,
        }

    def edge(self, edge_id, src, tgt, rel, metadata):
        return {
            "id": edge_id,
            "persona_id": self.persona["id"],
            "source_node_id": src,
            "target_node_id": tgt,
            "relation_type": rel,
            "metadata": metadata,
            "weight": 1,
        }

    def get_knowledge_node(self, node_id):
        return deepcopy(next((n for n in self.nodes if n["id"] == node_id), None))

    def get_persona_by_id(self, persona_id):
        return deepcopy(self.persona) if persona_id == self.persona["id"] else None

    def get_knowledge_item(self, item_id):
        return deepcopy(self.item) if item_id == self.item["id"] else None

    def list_all_knowledge_graph(self, persona_id=None, limit_nodes=2500):
        return deepcopy(self.nodes), deepcopy(self.edges)

    def upsert_approved_knowledge_snapshot(self, data):
        row = {**deepcopy(data), "id": "snapshot-1"}
        self.snapshots = [row]
        return deepcopy(row)

    def update_approved_knowledge_snapshot(self, snapshot_id, data):
        self.snapshots[0].update(deepcopy(data))
        return deepcopy(self.snapshots[0])

    def upsert_knowledge_rag_entry(self, data):
        row = {**deepcopy(data), "id": "rag-entry-1"}
        self.rag_entries = [row]
        return deepcopy(row)

    def replace_knowledge_rag_chunks(self, rag_entry_id, persona_id, chunks):
        self.chunks = [
            {**deepcopy(chunk), "id": f"chunk-{idx}", "rag_entry_id": rag_entry_id, "persona_id": persona_id}
            for idx, chunk in enumerate(chunks)
        ]
        return deepcopy(self.chunks)

    def update_knowledge_node(self, node_id, data):
        return {"id": node_id, **deepcopy(data)}

    def update_knowledge_item(self, item_id, data):
        return {"id": item_id, **deepcopy(data)}

    def ensure_embedded_node(self, persona_id):
        return self.node("n-embedded", "embedded", "embedded-default", "Embedded")

    def upsert_knowledge_edge(self, source_node_id, target_node_id, relation_type, persona_id=None, weight=1, metadata=None):
        row = {
            "id": "edge-embedded-1",
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "persona_id": persona_id,
            "weight": weight,
            "metadata": metadata or {},
        }
        self.embedded_edges = [row]
        return deepcopy(row)


def test_snapshot_hierarchy_and_chunk_context() -> None:
    from services import approved_knowledge_snapshots, knowledge_graph, supabase_client

    store = FakeHierarchyStore()
    patched = [
        "get_knowledge_node",
        "get_persona_by_id",
        "get_knowledge_item",
        "list_all_knowledge_graph",
        "upsert_approved_knowledge_snapshot",
        "update_approved_knowledge_snapshot",
        "upsert_knowledge_rag_entry",
        "replace_knowledge_rag_chunks",
        "update_knowledge_node",
        "update_knowledge_item",
        "ensure_embedded_node",
        "upsert_knowledge_edge",
    ]
    originals = {name: getattr(supabase_client, name) for name in patched}
    original_root = knowledge_graph._ensure_persona_root
    try:
        for name in patched:
            setattr(supabase_client, name, getattr(store, name))
        knowledge_graph._ensure_persona_root = lambda _pid: store.get_knowledge_node("n-persona")
        result = approved_knowledge_snapshots.publish_approved_node("n-faq")
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)
        knowledge_graph._ensure_persona_root = original_root

    _assert(result["success"] is True, "FAQ publication succeeds with repaired hierarchy")
    path_types = [step["node_type"] for step in store.snapshots[0]["hierarchy_path"]]
    _assert(path_types == ["persona", "briefing", "audience", "product", "copy", "faq"], "snapshot hierarchy is top-down without persona cycle")
    _assert(path_types.count("persona") == 1, "snapshot hierarchy contains persona only at root")
    _assert("mention" not in path_types, "mention is excluded from approved snapshot hierarchy")
    metadata = store.snapshots[0]["metadata"]
    branch_context = metadata.get("branch_context") or {}
    _assert([step["node_type"] for step in branch_context.get("path", [])] == path_types, "snapshot metadata branch_context path mirrors hierarchy")
    branch_edges = branch_context.get("edges") or []
    _assert(len(branch_edges) == 5, "snapshot metadata branch_context carries full branch edges")
    _assert(any(edge.get("semantic_relation") == "defines_audience" for edge in branch_edges), "branch edges carry safe semantic_relation metadata")
    _assert(metadata.get("brand_source") == "persona_fallback", "snapshot brand context falls back to persona when no brand node exists")
    _assert(metadata.get("briefing_context"), "snapshot metadata includes briefing context")
    _assert(metadata.get("audience_context"), "snapshot metadata includes audience context")
    _assert(metadata.get("product_context"), "snapshot metadata includes product context")
    _assert(metadata.get("copy_context"), "snapshot metadata includes copy context")
    _assert((metadata.get("faq_context") or {}).get("question"), "snapshot metadata includes FAQ question")
    _assert((metadata.get("faq_context") or {}).get("answer"), "snapshot metadata includes FAQ answer")
    chunk_text = store.chunks[0]["chunk_text"]
    _assert("Briefing: Campanha de inverno" in chunk_text, "FAQ chunk includes briefing context")
    _assert("Publico: Empreendedoras" in chunk_text, "FAQ chunk includes audience context")
    _assert("Copy/Oferta: Oferta do kit" in chunk_text, "FAQ chunk includes copy context")
    _assert("Caminho da branch:" in chunk_text, "FAQ chunk includes branch path")
    _assert("Relacoes:" in chunk_text and "defines_audience" in chunk_text, "FAQ chunk includes semantic relations")
    _assert("Briefing: Nao informado." not in chunk_text, "FAQ chunk does not lose briefing when it exists")
    _assert("Publico: Nao informado." not in chunk_text, "FAQ chunk does not lose audience when it exists")


def test_mentions_cannot_publish() -> None:
    from services import approved_knowledge_snapshots, supabase_client

    store = FakeHierarchyStore()
    original = supabase_client.get_knowledge_node
    try:
        supabase_client.get_knowledge_node = store.get_knowledge_node
        try:
            approved_knowledge_snapshots.publish_approved_node("n-mention")
        except ValueError as exc:
            _assert("Mention nodes cannot be published" in str(exc), "mention nodes cannot generate snapshots")
        else:
            raise AssertionError("mention publication should fail")
    finally:
        supabase_client.get_knowledge_node = original


def test_incomplete_faq_snapshot_needs_review_without_rag() -> None:
    from services import approved_knowledge_snapshots, knowledge_graph, supabase_client

    store = FakeHierarchyStore()
    store.item["content"] = "Pergunta: Qual o preco?\nResposta: Qual o preco?"
    faq = next(node for node in store.nodes if node["id"] == "n-faq")
    faq["summary"] = store.item["content"]
    patched = [
        "get_knowledge_node",
        "get_persona_by_id",
        "get_knowledge_item",
        "list_all_knowledge_graph",
        "upsert_approved_knowledge_snapshot",
        "update_approved_knowledge_snapshot",
        "upsert_knowledge_rag_entry",
        "replace_knowledge_rag_chunks",
        "update_knowledge_node",
        "update_knowledge_item",
        "ensure_embedded_node",
        "upsert_knowledge_edge",
    ]
    originals = {name: getattr(supabase_client, name) for name in patched}
    original_root = knowledge_graph._ensure_persona_root
    try:
        for name in patched:
            setattr(supabase_client, name, getattr(store, name))
        knowledge_graph._ensure_persona_root = lambda _pid: store.get_knowledge_node("n-persona")
        result = approved_knowledge_snapshots.publish_approved_node("n-faq")
    finally:
        for name, fn in originals.items():
            setattr(supabase_client, name, fn)
        knowledge_graph._ensure_persona_root = original_root

    _assert(result["success"] is False, "incomplete FAQ publication returns success=false")
    _assert(result["status"] == "needs_review", "incomplete FAQ snapshot is marked needs_review")
    _assert(not result["rag_chunk_ids"] and not store.chunks, "incomplete FAQ does not create active RAG chunks")
    _assert("faq_answer_not_useful" in result["review_warnings"], "incomplete FAQ returns review warning")


def test_classification_content_type_contract() -> None:
    kb_intake = (API_DIR / "services" / "kb_intake_service.py").read_text(encoding="utf-8")
    lifecycle = (API_DIR / "services" / "knowledge_lifecycle.py").read_text(encoding="utf-8")
    _assert('"content_type": payload["content_type"]' in kb_intake, "save metadata classification uses payload content_type")
    _assert('merged_classification["content_type"] = content_type' in lifecycle, "lifecycle aligns classification content_type")


def test_flexible_marketing_variations() -> None:
    from services import kb_intake_service

    def normalize(entries):
        return kb_intake_service._normalize_sofia_knowledge_plan(
            {"entries": entries},
            {"classification": {"persona_slug": "tock-fatal"}, "context": "- faq: 1 variacao"},
        )

    brand_plan = normalize([
        {"content_type": "brand", "slug": "tock-fatal", "title": "Tock Fatal", "content": "Marca."},
        {"content_type": "briefing", "slug": "briefing-modal", "title": "Briefing Modal", "content": "Briefing."},
        {"content_type": "audience", "slug": "revendedoras", "title": "Revendedoras", "content": "Publico."},
        {"content_type": "product", "slug": "kit-modal", "title": "Kit Modal", "content": "Produto."},
        {"content_type": "faq", "slug": "faq-kit-modal", "title": "FAQ Kit Modal", "content": "Pergunta: Preco?\nResposta: Validar."},
    ])
    by_slug = {entry["slug"]: entry for entry in brand_plan["entries"]}
    _assert((by_slug["tock-fatal"]["metadata"] or {}).get("parent_slug") == "self", "brand is direct child of persona")
    _assert((by_slug["briefing-modal"]["metadata"] or {}).get("parent_slug") == "tock-fatal", "brand inserted above briefing")

    product_briefing = normalize([
        {"content_type": "brand", "slug": "tock-fatal", "title": "Tock Fatal", "content": "Marca."},
        {"content_type": "product", "slug": "kit-modal", "title": "Kit Modal", "content": "Produto.", "metadata": {"parent_slug": "tock-fatal"}},
        {"content_type": "briefing", "slug": "briefing-kit-modal", "title": "Briefing Kit Modal", "content": "Briefing do produto.", "metadata": {"parent_slug": "kit-modal", "briefing_scope": "product"}},
        {"content_type": "faq", "slug": "faq-kit-modal", "title": "FAQ Kit Modal", "content": "Pergunta: Preco?\nResposta: Validar.", "metadata": {"parent_slug": "briefing-kit-modal"}},
    ])
    by_slug = {entry["slug"]: entry for entry in product_briefing["entries"]}
    _assert((by_slug["briefing-kit-modal"]["metadata"] or {}).get("parent_slug") == "kit-modal", "product-level briefing is accepted")
    _assert((by_slug["briefing-kit-modal"]["metadata"] or {}).get("briefing_scope") == "product", "product-level briefing keeps scope metadata")

    entity_group = normalize([
        {"content_type": "brand", "slug": "tock-fatal", "title": "Tock Fatal", "content": "Marca."},
        {"content_type": "entity", "slug": "modal", "title": "Modal", "content": "Grupo de produtos modal.", "metadata": {"parent_slug": "tock-fatal", "entity_role": "product_group"}},
        {"content_type": "product", "slug": "kit-modal", "title": "Kit Modal", "content": "Produto.", "metadata": {"parent_slug": "modal"}},
        {"content_type": "faq", "slug": "faq-kit-modal", "title": "FAQ Kit Modal", "content": "Pergunta: Preco?\nResposta: Validar."},
    ])
    by_slug = {entry["slug"]: entry for entry in entity_group["entries"]}
    _assert((by_slug["modal"]["metadata"] or {}).get("entity_structural") is True, "entity product_group is structural")
    _assert((by_slug["kit-modal"]["metadata"] or {}).get("parent_slug") == "modal", "product can stay under structural entity")

    attribute_entity = normalize([
        {"content_type": "product", "slug": "kit-modal", "title": "Kit Modal", "content": "Produto.", "metadata": {"attributes": {"cores": ["vermelho", "preto", "verde"]}}},
        {"content_type": "faq", "slug": "faq-kit-modal", "title": "FAQ Kit Modal", "content": "Pergunta: Cores?\nResposta: Vermelho, preto e verde."},
    ])
    _assert(not any(entry.get("slug") in {"vermelho", "preto", "verde"} for entry in attribute_entity["entries"]), "color attributes do not force visual entity nodes")
    product = next(entry for entry in attribute_entity["entries"] if entry["content_type"] == "product")
    _assert(product["metadata"]["price_status"] == "pending_validation", "product gets price_status placeholder")
    _assert(product["metadata"]["stock_status"] == "unknown", "product gets stock_status placeholder")
    audience = next(entry for entry in brand_plan["entries"] if entry["content_type"] == "audience")
    _assert(audience["metadata"]["audience_source"] == "manual", "audience gets source placeholder")
    _assert("crm_filters" in audience["metadata"], "audience gets CRM placeholder")


def test_branch_policy_variations() -> None:
    from services import kb_intake_service

    base_entries = [
        {"content_type": "briefing", "slug": "briefing-venda", "title": "Briefing Venda", "content": "Venda."},
        {"content_type": "audience", "slug": "audience-mulheres", "title": "Mulheres", "content": "Publico."},
        {"content_type": "product", "slug": "product-kit", "title": "Kit", "content": "Produto."},
        {"content_type": "copy", "slug": "copy-oferta-kit", "title": "Copy Oferta", "content": "Oferta."},
        {"content_type": "faq", "slug": "faq-preco-kit", "title": "FAQ Preco", "content": "Pergunta: Preco?\nResposta: Validar."},
    ]
    parallel = kb_intake_service._normalize_sofia_knowledge_plan(
        {"entries": deepcopy(base_entries)},
        {
            "classification": {"persona_slug": "tock-fatal"},
            "context": "crie copy e FAQs como galhos separados do produto\n- faq: 1 variacao",
        },
    )
    by_slug = {entry["slug"]: entry for entry in parallel["entries"]}
    _assert(parallel.get("tree_mode") == "pyramidal", "PLAN keeps pyramidal tree mode")
    _assert(parallel.get("branch_policy") == "top_down_pyramidal", "PLAN keeps top_down_pyramidal policy")
    parallel_faqs = [entry for entry in parallel["entries"] if entry.get("content_type") == "faq"]
    parallel_copy_slugs = {entry["slug"] for entry in parallel["entries"] if entry.get("content_type") == "copy"}
    _assert(
        parallel_faqs and all((entry.get("metadata") or {}).get("parent_slug") in parallel_copy_slugs for entry in parallel_faqs),
        "pyramidal policy keeps FAQ Golden Dataset under copy",
    )

    ambiguous = kb_intake_service._normalize_sofia_knowledge_plan(
        {"entries": [
            {"content_type": "briefing", "slug": "briefing-venda", "title": "Briefing Venda", "content": "Venda."},
            {"content_type": "copy", "slug": "copy-solta", "title": "Copy Solta", "content": "Oferta sem produto/campanha."},
        ]},
        {"classification": {"persona_slug": "tock-fatal"}, "context": "nova copy sem dizer produto campanha ou publico"},
    )
    copy = next(entry for entry in ambiguous["entries"] if entry["content_type"] == "copy")
    _assert(not (copy.get("metadata") or {}).get("parent_slug"), "ambiguous copy does not fall back to persona/briefing")
    violations = kb_intake_service.validate_sofia_knowledge_plan(ambiguous, session={"context": ""})
    _assert(any("requires a parent" in violation for violation in violations), "ambiguous new branch must ask before saving")

    raw_bad_single_branch = {
        "tree_mode": "single_branch",
        "entries": [
            {"content_type": "briefing", "slug": "briefing-venda", "title": "Briefing Venda", "content": "Venda.", "metadata": {"parent_slug": "self"}},
            {"content_type": "audience", "slug": "audience-mulheres", "title": "Mulheres", "content": "Publico.", "metadata": {"parent_slug": "briefing-venda"}},
            {"content_type": "product", "slug": "product-kit", "title": "Kit", "content": "Produto.", "metadata": {"parent_slug": "audience-mulheres"}},
            {"content_type": "copy", "slug": "copy-oferta-kit", "title": "Copy Oferta", "content": "Oferta.", "metadata": {"parent_slug": "product-kit"}},
            {"content_type": "faq", "slug": "faq-preco-kit", "title": "FAQ Preco", "content": "Pergunta: Preco?\nResposta: Validar.", "metadata": {"parent_slug": "product-kit"}},
        ],
        "links": [{"source_slug": "product-kit", "target_slug": "faq-preco-kit", "relation_type": "answers_question"}],
    }
    raw_violations = kb_intake_service.validate_sofia_knowledge_plan(raw_bad_single_branch, session={"context": ""})
    _assert(any("faq must use copy parent" in violation for violation in raw_violations), "pre-save validation rejects product -> faq when copy exists")


def test_multi_audience_duplicates_commercial_subbranches() -> None:
    from services import kb_intake_service

    normalized = kb_intake_service._normalize_sofia_knowledge_plan(
        {"entries": [
            {"content_type": "briefing", "slug": "briefing-venda", "title": "Briefing Venda", "content": "Venda."},
            {"content_type": "audience", "slug": "audience-a", "title": "Publico A", "content": "Publico A."},
            {"content_type": "audience", "slug": "audience-b", "title": "Publico B", "content": "Publico B."},
            {"content_type": "product", "slug": "product-kit", "title": "Kit", "content": "Produto."},
            {"content_type": "copy", "slug": "copy-oferta", "title": "Copy Oferta", "content": "Oferta.", "metadata": {"parent_slug": "product-kit"}},
            {"content_type": "faq", "slug": "faq-preco", "title": "FAQ Preco", "content": "Pergunta: Preco?\nResposta: Validar.", "metadata": {"parent_slug": "product-kit"}},
            {"content_type": "faq", "slug": "faq-promo", "title": "FAQ Promo", "content": "Pergunta: Promo?\nResposta: Validar.", "metadata": {"parent_slug": "product-kit"}},
        ]},
        {"classification": {"persona_slug": "tock-fatal"}, "context": "- faq: 2 variacoes"},
    )
    products = [entry for entry in normalized["entries"] if entry["content_type"] == "product"]
    offers = [entry for entry in normalized["entries"] if entry["content_type"] == "offer"]
    copies = [entry for entry in normalized["entries"] if entry["content_type"] == "copy"]
    faqs = [entry for entry in normalized["entries"] if entry["content_type"] == "faq"]
    product_slugs = {entry["slug"] for entry in products}
    copy_parent_slugs = {(entry.get("metadata") or {}).get("parent_slug") for entry in copies}
    copy_slugs = {entry["slug"] for entry in copies}
    faq_parent_slugs = [(entry.get("metadata") or {}).get("parent_slug") for entry in faqs]

    _assert(len(products) == 2, "two audiences receive product branches")
    _assert({(entry.get("metadata") or {}).get("parent_slug") for entry in products} == {"audience-a", "audience-b"}, "products are scoped under each audience")
    _assert(len(offers) == 0, "offers are not invented without commercial variation")
    _assert(len(copies) == 2 and copy_parent_slugs == product_slugs, "each product receives its own copy")
    _assert(len(faqs) == 2 and all(parent in copy_slugs for parent in faq_parent_slugs), "FAQ Golden Dataset creates one document under each copy")
    _assert(not any((entry.get("metadata") or {}).get("single_branch_parent_rewritten") for entry in faqs), "multi-audience expansion does not use parent rewrite")


def test_multi_product_keeps_each_lower_subbranch_scoped() -> None:
    from services import kb_intake_service

    normalized = kb_intake_service._normalize_sofia_knowledge_plan(
        {"entries": [
            {"content_type": "briefing", "slug": "briefing-venda", "title": "Briefing Venda", "content": "Venda."},
            {"content_type": "audience", "slug": "audience-a", "title": "Publico A", "content": "Publico A."},
            {"content_type": "product", "slug": "product-1", "title": "Produto 1", "content": "Produto 1."},
            {"content_type": "copy", "slug": "copy-product-1", "title": "Copy Produto 1", "content": "Copy 1.", "metadata": {"parent_slug": "product-1"}},
            {"content_type": "faq", "slug": "faq-product-1", "title": "FAQ Produto 1", "content": "Pergunta: Produto 1?\nResposta: Validar.", "metadata": {"parent_slug": "product-1"}},
            {"content_type": "product", "slug": "product-2", "title": "Produto 2", "content": "Produto 2."},
            {"content_type": "copy", "slug": "copy-product-2", "title": "Copy Produto 2", "content": "Copy 2.", "metadata": {"parent_slug": "product-2"}},
            {"content_type": "faq", "slug": "faq-product-2", "title": "FAQ Produto 2", "content": "Pergunta: Produto 2?\nResposta: Validar.", "metadata": {"parent_slug": "product-2"}},
        ]},
        {"classification": {"persona_slug": "tock-fatal"}, "context": "- faq: 1 variacao"},
    )
    by_slug = {entry["slug"]: entry for entry in normalized["entries"]}
    _assert((by_slug["product-1"]["metadata"] or {}).get("parent_slug") == "audience-a", "product 1 stays under audience")
    _assert((by_slug["product-2"]["metadata"] or {}).get("parent_slug") == "audience-a", "product 2 stays under audience")
    _assert((by_slug["copy-product-1"]["metadata"] or {}).get("parent_slug") == "product-1", "copy 1 stays under product 1")
    _assert((by_slug["copy-product-2"]["metadata"] or {}).get("parent_slug") == "product-2", "copy 2 stays under product 2")
    scoped_faqs = [entry for entry in normalized["entries"] if entry["content_type"] == "faq"]
    _assert(len(scoped_faqs) == 2, "FAQ Golden Dataset creates one document per product copy")
    _assert(
        {(faq["metadata"] or {}).get("parent_slug") for faq in scoped_faqs} == {"copy-product-1", "copy-product-2"},
        "FAQ documents stay under their scoped copies",
    )


def test_tag_edges_are_auxiliary_metadata() -> None:
    knowledge_graph = (API_DIR / "services" / "knowledge_graph.py").read_text(encoding="utf-8")
    _assert('"graph_layer": "semantic_tags"' in knowledge_graph, "tag edges carry semantic_tags graph_layer metadata")
    _assert('"primary_tree": False' in knowledge_graph, "tag edges are not primary tree")
    _assert('"visual_hidden": True' in knowledge_graph, "tag edges stay hidden from primary visual tree")


def test_duplicate_primary_tree_guard_is_present() -> None:
    supabase_client = (API_DIR / "services" / "supabase_client.py").read_text(encoding="utf-8")
    migration = (ROOT / "supabase" / "migrations" / "029_single_branch_primary_edge_policy.sql").read_text(encoding="utf-8")
    _assert("demote_duplicate_primary_edges_for_pair" in supabase_client, "runtime demotes duplicate primary source-target edges")
    _assert("duplicate_source_target" in supabase_client, "runtime marks duplicate primary edges hidden")
    _assert("PARTITION BY e.source_node_id, e.target_node_id" in migration, "migration repairs duplicate primary source-target edges")


def main() -> int:
    print("\n-- PLAN hierarchy --")
    test_plan_without_brand_parent_slugs()
    print("\n-- Snapshot / RAG context --")
    test_snapshot_hierarchy_and_chunk_context()
    print("\n-- Mentions --")
    test_mentions_cannot_publish()
    print("\n-- Incomplete FAQ gate --")
    test_incomplete_faq_snapshot_needs_review_without_rag()
    print("\n-- Classification metadata --")
    test_classification_content_type_contract()
    print("\n-- Flexible variations --")
    test_flexible_marketing_variations()
    print("\n-- Branch policy --")
    test_branch_policy_variations()
    print("\n-- Fractal commercial expansion --")
    test_multi_audience_duplicates_commercial_subbranches()
    test_multi_product_keeps_each_lower_subbranch_scoped()
    print("\n-- Auxiliary tags --")
    test_tag_edges_are_auxiliary_metadata()
    print("\n-- Duplicate edge guard --")
    test_duplicate_primary_tree_guard_is_present()
    print("\nPASS golden dataset hierarchy validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
