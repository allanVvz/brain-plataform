from pathlib import Path
import json

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gateway_strips_client_identity_and_blocks_new_internal_api():
    source = (ROOT / "api/gateway_main.py").read_text(encoding="utf-8")
    assert 'IDENTITY_HEADERS = {"x-brain-principal", "x-brain-principal-signature"}' in source
    assert 'route.startswith("/internal/")' in source


def test_gateway_has_own_readiness_and_minimal_image():
    source = (ROOT / "api/gateway_main.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "api/gateway.Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "api/requirements-gateway.txt").read_text(encoding="utf-8")
    assert '@app.get("/health/ready")' in source
    assert "UPSTREAM_ENVIRONMENTS" in source
    assert "api/gateway_main.py" in dockerfile
    assert "api/requirements.txt" not in dockerfile
    assert "faster-whisper" not in requirements


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
    assert {
        "gateway-blue", "gateway-green",
        "control-plane-blue", "control-plane-green",
        "runtime-blue", "runtime-green",
        "transport-blue", "transport-green",
    } <= set(services)
    assert services["gateway-blue"]["env_file"] != services["runtime-blue"]["env_file"]
    assert services["control-plane-blue"]["env_file"] != services["transport-blue"]["env_file"]
    assert "BRAIN_RUNTIME_URL" in services["control-plane-blue"]["environment"]
    assert "BRAIN_TRANSPORT_URL" in services["control-plane-blue"]["environment"]
    assert "BRAIN_RUNTIME_URL" in services["transport-blue"]["environment"]
    assert "BRAIN_RUNTIME_URL" in services["transport-green"]["environment"]
    for service in (
        "control-plane-blue", "control-plane-green", "runtime-blue",
        "runtime-green", "transport-blue", "transport-green",
    ):
        assert services[service]["environment"]["REQUIRED_SCHEMA_VERSION"] == "131"

    groups = {
        service["labels"]["brain.worker-group"]
        for service in services.values()
        if "brain.worker-group" in service.get("labels", {})
    }
    assert groups == {"conversation", "transport", "media", "knowledge", "integrations", "validator"}


def test_source_import_manifest_tracks_merged_service_heads():
    manifest = json.loads(
        (ROOT / "ops/microservices/source-import-manifest.json").read_text(encoding="utf-8")
    )
    heads = manifest["current_main_commits"]
    assert set(heads) == {
        "brain-contracts",
        "brain-control-plane",
        "brain-conversation-runtime",
        "brain-transport",
    }
    assert all(len(sha) == 40 for sha in heads.values())


def test_cutover_keeps_new_worker_groups_stopped_while_claims_are_paused():
    deploy = (ROOT / "ops/vps/deploy-microservice-blue-green.sh").read_text(encoding="utf-8")
    assert '.deploy/control/claims-paused.json' in deploy
    assert 'workers_paused=true' in deploy
    assert 'stop -t 120 "${target_services[@]:1}"' in deploy


def test_validator_uses_only_active_runtime_validator_and_stops_it_after_run():
    script = (ROOT / "ops" / "vps" / "run-microservice-wa-validator.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "run-production-wa-validator.yml").read_text()
    assert 'MODE="${1:---dry-run}"' in script
    assert 'runtime_name="brain-ai-runtime-${slot}-1"' in script
    assert 'validator_name="brain-ai-runtime-validator-${slot}-1"' in script
    assert 'claims_paused=true' in script
    assert 'docker start "$validator_name"' in script
    assert 'docker stop -t 120 "$validator_name"' in script
    assert 'docker start "$runner_cid"' in script
    assert 'docker stop -t 120 "$runner_cid"' in script
    assert "runner_deadline=$((SECONDS + 120))" in script
    assert "WA_VALIDATOR_RESULT=passed" in script
    assert "options: [dry-run, run]" in workflow
    assert "run-microservice-wa-validator.sh" in workflow
    assert "release_lifecycle.py show" not in workflow


def test_release_audit_accepts_missing_legacy_worker_only_under_valid_pause():
    audit = (ROOT / "ops/vps/validate-production-release.sh").read_text(encoding="utf-8")
    assert 'allow_paused_missing="${3:-false}"' in audit
    assert 'Path(".deploy/control/claims-paused.json")' in audit
    assert 'check_container_digest workers .deploy/release-worker-digest true' in audit


def test_microservice_resume_never_starts_legacy_worker_and_rolls_back_pause():
    script = (ROOT / "ops" / "vps" / "resume-microservice-workers.sh").read_text()
    workflow = (ROOT / ".github" / "workflows" / "resume-microservice-workers.yml").read_text()
    assert 'MODE="${1:---dry-run}"' in script
    assert "legacy monolith worker is running" in script
    assert 'docker start "$name"' in script
    assert 'docker stop -t 120 "$name"' in script
    assert 'cp "$pause_evidence" "$PAUSE_FILE"' in script
    assert "MICROSERVICE_WORKERS_RESUMED=passed" in script
    assert "worker_groups\": 7" in script
    assert "options: [dry-run, resume]" in workflow
    assert "validate-production-release.sh" in workflow
    assert "resume-production-workers.sh" not in workflow


def test_microservice_preflight_runs_immutable_auditor_without_sync():
    workflow = (ROOT / ".github/workflows/_deploy-microservice.yml").read_text(encoding="utf-8")
    preflight = workflow.split("  mutate:", 1)[0]
    assert "script_path: ops/vps/validate-production-release.sh" in preflight
    assert "scp-action" not in preflight
    assert 'with: {ref: "${{ inputs.manifest_sha }}"}' in workflow


def test_service_env_bootstrap_never_distributes_universal_database_secrets():
    bootstrap = (ROOT / "ops/microservices/bootstrap-service-envs.py").read_text(encoding="utf-8")
    assert 'source.setdefault("SUPABASE_URL", "http://kong:8000")' in bootstrap
    assert 'values["BRAIN_DB_JWT"] = mint(jwt_secret, role)' in bootstrap
    assert 'role="brain_control_plane"' in bootstrap
    assert 'role="brain_runtime"' in bootstrap
    assert 'role="brain_transport"' in bootstrap
    assert '"SERVICE_ROLE_KEY"' not in bootstrap
    assert '"POSTGRES_PASSWORD"' not in bootstrap


def test_schema_apply_is_backup_restore_and_pause_gated():
    schema = (ROOT / "ops/vps/apply-microservice-schema.sh").read_text(encoding="utf-8")
    for evidence in (
        "pause-claims --safety-pause", "stop -t 180 workers", "drain-worker-claims.sh",
        "backup.sh", "restore.sh", "--single-transaction",
        "131_microservice_role_grants.sql",
    ):
        assert evidence in schema


def test_schema_workflow_syncs_manifest_checksum_inputs():
    workflow = (ROOT / ".github/workflows/deploy-schema.yml").read_text(encoding="utf-8")
    assert "ops/microservices/route-map.json" in workflow
    assert "api/n8n-workflows/persona-conversation-template.json" in workflow
