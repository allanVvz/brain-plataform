#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc
from services import supabase_client as sb


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def parent_slug(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("parent_slug") or "")


def normalize(raw_plan: dict, context: str) -> dict:
    session = {
        "id": "fractal-commercial-contract",
        "context": context,
        "messages": [{"role": "user", "content": context}],
        "classification": {"persona_slug": "tock-fatal"},
    }
    state = svc.normalize_validate_summarize_plan(raw_plan, session)
    expect(state["validation"]["valid"] is True, f"plan valid: {state['validation']}")
    return state["normalized_plan"]


def base_plan(audiences: list[tuple[str, str]], products: list[str], *, include_rule: bool = True) -> dict:
    entries = [
        {"content_type": "briefing", "title": "Briefing Tock Fatal", "slug": "briefing-tock-fatal", "content": "Moda feminina em modal.", "metadata": {}},
        {"content_type": "campaign", "title": "Campanha Modal", "slug": "campaign-modal", "content": "Campanha comercial.", "metadata": {"parent_slug": "briefing-tock-fatal"}},
    ]
    entries.extend(
        {"content_type": "audience", "title": title, "slug": slug, "content": title, "metadata": {"parent_slug": "campaign-modal"}}
        for title, slug in audiences
    )
    entries.extend(
        {"content_type": "product", "title": title, "slug": f"product-{idx}", "content": title, "metadata": {}}
        for idx, title in enumerate(products, 1)
    )
    entries.append({"content_type": "copy", "title": "Copy comercial", "slug": "copy-comercial", "content": "Mensagem de WhatsApp.", "metadata": {}})
    if include_rule:
        entries.append({"content_type": "rule", "title": "Limites comerciais", "slug": "rule-limites-comerciais", "content": "Nao inventar preco, estoque ou condicoes.", "metadata": {}})
    entries.append({"content_type": "faq", "title": "FAQ inicial", "slug": "faq-inicial", "content": "Perguntas iniciais.", "metadata": {}})
    return {
        "source": "session",
        "persona_slug": "tock-fatal",
        "tree_mode": "pyramidal",
        "faq_count_policy": "per_branch",
        "copy_policy": "per_offer",
        "entries": entries,
        "links": [],
    }


def entries_by_type(plan: dict, content_type: str) -> list[dict]:
    return [entry for entry in plan["entries"] if entry["content_type"] == content_type]


def assert_no_internal_faq_terms(plan: dict) -> None:
    forbidden = ["arvore", "árvore", "grafo", "galho", "node", "branch", "regra", "estrutura", "conhecimento conectado"]
    faq = entries_by_type(plan, "faq")[0]
    lowered = str(faq.get("content") or "").lower()
    for term in forbidden:
        expect(term not in lowered, f"FAQ does not expose internal term {term}")


def test_two_audiences_two_products_different_offers() -> None:
    plan = normalize(
        base_plan(
            [("Publico final", "audience-publico-final"), ("Publico empreendedor", "audience-publico-empreendedor")],
            ["Kit Modal 1", "Kit Modal 2"],
        ),
        "1 peca R$ 59,90 e para publico final. 5 pecas R$ 249,00 e 10 pecas R$ 459,00 sao para empreendedoras. Criar FAQ.",
    )
    counts = svc.count_blocks_by_type(plan["entries"])
    expect(counts["audience"] == 2, "two audiences")
    expect(counts["product"] == 4, "products are contextualized per audience")
    expect(counts["offer"] == 6, "six offers distributed by audience role")
    expect(counts["copy"] == 4, "one copy per audience/product")
    expect(counts["rule"] == 1, "one governing rule")
    expect(counts["faq"] == 1, "one grouped FAQ")

    by_slug = {entry["slug"]: entry for entry in plan["entries"]}
    for copy in entries_by_type(plan, "copy"):
        expect(by_slug[parent_slug(copy)]["content_type"] == "product", "copy parent is product context")
    faq_parent = by_slug[parent_slug(entries_by_type(plan, "faq")[0])]
    expect(faq_parent["content_type"] == "rule", "FAQ is below rule")
    assert_no_internal_faq_terms(plan)


