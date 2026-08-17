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
WA_VALIDATOR = (
    ROOT / "api" / "services" / "wa_validator_service.py"
).read_text(encoding="utf-8")
API_DOCKERFILE = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")


def test_production_deploy_leaves_workers_paused_for_controlled_validation():
    assert 'KEEP_WORKERS_PAUSED:-false' in DEPLOY
    assert '"${COMPOSE[@]}" stop workers' in DEPLOY
    assert 'KEEP_WORKERS_PAUSED: "true"' in WORKFLOW
    assert "REQUESTED_TAG,KEEP_WORKERS_PAUSED" in WORKFLOW


def test_release_validator_requires_this_release_migration_and_exact_sha():
    assert "122_preserve_post_handoff_journey.sql" in VALIDATOR
    assert "126_journey_state_selector.sql" in VALIDATOR
    assert "127_sdr_name_service_confirmation.sql" in VALIDATOR
    assert "release migrations 112-127 are incomplete" in VALIDATOR
    assert "EXPECTED_RELEASE_SHA" in VALIDATOR
    assert "release_source_identity" in VALIDATOR


def test_release_validator_gate_counts_every_migration_it_lists():
    """O gate compara `count(*) <> N`. Se a lista crescer e o N ficar para
    tras, o gate passa com migration faltando -- confianca falsa exatamente no
    momento em que ela mais importa."""
    import re

    bloco = VALIDATOR[VALIDATOR.index("do $$"):VALIDATOR.index("are incomplete")]
    listadas = len(re.findall(r"'\d{3}_[a-z0-9_]+\.sql'", bloco))
    esperado = int(re.search(r"\)\) <> (\d+) then", bloco).group(1))
    assert listadas == esperado, f"{listadas} migrations listadas, gate espera {esperado}"


def test_portal_build_does_not_download_google_fonts_during_release():
    assert "next/font/google" not in PORTAL_LAYOUT


def test_sdr_corpus_is_packaged_inside_the_production_api_image():
    corpus = ROOT / "api" / "evaluation" / "sdr_flow_cases.json"
    assert corpus.is_file()
    assert '_API_DIR / "evaluation" / "sdr_flow_cases.json"' in WA_VALIDATOR
    assert "COPY --chown=appuser:appuser api/ /app/" in API_DOCKERFILE
    assert 'ROOT_DIR / "tests" / "fixtures"' not in WA_VALIDATOR
