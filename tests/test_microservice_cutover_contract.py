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
    assert 'validator_operational_state=claims_paused' in script
    assert 'validator_operational_state=workers_resumed' in script
    assert 'validator_service="runtime-validator-${slot}"' in script
    assert 'MANIFEST="$ROOT_DIR/ops/microservices/release-manifest.json"' in script
    assert 'export RUNTIME_DIGEST="$(manifest_value service conversation-runtime digest)"' in script
    assert 'export RUNTIME_ENV_FILE="$ROOT_DIR/.env.microservices/runtime.env"' in script
    assert 'export TRANSPORT_ENV_FILE="$ROOT_DIR/.env.microservices/transport.env"' in script
    assert '"${COMPOSE[@]}" up -d --no-deps "$validator_service"' in script
    assert 'docker stop -t 120 "$validator_name"' in script
    assert 'docker start "$runner_cid"' in script
    assert 'docker stop -t 120 "$runner_cid"' in script
    assert "runner_deadline=$((SECONDS + 120))" in script
    assert "WA_VALIDATOR_RESULT=passed" in script
    assert "options: [dry-run, run, inspect]" in workflow
    assert '[[ "$VALIDATOR_ACTION" == "inspect" ]] && mode=--inspect' in workflow
    assert "WA_VALIDATOR_INSPECTION=" in script
    assert "WA_VALIDATOR_INSPECT_RESULT=passed" in script
    assert "run-microservice-wa-validator.sh" in workflow
    assert "release_lifecycle.py show" not in workflow


def test_production_backup_workflow_is_bounded_and_restore_verified():
    workflow = (
        ROOT / ".github" / "workflows" / "verify-production-backup.yml"
    ).read_text()
    assert "options: [dry-run, run]" in workflow
    assert "environment: production" in workflow
    assert "bash ops/vps/backup.sh" in workflow
    assert "--confirm-isolated-restore" in workflow
    assert "^/var/backups/brain-ai/[0-9]{8}T[0-9]{6}Z$" in workflow
    assert "(( used < 40 ))" in workflow
    assert "BACKUP_VERIFY_RESULT=passed" in workflow


def test_legacy_runtime_retirement_requires_microservice_cutover_and_pause():
    script = (ROOT / "ops" / "vps" / "deprovision-legacy-runtime.sh").read_text()
    workflow = (
        ROOT / ".github" / "workflows" / "deprovision-production-legacy-runtime.yml"
    ).read_text()
    assert "options: [dry-run, deprovision]" in workflow
    assert "LEGACY_DEPROVISION_AUTHORIZED" in workflow
    assert "reverse_proxy gateway-${gateway_slot}:8080" in script
    assert "! grep -Eq 'reverse_proxy api:8080'" in script
    assert 'value.get("paused") is True' in script
    assert 'docker ps -aq --filter "ancestor=$image_id"' in script
    assert '"$status" == "running" && "$name" != "/brain-ai-api-1"' in script
    assert 'docker image rm "$image_id"' in script
    assert 'docker stop --time 30 "$cid"' in script and 'docker rm "$cid"' in script
    assert "volumes=preserved" in script
    assert "(( used < 40 ))" in script


def test_n8n_workflow_management_runs_in_active_control_plane_slot():
    workflow = (
        ROOT / ".github" / "workflows" / "manage-production-conversation-workflow.yml"
    ).read_text()
    assert '.deploy/microservices/slots.json' in workflow
    assert '["control-plane"]["active"]' in workflow
    assert 'control_service="control-plane-$control_slot"' in workflow
    assert 'infra/microservices/docker-compose.blue-green.yml' in workflow
    assert 'queue_drained|candidate_healthy' in workflow
    assert 'before="$(audit_template)"' in workflow
    assert 'required=("persona_slug","workflow_id","active","live_checksum","candidate_checksum","would_change")' in workflow
    assert 'active_api_service' not in workflow


def test_control_plane_and_transport_receive_internal_n8n_endpoint_in_both_slots():
    compose = (ROOT / "infra" / "microservices" / "docker-compose.blue-green.yml").read_text()
    # Both API services need the explicit endpoint in each blue/green slot:
    # control plane manages n8n bindings and transport dispatch validates them.
    assert compose.count("N8N_BASE_URL: ${N8N_BASE_URL:-http://n8n:5678}") == 4


def test_control_plane_n8n_credential_sync_is_redacted_and_authorized():
    script = (ROOT / "ops" / "microservices" / "sync-control-plane-n8n-credential.py").read_text()
    workflow = (ROOT / ".github" / "workflows" / "sync-production-control-plane-n8n-credential.yml").read_text()
    assert "N8N_CREDENTIAL_SYNC_AUTHORIZED" in script and "N8N_CREDENTIAL_SYNC_AUTHORIZED" in workflow
    assert "value=redacted" in script
    assert 'value.get("paused") is True' in workflow
    assert "options: [dry-run, audit-registry, sync-registry, rotate-registry, apply]" in workflow
    assert "N8N_API_KEY_REGISTRY_AUDIT" in script
    assert "N8N_REGISTRY_CREDENTIAL_SYNC_RESULT=passed value=redacted" in script


