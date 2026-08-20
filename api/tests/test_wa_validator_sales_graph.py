from __future__ import annotations

import json
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle, validator_sofia_insights, wa_validator_service


def _publication() -> dict:
    bundle = json.loads(
        (REPO_ROOT / "data" / "graph_bundles" / "tock-fatal" / "sdr-qualification-v1.json")
        .read_text(encoding="utf-8")
    )
    document = graph_bundle.compile_bundle(bundle)
    return {"version": 1, "checksum": document["checksum"], "document_json": document}


def test_sales_semantic_scripts_select_distinct_graph_branches():
    publication = _publication()

    retail = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_retail"
    )
    reseller = wa_validator_service._semantic_sales_script(
        publication=publication, flow_id="sdr_sales_reseller"
    )

    assert retail["driver"]["mode"] == "semantic_graph_v1"
    assert retail["driver"]["branch_anchor_node_id"] == "audience:tock-retail"
    assert reseller["driver"]["branch_anchor_node_id"] == "audience:tock-reseller"
    assert retail["driver"]["branch_anchor_node_id"] != reseller["driver"]["branch_anchor_node_id"]
    assert retail["driver"]["doubt"]["forbidden_claim_patterns"]


def test_validator_gaps_become_review_only_sofia_proposals():
    review = validator_sofia_insights.build_sofia_review(
        persona_slug="tock-fatal",
        session_id="session-1",
        gaps=[{
            "topic": "expected_branch_persisted",
            "evidence": "O runtime selecionou o galho errado.",
            "priority": "high",
        }, {
            "topic": "unsupported_claim_not_invented",
            "evidence": "A resposta afirmou preço sem evidência.",
            "priority": "high",
        }],
    )

    assert review["status"] == "pending_human_review"
    assert review["automatic_mutation"] is False
    assert [item["kind"] for item in review["proposals"]] == [
        "branch_resolution_review", "knowledge_gap"
    ]
    assert all(item["publication_allowed"] is False for item in review["proposals"])
