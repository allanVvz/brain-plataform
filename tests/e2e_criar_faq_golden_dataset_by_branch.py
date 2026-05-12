#!/usr/bin/env python3
from __future__ import annotations

import re
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
        "tags": [content_type, "golden-dataset-contract"],
        "metadata": {"parent_slug": parent_slug},
    }


def make_session(block_counts: dict[str, int]) -> dict:
    session = svc.create_session(
        model="gpt-4o-mini",
        initial_context="Criar FAQ Golden Dataset por galho terminal, sem explodir perguntas em cards.",
        initial_state={
            "mode": "criar",
            "persona_slug": "persona-generica",
            "source_url": "https://example.test/catalog",
            "initial_block_counts": block_counts,
        },
    )
    session["classification"]["persona_slug"] = "persona-generica"
    session["classification"]["content_type"] = "faq"
    session["classification"]["title"] = "Contrato FAQ Golden Dataset"
    return session


def normalize(entries: list[dict], block_counts: dict[str, int]) -> dict:
    session = make_session(block_counts)
    state = svc.normalize_validate_summarize_plan({
        "source": "https://example.test/catalog",
        "persona_slug": "persona-generica",
        "validation_policy": "human_validation_required",
        "tree_mode": "pyramidal",
        "branch_policy": "top_down_pyramidal",
        "entries": entries,
        "links": [],
    }, session)
    expect(state["validation"]["valid"] is True, "plan validates", state["validation"])
    return state["normalized_plan"]


def faq_entries(plan: dict) -> list[dict]:
    return [entry for entry in plan["entries"] if entry["content_type"] == "faq"]


def question_headings(markdown: str) -> int:
    return len(re.findall(r"(?m)^###\s+\d+\.", markdown or ""))


def question_titles(markdown: str) -> list[str]:
    return re.findall(r"(?m)^###\s+\d+\.\s+(.+)$", markdown or "")


def assert_real_faq_body(markdown: str) -> None:
    expect("Use o contexto deste galho para responder" not in markdown, "FAQ answers are final text, not generation instructions")
    expect("(9)" not in markdown and "(10)" not in markdown, "FAQ questions do not repeat with numeric suffixes")
    titles = question_titles(markdown)
    expect(len(titles) == len(set(titles)), "FAQ questions are unique")


def test_simple_tree() -> None:
    plan = normalize([
        entry("briefing", "briefing", "Briefing", "self"),
        entry("audience", "audience-a", "Publico A", "briefing"),
        entry("product", "product-a", "Produto A", "audience-a"),
        entry("copy", "copy-a", "Copy A", "product-a"),
    ], {"briefing": 1, "audience": 1, "product": 1, "copy": 1, "faq": 1})
    faqs = faq_entries(plan)
    expect(len(faqs) == 1, "simple tree creates one FAQ document", len(faqs))
    expect(faqs[0]["metadata"]["question_count"] == 10, "simple tree has ten questions", faqs[0]["metadata"])
    expect(question_headings(faqs[0]["content"]) == 10, "simple tree markdown has ten question headings")
    assert_real_faq_body(faqs[0]["content"])


def test_offer_tree() -> None:
    plan = normalize([
        entry("briefing", "briefing", "Briefing", "self"),
        entry("audience", "audience-a", "Publico A", "briefing"),
        entry("product", "product-a", "Produto A", "audience-a"),
        entry("offer", "offer-a", "Oferta A", "product-a"),
        entry("copy", "copy-a", "Copy A", "offer-a"),
    ], {"briefing": 1, "audience": 1, "product": 1, "offer": 0, "copy": 1, "faq": 1})
    faqs = faq_entries(plan)
    expect(len(faqs) == 1, "offer tree creates one FAQ document", len(faqs))
    expect(faqs[0]["metadata"]["question_count"] == 12, "offer tree has twelve questions", faqs[0]["metadata"])
    expect(question_headings(faqs[0]["content"]) == 12, "offer tree markdown has twelve question headings")


def test_multiple_branches_do_not_explode() -> None:
    entries = [entry("briefing", "briefing", "Briefing", "self")]
    for audience_idx in range(1, 3):
        audience_slug = f"audience-{audience_idx}"
        entries.append(entry("audience", audience_slug, f"Publico {audience_idx}", "briefing"))
        for product_idx in range(1, 3):
            suffix = f"{audience_idx}-{product_idx}"
            product_slug = f"product-{suffix}"
            offer_slug = f"offer-{suffix}"
            copy_slug = f"copy-{suffix}"
            entries.extend([
                entry("product", product_slug, f"Produto {suffix}", audience_slug),
                entry("offer", offer_slug, f"Oferta {suffix}", product_slug),
                entry("copy", copy_slug, f"Copy {suffix}", offer_slug),
            ])
    plan = normalize(entries, {"briefing": 1, "audience": 2, "product": 2, "offer": 0, "copy": 1, "faq": 1})
    faqs = faq_entries(plan)
    total_questions = sum(int((faq.get("metadata") or {}).get("question_count") or 0) for faq in faqs)
    expect(len(faqs) == 4, "four terminal copies create four FAQ documents", len(faqs))
    expect(total_questions == 48, "questions stay inside FAQ documents", total_questions)
    expect(all(question_headings(faq["content"]) == 12 for faq in faqs), "each branch document has twelve questions")
    expect(len(faqs) != total_questions, "questions did not become FAQ cards", {"faqs": len(faqs), "questions": total_questions})


def main() -> int:
    test_simple_tree()
    test_offer_tree()
    test_multiple_branches_do_not_explode()
    print("PASS e2e_criar_faq_golden_dataset_by_branch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
