"""The branch selector must not belong to one of the brands it chooses.

Tock Fatal sells the same catalogue under two brands at different prices. The
question that decides which brand a customer belongs to was declared twice, once
inside each brand, and the compiler builds the shared contract from the first
anchor in sorted order -- so `audience:tock-reseller` won on the alphabet and
every customer, retail included, was qualified through the wholesale branch's
node.

Production, publication v12:

    common_contract.purchase_profile.question_node_id = faq:tock-reseller-profile

Lead 181, 2026-09-04: arrived from the retail landing page, answered
"uso proprio", and was then asked "você está começando agora ou já tem loja ou
revenda?" -- a wholesale question -- with `active_branch_node_id` still null.

These tests pin the shape that prevents it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import graph_compiler_v3, site_blocks  # noqa: E402

# The head bundle. v16 contains the whole lineage -- v14's neutral branch
# selector, v15's flow FAQs and the rendered voice -- so the tests assert the
# version that would actually publish.
BUNDLE_PATH = (
    ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v16-voice-reachable.json"
)

RETAIL = "audience:tock-retail"
RESELLER = "audience:tock-reseller"
SELECTOR_KEY = "purchase_profile"
NEUTRAL_QUESTION = "faq:tock-purchase-profile"
RETIRED = ("faq:tock-retail-profile", "faq:tock-reseller-profile")
WHOLESALE_ONLY_QUESTION = "faq:tock-reseller-stage"


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nodes(bundle) -> dict:
    return {node["id"]: node for node in bundle["nodes"]}


def _selector_field(nodes: dict, anchor: str) -> dict:
    fields = ((nodes[anchor].get("data") or {}).get("qualification") or {}).get("fields") or []
    return next(field for field in fields if field.get("key") == SELECTOR_KEY)


@pytest.mark.unit
def test_selector_question_belongs_to_no_brand(nodes):
    """Both branches ask the same neutral node, so sort order stops deciding."""
    for anchor in (RETAIL, RESELLER):
        assert _selector_field(nodes, anchor)["question_node_id"] == NEUTRAL_QUESTION

    assert NEUTRAL_QUESTION in nodes
    for node_id in RETIRED:
        # Not archived and not removed: `archived` is not a publishable status,
        # and the publisher has no removal path yet, so a node dropped from the
        # bundle would stay active in the graph as an orphan. The retired nodes
        # keep their place and simply stop being referenced.
        assert nodes[node_id]["data"]["superseded_by"] == NEUTRAL_QUESTION
        assert nodes[node_id]["status"] != "archived"


@pytest.mark.unit
def test_compiler_still_recognises_the_selector(bundle, nodes):
    """The field must stay declared per branch, each owning its declaration.

    `branch_selection_field_key` refuses a selector declared by fewer than two
    branches, so collapsing the duplication into a single persona-owned field
    would silently disable branch selection altogether -- a worse failure than
    the one being fixed.
    """
    contracts = {
        anchor: {"fields": ((nodes[anchor].get("data") or {}).get("qualification") or {}).get("fields") or []}
        for anchor in (RETAIL, RESELLER)
    }
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")

    assert graph_compiler_v3.branch_selection_field_key(contracts, persona) == SELECTOR_KEY

    for anchor in (RETAIL, RESELLER):
        assert _selector_field(nodes, anchor)["owner_node_id"] == anchor


@pytest.mark.unit
def test_neutral_question_reaches_both_branches(bundle, nodes):
    for anchor in (RETAIL, RESELLER):
        closure = site_blocks.branch_closure(nodes, bundle["edges"], anchor)
        assert NEUTRAL_QUESTION in closure


@pytest.mark.unit
def test_wholesale_question_cannot_reach_a_retail_customer(bundle, nodes):
    """The exact defect observed with lead 181, pinned structurally."""
    retail = site_blocks.branch_closure(nodes, bundle["edges"], RETAIL)
    reseller = site_blocks.branch_closure(nodes, bundle["edges"], RESELLER)

    assert WHOLESALE_ONLY_QUESTION not in retail
    assert WHOLESALE_ONLY_QUESTION in reseller

    # The retired nodes stay in their own branch, which is harmless: nothing
    # references them, and `role: qualification_question` keeps them out of RAG
    # eligibility. What must never happen again is one brand's profile question
    # reaching the other brand's customer.
    assert "faq:tock-reseller-profile" not in retail
    assert "faq:tock-retail-profile" not in reseller


@pytest.mark.unit
def test_channels_stay_isolated(bundle, nodes):
    """Unchanged from the site's guarantee: one channel per branch."""
    def channels(closure: set[str], node_type: str) -> set[str]:
        return {
            (nodes[node_id].get("data") or {}).get("channel")
            for node_id in closure
            if nodes.get(node_id, {}).get("node_type") == node_type
        } - {None}

    retail = site_blocks.branch_closure(nodes, bundle["edges"], RETAIL)
    reseller = site_blocks.branch_closure(nodes, bundle["edges"], RESELLER)

    assert channels(retail, "offer") == {"varejo"}
    assert channels(reseller, "offer") == {"atacado"}
    assert channels(retail, "copy") == {"varejo"}
    assert channels(reseller, "copy") == {"atacado"}