def test_one_audience_two_products_same_offers() -> None:
    plan = normalize(
        base_plan([("Publico final", "audience-publico-final")], ["Kit Modal 1", "Kit Modal 2"]),
        "Criar ofertas iguais para os dois produtos: 1 peca R$ 59,90, 5 pecas R$ 249,00 e 10 pecas R$ 459,00. Criar FAQ.",
    )
    counts = svc.count_blocks_by_type(plan["entries"])
    expect(counts["product"] == 2, "two products")
    expect(counts["offer"] == 6, "same offers are created per product")
    expect(counts["copy"] == 2, "copy grouped per product context")
    expect(counts["faq"] == 1, "one grouped FAQ")


def test_two_audiences_one_product_different_offers() -> None:
    plan = normalize(
        base_plan(
            [("Cliente final", "audience-cliente-final"), ("Empreendedoras revendedoras", "audience-empreendedoras")],
            ["Kit Modal"],
        ),
        "1 peca R$ 59,90 e para cliente final. 5 pecas R$ 249,00 e 10 pecas R$ 459,00 sao para empreendedoras. Criar FAQ.",
    )
    counts = svc.count_blocks_by_type(plan["entries"])
    expect(counts["product"] == 2, "same product is contextualized for each audience")
    expect(counts["offer"] == 3, "offers follow audience roles")
    expect(counts["copy"] == 2, "one copy per audience/product")


def test_rule_before_faq() -> None:
    plan = normalize(
        base_plan([("Publico final", "audience-publico-final")], ["Kit Modal"]),
        "Criar oferta de 1 peca R$ 59,90. Nao inventar preco, estoque ou condicoes. Criar FAQ.",
    )
    by_slug = {entry["slug"]: entry for entry in plan["entries"]}
    faq = entries_by_type(plan, "faq")[0]
    rule = by_slug[parent_slug(faq)]
    expect(rule["content_type"] == "rule", "rule is structural parent before FAQ")
    expect(any(link["source_slug"] == rule["slug"] and link["target_slug"] == faq["slug"] for link in plan["links"]), "rule -> FAQ link exists")


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, store: "FakeClient", name: str):
        self.store = store
        self.name = name
        self.filters: list[tuple[str, object]] = []
        self.payload: dict | None = None

    def select(self, *_args):
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def eq(self, key: str, value):
        self.filters.append((key, value))
        return self

    def limit(self, _value: int):
        return self

    def execute(self):
        rows = self.store.rows[self.name]
        matched = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        if self.payload is not None:
            for row in matched:
                row.update(self.payload)
        return FakeResult([dict(row) for row in matched])


class FakeClient:
    def __init__(self):
        self.rows = {
            "knowledge_items": [
                {"id": "offer-1", "content_type": "offer", "persona_id": "p1", "metadata": {}, "updated_at": "old"},
                {"id": "faq-1", "content_type": "faq", "persona_id": "p1", "metadata": {}, "status": "approved", "updated_at": "old"},
            ],
            "knowledge_nodes": [
                {"id": "node-offer-1", "node_type": "offer", "persona_id": "p1", "source_id": "offer-1", "metadata": {}, "updated_at": "old"},
                {"id": "node-faq-1", "node_type": "faq", "persona_id": "p1", "metadata": {}, "status": "active", "updated_at": "old"},
            ],
        }

    def table(self, name: str):
        return FakeTable(self, name)


def test_related_node_change_marks_faq_stale() -> None:
    original = sb.get_client
    fake = FakeClient()
    sb.get_client = lambda: fake  # type: ignore[assignment]
    try:
        sb.update_knowledge_item("offer-1", {"content": "Oferta alterada"})
    finally:
        sb.get_client = original  # type: ignore[assignment]
    faq_item = fake.rows["knowledge_items"][1]
    faq_node = fake.rows["knowledge_nodes"][1]
    expect(faq_item["status"] == "pending_regeneration", "FAQ item status is pending_regeneration")
    expect(faq_item["updated_at"] != "old", "FAQ item updated_at changed")
    expect(faq_item["metadata"]["needs_update"] is True, "FAQ item metadata marks needs_update")
    expect(faq_node["status"] == "pending_regeneration", "FAQ node status is pending_regeneration")
    expect(faq_node["updated_at"] != "old", "FAQ node updated_at changed")


def main() -> int:
    test_two_audiences_two_products_different_offers()
    test_one_audience_two_products_same_offers()
    test_two_audiences_one_product_different_offers()
    test_rule_before_faq()
    test_related_node_change_marks_faq_stale()
    print("PASS e2e_criar_fractal_commercial_grouping_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
