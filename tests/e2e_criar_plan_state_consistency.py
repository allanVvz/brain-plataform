#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def _entry(content_type: str, slug: str, title: str, parent_slug: str, content: str = "") -> dict:
    return {
        "content_type": content_type,
        "title": title,
        "slug": slug,
        "status": "pendente_validacao",
        "content": content or title,
        "tags": [content_type],
        "metadata": {"parent_slug": parent_slug},
    }


def _raw_tockfatal_plan() -> dict:
    return {
        "source": "https://tockfatal.com",
        "persona_slug": "tock-fatal",
        "validation_policy": "human_validation_required",
        "tree_mode": "single_branch",
        "branch_policy": "single_branch_by_default",
        "faq_count_policy": "total",
        "entries": [
            _entry("briefing", "briefing-tockfatal-kits", "Briefing Tock Fatal Kits", "self"),
            _entry("campaign", "campaign-tockfatal-kits-modal", "Campanha Tock Fatal Kits Modal", "briefing-tockfatal-kits"),
            _entry("audience", "clientes-finais", "Clientes finais", "campaign-tockfatal-kits-modal", "Mulheres comprando uma peca para uso proprio."),
            _entry("audience", "empreendedoras", "Empreendedoras", "campaign-tockfatal-kits-modal", "Revendedoras e empreendedoras comprando kits."),
            _entry("product", "kit-modal-1", "Kit Modal 1", "campaign-tockfatal-kits-modal"),
            _entry("product", "kit-modal-2", "Kit Modal 2", "campaign-tockfatal-kits-modal"),
            _entry("copy", "copy-kits-modal", "Copy Kits Modal", "kit-modal-1", "Mensagem comercial para kits modal."),
            _entry("faq", "faq-preco", "Qual o preco?", "copy-kits-modal", "1 peca R$ 59,90; 5 pecas R$ 249,00; 10 pecas R$ 459,00."),
            _entry("faq", "faq-estoque", "Tem estoque?", "copy-kits-modal", "Confirmar estoque antes de prometer disponibilidade."),
            {"content_type": "rules", "title": "Regra comercial", "slug": "rules-publico-quantidade", "status": "pendente_validacao", "content": "1 peca = cliente final. 5 e 10 pecas = empreendedoras. Nao inventar preco e nao prometer estoque sem confirmacao.", "tags": ["rules"], "metadata": {}},
        ],
        "links": [],
    }


def _parent(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("parent_slug") or "")


def main() -> int:
    initial_counts = {"briefing": 1, "campaign": 1, "audience": 2, "product": 6, "entity": 1, "copy": 6, "faq": 6, "rule": 2}
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context=(
            "Persona: Tock Fatal\n"
            "Fonte: https://tockfatal.com\n"
            "Kit Modal 1 e Kit Modal 2 tem: 1 peca R$ 59,90, 5 pecas R$ 249,00, 10 pecas R$ 459,00.\n"
            "1 peca e para cliente final. 5 e 10 pecas sao para empreendedoras.\n"
            "Nao inventar preco e nao prometer estoque sem confirmacao.\n"
        ),
        initial_state={
            "mode": "criar",
            "persona_slug": "tock-fatal",
            "source_url": "https://tockfatal.com",
            "initial_block_counts": initial_counts,
        },
    )
    session["classification"]["persona_slug"] = "tock-fatal"
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Tock Fatal Kits Modal"
    svc._save_session(session)  # type: ignore[attr-defined]

    plan_state = svc.normalize_validate_summarize_plan(_raw_tockfatal_plan(), session)
    normalized = plan_state["normalized_plan"]
    entries = normalized["entries"]
    counts = svc.count_blocks_by_type(entries)
    summary_counts = plan_state["summary"]["current_block_counts"]

    _assert(plan_state["validation"]["valid"] is True, "normalized plan is valid")
    _assert(plan_state["plan_hash"], "normalized plan has canonical hash")
    _assert(counts == summary_counts, "summary counts match normalized entries")
    _assert(len(entries) == plan_state["summary"]["entry_count"], "entry_count matches normalized entries")
    _assert(normalized.get("faq_count_policy") == "total", "faq_count_policy defaults to total")
    _assert(counts["offer"] >= 6, "price and quantity infer commercial offers")
    _assert(counts["rule"] >= 1, "commercial rules normalize to rule entries")
    _assert(counts["faq"] == 6, "total FAQ policy keeps requested total")
    _assert(not any(entry.get("content_type") == "rules" for entry in entries), "rules alias normalized to rule")
    _assert(not any("-audience-" in str(entry.get("slug") or "") for entry in entries if entry.get("content_type") == "product"), "product slugs do not embed audience")

    by_slug = {str(entry["slug"]): entry for entry in entries}
    for rule in [entry for entry in entries if entry["content_type"] == "rule"]:
        parent_type = by_slug.get(_parent(rule), {}).get("content_type") if _parent(rule) != "self" else "persona"
        _assert(parent_type in {"campaign", "briefing", "brand", "persona"}, "rule is connected to governing scope")
    for offer in [entry for entry in entries if entry["content_type"] == "offer"]:
        _assert(by_slug.get(_parent(offer), {}).get("content_type") == "product", "offer stays below product")
    offer_exists = counts["offer"] > 0
    for copy in [entry for entry in entries if entry["content_type"] == "copy"]:
        parent_type = by_slug.get(_parent(copy), {}).get("content_type")
        if offer_exists:
            _assert(parent_type == "offer", "copy stays below offer when offers exist")
    for faq in [entry for entry in entries if entry["content_type"] == "faq"]:
        _assert(by_slug.get(_parent(faq), {}).get("content_type") == "copy", "FAQ stays below copy")

    update = svc.update_session_plan(session["id"], normalized, status="ready_to_save", last_change="e2e normalized plan")
    _assert(update["plan_hash"] == plan_state["plan_hash"], "PATCH stores the same canonical plan hash")
    _assert(update["plan_state"]["summary"] == plan_state["summary"], "PATCH returns the same normalized summary")

    rejected = svc.save(session["id"], "", {"plan_hash": "stale", "normalized_plan": normalized})
    _assert(rejected.get("error") == "Plan mismatch: save payload is not the current normalized plan.", "save blocks stale plan hash before persistence")

    page_source = (ROOT / "dashboard" / "app" / "knowledge" / "capture" / "page.tsx").read_text(encoding="utf-8")
    _assert("stage === \"ready_to_save\" && draftPlan && planStateValid" in page_source, "preview is gated by valid planState")
    _assert("normalizePreviewPlan(rebuildPlanLinks(draftPlan))" not in page_source, "frontend does not rebuild save payload from preview")
    _assert("plan_hash: planState.plan_hash" in page_source, "save sends current plan hash")
    _assert("Encountered two children with the same key" not in page_source, "no hardcoded duplicate-key failure message")

    print("PASS e2e_criar_plan_state_consistency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
