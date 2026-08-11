from __future__ import annotations

import sys
import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from schemas.graph_json_v2 import Edge, GraphJson, Node
from services import context_cards
from services.sdr_documents import compile_persona_documents


def _node(node_id: str, node_type: str, content: str, *, status: str = "validated") -> Node:
    return Node(
        id=node_id,
        node_type=node_type,
        slug=node_id,
        label=node_id.replace("-", " ").title(),
        data={"status": status, "source": "fixture", "summary": content, "aliases": [node_id]},
    )


def _graph(persona_slug: str = "aurora") -> GraphJson:
    nodes = [
        _node("persona", "persona", f"Identidade {persona_slug}"),
        _node("brand", "brand", f"Marca {persona_slug}"),
        _node("tone", "tone", "Fale de forma clara"),
        _node("rule", "rule", "Nunca invente preços"),
        _node("briefing", "briefing", "Briefing não relacionado"),
        _node("product", "product", "Lavagem premium a partir de R$ 180"),
        Node(
            id="faq",
            node_type="faq",
            slug="faq-lavagem",
            label="Quanto custa a lavagem?",
            data={
                "status": "validated", "source": "fixture",
                "question": "Quanto custa a lavagem?", "answer": "A partir de R$ 180.",
            },
        ),
    ]
    return GraphJson(
        schema_version="2.0",
        graph_id=f"graph-{persona_slug}",
        tenant="test",
        persona_slug=persona_slug,
        status="published",
        nodes=nodes,
        edges=[
            Edge(id="e-persona-brand", source="persona", target="brand", relation_type="contains"),
            Edge(id="e-brand-product", source="brand", target="product", relation_type="contains"),
            Edge(id="e-product-faq", source="product", target="faq", relation_type="answers"),
            Edge(id="e-brand-briefing", source="brand", target="briefing", relation_type="contains"),
        ],
    )


def test_resolver_uses_permanent_policy_and_multiple_relevant_cards_without_briefing_noise():
    cards = context_cards.resolve_cards(
        graph=_graph(), graph_version=7, graph_checksum="sha256:graph",
        query="quanto custa lavagem", max_cards=12,
    )
    ids = [card.id for card in cards]
    assert ids[:4] == ["persona", "brand", "tone", "rule"]
    assert "product" in ids and "faq" in ids
    assert "briefing" not in ids
    assert all(card.graph_version == 7 for card in cards)
    assert [card.position for card in cards] == list(range(len(cards)))
    assert all(card.rendered_content for card in cards)


def test_projected_uuids_are_trace_metadata_and_ten_ids_map_to_stable_graph_ids():
    projections = [
        {"id": f"00000000-0000-0000-0000-{index:012d}", "metadata": {"graph_json_node_id": f"node-{index}"}}
        for index in range(10)
    ]
    mapped = context_cards.canonicalize_ids([row["id"] for row in projections], projections)
    assert mapped == [f"node-{index}" for index in range(10)]


def test_exact_response_keeps_snapshot_and_marks_new_current_version(monkeypatch):
    old_graph = _graph()
    old_cards = context_cards.resolve_cards(
        graph=old_graph, graph_version=3, graph_checksum="old-graph",
        query="lavagem",
    )
    current_graph = _graph()
    product = next(node for node in current_graph.nodes if node.id == "product")
    product.data["summary"] = "Lavagem premium agora a partir de R$ 220"
    monkeypatch.setattr(context_cards, "current_graph", lambda _slug: (4, "new-graph", current_graph))

    message = {
        "id": 91,
        "message_id": "ai:turn-91",
        "role": "assistant",
        "direction": "outbound",
        "content": "A lavagem começa em R$ 180.",
        "metadata": {
            "knowledge_context": {
                "graph_version": 3,
                "graph_checksum": "old-graph",
                "decisive_node_ids": ["product"],
                "cards": [card.model_dump(mode="json") for card in old_cards],
            }
        },
    }
    result = context_cards.response_context(
        persona_slug="aurora", persona_id="p-1", lead_ref=1,
        messages=[message], response_message_id="ai:turn-91", query="lavagem",
    )
    assert result["mode"] == "exact"
    old_product = next(card for card in result["used_cards"] if card["id"] == "product")
    assert "180" in old_product["rendered_content"]
    assert "220" in result["current_cards"]["product"]["rendered_content"]
    assert result["graph_version"] == 3
    assert result["current_graph_version"] == 4


