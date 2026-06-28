"""E2E simples do cardapio contra o backend RODANDO.

Diferente dos testes unitarios (hermeticos, sempre verdes), este bate no
backend de verdade em `AI_BRAIN_BASE_URL` (default http://localhost:8080, a
porta do servico `api` no docker-compose) e valida o contrato publico do
cardapio em `GET /api/menu/{persona}`.

Se o backend nao estiver no ar, o teste FAZ SKIP (nao falha) — assim ele so
roda quando voce sobe a stack. Para rodar:

    # suba o backend (docker compose --env-file .env.compose up -d --build)
    # depois:
    python -m pytest -q tests/e2e_baita_cardapio_menu.py

Variaveis de ambiente:
    AI_BRAIN_BASE_URL   base do backend (default http://localhost:8080)
    CARDAPIO_PERSONA    persona/slug do cardapio (default baita-conveniencia)
"""
from __future__ import annotations

import os

import pytest
import requests

BASE_URL = (
    os.environ.get("AI_BRAIN_BASE_URL")
    or os.environ.get("API_BASE")
    or "http://localhost:8080"
).rstrip("/")
PERSONA = os.environ.get("CARDAPIO_PERSONA", "baita-conveniencia")
TIMEOUT = float(os.environ.get("AI_BRAIN_HTTP_TIMEOUT", "15"))


def _require_backend() -> None:
    """Skip (don't fail) when the backend isn't reachable — this is an e2e."""
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"backend offline em {BASE_URL} ({exc}); suba a stack antes de rodar o e2e")
    if resp.status_code != 200:
        pytest.skip(f"/health respondeu {resp.status_code} em {BASE_URL}; backend nao esta saudavel")


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
