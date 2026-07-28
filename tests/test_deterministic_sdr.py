import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "api"))

from services.deterministic_sdr import (
    Catalog,
    DeterministicSDR,
    Product,
    _price_from_graph_data,
    load_catalog,
)


def baita_engine():
    return DeterministicSDR(load_catalog(Path(__file__).parents[1] / "docs" / "sdr", "baita-conveniencia"))


def test_alias_and_price_are_exact_and_do_not_handoff():
    engine = baita_engine()
    result = engine.handle("Quanto custa redbull?")
    assert result["reply"] == "Red Bull 250 ml: R$ 15,00."
    assert result["handoff"] is False


def test_specific_product_tokens_outrank_unrelated_catalog_entries():
    product = baita_engine().catalog.find_product("Quanto custa Red Bull 250 ml?")
    assert product is not None
    assert product.slug == "red-bull-250ml"


def test_order_requires_confirmation_before_handoff():
    engine = baita_engine()
    state = engine.handle("Tem Red Bull?")["state"]
    state = engine.handle("Duas", state=state)["state"]
    state = engine.handle("Allan", state=state)["state"]
    result = engine.handle("Rua X, 100, Canoas", state=state)
    assert "Posso confirmar" in result["reply"]
    assert result["handoff"] is False
    result = engine.handle("Sim", state=result["state"])
    assert result["handoff"] is True
    assert result["state"]["confirmation_status"] == "confirmed_pending_human"


def test_missing_product_suggests_categories_without_generic_faq():
    engine = baita_engine()
    result = engine.handle("Tem produto inexistente?")
    assert "Não localizei" in result["reply"]
    assert "FAQ" not in result["reply"]


def test_persona_catalog_isolation():
    baita = load_catalog(Path(__file__).parents[1] / "docs" / "sdr", "baita-conveniencia")
    tock = Catalog("tock-fatal", products=[Product("modal", "Modal", aliases=("blusa modal",), price=59.9)])
    assert baita.find_product("modal") is None
    assert tock.find_product("modal").slug == "modal"


def test_full_unmatched_question_does_not_inherit_an_old_history_product():
    engine = DeterministicSDR(Catalog(
        "baita-conveniencia",
        products=[Product("crunch", "Chocolate Crunch", price=12)],
    ))
    result = engine.handle(
        "Quanto custa Red Bull 250 ml?",
        history=[{"sender_type": "lead", "texto": "Quero chocolate crunch"}],
    )
    assert "localizei esse item" in result["reply"]
    assert result["state"]["items"] == []


def test_graph_price_cents_is_read_as_an_approved_brl_price():
    assert _price_from_graph_data({"price_cents": 1200}, {}) == (12.0, "BRL")


def test_explicit_product_word_is_not_treated_as_quantity_only_followup():
    engine = baita_engine()
    result = engine.handle(
        "quero um chocolate",
        history=[{"sender_type": "lead", "texto": "quero coca cola 250ml"}],
    )
    assert result["state"]["items"] == []
    assert "COCA COLA" not in result["reply"]


def test_singular_beer_query_lists_every_product_linked_to_beer_group():
    engine = baita_engine()
    expected = engine.catalog.in_category("cervejas")
    result = engine.handle("quais opcoes de cerveja?")
    assert result["intent"] == "consult_category"
    assert len(expected) >= 40
    assert result["reply"].count("\n- ") == len(expected)
    assert all(product.public_name in result["reply"] for product in expected)
    assert len(result["reply"]) <= 4096


def test_category_query_interrupts_address_collection_without_mutating_address():
    engine = baita_engine()
    state = {
        "conversation_state": "awaiting_address",
        "customer_name": "Cliente QA",
        "items": [{"product_slug": "red-bull-250ml", "quantity": 1, "unit_price": 15}],
        "address": {},
    }
    result = engine.handle("tambem quero uma cerveja", state=state)
    assert result["intent"] == "consult_category"
    assert result["state"]["address"] == {}


def test_unknown_greeting_typo_is_not_saved_as_customer_name():
    result = baita_engine().handle("oio")
    assert result["state"]["customer_name"] is None


def test_number_only_address_does_not_become_a_street():
    engine = baita_engine()
    state = {
        "conversation_state": "awaiting_address",
        "customer_name": "Cliente QA",
        "items": [{"product_slug": "red-bull-250ml", "quantity": 1, "unit_price": 15}],
        "address": {},
    }
    result = engine.handle("152", state=state)
    assert result["state"]["address"] == {"number": "152"}
    assert "rua ou avenida" in result["reply"]