def test_checksum_validation_accepts_legacy_raw_snapshot_hash():
    rendered = "Linha 1\r\nLinha 2"
    legacy = "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    ok, actual = context_cards._content_checksum_matches(legacy, rendered)
    assert ok is True
    assert actual.startswith("sha256:")


def test_checksum_divergence_metric_is_bounded_per_snapshot(monkeypatch):
    emitted: list[dict] = []
    context_cards._DIVERGENCE_EMITTED_AT.clear()
    monkeypatch.setattr(context_cards, "emit_metric", lambda *args, **kwargs: emitted.append(kwargs))
    payload = {"response_message_id": "m-1", "node_id": "n-1", "expected": "x", "actual": "y"}
    context_cards._emit_checksum_divergence_once(persona_id="p-1", lead_ref=1, payload=payload)
    context_cards._emit_checksum_divergence_once(persona_id="p-1", lead_ref=1, payload=payload)
    assert len(emitted) == 1


def test_historical_reconstruction_never_promotes_inferred_related_cards(monkeypatch):
    historical = _graph()
    current = _graph()
    monkeypatch.setattr(context_cards, "current_graph", lambda _slug: (9, "current", current))
    monkeypatch.setattr(context_cards, "load_graph_version", lambda _slug, _version: (5, "historical", historical))
    monkeypatch.setattr(context_cards, "emit_metric", lambda *args, **kwargs: None)
    message = {
        "id": 55,
        "message_id": "ai:old",
        "role": "assistant",
        "direction": "outbound",
        "metadata": {"graph_version": 5, "evidence_node_ids": ["faq"]},
    }
    result = context_cards.response_context(
        persona_slug="aurora", persona_id="p-1", lead_ref=1,
        messages=[message], response_message_id="ai:old", query="lavagem",
    )
    assert result["mode"] == "reconstructed"
    assert [card["id"] for card in result["used_cards"]] == ["faq"]
    assert "product" in {card["id"] for card in result["related_cards"]}


def test_persona_graphs_never_cross_contaminate():
    aurora = context_cards.resolve_cards(
        graph=_graph("aurora"), graph_version=1, graph_checksum="a", query="lavagem",
    )
    baita = context_cards.resolve_cards(
        graph=_graph("baita"), graph_version=1, graph_checksum="b", query="lavagem",
    )
    assert all("baita" not in card.rendered_content.lower() for card in aurora)
    assert all("aurora" not in card.rendered_content.lower() for card in baita)


def test_runtime_legacy_json_string_checksum_is_accepted_without_divergence():
    rendered = "Pintura\r\ncom proteção"
    expected = context_cards.graph_compiler_v3.canonical_checksum(rendered)

    matches, actual = context_cards._content_checksum_matches(expected, rendered)

    assert matches is True
    assert actual == context_cards.graph_compiler_v3.canonical_content_checksum(rendered)


def test_real_baita_fixture_returns_product_faq_and_clean_prompt_cards():
    graph = compile_persona_documents(ROOT / "docs" / "sdr", "baita-conveniencia")
    cards = context_cards.resolve_cards(
        graph=graph, graph_version=1, graph_checksum="baita-fixture",
        query="Quanto custa o Red Bull 250 ml?", max_cards=12, max_tokens=8000,
    )
    types = {card.node_type for card in cards}
    assert {"persona", "brand", "tone", "rule", "product", "faq"} <= types
    assert "briefing" not in types
    assert len(cards) <= 12
    prompt = "\n".join(card.rendered_content for card in cards).lower()
    assert "rag_chunk" not in prompt
    assert "source_checksum" not in prompt
    assert "red bull" in prompt and "r$ 15" in prompt


def test_real_aurora_fixture_resolves_multiple_cards_inside_its_own_graph():
    payload = json.loads(
        (ROOT / "api" / "scripts" / "fixtures" / "aurora_graph_v2.json").read_text(encoding="utf-8")
    )
    graph = GraphJson.model_validate(payload)
    cards = context_cards.resolve_cards(
        graph=graph, graph_version=1, graph_checksum="aurora-fixture",
        query="quanto custa a lavagem e o que inclui", max_cards=12, max_tokens=8000,
    )
    assert len([card for card in cards if card.node_type == "faq"]) >= 2
    assert all(card.id.startswith("aurora-") for card in cards)
    assert len(cards) <= 12
    assert all("graph_json_node_id" not in card.rendered_content for card in cards)
