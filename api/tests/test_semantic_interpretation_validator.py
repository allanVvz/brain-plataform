"""Parametrized suite for services.semantic_interpretation_validator.

The old runtime rejected semantically correct customer messages because they
did not match a fixed phrase list (``_EXPLICIT_CONFIRMATIONS`` and friends).
This suite protects the replacement's actual invariant: wording never decides
whether an element survives. An element is dropped ONLY for:

  * an ``evidence_span`` that is not a verbatim (accent/case/punctuation-
    insensitive) substring of the customer's message,
  * a node id / field key not present in the supplied graph document or
    contract,
  * a value not allowed by the graph's own enum validation for that field,
  * a confirmation with no matching ``pending_confirmation_ref``,
  * a commercial claim with no published evidence node,
  * a handoff the graph does not permit.

Nothing here reproduces the retired phrase lists or matching logic. The
natural-language parametrizations below deliberately vary ONLY the wording of
an otherwise structurally-identical interpretation, to prove the validator is
blind to phrasing and decides on structure alone.

Fixtures use a generic, fictional persona ("Aria", a made-up boutique) so the
graph/contract shape stays persona-neutral. Only the explicitly-named
real-regression tests near the bottom reference the actual wording from
docs/handoffs (Vitória-style live findings) that motivated this validator.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import (
    CommercialClaim,
    ConversationContext,
    CustomerQuestion,
    ExtractedFact,
    FactInvalidation,
    SemanticBranchSelection,
    SemanticConfirmation,
    SemanticEntity,
    SemanticIntent,
    SemanticInterpretation,
)
from services.semantic_interpretation_validator import (
    ValidationResult,
    needs_clarification,
    validate_interpretation,
)


# ---------------------------------------------------------------------------
# Fixture fabric: a generic, fictional persona ("Aria", a boutique reselling
# dresses). None of this is a real product/persona; it exists purely to give
# the validator a graph-shaped document and contract to check spans against.
# ---------------------------------------------------------------------------

PERSONA_NODE = "persona:aria"
BRANCH_RETAIL = "branch:aria-retail"
BRANCH_RESELLER = "branch:aria-reseller"
EVIDENCE_NODE = "node:aria-evidence-published"
FOREIGN_NODE = "node:other-persona-evidence"  # deliberately absent from node_by_id
PENDING_REF = "confirm:aria-qualification-summary"

DEFAULT_NODES: dict[str, dict] = {
    PERSONA_NODE: {"id": PERSONA_NODE, "node_type": "persona", "slug": "aria"},
    BRANCH_RETAIL: {"id": BRANCH_RETAIL, "node_type": "product", "slug": "aria-retail"},
    BRANCH_RESELLER: {"id": BRANCH_RESELLER, "node_type": "product", "slug": "aria-reseller"},
    EVIDENCE_NODE: {"id": EVIDENCE_NODE, "node_type": "faq", "slug": "aria-evidence"},
}

DEFAULT_BRANCH_ANCHORS = {BRANCH_RETAIL, BRANCH_RESELLER}

DEFAULT_FIELDS: list[dict] = [
    {
        "key": "audience",
        "owner_node_id": PERSONA_NODE,
        "question_node_id": "faq:aria-audience",
        "validation": {
            "mode": "enum",
            "values": [
                {"value": "retail", "aliases": ["uso proprio", "pra mim", "consumo proprio"]},
                {"value": "reseller", "aliases": ["revenda", "revendedor", "revendedora"]},
            ],
        },
    },
    {
        "key": "customer_name",
        "owner_node_id": PERSONA_NODE,
        "question_node_id": "faq:aria-name",
        "validation": None,
    },
    {
        "key": "quantity",
        "owner_node_id": BRANCH_RETAIL,
        "question_node_id": "faq:aria-quantity",
        "validation": None,
    },
]


def make_document(*, node_by_id: dict | None = None, branch_anchors: set[str] | None = None) -> dict:
    nodes = dict(DEFAULT_NODES)
    if node_by_id:
        nodes.update(node_by_id)
    anchors = set(branch_anchors) if branch_anchors is not None else set(DEFAULT_BRANCH_ANCHORS)
    return {
        "node_by_id": nodes,
        "branch_anchors": anchors,
        "coordinates": {
            node_id: {"branch_anchor_node_id": None, "path_node_ids": [node_id]}
            for node_id in nodes
        },
    }


def make_contract(
    *,
    fields: list[dict] | None = None,
    required_fields: list[str] | None = None,
    handoff_rule_node_ids: list[str] | None = None,
    confirmation_required: bool = False,
) -> dict:
    return {
        "fields": [dict(spec) for spec in (fields if fields is not None else DEFAULT_FIELDS)],
        "required_fields": (
            list(required_fields) if required_fields is not None else ["audience", "customer_name"]
        ),
        "handoff_rule_node_ids": list(handoff_rule_node_ids or []),
        "confirmation_required": confirmation_required,
    }


def make_context(*, pending_confirmation_ref: str | None = None, **overrides) -> ConversationContext:
    payload = {
        "persona_slug": "aria-generic",
        "agent_slug": "aria-sdr",
        "graph_version": 1,
        "graph_checksum": "sha256:test-checksum",
        "messages": [],
        "cart": {},
        "rag_nodes": [],
        "rag_paths": [],
        "pending_confirmation_ref": pending_confirmation_ref,
    }
    payload.update(overrides)
    return ConversationContext.model_validate(payload)


# -- interpretation element builders (plain dicts, validated by pydantic) --

def _intent(kind: str, span: str) -> dict:
    return {"kind": kind, "evidence_span": span}


def _confirmation(
    state: str = "none",
    target_ref: str | None = None,
    span: str = "",
    correction_field_key: str | None = None,
    correction_value=None,
) -> dict:
    return {
        "state": state,
        "target_ref": target_ref,
        "evidence_span": span,
        "correction_field_key": correction_field_key,
        "correction_value": correction_value,
    }


def _branch_selection(action: str = "none", anchor: str | None = None, span: str = "") -> dict:
    return {"action": action, "branch_anchor_node_id": anchor, "evidence_span": span}


def _fact(field_key: str, value, owner_node_id: str, span: str, status: str = "known") -> dict:
    return {
        "field_key": field_key,
        "value": value,
        "owner_node_id": owner_node_id,
        "evidence_span": span,
        "status": status,
    }


def _question(kind: str, topic: str, span: str, entity_node_ids: list[str] | None = None) -> dict:
    return {
        "kind": kind,
        "topic": topic,
        "evidence_span": span,
        "entity_node_ids": entity_node_ids or [],
    }


def _entity(kind: str, value, span: str, node_id: str | None = None) -> dict:
    return {"kind": kind, "value": value, "evidence_span": span, "node_id": node_id}


def _invalidation(field_key: str, reason: str, span: str) -> dict:
    return {"field_key": field_key, "reason": reason, "evidence_span": span}


def _claim(claim_type: str, evidence_node_ids: list[str] | None = None) -> dict:
    return {
        "claim_type": claim_type,
        "value": {},
        "evidence_node_ids": evidence_node_ids or [],
        "evidence_chunk_ids": [],
    }


def make_interpretation(**overrides) -> SemanticInterpretation:
    base = {
        "intents": [],
        "state_relation": "unclear",
        "answers_field_key": None,
        "confirmation": _confirmation(),
        "branch_selection": _branch_selection(),
        "facts": [],
        "invalidated_facts": [],
        "entities": [],
        "questions": [],
        "claims": [],
        "recommended_next_action": "clarify",
        "cited_node_ids": [],
        "cited_chunk_ids": [],
        "reply": "",
        "handoff_requested": False,
    }
    base.update(overrides)
    return SemanticInterpretation.model_validate(base)


def run(
    interpretation: SemanticInterpretation,
    message: str,
    *,
    document: dict | None = None,
    contract: dict | None = None,
    context: ConversationContext | None = None,
) -> ValidationResult:
    return validate_interpretation(
        interpretation,
        message=message,
        document=document if document is not None else make_document(),
        contract=contract if contract is not None else make_contract(),
        context=context if context is not None else make_context(),
    )


# ===========================================================================
# Natural-language variety: same STRUCTURE, only the wording changes.
# The assertions never mention which phrase produced the surviving element --
# that is the point. Wording is irrelevant to the validator.
# ===========================================================================

PERSONAL_USE_PHRASES = [
    "uso próprio mesmo",
    "é pra mim",
    "quero comprar para usar",
    "e pra mim mesmo viu",
    "compra pra uso pessoal",
    "eh pra mim usar",
    "é só pra mim",
    "quero pra mim, uso pessoal",
    "uso proprio msm",
    "pra mim msm",
    "vou usar eu mesma",
    "é pro meu uso",
    "compro pra usar eu",
    "uso particular",
    "pra mim viu, nao eh pra revender",
    "quero pra consumo proprio",
    "so pra mim usar",
    "eh de uso pessoal",
    "vou usar, nao vender",
    "pra minha casa mesmo",
]

RESELLER_PHRASES = [
    "quero começar a revender",
    "é para revenda mesmo, quero montar um estoque",
    "vou revender",
    "sou revendedora",
    "quero comprar pra revender",
    "e pra revenda",
    "trabalho com revenda",
    "quero montar estoque pra vender",
    "vou abrir uma lojinha",
    "compro pra revender depois",
    "sou revendedor, preciso de quantidade",
    "quero virar revendedora de voces",
    "e pro meu comercio",
    "vou vender pra outras pessoas",
    "quero fornecer pra minhas clientes",
    "trampo com revenda mesmo",
    "preciso de lote pra revenda",
    "sou do ramo de revenda",
    "quero comprar no atacado pra revender",
    "e pra minha loja",
]

CONFIRMATION_PHRASES = [
    "sim",
    "sim, tá correto",
    "isso mesmo",
    "certinho",
    "pode seguir",
    "é isso aí",
    "tudo certo",
    "exato",
    "confirmo",
    "isso",
    "positivo",
    "correto",
    "beleza, pode confirmar",
    "confere sim",
    "fechado",
    "tá certo sim",
    "isso aí mesmo",
    "ok, confirmado",
    "sim senhora, esta certo",
    "aham, ta certo",
    "isso mesmo, pode confirmar",
    "confirmado",
    "sim pode confirmar",
    "esta tudo certo sim",
    "perfeito, confirma aí",
]

REJECTION_PHRASES = [
    "não está correto",
    "não é isso",
    "está errado",
    "não, tá errado",
    "isso não",
    "negativo",
    "num é isso nao",
    "ta errado",
    "não confere",
    "cancela isso",
    "nao foi isso que eu disse",
    "errado",
    "não é bem assim",
    "isso aí n",
    "n é isso nao",
]

CORRECTION_PHRASES = [
    "sim, mas muda para revenda",
    "isso, só que é pra revenda",
    "certo, mas troca pra revenda",
    "confirma, só corrige pra revenda",
    "sim so que na verdade e revenda",
    "ta certo, mas na real e pra revenda",
    "isso mesmo so que revenda viu",
    "correto so que muda pra revenda",
    "sim mas naum, e revenda",
    "positivo mas corrige pra revenda",
    "beleza so ajusta pra revenda",
    "fechado mas troca pra revenda",
    "sim, corrige: revenda",
    "confirmo mas e revenda na verdade",
    "isso aí mas muda pra revenda",
]


@pytest.mark.parametrize("phrase", PERSONAL_USE_PHRASES)
def test_personal_use_phrasing_survives_regardless_of_wording(phrase):
    interpretation = make_interpretation(
        facts=[_fact("audience", "retail", PERSONA_NODE, phrase)],
    )
    result = run(interpretation, phrase)
    assert result.valid is True
    assert len(result.interpretation.facts) == 1
    fact = result.interpretation.facts[0]
    assert fact.field_key == "audience"
    assert fact.value == "retail"
    assert not any(item["kind"] == "fact" for item in result.dropped)


@pytest.mark.parametrize("phrase", RESELLER_PHRASES)
def test_reseller_phrasing_survives_regardless_of_wording(phrase):
    interpretation = make_interpretation(
        facts=[_fact("audience", "reseller", PERSONA_NODE, phrase)],
    )
    result = run(interpretation, phrase)
    assert result.valid is True
    assert len(result.interpretation.facts) == 1
    fact = result.interpretation.facts[0]
    assert fact.field_key == "audience"
    assert fact.value == "reseller"
    assert not any(item["kind"] == "fact" for item in result.dropped)


@pytest.mark.parametrize("phrase", CONFIRMATION_PHRASES)
def test_confirmation_phrasing_survives_regardless_of_wording(phrase):
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span=phrase),
    )
    context = make_context(pending_confirmation_ref=PENDING_REF)
    result = run(interpretation, phrase, context=context)
    assert result.valid is True
    assert result.interpretation.confirmation.state.value == "affirm"
    assert result.interpretation.confirmation.target_ref == PENDING_REF
    assert not any(item["kind"] == "confirmation" for item in result.dropped)


@pytest.mark.parametrize("phrase", REJECTION_PHRASES)
def test_rejection_phrasing_survives_regardless_of_wording(phrase):
    interpretation = make_interpretation(
        confirmation=_confirmation(state="reject", target_ref=PENDING_REF, span=phrase),
    )
    context = make_context(pending_confirmation_ref=PENDING_REF)
    result = run(interpretation, phrase, context=context)
    assert result.valid is True
    assert result.interpretation.confirmation.state.value == "reject"
    assert not any(item["kind"] == "confirmation" for item in result.dropped)


@pytest.mark.parametrize("phrase", CORRECTION_PHRASES)
def test_correction_phrasing_survives_regardless_of_wording(phrase):
    interpretation = make_interpretation(
        confirmation=_confirmation(
            state="partial",
            target_ref=PENDING_REF,
            span=phrase,
            correction_field_key="audience",
            correction_value="reseller",
        ),
    )
    context = make_context(pending_confirmation_ref=PENDING_REF)
    result = run(interpretation, phrase, context=context)
    assert result.valid is True
    assert result.interpretation.confirmation.state.value == "partial"
    assert result.interpretation.confirmation.correction_field_key == "audience"
    assert result.interpretation.confirmation.correction_value == "reseller"


# ===========================================================================
# Behavioral / structural invariants
# ===========================================================================

def test_partial_confirmation_survives_when_correction_field_is_known():
    context = make_context(pending_confirmation_ref=PENDING_REF)
    interpretation = make_interpretation(
        confirmation=_confirmation(
            state="partial",
            target_ref=PENDING_REF,
            span="sim mas muda pra revenda",
            correction_field_key="audience",
            correction_value="reseller",
        ),
    )
    result = run(interpretation, "sim mas muda pra revenda", context=context)
    confirmation = result.interpretation.confirmation
    assert confirmation.state.value == "partial"
    assert confirmation.correction_field_key == "audience"
    assert confirmation.correction_value == "reseller"


def test_partial_confirmation_correction_dropped_when_field_is_unknown():
    context = make_context(pending_confirmation_ref=PENDING_REF)
    interpretation = make_interpretation(
        confirmation=_confirmation(
            state="partial",
            target_ref=PENDING_REF,
            span="sim mas muda um campo que nao existe",
            correction_field_key="campo_totalmente_inexistente",
            correction_value="qualquer coisa",
        ),
    )
    result = run(interpretation, "sim mas muda um campo que nao existe", context=context)
    confirmation = result.interpretation.confirmation
    assert confirmation.correction_field_key is None
    assert confirmation.correction_value is None
    assert any(
        item["kind"] == "confirmation_correction" and item["reason"] == "unknown_field_key"
        for item in result.dropped
    )


def test_sim_with_no_pending_confirmation_is_dropped():
    context = make_context(pending_confirmation_ref=None)
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=None, span="sim"),
    )
    result = run(interpretation, "sim", context=context)
    assert result.interpretation.confirmation.state.value == "none"
    assert any(
        item["kind"] == "confirmation" and item["reason"] == "no_pending_confirmation"
        for item in result.dropped
    )


def test_confirmation_target_ref_mismatch_is_dropped():
    context = make_context(pending_confirmation_ref="confirm:some-other-ref")
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span="sim"),
    )
    result = run(interpretation, "sim", context=context)
    assert result.interpretation.confirmation.state.value == "none"
    assert any(
        item["kind"] == "confirmation" and item["reason"] == "target_ref_mismatch"
        for item in result.dropped
    )


UNGROUNDED_SPAN = "essa frase definitivamente nao esta na mensagem nunca"
UNRELATED_MESSAGE = "mensagem totalmente diferente, sem nenhuma relacao com nada"

EVIDENCE_NOT_IN_MESSAGE_CASES = {
    "intent": (
        lambda span: make_interpretation(intents=[_intent("greeting", span)]),
        lambda interp: interp.intents == [],
    ),
    "fact": (
        lambda span: make_interpretation(
            facts=[_fact("customer_name", "Maria", PERSONA_NODE, span)]
        ),
        lambda interp: interp.facts == [],
    ),
    "branch_selection": (
        lambda span: make_interpretation(
            branch_selection=_branch_selection(action="select", anchor=BRANCH_RETAIL, span=span)
        ),
        lambda interp: interp.branch_selection.action.value == "none",
    ),
    "entity": (
        lambda span: make_interpretation(entities=[_entity("quantity", 10, span)]),
        lambda interp: interp.entities == [],
    ),
    "question": (
        lambda span: make_interpretation(
            questions=[_question("availability", "produto", span)]
        ),
        lambda interp: interp.questions == [],
    ),
    "invalidated_fact": (
        lambda span: make_interpretation(
            invalidated_facts=[_invalidation("customer_name", "mudou de ideia", span)]
        ),
        lambda interp: interp.invalidated_facts == [],
    ),
}


@pytest.mark.parametrize("kind", sorted(EVIDENCE_NOT_IN_MESSAGE_CASES))
def test_evidence_not_in_message_drops_the_element(kind):
    build, check_dropped = EVIDENCE_NOT_IN_MESSAGE_CASES[kind]
    interpretation = build(UNGROUNDED_SPAN)
    result = run(interpretation, UNRELATED_MESSAGE)
    assert check_dropped(result.interpretation)
    assert any(
        item["kind"] == kind and item["reason"] == "evidence_not_in_message"
        for item in result.dropped
    )


def test_grounding_is_accent_case_and_punctuation_insensitive():
    context = make_context(pending_confirmation_ref=PENDING_REF)
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span="TA CORRETO"),
    )
    result = run(interpretation, "Sim, tá correto!", context=context)
    assert result.interpretation.confirmation.state.value == "affirm"


def test_question_and_answer_in_one_message_both_survive():
    message = "é pra mim mesmo, vocês tem 50 vestidos em mousse?"
    interpretation = make_interpretation(
        answers_field_key="audience",
        facts=[_fact("audience", "retail", PERSONA_NODE, "é pra mim mesmo")],
        questions=[
            _question(
                "availability",
                "vestidos em mousse",
                "vocês tem 50 vestidos em mousse",
            )
        ],
    )
    result = run(interpretation, message)
    assert result.interpretation.answers_field_key == "audience"
    assert len(result.interpretation.facts) == 1
    assert len(result.interpretation.questions) == 1


def test_two_commercial_questions_in_one_message_both_survive():
    message = "vocês tem 50 vestidos em mousse disponíveis e qual o prazo de entrega?"
    interpretation = make_interpretation(
        questions=[
            _question(
                "availability",
                "vestidos em mousse",
                "vocês tem 50 vestidos em mousse disponíveis",
            ),
            _question("deadline", "prazo de entrega", "qual o prazo de entrega"),
        ],
    )
    result = run(interpretation, message)
    assert len(result.interpretation.questions) == 2
    kinds = {question.kind.value for question in result.interpretation.questions}
    assert kinds == {"availability", "deadline"}


def test_availability_question_and_quantity_entity_survive_without_becoming_a_fact():
    message = "vocês tem 50 vestidos em mousse?"
    interpretation = make_interpretation(
        questions=[
            _question("availability", "vestidos em mousse", "vocês tem 50 vestidos em mousse")
        ],
        entities=[_entity("quantity", 50, "50")],
    )
    result = run(interpretation, message)
    assert len(result.interpretation.questions) == 1
    assert len(result.interpretation.entities) == 1
    assert result.interpretation.facts == []
    assert not any(
        "vestidos" in str(fact.value) for fact in result.interpretation.facts
    )


def test_claim_without_evidence_is_dropped():
    interpretation = make_interpretation(
        claims=[_claim("availability", evidence_node_ids=[])],
    )
    result = run(interpretation, "temos sim, disponível")
    assert result.interpretation.claims == []
    assert any(
        item["kind"] == "claim" and item["reason"] == "no_published_evidence"
        for item in result.dropped
    )


def test_claim_with_published_evidence_survives():
    interpretation = make_interpretation(
        claims=[_claim("availability", evidence_node_ids=[EVIDENCE_NODE])],
    )
    result = run(interpretation, "temos sim, disponível")
    assert len(result.interpretation.claims) == 1
    assert result.interpretation.claims[0].evidence_node_ids == [EVIDENCE_NODE]


def test_claim_citing_foreign_node_dropped_persona_isolation():
    interpretation = make_interpretation(
        claims=[_claim("availability", evidence_node_ids=[FOREIGN_NODE])],
    )
    result = run(interpretation, "temos sim, disponível")
    assert result.interpretation.claims == []
    assert any(
        item["kind"] == "claim" and item["reason"] == "no_published_evidence"
        for item in result.dropped
    )


def test_cited_node_ids_strip_foreign_ids():
    interpretation = make_interpretation(cited_node_ids=[EVIDENCE_NODE, FOREIGN_NODE])
    result = run(interpretation, "qualquer mensagem, nao importa o texto")
    assert result.interpretation.cited_node_ids == [EVIDENCE_NODE]


def test_branch_selection_with_unknown_anchor_is_dropped():
    message = "quero mudar pra outra categoria"
    interpretation = make_interpretation(
        branch_selection=_branch_selection(
            action="select", anchor="branch:does-not-exist", span="mudar pra outra categoria"
        ),
    )
    result = run(interpretation, message)
    assert result.interpretation.branch_selection.action.value == "none"
    assert any(
        item["kind"] == "branch_selection" and item["reason"] == "unknown_branch_anchor"
        for item in result.dropped
    )


def test_branch_switch_with_valid_anchor_survives():
    message = "na verdade quero mudar pra revenda"
    interpretation = make_interpretation(
        branch_selection=_branch_selection(
            action="switch", anchor=BRANCH_RESELLER, span="mudar pra revenda"
        ),
    )
    result = run(interpretation, message)
    assert result.interpretation.branch_selection.action.value == "switch"
    assert result.interpretation.branch_selection.branch_anchor_node_id == BRANCH_RESELLER


def test_fact_with_unknown_field_key_is_dropped():
    interpretation = make_interpretation(
        facts=[_fact("campo_totalmente_inexistente", "x", PERSONA_NODE, "algum valor")],
    )
    result = run(interpretation, "algum valor")
    assert result.interpretation.facts == []
    assert any(
        item["kind"] == "fact" and item["reason"] == "unknown_field_key"
        for item in result.dropped
    )


def test_fact_with_unknown_owner_node_is_dropped():
    interpretation = make_interpretation(
        facts=[_fact("customer_name", "Maria", "node:does-not-exist", "Maria")],
    )
    result = run(interpretation, "Maria")
    assert result.interpretation.facts == []
    assert any(
        item["kind"] == "fact" and item["reason"] == "unknown_owner_node"
        for item in result.dropped
    )


def test_enum_field_value_matching_alias_survives():
    interpretation = make_interpretation(
        facts=[_fact("audience", "uso proprio", PERSONA_NODE, "uso proprio")],
    )
    result = run(interpretation, "uso proprio")
    assert len(result.interpretation.facts) == 1
    assert result.interpretation.facts[0].value == "uso proprio"


def test_enum_field_value_outside_enum_is_dropped():
    interpretation = make_interpretation(
        facts=[_fact("audience", "alienigena", PERSONA_NODE, "alienigena")],
    )
    result = run(interpretation, "alienigena")
    assert result.interpretation.facts == []
    assert any(
        item["kind"] == "fact" and item["reason"] == "value_not_allowed_by_graph"
        for item in result.dropped
    )


def test_free_text_field_accepts_any_grounded_value():
    interpretation = make_interpretation(
        facts=[_fact("customer_name", "Zzqx Ptlt", PERSONA_NODE, "Zzqx Ptlt")],
    )
    result = run(interpretation, "Zzqx Ptlt, esse e meu nome")
    assert len(result.interpretation.facts) == 1
    assert result.interpretation.facts[0].value == "Zzqx Ptlt"


def test_contradiction_confirmation_and_rejection_invalidates_result():
    interpretation = make_interpretation(
        intents=[_intent("confirmation", "sim"), _intent("rejection", "nao")],
    )
    result = run(interpretation, "sim nao, mudei de ideia")
    assert result.valid is False
    assert "contradiction_confirmation_and_rejection" in result.errors


def test_handoff_dropped_when_graph_permits_neither_rule_nor_confirmation():
    interpretation = make_interpretation(handoff_requested=True)
    contract = make_contract(handoff_rule_node_ids=[], confirmation_required=False)
    result = run(interpretation, "preciso falar com um humano", contract=contract)
    assert result.interpretation.handoff_requested is False
    assert any(item["kind"] == "handoff" for item in result.dropped)


def test_handoff_permitted_when_graph_has_handoff_rule():
    interpretation = make_interpretation(handoff_requested=True)
    contract = make_contract(handoff_rule_node_ids=["rule:aria-handoff"])
    result = run(interpretation, "preciso falar com um humano", contract=contract)
    assert result.interpretation.handoff_requested is True
    assert not any(item["kind"] == "handoff" for item in result.dropped)


def test_handoff_permitted_when_confirmation_required():
    interpretation = make_interpretation(handoff_requested=True)
    contract = make_contract(confirmation_required=True)
    result = run(interpretation, "preciso falar com um humano", contract=contract)
    assert result.interpretation.handoff_requested is True
    assert not any(item["kind"] == "handoff" for item in result.dropped)


def test_needs_clarification_true_when_everything_is_vague():
    interpretation = make_interpretation()
    result = run(interpretation, "oi, bom dia")
    assert needs_clarification(result) is True


NEEDS_CLARIFICATION_SURVIVORS = {
    "fact": lambda: (
        make_interpretation(facts=[_fact("customer_name", "Maria", PERSONA_NODE, "Maria")]),
        "Maria",
        make_context(),
    ),
    "question": lambda: (
        make_interpretation(
            questions=[_question("availability", "produto", "tem disponivel")]
        ),
        "tem disponivel",
        make_context(),
    ),
    "branch_selection": lambda: (
        make_interpretation(
            branch_selection=_branch_selection(
                action="select", anchor=BRANCH_RETAIL, span="quero esse aqui"
            )
        ),
        "quero esse aqui",
        make_context(),
    ),
    "confirmation": lambda: (
        make_interpretation(
            confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span="sim")
        ),
        "sim",
        make_context(pending_confirmation_ref=PENDING_REF),
    ),
    "invalidated_fact": lambda: (
        make_interpretation(
            invalidated_facts=[_invalidation("customer_name", "mudou", "mudei de ideia")]
        ),
        "mudei de ideia",
        make_context(),
    ),
}


@pytest.mark.parametrize("label", sorted(NEEDS_CLARIFICATION_SURVIVORS))
def test_needs_clarification_false_when_any_element_survives(label):
    interpretation, message, context = NEEDS_CLARIFICATION_SURVIVORS[label]()
    result = run(interpretation, message, context=context)
    assert needs_clarification(result) is False, label


# ===========================================================================
# No numeric confidence anywhere in the new contract.
#
# The old ConversationProposal/ExtractedFact stack already carries a
# `confidence` field on ExtractedFact -- that model is reused as-is by
# SemanticInterpretation.facts, so its `confidence` field is an intentional,
# documented exception (inherited from a pre-existing shared model), not a
# hole in the "no confidence anywhere" rule for the NEW semantic contract.
# ===========================================================================

NEW_MODELS_WITHOUT_CONFIDENCE = [
    SemanticInterpretation,
    SemanticIntent,
    SemanticConfirmation,
    SemanticBranchSelection,
    CustomerQuestion,
    SemanticEntity,
    FactInvalidation,
    CommercialClaim,
]


@pytest.mark.parametrize(
    "model", NEW_MODELS_WITHOUT_CONFIDENCE, ids=lambda model: model.__name__
)
def test_new_semantic_models_carry_no_confidence_field(model):
    assert "confidence" not in model.model_fields


def test_extracted_fact_confidence_is_a_documented_pre_existing_exception():
    # ExtractedFact predates this validator (shared with ConversationProposal)
    # and already publishes `confidence`. Documenting it here so a future
    # change that removes it does not silently pass this suite.
    assert "confidence" in ExtractedFact.model_fields


# ===========================================================================
# Real-regression cases, explicitly named from the live-testing findings that
# motivated this validator: semantically correct customer replies the OLD
# phrase-list matcher rejected.
# ===========================================================================

def test_regression_uso_proprio_mesmo_selects_retail_anchor():
    message = "uso próprio mesmo"
    interpretation = make_interpretation(
        branch_selection=_branch_selection(action="select", anchor=BRANCH_RETAIL, span=message),
    )
    result = run(interpretation, message)
    assert result.interpretation.branch_selection.action.value == "select"
    assert result.interpretation.branch_selection.branch_anchor_node_id == BRANCH_RETAIL


def test_regression_sim_ta_correto_confirms_pending_ref():
    context = make_context(pending_confirmation_ref=PENDING_REF)
    message = "sim, tá correto"
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span=message),
    )
    result = run(interpretation, message, context=context)
    assert result.interpretation.confirmation.state.value == "affirm"
    assert result.interpretation.confirmation.target_ref == PENDING_REF


def test_regression_availability_question_with_quantity_invents_no_claim():
    message = "vocês tem 50 vestidos em mousse?"
    interpretation = make_interpretation(
        questions=[
            _question("availability", "vestidos em mousse", "vocês tem 50 vestidos em mousse")
        ],
        entities=[_entity("quantity", 50, "50")],
    )
    result = run(interpretation, message)
    assert len(result.interpretation.questions) == 1
    assert len(result.interpretation.entities) == 1
    assert result.interpretation.claims == []


def test_regression_bare_sim_with_pending_ref_survives():
    # The new deterministic layer must be a strict superset of the old
    # phrase-list behavior for the one case it always got right.
    context = make_context(pending_confirmation_ref=PENDING_REF)
    interpretation = make_interpretation(
        confirmation=_confirmation(state="affirm", target_ref=PENDING_REF, span="sim"),
    )
    result = run(interpretation, "sim", context=context)
    assert result.interpretation.confirmation.state.value == "affirm"
    assert result.interpretation.confirmation.target_ref == PENDING_REF
