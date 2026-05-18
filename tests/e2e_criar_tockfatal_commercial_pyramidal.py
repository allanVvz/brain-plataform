#!/usr/bin/env python3
"""Tock Fatal commercial pyramidal contract.

Mirrors the prompt the operator describes for the Tock Fatal campaign:

  2 audiences (Cliente final, Empreendedoras)
  4 product contexts (Kit Modal 1/2 x Cliente final/Empreendedoras)
  6 offers (Kit Modal 1 -> {1, 5, 10}, Kit Modal 2 -> {1, 5, 10})
  4 copies (one per product/audience context)
  1 rule (commercial governing rule, structural before FAQ)
  1 FAQ grouped in markdown (faq_count_policy=grouped, parent=rule)

Validates:
  - RULE is treated as the structural node above FAQ (parent_type=rule).
  - FAQ markdown never exposes internal terms (arvore, grafo, galho, node,
    branch, regra, estrutura, ...).
  - Updating an offer/product/copy/rule marks every persona FAQ as
    pending_regeneration (and bumps updated_at).

Run:
  python tests/e2e_criar_tockfatal_commercial_pyramidal.py
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc  # noqa: E402
from services import supabase_client  # noqa: E402


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def parent_slug(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("parent_slug") or "")


# ─── Part A: pyramidal structure derived from the operator's prompt ────────


def _operator_prompt_session() -> dict:
    return {
        "id": "e2e-tockfatal-commercial-pyramidal",
        "context": """
# Plano comercial - campanha Tock Fatal
persona_slug: tock-fatal

## Variacoes por atributo
- briefing: 1
- campaign: 1
- audience: 2
- product: 6
- offer: 6
- copy: 1
- rule: 1
- faq: 1 (markdown agrupado)

## Publicos
- Cliente final (1 peca)
- Empreendedoras (5 e 10 pecas para revenda)

## Produtos
- Kit Modal 1
- Kit Modal 2

