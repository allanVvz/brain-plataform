"""Build Tock Fatal v18: let qualification continue after an interrupted name.

The v17 graph asks ``nome_cliente`` first and allows it to be asked only once.
It also made every later qualification field depend on that answer.  When a
customer changed purchase profile instead of answering the name question, the
no-repeat rule and those dependencies formed a deadlock: repeating the name
was forbidden and no other question was eligible.

This content-only patch keeps the name as the preferred first question, keeps
the one-attempt limit, and removes only ``nome_cliente`` as a hard dependency
of later fields.  Existing branch-local ordering remains intact.  It never
publishes or activates anything.

Usage:
    python api/scripts/build_tock_fatal_v18.py <v17-bundle> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


BASELINE_PURPOSE = "tock_fatal_v17_sales_conversation_repair"
PERSONA = "persona:tock-fatal"
SOURCE = "wa_validator_branch_switch_name_interruption_2026-09-06"


def _nodes(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in bundle.get("nodes") or []}


def _without_name_dependency(field: dict[str, Any]) -> None:
    field["depends_on"] = [
        str(value)
        for value in field.get("depends_on") or []
        if str(value) != "nome_cliente"
    ]


def build(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") or {}
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(
            f"expected baseline purpose {BASELINE_PURPOSE!r}, "
            f"got {metadata.get('purpose')!r}"
        )

    candidate = copy.deepcopy(source)
    nodes = _nodes(candidate)
    required_nodes = {
        PERSONA,
        "audience:tock-retail",
        "audience:tock-reseller",
    }
    missing = sorted(required_nodes - set(nodes))
    if missing:
        raise ValueError(f"baseline is missing required nodes: {missing}")

    persona = nodes[PERSONA]
    persona_data = persona.setdefault("data", {})
    qualification = persona_data.get("qualification") or {}
    persona_fields = {
        str(field.get("key")): field
        for field in qualification.get("fields") or []
    }
    expected_persona_fields = {
        "nome_cliente",
        "grau_qualificacao",
        "forma_recebimento",
    }
    if not expected_persona_fields <= set(persona_fields):
        raise ValueError("baseline is missing the v17 persona qualification fields")

    # The name itself still follows purchase_profile and remains the preferred
    # first question.  Only later questions stop treating an unanswered name
    # as a hard gate.
    for key in ("grau_qualificacao", "forma_recebimento"):
        _without_name_dependency(persona_fields[key])

    for anchor in ("audience:tock-retail", "audience:tock-reseller"):
        branch_qualification = (
            nodes[anchor].setdefault("data", {}).get("qualification") or {}
        )
        for field in branch_qualification.get("fields") or []:
            if field.get("key") != "purchase_profile":
                _without_name_dependency(field)

    conversation_policy = persona_data.setdefault("conversation_policy", {})
    question_policy = conversation_policy.setdefault("question_policy", {})
    question_policy.update({
        "after_purchase_profile_when_name_missing": (
            "ask_nome_cliente_first_if_never_asked_then_continue_with_other_eligible_fields"
        ),
        "after_interrupted_name_question": (
            "do_not_repeat_name_continue_with_other_eligible_fields"
        ),
        "name_is_preferred_not_dependency_gate": True,
    })
    instructions = list(question_policy.get("instructions") or [])
    instructions.append(
        "Se a pergunta do nome for interrompida por uma correção de perfil ou "
        "outra informação, não repita o nome; reconheça a mudança e avance "
        "delicadamente com outro campo elegível."
    )
    instructions.append(
        "O nome continua sendo a primeira pergunta preferida, mas uma resposta "
        "ainda ausente não bloqueia grau de qualificação, envio ou visita nem "
        "as perguntas próprias do perfil escolhido."
    )
    question_policy["instructions"] = instructions

    candidate["metadata"] = {
        **metadata,
        "purpose": "tock_fatal_v18_nonblocking_name_once",
        "content_revision": "3.7-nonblocking-name-once",
        "source": SOURCE,
        "publication_allowed": True,
        "change_summary": (
            "Mantém o nome como primeira pergunta e limita a uma tentativa, "
            "mas permite avançar por campos elegíveis quando essa pergunta é "
            "interrompida por uma troca de perfil."
        ),
        "conversation_regressions": [
            *(metadata.get("conversation_regressions") or []),
            "branch_switch_advances_without_repeating_name",
        ],
    }
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    candidate = build(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}")
    print(f"  nodes {len(source['nodes'])} -> {len(candidate['nodes'])}")
    print(f"  edges {len(source['edges'])} -> {len(candidate['edges'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