@pytest.mark.unit
def test_branch_is_stable_unless_a_declared_trigger_fires(bundle):
    """One journey per customer: only the declared triggers may switch branch."""
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    selection = persona["data"]["conversation_policy"]["branch_selection"]
    stability = selection["stability"]

    assert stability["policy"] == "single_journey_per_customer"
    triggers = {item["id"] for item in stability["switch_triggers"]}
    assert triggers == {
        "customer_requests_more_pieces",
        "order_reaches_wholesale_minimum",
    }
    quantity = next(
        item for item in stability["switch_triggers"]
        if item["id"] == "order_reaches_wholesale_minimum"
    )
    # 3 pieces is the wholesale minimum the operator approved and the graph
    # already prices against (rule:tock-desconto-atacado-30).
    assert quantity["min_total_quantity"] == 3
    assert quantity["to_branch_node_id"] == RESELLER


@pytest.mark.unit
def test_origin_binds_the_branch_before_the_first_turn(bundle):
    """A lead from a brand's own page must not be asked which brand it wants."""
    persona = next(node for node in bundle["nodes"] if node["node_type"] == "persona")
    binding = persona["data"]["conversation_policy"]["branch_selection"]["origin_binding"]

    assert binding["field_key"] == SELECTOR_KEY
    by_branch = {rule["branch_node_id"] for rule in binding["rules"]}
    assert by_branch == {RETAIL, RESELLER}
    # The retail landing page ships this ref in its WhatsApp CTA today.
    assert any(
        rule["origin_ref_prefix"] == "cabecalho:tock-fatal"
        and rule["branch_node_id"] == RETAIL
        for rule in binding["rules"]
    )


# ── Flow-direction FAQs (v15) ────────────────────────────────────────────
#
# The graph could answer but not steer: nothing covered a customer arriving from
# the public site, nothing covered "quero mais peças" (the one trigger that may
# move a customer between branches), and an item outside the catalogue was
# handled by improvisation rather than by a graph-owned refusal.

DOORWAY = "faq:tock-varejo-mais-pecas"
WHOLESALE_MINIMUM = "faq:tock-atacado-minimo"
MISSING_ITEM = "faq:tock-item-inexistente"
ENTRY_RETAIL = "faq:tock-varejo-entrada-site"
ENTRY_RESELLER = "faq:tock-atacado-entrada-site"


@pytest.mark.unit
def test_each_flow_faq_is_reachable_only_where_it_belongs(bundle, nodes):
    retail = site_blocks.branch_closure(nodes, bundle["edges"], RETAIL)
    reseller = site_blocks.branch_closure(nodes, bundle["edges"], RESELLER)

    assert ENTRY_RETAIL in retail and ENTRY_RETAIL not in reseller
    assert ENTRY_RESELLER in reseller and ENTRY_RESELLER not in retail
    assert WHOLESALE_MINIMUM in reseller and WHOLESALE_MINIMUM not in retail

    # The doorway is the deliberate exception: the branch that receives
    # "quero mais peças" has to be able to answer it.
    assert DOORWAY in retail and DOORWAY not in reseller

    # An honest refusal belongs to both brands.
    assert MISSING_ITEM in retail and MISSING_ITEM in reseller


