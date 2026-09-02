from __future__ import annotations

import json
import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_agent_runtime_v3  # noqa: E402


def _catalog_faq_row(
    node_id: str, question: str, aliases: list[str], semantic_score: float,
) -> dict:
    return {
        "faq_node_id": node_id,
        "chunk_id": f"chunk:{node_id}",
        "question": question,
        "aliases": aliases,
        "semantic_score": semantic_score,
        "lexical_score": 0,
    }


def test_contextual_price_followup_ranks_approved_product_faqs_for_model():
    # Rows are already scoped to the graph-selected retail branch. The lexical
    # resolver must not need a persona, customer or product literal in runtime.
    rows = [
        _catalog_faq_row(
            "faq:retail:cotele:description",
            "Como e o Conjunto em cotele e para quem ele e indicado?",
            ["me fala sobre o Conjunto em cotele"],
            0.415142,
        ),
        _catalog_faq_row(
            "faq:retail:cotele:price",
            "Qual e o preco do Conjunto em cotele no varejo?",
            ["quanto custa o Conjunto em cotele"],
            0.400100,
        ),
        _catalog_faq_row(
            "faq:retail:flare-cotele:price",
            "Qual e o preco da Calca flare em cotele no varejo?",
            ["quanto custa a Calca flare em cotele"],
            0.400577,
        ),
        _catalog_faq_row(
            "faq:retail:mousse:price",
            "Qual e o preco do Conjunto em mousse no varejo?",
            ["quanto custa o Conjunto em mousse"],
            0.395386,
        ),
    ]

    candidates = graph_agent_runtime_v3._rank_faq_candidates(
        "qual o valor do cotele",
        rows,
        context_hint="Entre as opcoes, temos o Conjunto em cotele.",
    )

    assert candidates[0]["faq_node_id"] == "faq:retail:cotele:price"
    assert all("contextual_lexical_rank" in candidate for candidate in candidates)


def test_tock_retail_profile_recovers_published_cotele_price_faq():
    bundle = json.loads((
        REPO_ROOT / "data" / "graph_bundles" / "tock-fatal"
        / "sdr-qualification-v12-model-owned.json"
    ).read_text(encoding="utf-8"))
    rows = []
    for node in bundle["nodes"]:
        data = node.get("data") or {}
        if (
            node.get("node_type") != "faq"
            or node.get("status") != "approved"
            or "audience:tock-retail" not in (data.get("branch_path") or [])
            or not data.get("claims")
        ):
            continue
        rows.append({
            "faq_node_id": node["id"],
            "chunk_id": f"chunk:{node['id']}",
            "question": data.get("question"),
            "aliases": data.get("question_aliases") or [],
            "semantic_score": 0.40,
            "lexical_score": 0,
            "answer": data.get("answer"),
        })

    candidates = graph_agent_runtime_v3._rank_faq_candidates(
        "qual o valor do cotele",
        rows,
        context_hint="Uma das opcoes e o Conjunto em cotele.",
    )

    assert candidates[0]["faq_node_id"] == (
        "faq:tock-conjuntos-conjunto-em-cotele-varejo-preco-canal-quantidade"
    )
    ranked_row = next(
        row for row in rows
        if row["faq_node_id"] == candidates[0]["faq_node_id"]
    )
    assert "R$ 119,90" in ranked_row["answer"]


def test_contextual_price_followup_exposes_both_tied_products_to_model():
    rows = [
        _catalog_faq_row(
            "faq:retail:cotele:price",
            "Qual e o preco do Conjunto em cotele no varejo?",
            ["quanto custa o Conjunto em cotele"],
            0.410,
        ),
        _catalog_faq_row(
            "faq:retail:flare-cotele:price",
            "Qual e o preco da Calca flare em cotele no varejo?",
            ["quanto custa a Calca flare em cotele"],
            0.405,
        ),
    ]

    candidates = graph_agent_runtime_v3._rank_faq_candidates(
        "qual o valor do cotele",
        rows,
        context_hint="Temos Conjunto em cotele e Calca flare em cotele.",
    )

    assert {candidate["faq_node_id"] for candidate in candidates[:2]} == {
        "faq:retail:cotele:price",
        "faq:retail:flare-cotele:price",
    }


def test_faq_context_hint_does_not_reuse_stale_catalog_mentions():
    messages = [
        {"role": "assistant", "content": "Temos uma Calca flare em cotele."},
        {"role": "user", "content": "Certo."},
        {"role": "assistant", "content": "Agora estamos vendo o Conjunto em cotele."},
        {"role": "user", "content": "Qual o valor do cotele?"},
    ]

    assert graph_agent_runtime_v3._faq_context_hint(messages) == (
        "Agora estamos vendo o Conjunto em cotele."
    )
