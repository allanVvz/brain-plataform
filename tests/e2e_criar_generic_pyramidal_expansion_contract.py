#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc

svc._emit_kb_event = lambda *args, **kwargs: None  # type: ignore[attr-defined]


def expect(condition: bool, message: str, detail: object | None = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")
    print(f"ok {message}")


def entry(content_type: str, slug: str, title: str, parent_slug: str, content: str | None = None) -> dict:
    return {
        "content_type": content_type,
        "title": title,
        "slug": slug,
        "status": "pendente_validacao",
        "content": content or f"{title} pendente de validacao.",
        "tags": [content_type, "generic"],
        "metadata": {"parent_slug": parent_slug},
    }


def parent(entry_: dict) -> str:
    return str((entry_.get("metadata") or {}).get("parent_slug") or "")


def make_session(block_counts: dict[str, int], text: str = "") -> dict:
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context=text or "Criar arvore piramidal generica com variacoes comerciais e FAQs por parent.",
        initial_state={
            "mode": "criar",
            "persona_slug": "persona-generica",
            "source_url": "https://example.test/catalog",
            "initial_block_counts": block_counts,
        },
    )
    session["classification"]["persona_slug"] = "persona-generica"
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Contrato generico de criacao"
    return session


def base_plan(*, faq_policy: str | None = None) -> dict:
    plan = {
        "source": "https://example.test/catalog",
        "persona_slug": "persona-generica",
        "validation_policy": "human_validation_required",
        "tree_mode": "pyramidal",
        "branch_policy": "top_down_pyramidal",
        "entries": [
            entry("briefing", "briefing-generico", "Briefing generico", "self"),
            entry("audience", "segmento-a", "Segmento A", "briefing-generico"),
            entry("audience", "segmento-b", "Segmento B", "briefing-generico"),
            entry("product", "produto-a", "Produto A", "segmento-a"),
            entry("product", "produto-b", "Produto B", "segmento-a"),
            entry("product", "produto-c", "Produto C", "segmento-a"),
            entry("copy", "copy-produto-a", "Copy Produto A", "produto-a"),
        ],
        "links": [],
    }
    if faq_policy:
        plan["faq_count_policy"] = faq_policy
    return plan


def question_count(entry_: dict) -> int:
    return int((entry_.get("metadata") or {}).get("question_count") or 0)


def markdown_questions(entry_: dict) -> int:
    import re
    return len(re.findall(r"(?m)^###\s+\d+\.", entry_.get("content") or ""))


def test_faq_golden_dataset_per_terminal_branch() -> None:
    session = make_session({"briefing": 1, "audience": 2, "product": 3, "offer": 2, "copy": 1, "faq": 2})
    state = svc.normalize_validate_summarize_plan(base_plan(), session)
    normalized = state["normalized_plan"]
    counts = state["summary"]["current_block_counts"]
    expect(state["validation"]["valid"] is True, "expanded plan validates", state["validation"])
    expect(normalized["faq_count_policy"] == "per_branch", "FAQ defaults to Golden Dataset per branch")
    expect(normalized["faq_parent_type"] == "copy", "FAQ parent type is copy")
    expect(counts["audience"] == 2, "two audiences created", counts)
    expect(counts["product"] == 6, "three products per audience expand to six products", counts)
    expect(counts["offer"] == 12, "two offers per product expand to twelve offers", counts)
    expect(counts["copy"] == 12, "one copy per offer expands to twelve copies", counts)
    expect(counts["faq"] == 12, "one FAQ Golden Dataset per terminal copy", counts)
    expect(state["summary"]["expansion"]["faq"]["expected"] == 12, "FAQ expected count is one document per terminal branch")
    expect(sum(question_count(faq) for faq in normalized["entries"] if faq.get("content_type") == "faq") == 144, "questions stay inside FAQ markdown documents")


def test_offer_branches_create_one_faq_document_each() -> None:
    session = make_session({"briefing": 1, "audience": 1, "product": 1, "offer": 4, "copy": 1, "faq": 3})
    plan = base_plan()
    plan["entries"] = plan["entries"][:2] + [entry("product", "produto-unico", "Produto Unico", "segmento-a")]
    state = svc.normalize_validate_summarize_plan(plan, session)
    normalized = state["normalized_plan"]
    counts = state["summary"]["current_block_counts"]
    expect(counts["offer"] == 4, "four offers created", counts)
    expect(counts["copy"] == 4, "one copy per offer", counts)
    expect(counts["faq"] == 4, "one FAQ Golden Dataset per copy", counts)
    expect(all(markdown_questions(faq) == question_count(faq) for faq in normalized["entries"] if faq.get("content_type") == "faq"), "markdown question headings match metadata")


def test_tags_are_secondary_and_tree_is_pyramidal() -> None:
    session = make_session({"briefing": 1, "audience": 1, "product": 1, "offer": 1, "copy": 1, "faq": 1})
    state = svc.normalize_validate_summarize_plan(base_plan(), session)
    normalized = state["normalized_plan"]
    secondary = normalized.get("secondary_semantic_edges") or []
    expect(secondary, "tags materialize as secondary semantic edges")
    expect(all(edge.get("primary_tree") is False for edge in secondary), "tag edges are not primary")
    expect(all(edge.get("graph_layer") == "semantic_tags" for edge in secondary), "tag edges use semantic_tags layer")
    by_slug = {str(item.get("slug")): item for item in normalized["entries"]}
    for faq in [item for item in normalized["entries"] if item.get("content_type") == "faq"]:
        chain = []
        current = faq
        while current:
            chain.append(current.get("content_type"))
            parent_slug = parent(current)
            if parent_slug == "self":
                chain.append("persona")
                break
            current = by_slug.get(parent_slug)
        expect(chain[-1] == "persona" and "copy" in chain and "product" in chain and "audience" in chain, "FAQ has full path to persona", chain)


def main() -> int:
    test_faq_golden_dataset_per_terminal_branch()
    test_offer_branches_create_one_faq_document_each()
    test_tags_are_secondary_and_tree_is_pyramidal()
    print("PASS e2e_criar_generic_pyramidal_expansion_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
