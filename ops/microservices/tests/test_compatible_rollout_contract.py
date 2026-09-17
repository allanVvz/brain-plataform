from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_candidate_starts_api_before_workers_and_drains_for_45_seconds():
    script = (ROOT / "ops/vps/deploy-microservice-blue-green.sh").read_text(encoding="utf-8")
    api_start = 'up -d --no-deps --force-recreate "$target_service"'
    worker_start = 'up -d --no-deps --force-recreate "${target_services[@]:1}"'
    readiness = 'http://127.0.0.1:8080/health/ready'
    assert api_start in script
    assert worker_start in script
    assert readiness in script
    assert script.index(api_start) < script.index(readiness) < script.index(worker_start)
    assert "/internal/v1/conversations/resolve-understanding" in script
    assert script.index(readiness) < script.index(
        "/internal/v1/conversations/resolve-understanding"
    ) < script.index(worker_start)
    assert 'stop -t 45 "${old_services[@]:1}"' in script
    assert 'elif [[ "$candidate_started" == "true" ]]' in script
    assert 'stop -t 45 "$target_service"' in script
    assert 'flock -w 120 9' in script
    assert 'public-upstream.previous-${SERVICE}.caddy' in script


def test_rollout_has_service_sha_digest_deduplication_and_automatic_rollback():
    script = (ROOT / "ops/vps/deploy-microservice-blue-green.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/_deploy-microservice.yml").read_text(encoding="utf-8")
    assert 'release_key="$(manifest_value service "$SERVICE" sha)-$(manifest_value service "$SERVICE" digest)"' in script
    assert 'release already promoted service=' in script
    assert "runtime canary failed; rolling back automatically" in workflow
    assert "conversation-runtime --rollback" in workflow
    assert 'WA_VALIDATOR_TIMEOUT_SECONDS: "300"' in workflow
    assert "install_active_caddy_config" not in script
    assert "rollout-microservices.sh status" in workflow
    assert workflow.index("Synchronize service release controls") < workflow.index(
        "Validate the exact controls and manifest"
    )


def test_integrated_release_has_no_artificial_service_serial_chain():
    workflow = (ROOT / ".github/workflows/integrated-release.yml").read_text(encoding="utf-8")
    assert "needs: [validate, control-plane]" not in workflow
    assert "needs: [validate, runtime]" not in workflow
    assert "needs: [validate, control-plane, runtime, transport]" not in workflow
