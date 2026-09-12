"""Regression guard for the Aurora price-disclosure policy while the price
plumbing refactor lands.

Aurora (and any persona with ``appointment_policy.price_disclosure ==
"human_only"``) must never let the agent state money for a service -- a human
closes. Meanwhile a separate refactor is normalizing five legacy price
storage shapes (``price_cents``, ``price.amount``, ``price.unit.amount``,
``offer.amount``, ...) into one canonical ``offer: {amount, currency}``. That
refactor changes *how* a price is resolved off a node; it must never change
*whether* the guard permits an agent to say it.

``graph_conversation_contract.price_disclosure_is_human_only()`` and
``reply_discloses_blocked_price()`` never look at a product node's price
field at all -- the first reads only the persona's policy dict, the second
scans reply *text* plus the cited nodes' own ``payment_policy`` claims. That
is by construction the right shape: successful price *resolution* (proven
here via ``routes.menu._compiled_offer``, the same helper the public catalog
uses) and price *disclosure permission* are independent axes. If a future
change ever wires node price data into the disclosure check, or if the
guard's text scan quietly regresses, this file should fail.

This file also documents, rather than hides, a real weakness found while
writing it: ``reply_discloses_blocked_price`` is a regex over the candidate
reply text. It fires on "R$ 189,90" and on "189,90 reais" (a lead-in word or
a currency token), but a bare "189,90" with neither a currency symbol nor a
lead-in phrase does NOT match -- see ``test_bare_numeric_price_is_not_detected``.
That is a real gap in the guard's coverage, called out here instead of
papered over.
"""
from __future__ import annotations

from routes import menu
from services import graph_conversation_contract


HUMAN_ONLY_POLICY = {"price_disclosure": "human_only"}


def _product_node(data: dict) -> dict:
    return {"id": "product:ceramic-coating", "node_type": "product", "data": data}


LEGACY_PRICE_SHAPES = [
    {"price_cents": 18990},
    {"price": {"amount": 189.9}},
    {"price": {"unit": {"amount": 189.9}}},
    {"offer": {"amount": 189.9}},
]


def test_price_disclosure_is_human_only_true_for_human_only_policy():
    assert graph_conversation_contract.price_disclosure_is_human_only(HUMAN_ONLY_POLICY) is True


def test_price_disclosure_is_human_only_false_for_other_or_missing_policy():
    assert graph_conversation_contract.price_disclosure_is_human_only({"price_disclosure": "agent_ok"}) is False
    assert graph_conversation_contract.price_disclosure_is_human_only({}) is False
    assert graph_conversation_contract.price_disclosure_is_human_only(None) is False


def test_resolvable_price_does_not_imply_disclosure_permission():
    """The key assertion: a node whose price IS resolvable still gets the
    human_only verdict from the disclosure guard -- resolution success and
    disclosure permission are independent concerns, not two views of the
    same fact.
    """
    for shape in LEGACY_PRICE_SHAPES:
        node = _product_node(shape)

        # Sanity check: the canonical offer resolver (shared with the public
        # catalog) actually resolves a price out of this legacy shape.
        resolved = menu._compiled_offer(node)
        assert resolved is not None, f"expected a resolvable price for shape {shape!r}"
        assert resolved["amount"] == 189.9

        # The disclosure guard is unmoved by that resolution -- it never
        # consults the node at all, only the persona's published policy.
        assert graph_conversation_contract.price_disclosure_is_human_only(HUMAN_ONLY_POLICY) is True


def test_reply_discloses_blocked_price_detects_currency_prefixed_amount():
    assert graph_conversation_contract.reply_discloses_blocked_price(
        "Fica R$ 189,90 na condição à vista.",
        HUMAN_ONLY_POLICY,
    ) is True


def test_reply_discloses_blocked_price_detects_amount_with_reais_suffix():
    assert graph_conversation_contract.reply_discloses_blocked_price(
        "O valor fica em 189,90 reais.",
        HUMAN_ONLY_POLICY,
    ) is True


def test_bare_numeric_price_is_not_detected():
    """Known gap: a reply that states just the bare number, with neither a
    currency symbol/word nor a recognized lead-in phrase before it, does not
    trip ``reply_discloses_blocked_price``. This is a real weakness in the
    guard's text scan, not a design choice being asserted as correct -- it is
    recorded here so a future change to the regex has a test to react to.
    """
    assert graph_conversation_contract.states_monetary_figure("189,90") is False
    assert graph_conversation_contract.reply_discloses_blocked_price(
        "189,90",
        HUMAN_ONLY_POLICY,
    ) is False


def test_reply_discloses_blocked_price_ignores_non_price_numbers():
    for text in ("Leva cerca de 48 horas.", "10% de desconto.", "Parcelamos em 4x sem juros."):
        assert graph_conversation_contract.reply_discloses_blocked_price(text, HUMAN_ONLY_POLICY) is False


def test_reply_discloses_blocked_price_false_when_policy_is_not_human_only():
    assert graph_conversation_contract.reply_discloses_blocked_price(
        "Fica R$ 189,90.",
        {"price_disclosure": "agent_ok"},
    ) is False


def test_reply_discloses_blocked_price_carved_out_by_payment_policy_claim():
    """A payment-terms figure (deposit, installments) that the graph itself
    authorizes via a ``payment_policy`` claim on a cited node must survive
    the guard -- the authorization comes from the node's published claim,
    never from the wording of the reply.
    """
    cited_nodes = [
        {"id": "policy:deposit", "data": {"claims": [{"claim_type": "payment_policy"}]}},
    ]
    assert graph_conversation_contract.reply_discloses_blocked_price(
        "O sinal é de R$ 50,00 para reservar o horário.",
        HUMAN_ONLY_POLICY,
        cited_nodes,
    ) is False


def test_legacy_price_shapes_all_resolve_to_the_same_canonical_offer():
    for shape in LEGACY_PRICE_SHAPES:
        resolved = menu._compiled_offer(_product_node(shape))
        assert resolved == {"amount": 189.9, "currency": "BRL"}
