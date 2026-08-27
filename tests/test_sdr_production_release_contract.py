from pathlib import Path


ROOT = Path(__file__).parents[1]
DEPLOY = (ROOT / "ops" / "vps" / "deploy.sh").read_text(encoding="utf-8")
INCREMENTAL_DEPLOY = (
    ROOT / "ops" / "vps" / "deploy-incremental.sh"
).read_text(encoding="utf-8")
RESUME_WORKFLOW = (
    ROOT / ".github" / "workflows" / "resume-production-workers.yml"
).read_text(encoding="utf-8")
RESUME_SCRIPT = (
    ROOT / "ops" / "vps" / "resume-production-workers.sh"
).read_text(encoding="utf-8")
VALIDATOR = (
    ROOT / "ops" / "vps" / "validate-production-release.sh"
).read_text(encoding="utf-8")
WORKFLOW = (
    ROOT / ".github" / "workflows" / "deploy-production.yml"
).read_text(encoding="utf-8")
PORTAL_LAYOUT = (
    ROOT / "dashboard" / "app" / "clientes" / "[personaSlug]" / "layout.tsx"
).read_text(encoding="utf-8")
WA_VALIDATOR = (
    ROOT / "api" / "services" / "wa_validator_service.py"
).read_text(encoding="utf-8")
API_DOCKERFILE = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_incremental_deploy_pauses_claims_and_requires_explicit_resume():
    assert "release_lifecycle.py pause-release" in INCREMENTAL_DEPLOY
    assert "drain-worker-claims.sh" in INCREMENTAL_DEPLOY
    assert "awaiting_resume_authorization" in INCREMENTAL_DEPLOY
    assert "release-resume.sh" in RESUME_WORKFLOW


def test_wa_validator_is_not_a_deploy_or_resume_gate():
    assert "run the internal WA Validator evidence step before resume" not in INCREMENTAL_DEPLOY
    assert "--stage awaiting_resume_authorization" in INCREMENTAL_DEPLOY
    assert "wa_validator=optional_not_release_gate" in INCREMENTAL_DEPLOY
    assert "wa_validator_session" not in RESUME_WORKFLOW


def test_non_migration_release_consumes_continuous_backup_evidence():
    assert 'impact_class="$(python3 ops/vps/release_lifecycle.py show --field impact_class' in VALIDATOR
    assert '[[ "$impact_class" == "migration" ]]' in VALIDATOR
    assert "environment_evidence.py" in VALIDATOR
    assert '[[ "$require_fresh_backup" == "true" ]]' in VALIDATOR
    assert "bash ops/vps/validate-production-release.sh >/dev/null" not in RESUME_SCRIPT


def test_release_validator_uses_dynamic_migration_manifest_and_exact_sha():
    assert "MIGRATION_MANIFEST.json" in VALIDATOR
    assert "migration_manifest.py" in VALIDATOR
    assert "release migrations 112-130 are incomplete" not in VALIDATOR
    assert "EXPECTED_RELEASE_SHA" in VALIDATOR
    assert "release_source_identity" in VALIDATOR


def test_release_validator_does_not_embed_a_fixed_migration_list():
    import re
    assert not re.search(r"'\d{3}_[a-z0-9_]+\.sql'", VALIDATOR)


def test_main_workflow_has_plan_and_approved_resume_actions():
    assert "options: [plan, deploy, rollback, resume]" in WORKFLOW
    assert "environment: production-resume" in WORKFLOW
    assert "release-resume.sh" in WORKFLOW


def test_portal_build_does_not_download_google_fonts_during_release():
    assert "next/font/google" not in PORTAL_LAYOUT


def test_sdr_corpus_is_packaged_inside_the_production_api_image():
    corpus = ROOT / "api" / "evaluation" / "sdr_flow_cases.json"
    assert corpus.is_file()
    assert '_API_DIR / "evaluation" / "sdr_flow_cases.json"' in WA_VALIDATOR
    assert "COPY --chown=appuser:appuser api/ /app/" in API_DOCKERFILE
    assert 'ROOT_DIR / "tests" / "fixtures"' not in WA_VALIDATOR


def test_graph_bundle_catalog_is_packaged_at_the_runtime_lookup_path():
    zypi_bundle = (
        ROOT
        / "data"
        / "graph_bundles"
        / "zypi-shop"
        / "sdr-whatsapp-multiproduto-draft.json"
    )
    assert zypi_bundle.is_file()
    assert "data/*" in DOCKERIGNORE
    assert "!data/graph_bundles/**" in DOCKERIGNORE
    assert (
        "COPY --chown=appuser:appuser data/graph_bundles/ "
        "/data/graph_bundles/"
    ) in API_DOCKERFILE


def test_api_image_application_layer_is_keyed_by_release_sha():
    assert "SOURCE_SHA=${{ env.TARGET_SHA }}" in WORKFLOW
    marker = 'RUN printf \'%s\' "${SOURCE_SHA}" > /image-source-sha'
    assert marker in API_DOCKERFILE
    assert API_DOCKERFILE.index(marker) < API_DOCKERFILE.index(
        "COPY --chown=appuser:appuser api/ /app/"
    )
