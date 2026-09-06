"""Regression tests for three defects found in the canonical n8n conversation
template on 2026-09-05, lead 209 (Tock Fatal / Vitoria).

A retail customer answered the branch-selection question with "Proprio". The
model wrote "Perfeito! Entao voce quer para uso proprio" and returned
`facts: []` and `branch_selections: []`, so `active_branch_node_id` stayed
null, retrieval stopped being branch scoped, and the agent quoted the WHOLESALE
price to a retail customer. Every guard passed: the proof checker returned
`valid: true, errors: []`.

Each defect found while reading that turn gets its own section below.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ROOT / "apps" / "conversation-runtime" / "n8n" / "persona-conversation-template.json"
WORKFLOW = json.loads(TEMPLATE.read_text(encoding="utf-8"))

VALIDATOR_NODES = ("Validate agent response", "Validate repaired agent response")


def _node(name: str) -> dict:
    return next(node for node in WORKFLOW["nodes"] if node["name"] == name)


def _require_node() -> None:
    if not shutil.which("node"):
        pytest.skip("node is required to execute the canonical n8n code node")


def _run_prompt_builder(context: dict, binding: dict) -> dict:
    _require_node()
    harness = """
const fs = require('fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  'Load published graph context': fixture.context,
  'Resolve conversation policy': {decision: {route: 'SDR', intent: 'commercial'}},
  'Validate conversation binding': fixture.binding,
};
const select = (name) => ({item: {json: nodes[name]}});
const result = new Function('$', fixture.javascript)(select);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({
            "context": context,
            "binding": binding,
            "javascript": _node("Build graph grounded agent request")["parameters"]["jsCode"],
        }),
        text=True, capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


