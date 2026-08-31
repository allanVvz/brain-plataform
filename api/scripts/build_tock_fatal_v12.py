from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


BASELINE_PUBLICATION = {
    "version": 11,
    "checksum": "sha256:e139c1370211ae59abe1624501addea6b22c9222c3d66a5964c67ce9a9a5dc65",
}
EXPECTED_BASELINE_PURPOSE = "tock_fatal_v11_full_catalog_product_media"
POLICY_SOURCE = "operator_conversation_unification_plan_2026-08-31"
PRESERVED_CONTENT_SHA256 = "e41d00fe5bb7bbe3d36f0be7a528dc6da8b6d274d095ebd71f37683685a083ef"
PRESERVED_EDGES_SHA256 = "9be24719adc32c24439683aae69daa549796eb954e63a5f549833b31db90ac1c"
PRESERVED_RULES_SHA256 = "06c16d190d543394c010cbc15904115fb2644864a3aae4b0c858da0426f1699b"


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _node(bundle: dict[str, Any], node_id: str) -> dict[str, Any]:
    matches = [node for node in bundle.get("nodes") or [] if node.get("id") == node_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one node {node_id!r}; found {len(matches)}")
    return matches[0]


def _assert_v11_baseline(bundle: dict[str, Any]) -> None:
    if (bundle.get("persona") or {}).get("slug") != "tock-fatal":
        raise ValueError("the baseline is not the Tock Fatal bundle")
    metadata = bundle.get("metadata") or {}
    if metadata.get("purpose") != EXPECTED_BASELINE_PURPOSE:
        raise ValueError("the input is not the approved v11 full-catalog baseline")
    if len(bundle.get("nodes") or []) != 1001 or len(bundle.get("edges") or []) != 1904:
        raise ValueError("the v11 baseline topology does not match the audited publication source")

    nodes = bundle.get("nodes") or []
    edges = bundle.get("edges") or []
    preserved_content = [
        node for node in nodes if node.get("node_type") not in {"persona", "tone", "rule"}
    ]
    preserved_rules = [node for node in nodes if node.get("node_type") == "rule"]
    if _sha256(preserved_content) != PRESERVED_CONTENT_SHA256:
        raise ValueError("the catalog/content fingerprint does not match the audited v11 source")
    if _sha256(edges) != PRESERVED_EDGES_SHA256:
        raise ValueError("the edge fingerprint does not match the audited v11 source")
    if _sha256(preserved_rules) != PRESERVED_RULES_SHA256:
        raise ValueError("the commercial-rule fingerprint does not match the audited v11 source")
    faq_ids = {node["id"] for node in nodes if node.get("node_type") == "faq"}
    embed_ids = {
        node["id"] for node in nodes if node.get("node_type") in {"embed", "embedded"}
    }
    projected_faq_ids = {
        edge.get("source")
        for edge in edges
        if edge.get("relation_type") == "publishes_to"
        and edge.get("target") in embed_ids
    }
    if len(faq_ids) != 605 or not faq_ids <= projected_faq_ids:
        raise ValueError("the v11 FAQ/Embedded coverage audit no longer matches")
    if any(not (node.get("data") or {}).get("source") for node in nodes if node.get("id") in faq_ids):
        raise ValueError("the v11 baseline contains a FAQ without an approved source")


def build(source: dict[str, Any]) -> dict[str, Any]:
    _assert_v11_baseline(source)
    candidate = copy.deepcopy(source)

    metadata = candidate.setdefault("metadata", {})
    metadata.update(
        {
            "purpose": "tock_fatal_v12_model_owned_conversation",
            "content_revision": "3.1-model-owned-conversation",
            "baseline_publication": BASELINE_PUBLICATION,
            "policy_source": POLICY_SOURCE,
            "preserved_v11_fingerprints": {
                "catalog_content_sha256": PRESERVED_CONTENT_SHA256,
                "edges_sha256": PRESERVED_EDGES_SHA256,
                "rules_sha256": PRESERVED_RULES_SHA256,
            },
            "faq_coverage_audit": {
                "faq_count": 605,
                "product_group_navigation_faq_count": 7,
                "all_faqs_have_source": True,
                "all_faqs_projected_to_embedded": True,
                "new_faqs_added": 0,
            },
        }
    )

    persona = _node(candidate, "persona:tock-fatal")
    persona_data = persona.setdefault("data", {})
    policy = persona_data.setdefault("conversation_policy", {})
    policy.update(
        {
            "response_ownership": {
                "mode": "model",
                "answer_and_explain_before_qualification": True,
                "deterministic_validator": "advisory",
            },
            "opening": {
                "respond_to_current_content_first": True,
                "customer_name_required_before_help": False,
                "request_customer_name": "naturally_after_intent_is_understood",
            },
            "question_policy": {
                "max_useful_questions_per_reply": 1,
                "force_question": False,
                "force_question_on": [],
                "suppress_when": [
                    "greeting",
                    "playful_message",
                    "acknowledgement",
                    "customer_doubt",
                ],
                "selection": "model_natural_from_eligible_graph_fields",
            },
            "catalog_discovery": {
                "allow_before_purchase_profile": True,
                "retrieve_product_groups_and_faqs": True,
                "purchase_profile_required_only_for_channel_specific_claims": True,
            },
            "explicit_unknown_only": True,
        }
    )
    qualification = policy.setdefault("qualification", {})
    qualification.update(
        {
            "next_question_selection": "model_natural_from_eligible_graph_fields",
            "max_questions_per_reply": 1,
            "question_required": False,
        }
    )
    persona_data["source"] = POLICY_SOURCE

    tone = _node(candidate, "tone:tock-vitoria-voice")
    tone_data = tone.setdefault("data", {})
    voice = tone_data.setdefault("voice", {})
    voice["guidelines"] = [
        "Responda primeiro ao conteúdo que a pessoa trouxe.",
        "Use frases curtas e palavras comuns.",
        "Converse com naturalidade e não transforme a conversa em formulário.",
        "Faça no máximo uma pergunta útil por resposta e somente quando ela ajudar.",
        "Não force pergunta em saudação, brincadeira, confirmação ou dúvida.",
        "Peça o nome naturalmente depois de entender a intenção; o nome não bloqueia ajuda inicial.",
        "Reconheça mudanças de preferência sem narrar o que foi alterado.",
    ]
    tone_data["source"] = POLICY_SOURCE

    clear_tone = _node(candidate, "tone:tock-vitoria-clear-language")
    clear_data = clear_tone.setdefault("data", {})
    clear_data["guidelines"] = [
        "Explique ou responda antes de qualificar.",
        "Pergunte somente o próximo assunto útil escolhido naturalmente pelo modelo.",
        "Não descreva mudanças feitas por trás do atendimento.",
        "Quando a pessoa mudar de ideia, acolha a nova escolha e siga sem repetir pergunta conhecida.",
    ]
    clear_data["source"] = POLICY_SOURCE

    # The content release changes only Persona/Tone policy plus bundle metadata.
    # Catalog nodes, facts, offers, FAQs, assets and every edge remain untouched.
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Tock Fatal v12 GraphBundle from the audited production v11 source."
    )
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
