"""Guard against silent drift between the monolith and the deployed microservices.

Production runs the microservice copies under `apps/*/api/services/`, never the
monolith at `api/services/`. But `252cac8 feat: consolidate microservices and
contracts in monorepo` carved those copies out of a stale snapshot: it copied
`graph_compiler_v3.py` at `graph-compiler-v3.6.2` while the monolith was already
at `graph-compiler-v3.6.4`. Nothing checked that the copies stayed in sync, so
they kept drifting after the carve-out. The real cost: a fix landed in
`api/services/graph_compiler_v3.py`, never reached the deployed compiler, and a
graph publication was blocked because the deployed copy computed a different
checksum than the one that had been approved.

This test cannot stop the duplication -- that is a larger refactor -- but it
makes drift a decision instead of an accident:

* every module duplicated between `api/services/` and each `apps/*/api/services/`
  is discovered from the filesystem (the app list is never hardcoded);
* today's known divergences are pinned in `DIVERGENT_BASELINE` below, so the
  suite is green right now;
* a pair that is identical today but diverges tomorrow fails the suite --
  that failure is exactly the bug described above, caught before it reaches
  production;
* a wholly new duplicated file that nobody added to `DUPLICATED_BASELINE`
  fails too, so growing the duplication footprint is a deliberate, reviewed
  choice rather than something that happens by copy-pasting a file into an
  app directory;
* a baseline divergence that gets fixed does not fail anything -- it is
  reported so the baseline can be trimmed, because punishing a fix would just
  teach people to leave the baseline stale.

File content is compared with line endings normalised, because this repo mixes
CRLF and LF (`.gitattributes` pins some paths to LF and Windows checkouts can
introduce CRLF elsewhere) and a pure EOL difference is not a real divergence.
`__pycache__` and `__init__.py` are ignored: the former is never source, and
the latter is near-universally an empty marker that duplicates trivially.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MONOLITH_SERVICES = ROOT / "api" / "services"
APPS_ROOT = ROOT / "apps"


def _discover_apps() -> tuple[str, ...]:
    return tuple(
        sorted(
            child.name
            for child in APPS_ROOT.iterdir()
            if child.is_dir() and (child / "api" / "services").is_dir()
        )
    )


def _discover_monolith_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(MONOLITH_SERVICES).as_posix()
            for path in MONOLITH_SERVICES.rglob("*.py")
            if "__pycache__" not in path.parts and path.name != "__init__.py"
        )
    )


def _discover_duplicated_pairs() -> tuple[tuple[str, str], ...]:
    """Every (app, relative_path) where the app carved a copy of a monolith module."""
    pairs = []
    modules = _discover_monolith_modules()
    for app in _discover_apps():
        app_services = APPS_ROOT / app / "api" / "services"
        for relative_path in modules:
            if (app_services / relative_path).is_file():
                pairs.append((app, relative_path))
    return tuple(sorted(pairs))


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _pair_paths(app: str, relative_path: str) -> tuple[Path, Path]:
    return MONOLITH_SERVICES / relative_path, APPS_ROOT / app / "api" / "services" / relative_path


def _pair_exists(app: str, relative_path: str) -> bool:
    monolith_path, app_path = _pair_paths(app, relative_path)
    return monolith_path.is_file() and app_path.is_file()


def _is_identical(app: str, relative_path: str) -> bool:
    monolith_path, app_path = _pair_paths(app, relative_path)
    return _normalized(monolith_path) == _normalized(app_path)


# Pinned 2026-09-05 by walking api/services against every apps/*/api/services
# directory found on disk (control-plane, conversation-runtime, transport).
# This is every (app, relative_path) pair where the app carries its own copy
# of a monolith module, identical or not. A pair missing from this tuple means
# nobody has reviewed that duplication yet.
DUPLICATED_BASELINE: tuple[tuple[str, str], ...] = (
    ("control-plane", "agent_harness.py"),
    ("control-plane", "agent_harness_repository.py"),
    ("control-plane", "agent_harness_tools.py"),
    ("control-plane", "agent_tool_registry.py"),
    ("control-plane", "approved_knowledge_snapshots.py"),
    ("control-plane", "asset_pipeline/ai_fallback.py"),
    ("control-plane", "asset_pipeline/classifier.py"),
    ("control-plane", "asset_pipeline/ocr_local.py"),
    ("control-plane", "asset_pipeline/pdf_text.py"),
    ("control-plane", "asset_pipeline/renamer.py"),
    ("control-plane", "asset_pipeline/schemas.py"),
    ("control-plane", "asset_pipeline/transcribe.py"),
    ("control-plane", "asset_pipeline/video_mock.py"),
    ("control-plane", "audit_helpers.py"),
    ("control-plane", "auth_service.py"),
    ("control-plane", "campaigns_service.py"),
    ("control-plane", "catalog_crawler.py"),
    ("control-plane", "context_cards.py"),
    ("control-plane", "conversation_repetition.py"),
    ("control-plane", "deepseek_n8n_service.py"),
    ("control-plane", "deterministic_sdr.py"),
    ("control-plane", "document_candidate_extractor.py"),
    ("control-plane", "embedded_markdown.py"),
    ("control-plane", "event_emitter.py"),
    ("control-plane", "faq_bulk_generator.py"),
    ("control-plane", "graph_action_policy.py"),
    ("control-plane", "graph_bundle.py"),
    ("control-plane", "graph_bundle_adapter.py"),
    ("control-plane", "graph_bundle_error_translations.py"),
    ("control-plane", "graph_bundle_publisher.py"),
    ("control-plane", "graph_bundle_view.py"),
    ("control-plane", "graph_compiler_v3.py"),
    ("control-plane", "graph_context_resolver_v2.py"),
    ("control-plane", "graph_conversation_contract.py"),
    ("control-plane", "graph_document_publisher.py"),
    ("control-plane", "graph_json_importer.py"),
    ("control-plane", "graph_json_v21_adapter.py"),
    ("control-plane", "graph_json_v2_backfill.py"),
    ("control-plane", "graph_json_v2_store.py"),
    ("control-plane", "graph_json_v2_validator.py"),
    ("control-plane", "graph_json_validator.py"),
    ("control-plane", "graph_markdown.py"),
    ("control-plane", "graph_validation.py"),
    ("control-plane", "integration_service.py"),
    ("control-plane", "kb_intake_service.py"),
    ("control-plane", "knowledge_catalog.py"),
    ("control-plane", "knowledge_graph.py"),
    ("control-plane", "knowledge_lifecycle.py"),
    ("control-plane", "knowledge_rag_backfill.py"),
    ("control-plane", "knowledge_rag_intake.py"),
    ("control-plane", "knowledge_service.py"),
    ("control-plane", "knowledge_taxonomy.py"),
    ("control-plane", "model_router.py"),
    ("control-plane", "n8n_client.py"),
    ("control-plane", "product_import_service.py"),
    ("control-plane", "public_site.py"),
    ("control-plane", "sdr_documents.py"),
    ("control-plane", "secret_store.py"),
    ("control-plane", "sofia_faq_tool.py"),
    ("control-plane", "sofia_orchestrator.py"),
    ("control-plane", "sofia_tools.py"),
    ("control-plane", "sre_logger.py"),
    ("control-plane", "supabase_client.py"),
    ("control-plane", "vault_sync.py"),
    ("conversation-runtime", "agents_service.py"),
    ("conversation-runtime", "auth_service.py"),
    ("conversation-runtime", "context_cards.py"),
    ("conversation-runtime", "conversation_repetition.py"),
    ("conversation-runtime", "conversation_runtime.py"),
    ("conversation-runtime", "deepseek_n8n_service.py"),
    ("conversation-runtime", "deterministic_appointment.py"),
    ("conversation-runtime", "deterministic_sdr.py"),
    ("conversation-runtime", "event_emitter.py"),
    ("conversation-runtime", "graph_action_policy.py"),
    ("conversation-runtime", "graph_agent_runtime_v3.py"),
    ("conversation-runtime", "graph_bundle.py"),
    ("conversation-runtime", "graph_compiler_v3.py"),
    ("conversation-runtime", "graph_conversation_contract.py"),
    ("conversation-runtime", "graph_json_v21_adapter.py"),
    ("conversation-runtime", "graph_json_v2_store.py"),
    ("conversation-runtime", "graph_json_v2_validator.py"),
    ("conversation-runtime", "graph_markdown.py"),
    ("conversation-runtime", "graph_proof_checker_v3.py"),
    ("conversation-runtime", "graph_validation.py"),
    ("conversation-runtime", "integration_service.py"),
    ("conversation-runtime", "journey_outcome.py"),
    ("conversation-runtime", "knowledge_graph.py"),
    ("conversation-runtime", "knowledge_service.py"),
    ("conversation-runtime", "knowledge_taxonomy.py"),
    ("conversation-runtime", "lead_qualification.py"),
    ("conversation-runtime", "model_pricing.py"),
    ("conversation-runtime", "model_router.py"),
    ("conversation-runtime", "n8n_client.py"),
    ("conversation-runtime", "public_site.py"),
    ("conversation-runtime", "sdr_documents.py"),
    ("conversation-runtime", "secret_store.py"),
    ("conversation-runtime", "shared_lead_memory.py"),
    ("conversation-runtime", "sre_logger.py"),
    ("conversation-runtime", "supabase_client.py"),
    ("conversation-runtime", "validator_sofia_insights.py"),
    ("conversation-runtime", "wa_validator_service.py"),
    ("transport", "asset_pipeline/ai_fallback.py"),
    ("transport", "asset_pipeline/classifier.py"),
    ("transport", "asset_pipeline/ocr_local.py"),
    ("transport", "asset_pipeline/pdf_text.py"),
    ("transport", "asset_pipeline/renamer.py"),
    ("transport", "asset_pipeline/schemas.py"),
    ("transport", "asset_pipeline/transcribe.py"),
    ("transport", "asset_pipeline/video_mock.py"),
    ("transport", "auth_service.py"),
    ("transport", "conversation_repetition.py"),
    ("transport", "deepseek_n8n_service.py"),
    ("transport", "event_emitter.py"),
    ("transport", "graph_conversation_contract.py"),
    ("transport", "integration_service.py"),
    ("transport", "media_ingest.py"),
    ("transport", "model_router.py"),
    ("transport", "n8n_client.py"),
    ("transport", "public_site.py"),
    ("transport", "secret_store.py"),
    ("transport", "shared_lead_memory.py"),
    ("transport", "sre_logger.py"),
    ("transport", "supabase_client.py"),
    ("transport", "whatsapp_outbox.py"),
    ("transport", "whatsapp_providers/base.py"),
    ("transport", "whatsapp_providers/evolution.py"),
    ("transport", "whatsapp_providers/media.py"),
    ("transport", "whatsapp_providers/meta.py"),
    ("transport", "whatsapp_providers/mock.py"),
    ("transport", "whatsapp_providers/registry.py"),
)

# Subset of DUPLICATED_BASELINE that differs from api/services today, content
# normalised for line endings. This is the graph_compiler_v3.py incident's
# blast radius made visible: graph_compiler_v3.py itself is on this list for
# both control-plane and conversation-runtime, still uncorrected.
DIVERGENT_BASELINE: tuple[tuple[str, str], ...] = (
    ("control-plane", "campaigns_service.py"),
    ("control-plane", "conversation_repetition.py"),
    ("control-plane", "deepseek_n8n_service.py"),
    ("control-plane", "graph_bundle_publisher.py"),
    ("control-plane", "graph_bundle_view.py"),
    ("control-plane", "graph_compiler_v3.py"),
    ("control-plane", "graph_json_v2_validator.py"),
    ("control-plane", "integration_service.py"),
    ("control-plane", "kb_intake_service.py"),
    ("control-plane", "sofia_orchestrator.py"),
    ("control-plane", "supabase_client.py"),
    ("conversation-runtime", "agents_service.py"),
    ("conversation-runtime", "conversation_repetition.py"),
    ("conversation-runtime", "conversation_runtime.py"),
    ("conversation-runtime", "deepseek_n8n_service.py"),
    ("conversation-runtime", "graph_agent_runtime_v3.py"),
    ("conversation-runtime", "graph_compiler_v3.py"),
    ("conversation-runtime", "graph_json_v2_store.py"),
    ("conversation-runtime", "graph_json_v2_validator.py"),
    ("conversation-runtime", "graph_proof_checker_v3.py"),
    ("conversation-runtime", "integration_service.py"),
    ("conversation-runtime", "knowledge_service.py"),
    ("conversation-runtime", "supabase_client.py"),
    ("conversation-runtime", "wa_validator_service.py"),
    ("transport", "conversation_repetition.py"),
    ("transport", "deepseek_n8n_service.py"),
    ("transport", "integration_service.py"),
    ("transport", "supabase_client.py"),
    ("transport", "whatsapp_providers/meta.py"),
)


@pytest.mark.unit
def test_baselines_are_sorted_and_consistent() -> None:
    assert list(DUPLICATED_BASELINE) == sorted(set(DUPLICATED_BASELINE)), (
        "DUPLICATED_BASELINE must be sorted with no duplicate entries."
    )
    assert list(DIVERGENT_BASELINE) == sorted(set(DIVERGENT_BASELINE)), (
        "DIVERGENT_BASELINE must be sorted with no duplicate entries."
    )
    unknown = set(DIVERGENT_BASELINE) - set(DUPLICATED_BASELINE)
    assert not unknown, (
        f"DIVERGENT_BASELINE lists pairs missing from DUPLICATED_BASELINE: {sorted(unknown)}"
    )


@pytest.mark.unit
def test_no_undeclared_duplication_appears() -> None:
    current = set(_discover_duplicated_pairs())
    unexpected = sorted(current - set(DUPLICATED_BASELINE))
    assert not unexpected, (
        "New file(s) duplicated between api/services and an app that are not "
        f"in DUPLICATED_BASELINE: {unexpected}. Carving a copy of a monolith "
        "module into a microservice is exactly how 252cac8 created the stale "
        "graph_compiler_v3.py that later blocked a graph publication -- if "
        "this duplication is intentional, add the pair to DUPLICATED_BASELINE "
        "(and to DIVERGENT_BASELINE too, if its content differs)."
    )


@pytest.mark.unit
def test_no_new_divergence_appears() -> None:
    still_present = [pair for pair in DUPLICATED_BASELINE if _pair_exists(*pair)]
    divergent_now = {pair for pair in still_present if not _is_identical(*pair)}
    new_divergence = sorted(divergent_now - set(DIVERGENT_BASELINE))
    assert not new_divergence, (
        "A microservice copy that matched api/services at baseline time now "
        f"differs from it: {new_divergence}. This is precisely the failure "
        "mode from 252cac8, where the carved-out graph_compiler_v3.py froze "
        "at graph-compiler-v3.6.2 while the monolith moved on to "
        "graph-compiler-v3.6.4, and the deployed compiler went on to compute "
        "a different checksum than the one a graph publication had approved. "
        "If this divergence is deliberate, add the pair to DIVERGENT_BASELINE "
        "with eyes open; otherwise port the fix into the microservice copy."
    )


@pytest.mark.unit
def test_resolved_baseline_divergences_can_be_pruned() -> None:
    """A baseline entry going green is progress, not a regression.

    Failing here would train people to leave stale entries in the baseline
    forever rather than fix them, so this never fails -- it only names the
    pairs that are safe to delete from DIVERGENT_BASELINE.
    """
    resolved = [
        pair
        for pair in DIVERGENT_BASELINE
        if _pair_exists(*pair) and _is_identical(*pair)
    ]
    for app, relative_path in resolved:
        warnings.warn(
            f"DIVERGENT_BASELINE entry ({app!r}, {relative_path!r}) is now "
            "identical to api/services -- remove it from DIVERGENT_BASELINE "
            "in tests/test_service_copy_divergence.py.",
            stacklevel=1,
        )
    assert all(_is_identical(*pair) for pair in resolved)
