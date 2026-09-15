from services import graph_agent_runtime_v3


def test_repair_package_keeps_requested_nodes_without_rag_chunks():
    requirements = [
        {"kind": "node", "id": "audience:reseller"},
        {"kind": "node", "id": "faq:purchase-profile"},
    ]
    node_by_id = {
        "audience:reseller": {"id": "audience:reseller"},
        "faq:purchase-profile": {"id": "faq:purchase-profile"},
    }

    assert graph_agent_runtime_v3._repair_card_sources(
        [], requirements, node_by_id,
    ) == {
        "audience:reseller": [],
        "faq:purchase-profile": [],
    }


def test_repair_package_attaches_chunks_to_their_node():
    chunk = {
        "chunk_id": "chunk:1",
        "source_graph_node_id": "faq:purchase-profile",
    }

    assert graph_agent_runtime_v3._repair_card_sources(
        [chunk],
        [{"kind": "node", "id": "faq:purchase-profile"}],
        {"faq:purchase-profile": {"id": "faq:purchase-profile"}},
    ) == {"faq:purchase-profile": [chunk]}
