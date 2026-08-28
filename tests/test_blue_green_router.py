import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "ops/microservices/render-active-routes.py"


def test_renderer_keeps_legacy_public_route_before_cutover(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"gateway": {"active": "legacy"}}), encoding="utf-8")
    output = tmp_path / "rendered"
    subprocess.run([sys.executable, str(RENDERER), str(state), str(output)], check=True)
    assert "reverse_proxy api:8080" in (output / "public-upstream.caddy").read_text()
    assert "respond 503" in (output / "internal-upstreams.caddy").read_text()


def test_renderer_switches_each_service_independently(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "gateway": {"active": "green"},
        "control-plane": {"active": "blue"},
        "conversation-runtime": {"active": "green"},
        "transport": {"active": "blue"},
    }), encoding="utf-8")
    output = tmp_path / "rendered"
    subprocess.run([sys.executable, str(RENDERER), str(state), str(output)], check=True)
    public = (output / "public-upstream.caddy").read_text()
    internal = (output / "internal-upstreams.caddy").read_text()
    assert "gateway-green:8080" in public
    assert "control-plane-blue:8080" in internal
    assert "runtime-green:8080" in internal
    assert "transport-blue:8080" in internal


def test_deployer_defaults_to_dry_run_and_requires_explicit_apply():
    source = (ROOT / "ops/vps/deploy-microservice-blue-green.sh").read_text()
    assert 'ACTION="${3:---dry-run}"' in source
    assert "--apply|--rollback" in source
    assert "caddy validate" in source
    assert "caddy reload" in source
    assert 'stop -t 120' in source


def test_workflow_audits_before_sync_or_mutation():
    source = (ROOT / ".github/workflows/_deploy-microservice.yml").read_text()
    preflight, mutate = source.split("  mutate:", 1)
    assert "validate-production-release.sh" in preflight
    assert "scp-action" not in preflight
    assert "environment: production-${{ inputs.service }}" in mutate
    assert "scp-action" in mutate
    assert "--apply" in mutate
