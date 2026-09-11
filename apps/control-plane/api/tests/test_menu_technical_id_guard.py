"""`[grupo:conjuntos]` reached a real customer's WhatsApp message on 2026-09-05.

Authored CTA copy is Portuguese, but `_TECHNICAL_ID_PATTERN` only banned the
English node-type word (`group`, not `grupo`) -- a bracketed technical ref in
Portuguese slipped straight past the "never leak internal IDs" guard
(`docs/tock-fatal-public-site.md:93`) and out to the customer's WhatsApp.
"""
from __future__ import annotations

from routes import menu


def test_portuguese_technical_ids_are_rejected_same_as_english() -> None:
    errors: list[str] = []
    menu._required_natural_message(
        {"message_template": "Quero ver as opções de conjuntos. [grupo:conjuntos]"},
        "message_template", "site.audiences[0]", errors,
    )

    assert errors == ["site.audiences[0].message_template:technical_id_forbidden"]


def test_site_cta_drops_a_portuguese_technical_id_the_same_way_as_english() -> None:
    cta = menu._site_cta({
        "id": "product_group:conjuntos",
        "data": {"cta": {
            "label": "Quero conhecer este estilo",
            "message_template": "Quero ver as opções de conjuntos. [grupo:conjuntos]",
        }},
    })

    assert cta is None
