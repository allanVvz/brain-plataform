#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc
from services import knowledge_graph


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def _entry(content_type: str, slug: str, title: str, parent_slug: str = "", content: str = "") -> dict:
    metadata = {"parent_slug": parent_slug} if parent_slug else {}
    return {
        "content_type": content_type,
        "title": title,
        "slug": slug,
        "status": "pendente_validacao",
        "content": content or title,
        "tags": [content_type],
        "metadata": metadata,
    }


def _parent(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("parent_slug") or "")


def _raw_plan() -> dict:
    entries = [
        _entry("briefing", "briefing-tockfatal-kits", "Briefing Tock Fatal Kits", "self"),
        _entry("campaign", "campaign-tockfatal-kits-modal", "Campanha Tock Fatal Kits Modal", "briefing-tockfatal-kits"),
        _entry("audience", "cliente-final", "Cliente final", "campaign-tockfatal-kits-modal"),
        _entry("audience", "empreendedoras", "Empreendedoras", "campaign-tockfatal-kits-modal"),
    ]
    entries.extend(
        _entry("product", f"kit-modal-{idx}", f"Kit Modal {idx}", "campaign-tockfatal-kits-modal")
        for idx in range(1, 7)
    )
    entries.extend([
        _entry("copy", "copy-kits-modal", "Copy Kits Modal", "kit-modal-1"),
        _entry("faq", "faq-preco", "Qual o preco?", "copy-kits-modal", "1 peca R$ 59,90; 5 pecas R$ 249,00; 10 pecas R$ 459,00."),
        {"content_type": "rules", "title": "Regra comercial", "slug": "rules-publico-quantidade", "status": "pendente_validacao", "content": "1 peca = cliente final. 5 e 10 pecas = empreendedoras. Nao inventar preco e nao prometer estoque.", "tags": ["rules"], "metadata": {}},
    ])
    return {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "validation_policy": "human_validation_required",
        "tree_mode": "single_branch",
        "branch_policy": "single_branch_by_default",
        "faq_count_policy": "total",
        "entries": entries,
        "links": [],
    }


def _session() -> dict:
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context=(
            "Persona: Tock Fatal\n"
            "Fonte: https://tockfatal.com\n"
            "Criar grafo com 2 publicos, 6 produtos, 12 FAQs, briefing, copy, offer e rule.\n"
            "1 peca R$ 59,90. 5 pecas R$ 249,00. 10 pecas R$ 459,00.\n"
            "1 peca = cliente final. 5 e 10 pecas = empreendedoras. Nao inventar preco e nao prometer estoque.\n"
        ),
        initial_state={
            "mode": "criar",
            "persona_slug": "tock-fatal",
            "source_url": "https://tockfatal.com",
            "initial_block_counts": {"briefing": 1, "campaign": 1, "audience": 2, "product": 6, "copy": 6, "faq": 12, "rule": 1},
        },
    )
    session["classification"]["persona_slug"] = "tock-fatal"
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Tock Fatal Kits Modal"
    svc._save_session(session)  # type: ignore[attr-defined]
    return session


def _assert_path_to_root(entries: list[dict], entry: dict) -> None:
    by_slug = {str(item.get("slug")): item for item in entries if item.get("slug")}
    seen: set[str] = set()
    cursor = entry
    for _ in range(20):
        parent = _parent(cursor)
        if parent == "self":
            return
        if not parent or parent in seen:
            break
        seen.add(parent)
        cursor = by_slug.get(parent) or {}
    raise AssertionError(f"{entry.get('content_type')}:{entry.get('slug')} has no path to persona")


