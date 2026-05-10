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
    _assert(parent("copy-campanha-tock-fatal") == "kit-roupas-tock-fatal", "copy stays under product")
    faq_entries = [entry for entry in normalized["entries"] if entry.get("content_type") == "faq"]
    _assert(bool(faq_entries), "PLAN contains FAQ entries after normalization")
    _assert(
        all((entry.get("metadata") or {}).get("parent_slug") == "copy-campanha-tock-fatal" for entry in faq_entries),
        "faq stays under copy in single_branch marketing flow",
    )
    _assert(normalized.get("tree_mode") == "single_branch", "PLAN defaults to single_branch")
    _assert(normalized.get("branch_policy") == "ask_before_new_branch", "PLAN asks before new branch by default")
    links = {(link["source_slug"], link["target_slug"]) for link in normalized.get("links") or []}
    _assert(("self", "briefing-tock-fatal") in links, "PLAN emits persona -> briefing link")
    _assert(("briefing-tock-fatal", "publico-tock-fatal") in links, "PLAN emits briefing -> audience link")
    _assert(("publico-tock-fatal", "kit-roupas-tock-fatal") in links, "PLAN emits audience -> product link")
    _assert(("kit-roupas-tock-fatal", "copy-campanha-tock-fatal") in links, "PLAN emits product -> copy link")
    _assert(
        any(source == "copy-campanha-tock-fatal" and target.startswith("faq-tock-fatal") for source, target in links),
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
    chunk_text = store.chunks[0]["chunk_text"]
    _assert("Briefing: Campanha de inverno" in chunk_text, "FAQ chunk includes briefing context")
    _assert("Publico: Empreendedoras" in chunk_text, "FAQ chunk includes audience context")
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
    _assert(parallel.get("tree_mode") == "parallel_outputs", "explicit parallel request sets parallel_outputs")
    parallel_faqs = [entry for entry in parallel["entries"] if entry.get("content_type") == "faq"]
    _assert(
        parallel_faqs and all((entry.get("metadata") or {}).get("parent_slug") == "product-kit" for entry in parallel_faqs),
        "parallel_outputs keeps FAQ under product",
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
    print("\n-- Classification metadata --")
    test_classification_content_type_contract()
    print("\n-- Flexible variations --")
    test_flexible_marketing_variations()
    print("\n-- Branch policy --")
    test_branch_policy_variations()
    print("\n-- Duplicate edge guard --")
    test_duplicate_primary_tree_guard_is_present()
    print("\nPASS golden dataset hierarchy validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