@pytest.mark.unit
def test_retail_never_quotes_a_wholesale_figure(bundle, nodes):
    """The doorway may name the quantity that opens it, never the terms.

    The quantity is the journey rule; the discount and the wholesale prices
    belong to the other brand and only apply after the switch. The compiler
    enforces the evidence side of this
    (`commercial_claim_evidence_outside_scope`); this pins the prose.
    """
    import re

    retail = site_blocks.branch_closure(nodes, bundle["edges"], RETAIL)
    offenders = [
        node_id for node_id in retail
        if nodes.get(node_id, {}).get("node_type") == "faq"
        and re.search(
            r"30\s*%|atacado[^.]{0,40}R\$|R\$[^.]{0,40}atacado",
            str((nodes[node_id].get("data") or {}).get("answer") or ""),
            re.I,
        )
    ]
    assert offenders == []

    answer = nodes[DOORWAY]["data"]["answer"]
    assert "3 peças" in answer
    assert "30%" not in answer and "R$" not in answer


@pytest.mark.unit
def test_flow_faqs_carry_self_evidence(nodes):
    """`published_accumulated_faq` means the published FAQ is the evidence.

    The compiler requires `evidence_node_ids == [own id]`; citing another node
    -- including the discount rule -- is rejected.
    """
    for node_id in (ENTRY_RETAIL, ENTRY_RESELLER, DOORWAY, WHOLESALE_MINIMUM, MISSING_ITEM):
        claims = nodes[node_id]["data"]["claims"]
        assert len(claims) == 1
        assert claims[0]["policy"] == "published_accumulated_faq"
        assert claims[0]["evidence_node_ids"] == [node_id]


@pytest.mark.unit
def test_navigation_faqs_ask_instead_of_describing_the_agent(nodes):
    """Seven answers ended with a note about what the agent can do.

    "A recomendação pode ser refinada pelo estilo, ocasião ou objetivo que o
    cliente informar" is documentation aimed at whoever reads the graph. Said to
    a customer it stalls the turn, because it asks for nothing.
    """
    navigation = [
        node for node in nodes.values()
        if node.get("node_type") == "faq" and node["id"].endswith("-navegacao")
    ]
    assert len(navigation) == 7
    for node in navigation:
        answer = node["data"]["answer"]
        assert "pode ser refinada" not in answer
        assert answer.rstrip().endswith("?"), (
            "a navigation answer has to hand the turn back with a question"
        )


# ── Voice reachability (v16) ─────────────────────────────────────────────
#
# `conversation_runtime.build_system_prompt` reads each tone and rule node as
# `data.markdown or data.summary`. Tock's tone nodes carried only a one-line
# summary, so the seven guidelines that actually describe how Vitória speaks
# never reached the model.

@pytest.mark.unit
def test_voice_guidelines_reach_the_system_prompt(nodes):
    voice = nodes["tone:tock-vitoria-voice"]["data"]
    markdown = voice.get("markdown") or ""

    # Every published guideline has to survive into the field the prompt reads.
    for guideline in voice["voice"]["guidelines"]:
        assert guideline in markdown, f"guideline dropped from the prompt: {guideline}"
    for style in voice["voice"]["style"]:
        assert style in markdown


@pytest.mark.unit
def test_rule_facts_reach_the_system_prompt(nodes):
    discount = nodes["rule:tock-desconto-atacado-30"]["data"]
    markdown = discount.get("markdown") or ""
    for fact in discount["facts"]:
        assert fact in markdown


@pytest.mark.unit
def test_rendering_never_shrinks_a_node(nodes):
    """The summary must still be there; markdown adds, never replaces."""
    for node_id in (
        "tone:tock-vitoria-voice",
        "tone:tock-vitoria-clear-language",
        "rule:tock-safe-handoff",
        "rule:tock-desconto-atacado-30",
    ):
        node = nodes[node_id]
        assert node["summary"].strip() in node["data"]["markdown"]