def _run_response_validator(node_name: str, interpretation: dict, graph_contract: dict) -> dict:
    _require_node()
    harness = """
const fs = require('fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {
  'Build graph grounded agent request': {llm_call_started_at: Date.now(), prompt_estimated_tokens: 1, prompt_context_manifest: {}},
  'Build graph repair request': {llm_call_started_at: Date.now(), prompt_estimated_tokens: 1, prompt_context_manifest: {}},
  'Validate agent response': {model_observation: {token_usage: null, interpretation: {}}},
  'Validate conversation binding': {model: 'fixture-model', external_message_id: 'wamid-fixture'},
  'Load published graph context': {graph_contract: fixture.graphContract, retrieval_trace: {}},
  'Reconcile fields with graph policy': {response: {proof: {accepted_facts: []}}},
};
const select = (name) => ({item: {json: nodes[name]}});
const payload = {choices: [{message: {content: JSON.stringify(fixture.interpretation)}}]};
const result = new Function('$', '$json', fixture.javascript)(select, payload);
process.stdout.write(JSON.stringify(result[0].json));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({
            "javascript": _node(node_name)["parameters"]["jsCode"],
            "interpretation": interpretation,
            "graphContract": graph_contract,
        }),
        text=True, capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


def _envelope(**overrides) -> dict:
    envelope = {
        "envelope_version": "3",
        "reply": "Perfeito! O que voce procura hoje?",
        "facts": [],
        "branch_selections": [],
        "confirmation": {
            "state": "none", "target_ref": None, "evidence_span": "",
            "correction_field_key": None, "correction_value": None,
        },
        "customer_questions": [],
        "claims": [],
        "cited_node_ids": [],
        "cited_chunk_ids": [],
        "asked_field_key": None,
        "handoff_requested": False,
    }
    envelope.update(overrides)
    return envelope


def _purchase_profile_contract() -> dict:
    """The shape that actually shipped for Tock Fatal v12/v13."""
    return {
        "branch_anchor_node_id": "audience:tock-retail",
        "fields": [
            {
                "key": "purchase_profile",
                "label": "tipo de compra",
                "owner_node_id": "audience:tock-retail",
                "question_node_id": "faq:tock-purchase-profile",
                "required": True,
                "depends_on": [],
                "validation": {
                    "mode": "enum",
                    "values": [
                        {
                            "value": "uso-proprio-varejo",
                            "aliases": ["uso proprio", "pra mim", "varejo", "comprar para mim"],
                        },
                        {
                            "value": "atacado-revenda",
                            "aliases": ["revenda", "revender", "atacado", "minha loja", "empreender"],
                        },
                    ],
                },
            },
        ],
        "questions": {
            "faq:tock-purchase-profile": {
                "field_key": "purchase_profile",
                "text": "Voce quer ver pra uso proprio ou pra revenda?",
                "depends_on": [],
            },
        },
        "conversation_policy": {},
    }


def _context(**overrides) -> dict:
    context = {
        "persona_slug": "fixture-persona",
        "agent_slug": "fixture-agent",
        "graph_version": 13,
        "graph_checksum": "sha256:fixture",
        "system_prompt": "voz publicada",
        "graph_contract": _purchase_profile_contract(),
        "context_cards": [],
        "rag_chunks": [],
        "cart": {"asked_question_node_ids": [], "facts_by_key": {}},
        "messages": [],
        "shared_memory": {},
        "retrieval_trace": {},
        "active_branch_node_id": None,
        "active_branch_node_ids": [],
    }
    context.update(overrides)
    return context


def _binding(**overrides) -> dict:
    binding = {
        "message": "Proprio",
        "external_message_id": "wamid-209",
        "model": "fixture-model",
        "origin_ref": None,
    }
    binding.update(overrides)
    return binding


# --------------------------------------------------------------------------
# Defect 1 -- the closed alias list froze the model
# --------------------------------------------------------------------------


def test_prompt_never_tells_the_model_to_normalize_by_alias_list():
    """The exact wording that made lead 209 emit no fact at all.

    "Proprio" is not in `purchase_profile`'s aliases, so an instruction to
    "normalize it with that field validation aliases" is an instruction to
    stay silent -- and a silent fact means no branch, and no branch means the
    other brand's prices reach the customer. Reintroducing any alias-driven
    normalization rule must fail here.
    """
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]

    assert "normalize it with that field validation aliases" not in initial
    assert "normalize it with that field validation aliases" not in json.dumps(WORKFLOW)


def test_prompt_asks_for_semantic_classification_against_canonical_values():
    _require_node()
    result = _run_prompt_builder(_context(), _binding())
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    # The canonical value is the target, and the model must emit it verbatim.
    assert "validation.values" in instructions
    assert "canonical value" in instructions
    # The aliases are examples of phrasing, explicitly not a filter.
    assert "not a closed list" in instructions
    assert "examples" in instructions
    # A short/misspelled/unaccented answer such as "Proprio" still counts.
    for word in ("one-word", "misspelled", "unaccented", "paraphrased"):
        assert word in instructions, word
    # Ambiguity is asked about, never guessed -- and never silently dropped.
    assert "emit no fact for that field and ask one short question" in instructions
    assert "do not guess" in instructions
    # evidence_span stays literal; canonicalizing a value is not a licence.
    assert "character for character" in instructions

    # The model can only classify if the published values actually reach it.
    field = next(
        item for item in prompt["graph_contract"]["fields"]
        if item["key"] == "purchase_profile"
    )
    assert field["validation"]["mode"] == "enum"
    assert [value["value"] for value in field["validation"]["values"]] == [
        "uso-proprio-varejo", "atacado-revenda",
    ]


def test_branch_selection_instruction_does_not_depend_on_literal_matching():
    """Branch selection is the same classification problem as the fact.

    Selecting on "the customer answers the selection field" left the model
    free to fall back to text matching, which is the failure that let the
    branch stay null while the reply said "uso proprio".
    """
    _require_node()
    result = _run_prompt_builder(_context(), _binding())
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    assert "classify the answer to the selection field the same semantic way" in instructions
    assert "never has to name the branch or repeat a published term" in instructions
    # The origin shortcut must survive the rewrite.
    assert "policy.rules.branch_selection.origin_binding" in instructions


# --------------------------------------------------------------------------
# Defect 2 -- next_question_node_id, and who is allowed to resolve it
# --------------------------------------------------------------------------


@pytest.mark.parametrize("node_name", VALIDATOR_NODES)
def test_validator_leaves_question_resolution_to_the_runtime(node_name):
    """The null is real but it is not the whole story, and the fix is not here.

    `graph_agent_runtime_v3._decide` already converts asked_field_key into a
    question node id -- `if asked_field_key and not
    proposal.next_question_node_id` -- using the contract it builds for the
    branch THIS proposal selects. `/internal/v1/conversations/decide`, the
    endpoint both reconcile nodes call, goes straight through it.

    This node can only see `context.graph_contract`, fixed before the model
    answered. When the two contracts name different question nodes for the
    same field key -- two branches each publishing their own copy of the
    selection question, the alphabetical accident that qualified retail
    customers inside the wholesale branch -- a local resolver sends the wrong
    id. And any non-null value, right or wrong, switches the runtime rescue
    off, because that is its guard. A second resolver here can tie with the
    runtime or lose to it; it can never win. So: one resolver, in the place
    that knows the branch.
    """
    code = _node(node_name)["parameters"]["jsCode"]

    assert "next_question_node_id: null" in code
    # No local resolver, under any name.
    assert "graphContract.questions" not in code
    assert "question_node_id" not in code.replace("next_question_node_id", "")
    # And the reason is written where the null is, not only in a commit.
    assert "graph_agent_runtime_v3._decide" in code
    assert "One resolver," in code


@pytest.mark.parametrize("node_name", VALIDATOR_NODES)
def test_validator_forwards_asked_field_key_untouched(node_name):
    """Whatever the runtime resolves, it resolves from this. If the key stops
    arriving, the rescue has nothing to work with and the null becomes the
    fatal one it was first reported to be."""
    result = _run_response_validator(
        node_name,
        _envelope(asked_field_key="purchase_profile"),
        _purchase_profile_contract(),
    )

    interpretation = result["model_observation"]["interpretation"]
    assert interpretation["asked_field_key"] == "purchase_profile"
    assert result["model_observation"]["proposal"]["next_question_node_id"] is None


def test_prompt_does_not_replace_eligible_qualification_with_consultative_question():
    result = _run_prompt_builder(_context(), _binding())
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    assert "any question you choose to advance the conversation" in instructions
    assert "exactly one of those eligible fields" in instructions
    assert "asked_field_key must name it" in instructions
    assert "untracked product-selection or consultative question" in instructions


def test_prompt_does_not_repeat_pending_name_after_branch_switch():
    context = _context(
        cart={
            "asked_question_node_ids": ["faq:tock-customer-name"],
            "asked_field_keys": ["nome_cliente"],
            "facts_by_key": {},
        },
    )
    result = _run_prompt_builder(
        context, _binding(message="Na verdade, e para uso proprio."),
    )
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    assert prompt["asked_field_keys"] == ["nome_cliente"]
    assert prompt["expected_answer_field_key"] == "nome_cliente"
    assert "changes branch" in instructions
    assert "without asking the pending field again" in instructions
    assert "Ask no question unless a different eligible field has never been asked" in instructions


def test_prompt_uses_published_confirmation_then_announced_handoff():
    contract = _purchase_profile_contract()
    contract["conversation_policy"] = {
        "qualification": {
            "confirmation_question": "As informacoes estao corretas?",
            "completion_message": "Perfeito. A equipe continua o atendimento.",
        },
        "handoff": {
            "pre_notice_required": True,
            "notice": "Vou avisar uma pessoa da equipe para continuar com voce.",
        },
    }
    context = _context(
        graph_contract=contract,
        pending_confirmation_ref="qualification:current:7",
    )
    result = _run_prompt_builder(context, _binding(message="Sim"))
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    assert prompt["pending_confirmation_ref"] == "qualification:current:7"
    assert "qualification completes on this turn" in instructions
    assert "Do not ask a catalog, product-detail or consultative question" in instructions
    assert "confirmation.target_ref exactly to pending_confirmation_ref" in instructions
    assert "handoff_requested=true" in instructions
    assert "without another question" in instructions


@pytest.mark.parametrize("node_name", VALIDATOR_NODES)
def test_validator_documents_prompt_owned_consultative_question_boundary(node_name):
    code = _node(node_name)["parameters"]["jsCode"]

    assert "prevents an untracked consultative question" in code
    assert "branch-aware runtime" in code


@pytest.mark.parametrize("node_name", VALIDATOR_NODES)
def test_interaction_observation_is_fixed_on_purpose_and_says_so(node_name):
    """Envelope v3 is additionalProperties:false and declares no
    interaction_observation, so there is nothing to forward. Anyone reading
    the fixed object must find the reason next to it instead of filing a bug."""
    code = _node(node_name)["parameters"]["jsCode"]
    request = _node("Build graph grounded agent request")["parameters"]["jsCode"]

    assert "interaction_observation: { kind: 'unclear', evidence_span: '', confidence: 0 }" in code
    assert "Envelope v3 does not declare the key" in code
    assert "interaction_observation" not in request


# --------------------------------------------------------------------------
# Defect 3 -- reported as "approved_chunks always empty"; it is not
# --------------------------------------------------------------------------


def test_published_rag_chunks_reach_the_prompt_as_approved_chunks():
    """`const approvedChunks = [];` is an initializer, not the whole story: the
    loop three lines below fills it from `context.rag_chunks`. Pinned here so
    the report cannot quietly become true, and so the boundary the prompt
    promises ("approved_nodes and approved_chunks already exclude every other
    branch") keeps existing."""
    _require_node()
    chunks = [
        {
            "chunk_id": "chunk-retail-1",
            "source_node_id": "faq:tock-retail-entry",
            "chunk_kind": "faq",
            "chunk_text": "Na loja de varejo a peca sai por R$ 99,90.",
            "chunk_checksum": "sha256:retail",
            "path_checksum": "sha256:path-retail",
            "metadata": {"provenance": {"source": "published_graph", "status": "validated"}},
        },
        {
            "chunk_id": "chunk-retail-2",
            "source_node_id": "faq:tock-retail-entry",
            "chunk_kind": "faq",
            "chunk_text": "A porta de entrada do varejo comeca em 1 peca.",
            "chunk_checksum": "sha256:retail-2",
            "path_checksum": "sha256:path-retail",
            "metadata": {"provenance": {}},
        },
    ]
    result = _run_prompt_builder(_context(rag_chunks=chunks), _binding())
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    manifest = result["prompt_context_manifest"]

    assert [chunk["chunk_id"] for chunk in prompt["approved_chunks"]] == [
        "chunk-retail-1", "chunk-retail-2",
    ]
    assert prompt["approved_chunks"][0]["text"] == chunks[0]["chunk_text"]
    assert prompt["approved_chunks"][0]["source_node_id"] == "faq:tock-retail-entry"
    assert prompt["approved_chunks"][0]["checksum"] == "sha256:retail"
    assert prompt["approved_chunks"][0]["provenance"]["status"] == "validated"

    # The manifest must account for what was retained, never silently.
    assert manifest["retained_chunk_count"] == 2
    assert manifest["retained_rag_tokens"] > 0
    assert manifest["removed_context"] == []
    assert manifest["token_limits"] == "provider_managed"


def test_prompt_only_claims_a_boundary_it_actually_ships():
    """The instruction leans on approved_chunks as a real fence. If a future
    change stops shipping chunks, the sentence has to go with it."""
    initial = _node("Build graph grounded agent request")["parameters"]["jsCode"]

    claims_boundary = "approved_nodes and approved_chunks already exclude every other branch" in initial
    ships_chunks = (
        "for (const chunk of (context.rag_chunks || []))" in initial
        and "approvedChunks.push(compact)" in initial
        and "approved_chunks: approvedChunks" in initial
    )
    assert claims_boundary is ships_chunks, (
        "the prompt promises a branch boundary built from approved_chunks; "
        "either keep populating them from context.rag_chunks or drop the claim"
    )


def test_prompt_marks_first_assistant_turn_and_requires_one_ai_introduction():
    first = _run_prompt_builder(_context(messages=[]), _binding())
    first_prompt = json.loads(first["request_body"]["messages"][1]["content"])
    assert first_prompt["is_first_assistant_turn"] is True

    later = _run_prompt_builder(
        _context(messages=[{"role": "assistant", "content": "Oi, eu sou a assistente virtual."}]),
        _binding(),
    )
    later_prompt = json.loads(later["request_body"]["messages"][1]["content"])
    assert later_prompt["is_first_assistant_turn"] is False

    instructions = " ".join(first_prompt["policy"]["instructions"])
    assert "introduce yourself once" in instructions
    assert "AI/virtual assistant" in instructions
    assert "Never repeat that introduction" in instructions


def test_prompt_owns_sales_language_media_and_pre_handoff_notice():
    result = _run_prompt_builder(_context(), _binding())
    prompt = json.loads(result["request_body"]["messages"][1]["content"])
    instructions = " ".join(prompt["policy"]["instructions"])

    assert "product group or service when the graph business model is sales" in instructions
    assert "asked_field_key must be that exact field key" in instructions
    assert "approved image for the exact product" in instructions
    assert "do not mention photos unless the customer explicitly asks" in instructions
    assert "freight cost and delivery timing as specialist-confirmed" in instructions
    assert "A conversational handoff is never silent" in instructions


def test_repair_prompt_prefers_announced_handoff_over_silence():
    code = _node("Build graph repair request")["parameters"]["jsCode"]
    assert "published customer-facing pre-handoff notice" in code
    assert "never hand off silently" in code
