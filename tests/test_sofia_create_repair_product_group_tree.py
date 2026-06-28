#!/usr/bin/env python3
"""[PATH: CREATE] Repair: an old tree corrected into product groups stays grouped.

Create path: UI /knowledge/capture, /kb-intake/*, normalize_validate_summarize_plan.
See tests/SOFIA_PATHS.md.

Scenario (the user's): products were created, then the operator corrects the
request asking for 3 groups (Radar / Juliet / HSTN) with 3 products each. The
normalize/repair pass must:
  * keep every product under its product_group (audience -> product_group -> product),
  * NOT force products back up to briefing/audience,
  * NOT clone/expand products per audience,
  * leave 0 blocking violations.

Runs in canonical mode (SOFIA_TOOLS_ENABLED=true) where normalize is a cleanup
pass rather than the legacy per-audience product cloner.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc  # noqa: E402


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


@contextmanager
def canonical_mode():
    prev = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev


def _entry(content_type: str, slug: str, parent_slug: str | None) -> dict:
    meta = {"parent_slug": parent_slug} if parent_slug is not None else {}
    return {
        "content_type": content_type,
        "title": slug.replace("-", " ").title(),
        "slug": slug,
        "status": "pendente_validacao",
        "content": f"{content_type} {slug}",
        "metadata": meta,
    }


def _grouped_plan() -> dict:
    entries = [
        _entry("briefing", "briefing-vz", "self"),
        _entry("campaign", "campaign-esportivos", "briefing-vz"),
        _entry("audience", "publico-esportistas", "campaign-esportivos"),
    ]
    links = [
        ("briefing-vz", "campaign-esportivos"),
        ("campaign-esportivos", "publico-esportistas"),
    ]
    groups = {
        "grupo-radar": ["radar-areia-ruby", "radar-transparente", "radar-preto"],
        "grupo-juliet": ["juliet-roxa", "juliet-squared", "juliet-classic"],
        "grupo-hstn": ["hstn-matte-black", "hstn-brown", "hstn-clear"],
    }
    for group_slug, products in groups.items():
        entries.append(_entry("product_group", group_slug, "publico-esportistas"))
        links.append(("publico-esportistas", group_slug))
        for prod in products:
            entries.append(_entry("product", prod, group_slug))
            links.append((group_slug, prod))
    return {
        "source": "session",
        "persona_slug": "vz-lupas",
        "tree_mode": "pyramidal",
        "entries": entries,
        "links": [{"source_slug": s, "target_slug": t} for s, t in links],
    }


def _session() -> dict:
    return {
        "id": "sofia-repair-test",
        "messages": [{"role": "user", "content": "crie 3 grupos de produtos com 3 produtos cada: Radar, Juliet, HSTN"}],
        "classification": {"persona_slug": "vz-lupas"},
    }


def _normalized(plan: dict) -> dict:
    with canonical_mode():
        return svc.normalize_validate_summarize_plan(plan, _session())


def test_repair_keeps_products_grouped_and_valid() -> None:
    state = _normalized(_grouped_plan())
    expect(state["validation"]["valid"] is True, f"plan valid (got {state['validation']})")

    plan = state["normalized_plan"]
    by_slug = {e["slug"]: e for e in plan["entries"]}
    products = [e for e in plan["entries"] if e["content_type"] == "product"]
    expect(len(products) == 9, f"9 products preserved, no per-audience cloning (got {len(products)})")

    parent_types = set()
    for prod in products:
        parent_slug = (prod.get("metadata") or {}).get("parent_slug")
        parent_types.add((by_slug.get(parent_slug) or {}).get("content_type"))
    expect(parent_types == {"product_group"}, f"every product hangs off a product_group (got {parent_types})")
    expect("briefing" not in parent_types, "repair did not force products up to briefing")
    expect("audience" not in parent_types, "repair did not force products up to audience")

    groups = [e for e in plan["entries"] if e["content_type"] == "product_group"]
    expect(len(groups) == 3, f"3 product groups preserved (got {len(groups)})")


def test_product_without_group_is_valid_under_audience() -> None:
    """Product Group is optional; direct Audience -> Product is valid."""
    plan = {
        "source": "session",
        "persona_slug": "vz-lupas",
        "tree_mode": "pyramidal",
        "entries": [
            _entry("briefing", "briefing-vz", "self"),
            _entry("campaign", "campaign-esportivos", "briefing-vz"),
            _entry("audience", "publico-esportistas", "campaign-esportivos"),
            _entry("product", "radar-areia-ruby", "publico-esportistas"),
        ],
        "links": [{"source_slug": s, "target_slug": t} for s, t in [
            ("briefing-vz", "campaign-esportivos"),
            ("campaign-esportivos", "publico-esportistas"),
            ("publico-esportistas", "radar-areia-ruby"),
        ]],
    }
    with canonical_mode():
        state = svc.normalize_validate_summarize_plan(plan, {
            "id": "sofia-no-group", "messages": [{"role": "user", "content": "um produto"}],
            "classification": {"persona_slug": "vz-lupas"},
        })
    violations = state["validation"]["blocking_violations"]
    expect(not any("product nao pode ficar abaixo de audience" in item or "product precisa" in item for item in violations),
           f"product directly under audience is accepted (got {violations})")


def main() -> int:
    test_repair_keeps_products_grouped_and_valid()
    test_product_without_group_is_valid_under_audience()
    print("PASS test_sofia_repair_product_group_tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
