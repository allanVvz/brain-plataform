from pathlib import Path


ROOT = Path(__file__).parents[1]
DEPLOY = (ROOT / "ops" / "vps" / "deploy.sh").read_text(encoding="utf-8")
VALIDATOR = (
    ROOT / "ops" / "vps" / "validate-production-release.sh"
).read_text(encoding="utf-8")
WORKFLOW = (
    ROOT / ".github" / "workflows" / "deploy-production.yml"
).read_text(encoding="utf-8")
PORTAL_LAYOUT = (
    ROOT / "dashboard" / "app" / "clientes" / "[personaSlug]" / "layout.tsx"
).read_text(encoding="utf-8")


def test_production_deploy_leaves_workers_paused_for_controlled_validation():
    assert 'KEEP_WORKERS_PAUSED:-false' in DEPLOY
    assert '"${COMPOSE[@]}" stop workers' in DEPLOY
    assert 'KEEP_WORKERS_PAUSED: "true"' in WORKFLOW
    assert "REQUESTED_TAG,KEEP_WORKERS_PAUSED" in WORKFLOW


def test_release_validator_requires_this_release_migration_and_exact_sha():
    assert "121_sdr_journey_state_machine.sql" in VALIDATOR
    assert "release migrations 112-121 are incomplete" in VALIDATOR
    assert "EXPECTED_RELEASE_SHA" in VALIDATOR
    assert "release_source_identity" in VALIDATOR


def test_portal_build_does_not_download_google_fonts_during_release():
    assert "next/font/google" not in PORTAL_LAYOUT
