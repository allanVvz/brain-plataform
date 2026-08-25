from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
CADDYFILE = (ROOT / "infra" / "Caddyfile").read_text(encoding="utf-8")
DEPLOY = (ROOT / "ops" / "vps" / "deploy-incremental.sh").read_text(encoding="utf-8")
BLUE_GREEN = (ROOT / "ops" / "vps" / "deploy-api-blue-green.sh").read_text(encoding="utf-8")
RESUME = (ROOT / "ops" / "vps" / "resume-production-workers.sh").read_text(encoding="utf-8")
RETENTION = (ROOT / "ops" / "vps" / "retain-release-images.sh").read_text(encoding="utf-8")


def test_api_has_two_slots_and_candidate_uses_alternate_local_port():
    assert "  api-candidate:" in COMPOSE
    assert "${API_CANDIDATE_PORT:-8081}:8080" in COMPOSE
    assert 'profiles: ["blue-green"]' in COMPOSE


def test_blue_green_validates_then_reloads_before_stopping_old_slot():
    validate = BLUE_GREEN.index("caddy validate")
    reload_ = BLUE_GREEN.index("caddy reload --config /tmp/Caddyfile.next")
    external = BLUE_GREEN.index("https://$api_domain/health/ready")
    stop = BLUE_GREEN.index('stop api-candidate', external)
    assert validate < reload_ < external < stop
    assert "source_sha" in BLUE_GREEN
    assert "restore_previous_upstream" in BLUE_GREEN


def test_blue_green_uses_local_only_caddy_admin_with_bootstrap():
    assert "admin 127.0.0.1:2019" in CADDYFILE
    assert "2019:2019" not in COMPOSE
    assert "bootstrapping local Caddy admin endpoint" in BLUE_GREEN
    assert "--address 127.0.0.1:2019" in BLUE_GREEN


def test_api_only_path_finishes_before_claim_pause_branch():
    api_branch = DEPLOY.index('if [[ "$IMPACT" == "api" ]]')
    api_exit = DEPLOY.index("exit 0", api_branch)
    claims_pause = DEPLOY.index("release_lifecycle.py pause-claims", api_exit)
    assert "deploy-api-blue-green.sh" in DEPLOY[api_branch:api_exit]
    assert api_exit < claims_pause


def test_first_split_image_release_bootstraps_from_existing_api_registry():
    assert 'API_IMAGE="$(read_env_value API_IMAGE)"' in DEPLOY
    assert 'image_prefix="${API_IMAGE%brain-api}"' in DEPLOY
    assert 'WORKER_IMAGE="${WORKER_IMAGE:-${image_prefix}brain-workers}"' in DEPLOY
    assert "export API_IMAGE WORKER_IMAGE MIGRATE_IMAGE" in DEPLOY


def test_abandoned_pre_pause_candidate_can_be_superseded_safely():
    assert '"$STATE_DIR/lifecycle.json"' in DEPLOY
    assert (
        '"$existing_stage" =~ '
        '^(prepared|images_pulled|claims_paused|queue_drained)$'
    ) in DEPLOY
    assert '"$existing_previous" == "$CURRENT_SHA"' in DEPLOY
    assert "prepare_args+=(--force --force-reason" in DEPLOY
    assert "unfinished release cannot be superseded safely" in DEPLOY


def test_resume_checks_digest_and_is_idempotent_after_verified():
    assert "image_digests_verified=true" in RESUME
    assert "workers already resumed and release verified" in RESUME
    assert "automatic safety pause after resume verification failure" in RESUME


def test_resume_uses_the_same_immutable_registry_repositories_as_deploy():
    assert 'API_IMAGE="$(read_env_value API_IMAGE)"' in RESUME
    assert 'image_prefix="${API_IMAGE%brain-api}"' in RESUME
    assert 'WORKER_IMAGE="${WORKER_IMAGE:-${image_prefix}brain-workers}"' in RESUME
    assert "export API_IMAGE WORKER_IMAGE MIGRATE_IMAGE" in RESUME


def test_retention_is_dry_run_by_default_and_component_precise():
    assert 'MODE="${1:-${RETENTION_MODE:---dry-run}}"' in RETENTION
    assert "CLEANUP_AUTHORIZED=true" in RETENTION
    assert 'keep["$component:$value"]' in RETENTION
    assert "docker volume" not in RETENTION


def test_retention_only_removes_stopped_stale_release_containers():
    assert "exited|dead|created" in RETENTION
    assert "KEEP_CONTAINER" in RETENTION
    assert "STALE_CONTAINER" in RETENTION
    assert 'docker container rm "${removable_containers[@]}"' in RETENTION
