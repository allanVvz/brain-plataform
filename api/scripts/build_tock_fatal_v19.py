"""Build Tock Fatal v19: keep the one-time name question non-blocking.

The v18 graph lets the conversation advance after an interrupted name, but
still marks ``nome_cliente`` as required. After every other sales field is
known, that leaves qualification incomplete while the one-attempt policy
correctly forbids asking the name again.

This content-only patch keeps the published name question, its first priority,
and the one-attempt limit, while making the field optional for completion. It
never publishes or activates anything.

Usage:
    python api/scripts/build_tock_fatal_v19.py <v18-bundle> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


BASELINE_PURPOSE = "tock_fatal_v18_nonblocking_name_once"
PERSONA = "persona:tock-fatal"
SOURCE = "wa_validator_optional_name_completion_2026-09-06"


def _nodes(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in bundle.get("nodes") or []}


def build(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") or {}
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(
            f"expected baseline purpose {BASELINE_PURPOSE!r}, "
            f"got {metadata.get('purpose')!r}"
        )

    candidate = copy.deepcopy(source)
    nodes = _nodes(candidate)
    if PERSONA not in nodes:
        raise ValueError(f"baseline is missing required node: {PERSONA}")

    persona_data = nodes[PERSONA].setdefault("data", {})
    qualification = persona_data.get("qualification") or {}
    fields = {
        str(field.get("key")): field
        for field in qualification.get("fields") or []
    }
    name_field = fields.get("nome_cliente")
    if not name_field:
        raise ValueError("baseline is missing nome_cliente")
    if name_field.get("required") is not True:
        raise ValueError("baseline nome_cliente is not required as expected")

    name_field["required"] = False

    conversation_policy = persona_data.setdefault("conversation_policy", {})
    question_policy = conversation_policy.setdefault("question_policy", {})
    question_policy.update({
        "name_is_preferred_optional_once": True,
        "unanswered_name_does_not_block_completion": True,
    })
    instructions = list(question_policy.get("instructions") or [])
    instructions.append(
        "Pergunte o nome somente uma vez e preserve a resposta quando houver; "
        "se a pessoa não responder, continue sem insistir e não deixe a ausência "
        "do nome bloquear a confirmação final nem o handoff anunciado."
    )
    question_policy["instructions"] = instructions

    candidate["metadata"] = {
        **metadata,
        "purpose": "tock_fatal_v19_optional_name_once",
        "content_revision": "3.8-optional-name-once",
        "source": SOURCE,
        "publication_allowed": True,
        "change_summary": (
            "Mantém a pergunta de nome como primeira preferência e limitada a "
            "uma tentativa, mas torna a resposta opcional para concluir a "
            "qualificação quando a pessoa decide não respondê-la."
        ),
        "conversation_regressions": [
            *(metadata.get("conversation_regressions") or []),
            "unanswered_name_does_not_block_confirmation_or_handoff",
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
