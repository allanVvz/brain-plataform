"""Build Tock Fatal v20: author the optional customer name as collect-once.

The v19 content correctly made ``nome_cliente`` non-blocking, but it did not
declare that this optional field is still a legitimate one-time question. The
runtime therefore discarded its question pointer even while preserving the
model's natural reply.

This content-only patch adds the generic ``ask_once_optional`` collection mode.
It never publishes or activates anything.

Usage:
    python api/scripts/build_tock_fatal_v20.py <v19-bundle> <output>
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


BASELINE_PURPOSE = "tock_fatal_v19_optional_name_once"
PERSONA = "persona:tock-fatal"
SOURCE = "wa_validator_optional_name_collect_once_2026-09-06"


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
    persona_data = nodes[PERSONA].setdefault("data", {})
    fields = {
        str(field.get("key")): field
        for field in (persona_data.get("qualification") or {}).get("fields") or []
    }
    name_field = fields.get("nome_cliente")
    if not name_field or name_field.get("required") is not False:
        raise ValueError("baseline must contain optional nome_cliente")
    name_field["collection_mode"] = "ask_once_optional"

    question_policy = persona_data.setdefault("conversation_policy", {}).setdefault(
        "question_policy", {}
    )
    question_policy.update({
        "name_is_authored_collect_once": True,
        "optional_collection_does_not_change_completion": True,
    })

    candidate["metadata"] = {
        **metadata,
        "purpose": "tock_fatal_v20_optional_name_collect_once",
        "content_revision": "3.9-optional-name-collect-once",
        "source": SOURCE,
        "publication_allowed": True,
        "change_summary": (
            "Declara nome_cliente como pergunta opcional de coleta unica: deve "
            "ser perguntada no inicio, registrada no ledger e nunca repetida, "
            "sem bloquear confirmacao ou handoff quando nao respondida."
        ),
        "conversation_regressions": list(dict.fromkeys([
            *(metadata.get("conversation_regressions") or []),
            "optional_name_question_is_recorded_once",
        ])),
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
