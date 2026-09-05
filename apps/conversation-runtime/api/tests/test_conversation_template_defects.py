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