def main() -> int:
    session = _session()
    plan_state = svc.normalize_validate_summarize_plan(_raw_plan(), session)
    normalized = plan_state["normalized_plan"]
    entries = normalized["entries"]
    counts = svc.count_blocks_by_type(entries)
    by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}

    _assert(plan_state["validation"]["valid"] is True, "normalizedPlan is valid")
    _assert(counts == plan_state["summary"]["current_block_counts"], "summary counts match normalizedPlan")
    _assert(counts["audience"] == 2, "two audiences remain")
    _assert(counts["product"] == 6, "six products remain without cross-duplicating")
    _assert(counts["offer"] > 0, "offers are inferred from price and quantity")
    _assert(counts["copy"] >= counts["offer"], "copy exists under offers")
    _assert(counts["faq"] == 12, "FAQ total policy keeps twelve FAQs")
    _assert(counts["rule"] >= 1, "commercial rule is created/normalized")
    _assert(knowledge_graph._CONTENT_TYPE_TO_NODE.get("offer") == "offer", "offer materializes as knowledge node type offer")

    for entry in entries:
        if entry.get("content_type") not in {"brand", "briefing"}:
            _assert_path_to_root(entries, entry)
    for offer in [entry for entry in entries if entry.get("content_type") == "offer"]:
        _assert(by_slug.get(_parent(offer), {}).get("content_type") == "product", "offer is below product")
    for copy in [entry for entry in entries if entry.get("content_type") == "copy"]:
        _assert(by_slug.get(_parent(copy), {}).get("content_type") == "offer", "copy is below offer")
    for faq in [entry for entry in entries if entry.get("content_type") == "faq"]:
        _assert(by_slug.get(_parent(faq), {}).get("content_type") == "copy", "FAQ is below copy")
    for rule in [entry for entry in entries if entry.get("content_type") == "rule"]:
        _assert(by_slug.get(_parent(rule), {}).get("content_type") in {"campaign", "briefing", "brand"}, "rule is under governing scope")

    extra_copy_plan = {**normalized, "entries": [*entries, _entry("copy", "copy-extra", "Copy extra sem parent")]}
    extra_copy_state = svc.normalize_validate_summarize_plan(extra_copy_plan, session)
    extra_copy = next(entry for entry in extra_copy_state["normalized_plan"]["entries"] if entry.get("title") == "Copy extra sem parent")
    _assert(extra_copy_state["validation"]["valid"] is True, "extra copy is normalized instead of staying loose")
    _assert(extra_copy.get("metadata", {}).get("parent_slug"), "extra copy receives a parent")

    extra_offer_plan = {**normalized, "entries": [*entries, _entry("offer", "offer-extra", "Oferta extra sem parent")]}
    extra_offer_state = svc.normalize_validate_summarize_plan(extra_offer_plan, session)
    extra_offer = next(entry for entry in extra_offer_state["normalized_plan"]["entries"] if entry.get("title") == "Oferta extra sem parent")
    extra_offer_by_slug = {str(entry.get("slug")): entry for entry in extra_offer_state["normalized_plan"]["entries"] if entry.get("slug")}
    _assert(extra_offer_by_slug.get(_parent(extra_offer), {}).get("content_type") == "product", "extra offer receives a product parent")

    update = svc.update_session_plan(session["id"], normalized, status="ready_to_save", last_change="topdown e2e")
    _assert(update["plan_hash"] == plan_state["plan_hash"], "PATCH preserves canonical plan hash")
    rejected = svc.save(session["id"], "", {"plan_hash": "stale", "normalized_plan": normalized})
    _assert(rejected.get("error") == "Plan mismatch: save payload is not the current normalized plan.", "save blocks non-current payload")

    page_source = (ROOT / "dashboard" / "app" / "knowledge" / "capture" / "page.tsx").read_text(encoding="utf-8")
    _assert("const previewPlan = plan;" in page_source, "preview uses normalizedPlan directly")
    _assert("expected}/{created}" in page_source, "sidebar renders expected/created counts")
    _assert("stage === \"ready_to_save\" && draftPlan && planStateValid" in page_source, "preview is gated by valid planState")

    print("PASS e2e_criar_fractal_topdown_tree_integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
