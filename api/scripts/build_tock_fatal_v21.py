"""Build Tock Fatal v21: make confirmation and handoff sequence explicit.

Content-only transform. It does not publish or activate anything.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


BASELINE_PURPOSE = "tock_fatal_v20_optional_name_collect_once"
PERSONA = "persona:tock-fatal"
HANDOFF_RULE = "rule:tock-safe-handoff"
SOURCE = "wa_validator_confirmation_handoff_2026-09-06"


def _nodes(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in bundle.get("nodes") or []}


def build(source: dict[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata") or {}
    if metadata.get("purpose") != BASELINE_PURPOSE:
        raise ValueError(f"unexpected baseline purpose: {metadata.get('purpose')!r}")

    candidate = copy.deepcopy(source)
    nodes = _nodes(candidate)
    policy = nodes[PERSONA].setdefault("data", {}).setdefault(
        "conversation_policy", {}
    )
    policy["confirmation_and_handoff"] = {
        "when_required_fields_become_complete": (
            "Na mesma resposta, resuma naturalmente os dados coletados e pergunte "
            "se estao corretos. Nao encerre apenas dizendo que registrou."
        ),
        "when_customer_confirms_summary": (
            "Reconheca a confirmacao e avise claramente, antes de encaminhar, que "
            "uma pessoa da equipe continuara o atendimento. Nao repita a resposta "
            "anterior nem faca outra pergunta de qualificacao."
        ),
        "handoff_pre_notice_required": True,
        "silent_handoff_forbidden": True,
    }
    policy.setdefault("instructions", []).extend([
        "Quando o ultimo campo obrigatorio for informado, faca o resumo completo e peça confirmacao na mesma resposta.",
        "Quando a pessoa confirmar o resumo, reconheca e avise antes que uma pessoa da equipe continuara o atendimento.",
        "Nunca repita a mensagem de registro do ultimo campo depois de uma confirmacao.",
    ])

    rule = nodes[HANDOFF_RULE].setdefault("data", {}).setdefault("handoff_rule", {})
    rule["condition"] = "qualification_complete"
    rule["pre_notice_required"] = True
    rule["silent_handoff_forbidden"] = True

    candidate["metadata"] = {
        **metadata,
        "purpose": "tock_fatal_v21_confirmation_then_handoff",
        "content_revision": "4.0-confirmation-then-handoff",
        "source": SOURCE,
        "publication_allowed": True,
        "change_summary": (
            "Exige resumo e confirmacao ao completar a qualificacao, seguido de "
            "aviso previo de handoff apos confirmacao do cliente."
        ),
        "conversation_regressions": list(dict.fromkeys([
            *(metadata.get("conversation_regressions") or []),
            "last_required_field_triggers_summary_confirmation",
            "confirmed_summary_triggers_handoff_pre_notice",
            "confirmation_does_not_repeat_previous_reply",
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
    args.output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
