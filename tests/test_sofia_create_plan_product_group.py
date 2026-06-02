#!/usr/bin/env python3
"""[PATH: CREATE] Sofia Create plan validator must accept the product_group layer.

Create path: UI /knowledge/capture, endpoint /kb-intake/*, validator
`validate_sofia_knowledge_plan` (shared rules in services/graph_validation.py).
See tests/SOFIA_PATHS.md.

Bug: with SOFIA_TOOLS_ENABLED off, the legacy branch of
`validate_sofia_knowledge_plan` rejected `product_group -> product` and forced
every product directly under `audience`, producing the UI error
"Produto deve ficar abaixo de audience, campaign, briefing ou brand" for the
9 products the user explicitly grouped (Radar / Juliet / HSTN).

These tests assert the canonical chain
    persona -> brand -> briefing -> campaign -> audience -> product_group -> product
validates in BOTH legacy and canonical (tools) modes, and that the grouping
layer is enforced the right way round (product_group hangs off audience, not
off product).
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
def sofia_tools(enabled: bool):
    prev = os.environ.get("SOFIA_TOOLS_ENABLED")
    os.environ["SOFIA_TOOLS_ENABLED"] = "true" if enabled else "false"
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


def _links(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"source_slug": s, "target_slug": t} for s, t in pairs]


def _neutral_session() -> dict:
    # No price/kit/rule signals -> offers/rules are not required by the validator.
    return {
        "id": "sofia-product-group-test",
        "messages": [{"role": "user", "content": "criar grupos de produto"}],
        "classification": {"persona_slug": "vz-lupas"},
    }


def _grouped_plan() -> dict:
    """3 product groups (Radar/Juliet/HSTN) with 3 products each = the bug case."""
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
        "links": _links(links),
    }


_PRODUCT_PARENT_VIOLATIONS = (
    "product has invalid parent",
    "product must stay under audience",
    "has no complete path to persona",
)


def _assert_no_product_parent_violations(violations: list[str], label: str) -> None:
    offending = [
        v for v in violations
        if any(marker in v for marker in _PRODUCT_PARENT_VIOLATIONS)
    ]
    expect(not offending, f"{label}: no product-parent violations (got {offending})")


def test_grouped_products_valid_legacy() -> None:
    with sofia_tools(False):
        violations = svc.validate_sofia_knowledge_plan(_grouped_plan(), _neutral_session())
    _assert_no_product_parent_violations(violations, "legacy mode")


def test_grouped_products_valid_canonical() -> None:
    with sofia_tools(True):
        violations = svc.validate_sofia_knowledge_plan(_grouped_plan(), _neutral_session())
    _assert_no_product_parent_violations(violations, "canonical mode")


def test_product_directly_under_audience_is_valid() -> None:
    """Product Group is optional; product may sit directly under audience."""
    entries = [
        _entry("briefing", "briefing-vz", "self"),
        _entry("campaign", "campaign-esportivos", "briefing-vz"),
        _entry("audience", "publico-esportistas", "campaign-esportivos"),
        _entry("product", "radar-areia-ruby", "publico-esportistas"),
    ]
    plan = {
        "source": "session",
        "persona_slug": "vz-lupas",
        "tree_mode": "pyramidal",
        "entries": entries,
        "links": _links([
            ("briefing-vz", "campaign-esportivos"),
            ("campaign-esportivos", "publico-esportistas"),
            ("publico-esportistas", "radar-areia-ruby"),
        ]),
    }
    with sofia_tools(False):
        violations = svc.validate_sofia_knowledge_plan(plan, _neutral_session())
    offending = [v for v in violations if "product" in v and "parent" in v]
    expect(not offending, f"product directly under audience is accepted (got {violations})")


def test_product_group_under_product_is_invalid_canonical() -> None:
    """Grouping layer must hang off audience, never off a product (Test 5)."""
    entries = [
        _entry("briefing", "briefing-vz", "self"),
        _entry("campaign", "campaign-esportivos", "briefing-vz"),
        _entry("audience", "publico-esportistas", "campaign-esportivos"),
        _entry("product", "radar-areia-ruby", "publico-esportistas"),
        _entry("product_group", "grupo-invertido", "radar-areia-ruby"),
    ]
    plan = {
        "source": "session",
        "persona_slug": "vz-lupas",
        "tree_mode": "pyramidal",
        "entries": entries,
        "links": _links([
            ("briefing-vz", "campaign-esportivos"),
            ("campaign-esportivos", "publico-esportistas"),
            ("publico-esportistas", "radar-areia-ruby"),
            ("radar-areia-ruby", "grupo-invertido"),
        ]),
    }
    with sofia_tools(True):
        violations = svc.validate_sofia_knowledge_plan(plan, _neutral_session())
    bad = [v for v in violations if "product_group" in v and "parent" in v]
    expect(bool(bad), f"canonical mode rejects product_group under product (got {violations})")


def main() -> int:
    test_grouped_products_valid_legacy()
    test_grouped_products_valid_canonical()
    test_product_directly_under_audience_is_valid()
    test_product_group_under_product_is_invalid_canonical()
    print("PASS test_sofia_plan_product_group")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