def test_release_audit_accepts_retired_monolith_only_with_active_microservices():
    script = (ROOT / "ops" / "vps" / "validate-production-release.sh").read_text()
    assert 'gateway_slot" =~ ^(blue|green)$' in script
    assert "PASS\\tlegacy_api\\tretired" in script
    for service in ("gateway", "control-plane", "conversation-runtime", "transport"):
        assert service in script


def test_release_audit_allows_only_healthy_digest_drift_during_preflight():
    script = (ROOT / "ops" / "vps" / "validate-production-release.sh").read_text()
    assert 'ALLOW_PENDING_MICROSERVICE_DIGESTS="${ALLOW_PENDING_MICROSERVICE_DIGESTS:-false}"' in script
    assert '"$health" == "healthy" && "$ALLOW_PENDING_MICROSERVICE_DIGESTS" == "true"' in script
    assert "candidate digest pending" in script


def test_wa_validator_runner_is_an_immutable_internal_image():
    compose = (ROOT / "docker-compose.yml").read_text()
    build = (ROOT / ".github" / "workflows" / "build-wa-validator-image.yml").read_text()
    provision = (ROOT / "ops" / "vps" / "provision-wa-validator-runner.sh").read_text()
    assert "image: ${WA_VALIDATOR_IMAGE" in compose
    assert "Dockerfile.wa-validator" not in compose
    assert "ghcr.io/allanvvz/brain-wa-validator" in build
    assert 'MODE="${1:---dry-run}"' in provision
    assert "docker compose" in provision
    assert "up -d --no-deps wa-validator" in provision
    assert 'MODE" == "--deprovision"' in provision
    assert "WA_VALIDATOR_DEPROVISIONED=passed" in provision
    assert "volumes=preserved" in provision
    assert "docker volume" not in provision
    assert "options: [dry-run, deploy, deprovision]" in (
        ROOT / ".github" / "workflows" / "provision-production-wa-validator.yml"
    ).read_text()
    assert "exposure=internal" in provision
    assert "ports:" not in compose[compose.index("  wa-validator:"):compose.index("  grafana:")]


def test_shared_runtime_release_has_audited_global_microservice_pause():
    workflow = (
        ROOT / ".github" / "workflows" / "pause-microservice-workers.yml"
    ).read_text()

    assert "options: [dry-run, pause]" in workflow
    assert "disk gate failed" in workflow
    assert "pause-worker-claims.sh" in workflow
    assert "drain-worker-claims.sh" in workflow
    assert "status in ('processing','awaiting_proof')" in workflow
    assert "runtime-conversation-$runtime_slot" in workflow
    assert "transport-dispatch-$transport_slot" in workflow
    assert "control-plane-knowledge-$control_slot" in workflow
    assert "MICROSERVICE_WORKERS_PAUSED=passed" in workflow


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
    assert '"${COMPOSE[@]}" up -d --no-deps "${worker_services[@]}"' in script
    assert '"${COMPOSE[@]}" stop -t 120 "${started[@]}"' in script
    assert "docker image inspect" in script
    assert "release-manifest.json" in script
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
    assert 'ALLOW_PENDING_MICROSERVICE_DIGESTS: "true"' in preflight
    assert "AUDIT_ROOT,ALLOW_PENDING_MICROSERVICE_DIGESTS" in preflight
    assert 'with: {ref: "${{ inputs.manifest_sha }}"}' in workflow


def test_microservice_mutation_syncs_manifest_checksum_inputs():
    workflow = (ROOT / ".github/workflows/_deploy-microservice.yml").read_text(encoding="utf-8")
    mutate = workflow.split("  mutate:", 1)[1]
    assert "ops/microservices" in mutate
    assert "api/n8n-workflows/persona-conversation-template.json" in mutate


def test_service_env_bootstrap_never_distributes_universal_database_secrets():
    bootstrap = (ROOT / "ops/microservices/bootstrap-service-envs.py").read_text(encoding="utf-8")
    assert 'source.setdefault("SUPABASE_URL", "http://kong:8000")' in bootstrap
    assert 'values["BRAIN_DB_JWT"] = mint(jwt_secret, role)' in bootstrap
    assert 'role="brain_control_plane"' in bootstrap
    assert 'role="brain_runtime"' in bootstrap
    assert 'role="brain_transport"' in bootstrap
    assert 'TRANSPORT = COMMON | {\n    # The transport dispatch worker invokes' in bootstrap
    assert '    "N8N_BASE_URL",' in bootstrap
    assert '    "AI_BRAIN_SECRETS_KEY",' in bootstrap
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
