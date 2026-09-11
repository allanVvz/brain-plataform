"""catalog_url used to be a free-text field nobody validated against the real
Card-pio deployment. baita-conveniencia and vz-lupas both drifted to broken/QA
domains in production (2026-09-11) because nothing kept them in sync with the
one shared Card-pio project that actually serves any persona's cardapio via a
generic `/cardapio/:site_slug` route. When no explicit catalog_url is set,
public_site_payload must derive it from that shared domain instead of
returning None.
"""
from __future__ import annotations

from services import public_site


def _persona(**overrides):
    persona = {"id": "persona-1", "config": {"public_site": {"site_slug": "baita"}}}
    persona.update(overrides)
    return persona


def test_catalog_url_defaults_to_the_shared_card_pio_domain_when_unset():
    payload = public_site.public_site_payload(_persona(), public_site.DEFAULT_FORMATS)

    assert payload["catalog_url"] == "https://lp-catalogo-cardapio.vercel.app/cardapio/baita"


def test_explicit_persona_catalog_url_overrides_the_default():
    payload = public_site.public_site_payload(
        _persona(catalog_url="https://tockfatal.com/pages/catalogo-modal"),
        public_site.DEFAULT_FORMATS,
    )

    assert payload["catalog_url"] == "https://tockfatal.com/pages/catalogo-modal"


def test_explicit_call_argument_overrides_both_default_and_persona_field():
    payload = public_site.public_site_payload(
        _persona(catalog_url="https://stale.example.com/old"),
        public_site.DEFAULT_FORMATS,
        catalog_url="https://fresh.example.com/new",
    )

    assert payload["catalog_url"] == "https://fresh.example.com/new"
