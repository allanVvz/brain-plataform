from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_API = ROOT / "apps" / "control-plane" / "api"
if str(CONTROL_PLANE_API) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE_API))

from services.graph_bundle import build_publication_plan


BUNDLE_PATH = ROOT / "data" / "graph_bundles" / "utzig-garage" / "utzig-complete-knowledge-v5.DRAFT.json"


def _normalized(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in folded if not unicodedata.combining(char)).split())


def test_complete_knowledge_candidate_is_publishable_and_source_backed() -> None:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    plan = build_publication_plan(bundle)

    assert plan["validation_errors"] == []
    assert plan["publication_allowed"] is True
    assert bundle["metadata"]["content_approval"] == {
        "status": "operator_approved",
        "source_publication_id": "d5c7afd7-24ea-44d6-90e9-8532fd3fc303",
        "source_publication_checksum": "sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec",
        "approved_faq_count": 23,
        "enriched_copy_count": 11,
    }
    enriched = [node for node in bundle["nodes"] if node["id"].count(":") >= 3 and node["id"].startswith("faq:service:")]
    assert len(enriched) == 23
    assert len(bundle["nodes"]) == 124
    assert all(node["status"] == "approved" for node in bundle["nodes"])
    assert all((node.get("data") or {}).get("source") != "pending_source" for node in bundle["nodes"])
    assert len({node["id"] for node in bundle["nodes"] if node["node_type"] == "faq"}) == 51
    edges = bundle["edges"]
    for faq in enriched:
        assert faq["status"] == "approved"
        assert faq["data"]["source_node_type"] == "product"
        assert faq["data"]["import_provenance"]["source_validation_status"] == "approved"
        assert sum(
            edge["source"] == faq["data"]["source_node_id"]
            and edge["target"] == faq["id"]
            and edge["relation_type"] == "contains"
            and edge.get("primary") is True
            for edge in edges
        ) == 1
        assert sum(
            edge["source"] == faq["id"]
            and edge["target"] == "embedded:utzig"
            and edge["relation_type"] == "publishes_to"
            for edge in edges
        ) == 1

    questions = [_normalized(faq["data"]["question"]) for faq in enriched]
    assert len(questions) == len(set(questions))
    assert all(len(faq["data"]["question_aliases"]) >= 4 for faq in enriched)

    enriched_copies = [
        node for node in bundle["nodes"]
        if node["node_type"] == "copy" and (node.get("data") or {}).get("conversation_variants")
    ]
    assert len(enriched_copies) == 11
    for copy_node in enriched_copies:
        assert {variant["purpose"] for variant in copy_node["data"]["conversation_variants"]} == {
            "explain", "set_expectation", "next_step",
        }


def test_complete_knowledge_keeps_commercial_confirmation_human() -> None:
    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    text = " ".join(
        str((node.get("data") or {}).get("answer") or "")
        for node in bundle["nodes"]
        if node["node_type"] == "faq"
    ).casefold()

    assert "preço e duração" in text or "preço, prazo" in text
    assert "confirmados pela equipe" in text or "confirmado pela equipe" in text
    assert "r$" not in text
