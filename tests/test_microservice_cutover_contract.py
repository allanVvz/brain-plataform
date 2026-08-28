from pathlib import Path

import yaml


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
    assert 'route.startswith("/internal/")' in source


def test_gateway_routes_decisions_to_runtime_not_transport():
    source = (ROOT / "api/gateway_main.py").read_text(encoding="utf-8")
    transport_rule, runtime_rule = source.split("def _upstream", 1)[1].split(
        "def _principal", 1
    )[0].split("return os.environ[\"BRAIN_TRANSPORT_URL\"]", 1)
    assert '"/process"' not in transport_rule
    assert '"/process"' in runtime_rule


def test_canonical_n8n_template_has_no_microservice_fork():
    templates = list((ROOT / "api/n8n-workflows").glob("persona-conversation-template.json"))
    assert len(templates) == 1


def test_blue_green_has_gateway_and_role_separated_env_files():
    compose = yaml.safe_load(
        (ROOT / "infra/microservices/docker-compose.blue-green.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert set(services) == {
        "gateway-blue", "gateway-green",
        "control-plane-blue", "control-plane-green",
        "runtime-blue", "runtime-green",
        "transport-blue", "transport-green",
    }
    assert services["gateway-blue"]["env_file"] != services["runtime-blue"]["env_file"]
    assert services["control-plane-blue"]["env_file"] != services["transport-blue"]["env_file"]
    assert "BRAIN_RUNTIME_URL" in services["control-plane-blue"]["environment"]
    assert "BRAIN_TRANSPORT_URL" in services["control-plane-blue"]["environment"]
