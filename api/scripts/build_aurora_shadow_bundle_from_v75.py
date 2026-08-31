from __future__ import annotations

import argparse
import copy
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


ACTIVE_V75_CHECKSUM = "sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec"
EXPECTED_COUNTS = {"nodes": 140, "edges": 274, "branch_contracts": 14, "chunks": 551}
POLICY_SOURCE = "operator_conversation_unification_plan_2026-08-31"
REMOVED_POLICY_KEYS = {
    "ask_order",
    "forced_question",
    "forced_question_sequence",
    "mandatory_question",
    "mandatory_question_sequence",
    "qualification_sequence",
    "rigid_question_sequence",
}


def _plain(value: Any) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value or "").lower())
        if not unicodedata.combining(character)
    )


def _without_legacy_rigidity(value: Any, removed: list[str], path: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in REMOVED_POLICY_KEYS:
                removed.append(child_path)
                continue
            result[key] = _without_legacy_rigidity(child, removed, child_path)
        return result
    if isinstance(value, list):
        result = []
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            if isinstance(child, str) and "quem pergunta controla" in _plain(child):
                removed.append(child_path)
                continue
            result.append(_without_legacy_rigidity(child, removed, child_path))
        return result
    if isinstance(value, str) and "quem pergunta controla" in _plain(value):
        removed.append(path)
        return ""
    return copy.deepcopy(value)


def _canonical_checksum(value: Any) -> str:
    from services.graph_compiler_v3 import canonical_checksum

    return canonical_checksum(value)


def _read_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    publication = snapshot.get("publication")
    document = snapshot.get("document")
    if not isinstance(publication, dict) or not isinstance(document, dict):
        raise ValueError("snapshot must contain publication and document objects")

    version = int(publication.get("version") or 0)
    checksum = str(publication.get("checksum") or "")
    if version != 75 or checksum != ACTIVE_V75_CHECKSUM:
        raise ValueError("snapshot is not the audited active Aurora v75 publication")
    if str(document.get("checksum") or "") != checksum:
        raise ValueError("publication/document checksum mismatch")
    checksum_payload = copy.deepcopy(document)
    checksum_payload.pop("checksum", None)
    if _canonical_checksum(checksum_payload) != checksum:
        raise ValueError("document bytes do not reproduce the audited v75 checksum")

    branch_contracts = document.get("branch_contracts") or {}
    actual_counts = {
        "nodes": len(document.get("nodes") or []),
        "edges": len(document.get("edges") or []),
        "branch_contracts": len(branch_contracts),
        "chunks": int(snapshot.get("chunk_count") or len(snapshot.get("chunks") or [])),
    }
    if actual_counts != EXPECTED_COUNTS:
        raise ValueError(f"Aurora v75 count mismatch: {actual_counts!r}")
    return publication, document


def build(snapshot: dict[str, Any]) -> dict[str, Any]:
    publication, document = _read_snapshot(snapshot)
    embedding_profile = snapshot.get("embedding_profile")
    if not isinstance(embedding_profile, dict):
        raise ValueError("snapshot must include the v75 embedding_profile")

    nodes = copy.deepcopy(document.get("nodes") or [])
    edges = copy.deepcopy(document.get("edges") or [])
    allowed_types = {"persona", "tone", "rule"}
    policy_nodes = [node for node in nodes if node.get("node_type") in allowed_types]
    persona_nodes = [node for node in policy_nodes if node.get("node_type") == "persona"]
    tone_nodes = [node for node in policy_nodes if node.get("node_type") == "tone"]
    rule_nodes = [node for node in policy_nodes if node.get("node_type") == "rule"]
    if len(persona_nodes) != 1 or not tone_nodes or not rule_nodes:
        raise ValueError("v75 must expose one Persona plus Tone and Rule nodes")

    before_non_policy = {
        node["id"]: copy.deepcopy(node)
        for node in nodes
        if node.get("node_type") not in allowed_types
    }
    removed: list[str] = []
    for node in policy_nodes:
        node["data"] = _without_legacy_rigidity(
            node.get("data") or {}, removed, f"nodes.{node.get('id')}.data"
        )

    persona = persona_nodes[0]
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
                "suppress_when": [
                    "greeting",
                    "playful_message",
                    "acknowledgement",
                    "customer_doubt",
                ],
                "selection": "model_natural_from_eligible_graph_fields",
            },
            "qualification": {
                **(policy.get("qualification") or {}),
                "next_question_selection": "model_natural_from_eligible_graph_fields",
                "max_questions_per_reply": 1,
                "question_required": False,
            },
        }
    )
    persona_data["conversation_policy_revision"] = {
        "source": POLICY_SOURCE,
        "baseline_version": 75,
    }

    tone_guidelines = [
        "Responda e explique antes de qualificar.",
        "Faça no máximo uma pergunta útil por resposta e somente quando ela ajudar.",
        "Não force pergunta em saudação, brincadeira, confirmação ou dúvida.",
        "Peça o nome naturalmente depois de entender a intenção.",
        "Não use travessão, meia-risca ou hífen como pausa de fala; prefira ponto ou vírgula.",
    ]
    for node in tone_nodes:
        data = node.setdefault("data", {})
        guidelines = list(data.get("guidelines") or [])
        data["guidelines"] = list(dict.fromkeys([*guidelines, *tone_guidelines]))
        data["conversation_policy_revision"] = POLICY_SOURCE

    rule = sorted(rule_nodes, key=lambda item: str(item.get("id") or ""))[0]
    rule_data = rule.setdefault("data", {})
    rule_data["model_conversation_policy"] = {
        "source": POLICY_SOURCE,
        "reply_before_qualification": True,
        "max_useful_questions_per_reply": 1,
        "forced_question": False,
        "speech_pause_punctuation": [".", ","],
        "forbidden_speech_pause_characters": ["—", "–", "-"],
        "production_enforcement": "telemetry_only",
    }

    after_non_policy = {
        node["id"]: node
        for node in nodes
        if node.get("node_type") not in allowed_types
    }
    if before_non_policy != after_non_policy:
        raise AssertionError("Aurora migration changed a non Persona/Tone/Rule node")

    return {
        "bundle_version": "1.0",
        "persona": {
            "id": str(publication.get("persona_id") or (document.get("persona") or {}).get("id") or ""),
            "slug": str(publication.get("persona_slug") or (document.get("persona") or {}).get("slug") or "aurora"),
        },
        "metadata": {
            "purpose": "aurora_first_declarative_graphbundle_shadow",
            "source": "active_graph_publication_v75",
            "publication_allowed": False,
            "activation_allowed": False,
            "shadow_only": True,
            "embedding_profile": copy.deepcopy(embedding_profile),
            "baseline_publication": {
                "version": 75,
                "checksum": ACTIVE_V75_CHECKSUM,
                "compiler_version": publication.get("compiler_version"),
            },
            "baseline_counts": copy.deepcopy(EXPECTED_COUNTS),
            "allowed_changed_node_types": sorted(allowed_types),
            "removed_legacy_policy_paths": removed,
            "policy_source": POLICY_SOURCE,
        },
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Aurora's shadow-only GraphBundle from an audited active-v75 export."
    )
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    candidate = build(snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