## Ofertas
Kit Modal 1 -> Cliente final -> 1 peca R$ 59,90
Kit Modal 1 -> Empreendedoras -> 5 pecas R$ 249,00
Kit Modal 1 -> Empreendedoras -> 10 pecas R$ 459,00
Kit Modal 2 -> Cliente final -> 1 peca R$ 59,90
Kit Modal 2 -> Empreendedoras -> 5 pecas R$ 249,00
Kit Modal 2 -> Empreendedoras -> 10 pecas R$ 459,00
""",
        "messages": [
            {
                "role": "user",
                "content": (
                    "2 audiencias: Cliente final e Empreendedoras. "
                    "Kit Modal 1 e Kit Modal 2 vendidos para os dois publicos. "
                    "Ofertas: 1 peca para Cliente final; 5 e 10 pecas para Empreendedoras. "
                    "Quero uma regra comercial e 1 FAQ agrupado em markdown ao final."
                ),
            }
        ],
        "classification": {"persona_slug": "tock-fatal"},
    }


def _operator_prompt_raw_plan() -> dict:
    return {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "tree_mode": "pyramidal",
        "entries": [
            {"content_type": "briefing", "title": "Briefing Tock Fatal", "slug": "briefing-tock-fatal", "content": "Briefing comercial", "metadata": {}},
            {"content_type": "campaign", "title": "Campanha Kits Modal", "slug": "campaign-kits-modal", "content": "Campanha", "metadata": {"parent_slug": "briefing-tock-fatal"}},
            {"content_type": "audience", "title": "Cliente final", "slug": "audience-cliente-final", "content": "Cliente final que compra 1 peca", "metadata": {"parent_slug": "campaign-kits-modal"}},
            {"content_type": "audience", "title": "Empreendedoras", "slug": "audience-empreendedoras", "content": "Empreendedoras que revendem em kits", "metadata": {"parent_slug": "campaign-kits-modal"}},
            {"content_type": "product", "title": "Kit Modal 1", "slug": "produto-kit-modal-1", "content": "Kit Modal 1", "metadata": {}},
            {"content_type": "product", "title": "Kit Modal 2", "slug": "produto-kit-modal-2", "content": "Kit Modal 2", "metadata": {}},
            {"content_type": "copy", "title": "Copy comercial", "slug": "copy-comercial", "content": "Texto comercial base", "metadata": {}},
            {"content_type": "rule", "title": "Regra: publico x quantidade", "slug": "rule-publico-quantidade", "content": "1 peca para cliente final; 5 e 10 pecas para empreendedoras", "metadata": {}},
            {"content_type": "faq", "title": "FAQ Tock Fatal", "slug": "faq-tockfatal", "content": "Perguntas frequentes", "metadata": {}},
        ],
        "links": [],
    }


def _check_pyramidal_contract() -> None:
    session = _operator_prompt_session()
    raw_plan = _operator_prompt_raw_plan()

    normalized = svc._normalize_sofia_knowledge_plan(raw_plan, session)  # type: ignore[attr-defined]
    violations = svc.validate_sofia_knowledge_plan(normalized, session=session)
    summary = svc.summarize_normalized_plan(normalized)  # type: ignore[attr-defined]
    counts = summary["current_block_counts"]
    entries = normalized["entries"]
    by_slug = {entry["slug"]: entry for entry in entries}

    expect(violations == [], f"normalized plan has no violations: {violations}")
    expect(normalized["tree_mode"] == "pyramidal", "tree_mode stays pyramidal")
    expect(normalized["faq_count_policy"] == "grouped", "faq_count_policy=grouped (1 markdown agrupado)")
    expect(normalized["faq_parent_type"] == "rule", "FAQ sits under rule, not copy/product")

    expect(counts["briefing"] == 1, "1 briefing")
    expect(counts["campaign"] == 1, "1 campaign")
    expect(counts["audience"] == 2, "2 audiences (Cliente final + Empreendedoras)")
    expect(counts["product"] == 4, "4 product contexts (Kit Modal 1/2 x 2 audiences)")
    expect(counts["offer"] == 6, "6 offers (1+5+10 pecas por kit)")
    expect(counts["copy"] == 4, "4 copies (1 por contexto produto/audiencia)")
    expect(counts["rule"] >= 1, "rule comercial presente")
    expect(counts["faq"] == 1, "1 FAQ agrupado em markdown")

    offers = [entry for entry in entries if entry["content_type"] == "offer"]
    qtys = sorted({int((entry.get("metadata") or {}).get("quantity") or 0) for entry in offers})
    expect(qtys == [1, 5, 10], f"offer quantities = 1/5/10, got {qtys}")

    rules = [entry for entry in entries if entry["content_type"] == "rule"]
    expect(rules, "at least one rule entry")
    for rule in rules:
        parent = by_slug.get(parent_slug(rule))
        expect(parent and parent["content_type"] in {"campaign", "briefing", "brand", "persona"},
               f"rule {rule['slug']} parent is governing scope, got {parent and parent['content_type']}")

    faqs = [entry for entry in entries if entry["content_type"] == "faq"]
    expect(len(faqs) == 1, "exactly one FAQ document")
    for faq in faqs:
        parent = by_slug.get(parent_slug(faq))
        expect(parent and parent["content_type"] == "rule", f"FAQ parent is rule (got {parent and parent['content_type']})")
        body = str(faq.get("content") or "").lower()
        for forbidden in ["arvore", "árvore", "grafo", "galho", "node", "branch", "regra", "estrutura", "conhecimento conectado"]:
            expect(forbidden not in body, f"FAQ markdown does not leak internal term '{forbidden}'")

    expansion = summary.get("expansion", {})
    faq_expansion = expansion.get("faq") or {}
    expect(int(faq_expansion.get("created") or 0) == 1, "expansion.faq.created == 1 (grouped markdown)")
    expect(int(faq_expansion.get("questions_total") or 0) > 0, "FAQ markdown contains internal questions")

    print("counts", counts)
    print("expansion.faq", faq_expansion)


# ─── Part B: pending_regeneration trigger when commercial context changes ──


class _Builder:
    """Mimics the Supabase Python client chain: table().update().eq().execute()
    and table().select().eq().limit().execute(). All chain hops return self;
    execute() materialises the result via the recorder hooks."""

    def __init__(self, store: "FakeSupabase", op: str):
        self.store = store
        self.op = op
        self.table_name: str | None = None
        self.filters: dict[str, object] = {}
        self.payload: dict[str, object] | None = None
        self.selected_columns: str | None = None
        self.limit_n: int | None = None

    def update(self, data):
        self.op = "update"; self.payload = data; return self

    def insert(self, data):
        self.op = "insert"; self.payload = data; return self

    def select(self, columns="*"):
        self.op = "select"; self.selected_columns = columns; return self

    def delete(self):
        self.op = "delete"; return self

    def eq(self, key, value):
        self.filters[key] = value; return self

    def limit(self, n):
        self.limit_n = n; return self

    def order(self, *_a, **_kw):
        return self

    def execute(self):
        if self.op == "update":
            self.store.apply_update(self.table_name, self.filters, self.payload or {})
            return type("R", (), {"data": []})()
        if self.op == "select":
            rows = self.store.run_select(self.table_name, self.filters, self.limit_n)
            return type("R", (), {"data": rows})()
        return type("R", (), {"data": []})()


class FakeSupabase:
    def __init__(self) -> None:
        self.knowledge_items: list[dict] = []
        self.knowledge_nodes: list[dict] = []
        self.update_log: list[dict] = []

    def seed(self) -> None:
        persona_id = "p-tock"
        self.knowledge_items.append({
            "id": "ki-offer-1", "persona_id": persona_id, "content_type": "offer",
            "title": "Kit Modal 1 - 1 peca", "metadata": {"price": 5990}, "status": "approved",
            "updated_at": "2026-05-01T00:00:00",
        })
        self.knowledge_items.append({
            "id": "ki-faq-grouped", "persona_id": persona_id, "content_type": "faq",
            "title": "FAQ Tock Fatal", "metadata": {"faq_document_type": "golden_dataset"},
            "status": "approved", "curation_status": "approved", "updated_at": "2026-05-10T00:00:00",
        })
        self.knowledge_nodes.append({
            "id": "n-faq-grouped", "persona_id": persona_id, "node_type": "faq",
            "slug": "faq-tockfatal", "title": "FAQ Tock Fatal",
            "metadata": {}, "status": "validated", "updated_at": "2026-05-10T00:00:00",
        })

    # Table dispatcher used by the patched get_client.
    def table(self, name: str) -> _Builder:
        b = _Builder(self, op="noop"); b.table_name = name; return b

    # ── Mutations ─────────────────────────────────────────────────────────
    def apply_update(self, table: str, filters: dict, payload: dict) -> None:
        target = self._rows_for(table)
        for row in target:
            if self._matches(row, filters):
                for key, value in payload.items():
                    row[key] = value
                self.update_log.append({"table": table, "id": row.get("id"), "payload": deepcopy(payload)})

    def run_select(self, table: str, filters: dict, limit_n: int | None) -> list[dict]:
        rows = [deepcopy(r) for r in self._rows_for(table) if self._matches(r, filters)]
        if limit_n is not None:
            rows = rows[: int(limit_n)]
        return rows

    def _rows_for(self, table: str) -> list[dict]:
        if table == "knowledge_items":
            return self.knowledge_items
        if table == "knowledge_nodes":
            return self.knowledge_nodes
        return []

    def _matches(self, row: dict, filters: dict) -> bool:
        return all(row.get(k) == v for k, v in filters.items())


def _check_pending_regeneration_trigger() -> None:
    fake = FakeSupabase(); fake.seed()
    orig_get_client = getattr(supabase_client, "get_client")
    supabase_client.get_client = lambda: fake  # type: ignore[assignment]
    try:
        # Touch the offer — content_type in {brand,briefing,audience,product,offer,copy,rule}
        supabase_client.update_knowledge_item("ki-offer-1", {"title": "Kit Modal 1 - 1 peca (revisado)"})
    finally:
        supabase_client.get_client = orig_get_client  # type: ignore[assignment]

    faq_item = next(r for r in fake.knowledge_items if r["id"] == "ki-faq-grouped")
    faq_node = next(r for r in fake.knowledge_nodes if r["id"] == "n-faq-grouped")

    expect(faq_item["status"] == "pending_regeneration", "FAQ item status flips to pending_regeneration when offer changes")
    expect(faq_item.get("curation_status") == "stale", "FAQ item curation_status=stale")
    meta = faq_item.get("metadata") or {}
    expect(meta.get("faq_status") == "pending_regeneration", "FAQ metadata.faq_status=pending_regeneration")
    expect(meta.get("needs_update") is True, "FAQ metadata.needs_update=True")
    expect(meta.get("stale_reason") == "related_context_changed", "FAQ metadata.stale_reason=related_context_changed")
    expect(meta.get("changed_source_id") == "ki-offer-1", "FAQ metadata.changed_source_id points to the offer")
    expect(bool(meta.get("stale_marked_at")), "FAQ metadata.stale_marked_at is set")
    expect(faq_item.get("updated_at") and faq_item["updated_at"] != "2026-05-10T00:00:00",
           "FAQ item updated_at is bumped")

    expect(faq_node["status"] == "pending_regeneration", "FAQ node status=pending_regeneration")
    node_meta = faq_node.get("metadata") or {}
    expect(node_meta.get("faq_status") == "pending_regeneration", "FAQ node metadata.faq_status=pending_regeneration")
    expect(node_meta.get("changed_source_id") == "ki-offer-1", "FAQ node metadata.changed_source_id points to the offer")
    expect(faq_node.get("updated_at") and faq_node["updated_at"] != "2026-05-10T00:00:00",
           "FAQ node updated_at is bumped")


def main() -> int:
    print("== Part A: pyramidal structure ==")
    _check_pyramidal_contract()
    print("== Part B: pending_regeneration trigger ==")
    _check_pending_regeneration_trigger()
    print("PASS e2e_criar_tockfatal_commercial_pyramidal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
