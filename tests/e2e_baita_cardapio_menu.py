"""E2E opt-in do cardapio contra um backend remoto informado explicitamente.

O modulo nao e coletado pela suite padrao. Para habilita-lo, informe
`RUN_MENU_LIVE_E2E=1` e `AI_BRAIN_BASE_URL`; indisponibilidade e contrato
invalido falham o teste em vez de produzir skip. Nunca inicia Docker local.

Variaveis de ambiente:
    AI_BRAIN_BASE_URL   base remota do backend
    CARDAPIO_PERSONA    persona/slug do cardapio (default baita-conveniencia)
"""
from __future__ import annotations

import os

import requests

BASE_URL = (
    os.environ.get("AI_BRAIN_BASE_URL")
    or os.environ.get("API_BASE")
).rstrip("/")
PERSONA = os.environ.get("CARDAPIO_PERSONA", "baita-conveniencia")
TIMEOUT = float(os.environ.get("AI_BRAIN_HTTP_TIMEOUT", "15"))


def _require_backend() -> None:
    """Fail with endpoint context when the enabled backend is unavailable."""
    assert BASE_URL, "AI_BRAIN_BASE_URL is required for the explicitly enabled live test"
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise AssertionError(f"backend offline em {BASE_URL}: {exc}") from exc
    if resp.status_code != 200:
        raise AssertionError(
            f"GET {BASE_URL}/health respondeu HTTP {resp.status_code}: {resp.text[:500]}"
        )


def _get_menu() -> dict:
    resp = requests.get(f"{BASE_URL}/api/menu/{PERSONA}", timeout=TIMEOUT)
    # Um 500 aqui e justamente o bug que queremos pegar — falhe com o corpo.
    assert resp.status_code == 200, (
        f"GET /api/menu/{PERSONA} retornou {resp.status_code}: {resp.text[:1000]}"
    )
    return resp.json()


def test_health_ok():
    _require_backend()
    resp = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
    assert resp.status_code == 200, resp.text[:500]


def test_menu_contract_for_persona():
    _require_backend()
    payload = _get_menu()

    assert payload.get("ok") is True, payload
    persona = payload.get("persona") or {}
    assert persona.get("slug") == PERSONA, persona
    collections = persona.get("collections") or []
    assert collections, f"persona {PERSONA} sem collections: {payload}"

    collection = collections[0]
    categories = collection.get("categories") or []
    # Contrato canonico: o cardapio expoe product_groups como categorias.
    assert isinstance(categories, list), collection

    # Slugs de categoria nao podem duplicar (grupo "sozinho"/duplicado quebra a UI).
    slugs = [c.get("slug") for c in categories]
    assert len(slugs) == len(set(slugs)), f"categorias com slug duplicado: {slugs}"

    # Cada produto precisa do shape minimo que o frontend baita-cardapio consome.
    total_products = 0
    for category in categories:
        assert category.get("slug"), category
        assert category.get("title"), category
        for product in category.get("products") or []:
            total_products += 1
            assert product.get("slug"), product
            assert product.get("name"), product
            assert isinstance(product.get("price_cents"), int), product
            assert isinstance(product.get("faqs"), list), product
            assert isinstance(product.get("assets"), list), product

    # Diagnostico util no log do pytest (-s) sem travar quando a persona esta vazia.
    print(
        f"[e2e] {PERSONA} @ {BASE_URL}: "
        f"{len(categories)} categorias, {total_products} produtos"
    )
