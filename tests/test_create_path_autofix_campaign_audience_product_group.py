from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc  # noqa: E402


def _entry(content_type: str, slug: str, parent_slug: str | None = None) -> dict:
    metadata = {"parent_slug": parent_slug} if parent_slug else {}
    return {
        "content_type": content_type,
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "content": slug.replace("-", " "),
        "metadata": metadata,
    }


def test_create_preview_autofixes_campaign_audience_product_group_chain() -> None:
    previous = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        state = svc.normalize_validate_summarize_plan(
            {
                "persona_slug": "vz-lupas",
                "entries": [
                    _entry("brand", "vz-lupas", "self"),
                    _entry("briefing", "briefing-vz", "vz-lupas"),
                    _entry("campaign", "campanha-vz"),
                    _entry("audience", "publico-jovem"),
                    _entry("product_group", "juliet"),
                    _entry("product_group", "plantaris"),
                    _entry("product_group", "radar"),
                    _entry("product", "juliet-produto-1"),
                    _entry("product", "plantaris-produto-1"),
                    _entry("product", "radar-produto-1"),
                ],
            },
            {
                "context": "Missao: vz-lupas | Blocos: briefing, audience, product",
                "persona_slug": "vz-lupas",
                "classification": {"persona_slug": "vz-lupas"},
                "initial_block_counts": {"briefing": 1, "audience": 1, "product_group": 3, "product": 3},
                "messages": [{"role": "user", "content": "campanha de retorno vz inverno com audience e grupos juliet plantaris radar"}],
            },
        )
    finally:
        if previous is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = previous

    entries = state["normalized_plan"]["entries"]
    by_slug = {entry["slug"]: entry for entry in entries}

    assert svc._entry_parent_slug(by_slug["campanha-vz"]) == "briefing-vz"
    assert svc._entry_parent_slug(by_slug["publico-jovem"]) == "campanha-vz"
    assert svc._entry_parent_slug(by_slug["juliet"]) == "publico-jovem"
    assert svc._entry_parent_slug(by_slug["plantaris"]) == "publico-jovem"
    assert svc._entry_parent_slug(by_slug["radar"]) == "publico-jovem"
    assert svc._entry_parent_slug(by_slug["juliet-produto-1"]) == "juliet"
    assert svc._entry_parent_slug(by_slug["plantaris-produto-1"]) == "plantaris"
    assert svc._entry_parent_slug(by_slug["radar-produto-1"]) == "radar"
    assert state["validation"]["blocking_violations"] == []


def test_create_preview_repairs_product_group_campaign_shortcut() -> None:
    previous = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        state = svc.normalize_validate_summarize_plan(
            {
                "persona_slug": "tock-fatal",
                "entries": [
                    _entry("briefing", "campanha-de-inverno", "self"),
                    _entry("audience", "atacarejo", "campanha-de-inverno"),
                    _entry("product_group", "grupo-de-produtos-de-inverno", "campanha-de-inverno"),
                    _entry("product", "kit-modal-1", "campanha-de-inverno"),
                    _entry("product", "kit-modal-2", "campanha-de-inverno"),
                ],
                "links": [
                    {"source_slug": "campanha-de-inverno", "target_slug": "grupo-de-produtos-de-inverno"},
                    {"source_slug": "campanha-de-inverno", "target_slug": "kit-modal-1"},
                    {"source_slug": "campanha-de-inverno", "target_slug": "kit-modal-2"},
                ],
            },
            {
                "context": "Missao: tock-fatal | Fonte: https://tockfatal.com",
                "persona_slug": "tock-fatal",
                "classification": {"persona_slug": "tock-fatal"},
                "initial_block_counts": {"briefing": 1, "audience": 1, "product_group": 1, "product": 2},
                "messages": [{"role": "user", "content": "campanha de inverno publico atacarejo gere"}],
            },
        )
    finally:
        if previous is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = previous

    entries = state["normalized_plan"]["entries"]
    by_slug = {entry["slug"]: entry for entry in entries}
    links = {
        (link.get("source_slug"), link.get("target_slug"))
        for link in state["normalized_plan"].get("links", [])
    }

    assert svc._entry_parent_slug(by_slug["atacarejo"]) == "campanha-de-inverno"
    assert svc._entry_parent_slug(by_slug["grupo-de-produtos-de-inverno"]) == "atacarejo"
    assert svc._entry_parent_slug(by_slug["kit-modal-1"]) == "grupo-de-produtos-de-inverno"
    assert svc._entry_parent_slug(by_slug["kit-modal-2"]) == "grupo-de-produtos-de-inverno"
    assert ("campanha-de-inverno", "grupo-de-produtos-de-inverno") not in links
    assert ("campanha-de-inverno", "kit-modal-1") not in links
    assert ("atacarejo", "grupo-de-produtos-de-inverno") in links
    assert ("grupo-de-produtos-de-inverno", "kit-modal-1") in links
    assert state["validation"]["blocking_violations"] == []


def test_create_preview_repairs_product_group_product_cycle() -> None:
    previous = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        state = svc.normalize_validate_summarize_plan(
            {
                "persona_slug": "tock-fatal",
                "entries": [
                    _entry("briefing", "campanha-de-inverno", "self"),
                    _entry("campaign", "campanha-modal", "campanha-de-inverno"),
                    _entry("audience", "atacarejo", "grupo-de-produtos-de-inverno"),
                    _entry("product_group", "grupo-de-produtos-de-inverno", "kit-modal-1"),
                    _entry("product", "kit-modal-1", "grupo-de-produtos-de-inverno"),
                    _entry("product", "kit-modal-2", "grupo-de-produtos-de-inverno"),
                ],
            },
            {
                "context": "Missao: tock-fatal | Fonte: https://tockfatal.com",
                "persona_slug": "tock-fatal",
                "classification": {"persona_slug": "tock-fatal"},
                "initial_block_counts": {"briefing": 1, "campaign": 1, "audience": 1, "product_group": 1, "product": 2},
                "messages": [{"role": "user", "content": "campanha de inverno publico atacarejo produtos modais gere"}],
            },
        )
    finally:
        if previous is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = previous

    entries = state["normalized_plan"]["entries"]
    by_slug = {entry["slug"]: entry for entry in entries}

    assert svc._entry_parent_slug(by_slug["atacarejo"]) == "campanha-modal"
    assert svc._entry_parent_slug(by_slug["grupo-de-produtos-de-inverno"]) == "atacarejo"
    assert svc._entry_parent_slug(by_slug["kit-modal-1"]) == "grupo-de-produtos-de-inverno"
    assert svc._entry_parent_slug(by_slug["kit-modal-2"]) == "grupo-de-produtos-de-inverno"
    assert not any("cycle detected" in item for item in state["validation"]["blocking_violations"])
    assert state["validation"]["blocking_violations"] == []
