from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_turn_runtime_only_reads_active_publication_at_context_start():
    source = (ROOT / "api/services/graph_agent_runtime_v3.py").read_text(encoding="utf-8")
    assert source.count("get_active_graph_publication") == 3
    assert source.count("get_graph_publication_by_id") == 1
    assert source.count("_turn_publication(context)") >= 3
    assert 'if runtime == "production"' in source


def test_gateway_strips_client_identity_and_blocks_new_internal_api():
    source = (ROOT / "api/gateway_main.py").read_text(encoding="utf-8")
    assert 'IDENTITY_HEADERS = {"x-brain-principal", "x-brain-principal-signature"}' in source
    assert 'route.startswith("/internal/v1/")' in source


def test_canonical_n8n_template_has_no_microservice_fork():
    templates = list((ROOT / "api/n8n-workflows").glob("persona-conversation-template.json"))
    assert len(templates) == 1
