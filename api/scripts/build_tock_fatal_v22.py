"""Build Tock Fatal v22: persist acknowledged retail answers before replying."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

BASELINE_PURPOSE = "tock_fatal_v21_confirmation_then_handoff"
PERSONA = "persona:tock-fatal"


def build(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") or {}
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(f"unexpected baseline purpose: {metadata.get('purpose')!r}")
    candidate = copy.deepcopy(source)
    nodes = {str(node["id"]): node for node in candidate.get("nodes") or []}
    persona = nodes[PERSONA]["data"]
    for node in nodes.values():
        for field in (node.get("data", {}).get("qualification") or {}).get("fields") or []:
            if field.get("key") in {"retail_need", "retail_style"}:
                validation = field.setdefault("validation", {})
                validation["extraction_required_when_expected"] = True
                validation["acknowledgement_requires_fact"] = True
    policy = persona.setdefault("conversation_policy", {})
    policy.setdefault("instructions", []).extend([
        "Antes de responder, extraia e persista todo dado que responda ao campo perguntado no turno anterior.",
        "Se reconhecer na resposta uma necessidade ou estilo informado pela pessoa, inclua obrigatoriamente o mesmo campo em facts; nunca apenas repita o dado na fala.",
    ])
    candidate["metadata"] = {
        **metadata,
        "purpose": "tock_fatal_v22_persist_acknowledged_retail_facts",
        "content_revision": "4.1-persist-acknowledged-retail-facts",
        "source": "wa_validator_retail_fact_persistence_2026-09-06",
        "publication_allowed": True,
        "change_summary": "Exige persistencia da necessidade e do estilo de varejo antes da resposta.",
        "conversation_regressions": list(dict.fromkeys([
            *(metadata.get("conversation_regressions") or []),
            "acknowledged_retail_answer_is_persisted",
        ])),
    }
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(json.loads(args.source.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
