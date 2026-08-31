from __future__ import annotations

import ast
import base64
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("SUPABASE_OFFLINE", "true")
os.environ.setdefault("KNOWLEDGE_TAXONOMY_OFFLINE", "true")
os.environ.setdefault("CURRENT_SCHEMA_VERSION", "131")

import main
from repositories import runtime as runtime_repository
from services import supabase_client
from middleware.auth import is_public_path
from workers.runner import WORKERS


ROOT = Path(__file__).resolve().parents[2]


FORBIDDEN_PREFIXES = (
    "/auth",
    "/personas",
    "/knowledge",
    "/webhooks",
    "/messages",
    "/messaging",
)


def test_service_identity_and_readiness_surface():
    assert main.app.title == "Brain Conversation Runtime"
    paths = set(main.app.openapi()["paths"])
    assert "/health" in paths
    assert "/health/ready" in paths
    assert "/process" in paths
    assert "/internal/v1/conversations/context" in paths
    assert "/internal/v1/conversations/execute" in paths
    assert "/internal/v1/agents/leads/{lead_ref}/journey-events" in paths
    assert "/internal/v1/agents/leads/{lead_ref}/journey-state" in paths
    assert "/internal/v1/runtime/leads/{lead_ref}/pause" in paths
    assert "/internal/v1/runtime/leads/{lead_ref}/resume" in paths
    assert "/internal/v1/runtime/leads/decorate" in paths
    assert not any(path.startswith("/agent-harness") for path in paths)
    assert not any(path.startswith("/qa/") for path in paths)
    assert not any(path.startswith("/sofia/") for path in paths)
    assert "/internal/conversations/context" not in paths


def test_worker_group_is_domain_scoped():
    assert set(WORKERS) == {
        "health_check",
        "inactivity_recovery",
        "wa_validator",
    }


def test_public_surface_excludes_other_domains():
    paths = set(main.app.openapi()["paths"])
    offenders = sorted(
        path
        for path in paths
        for prefix in FORBIDDEN_PREFIXES
        if path == prefix or path.startswith(prefix + "/")
    )
    assert offenders == []


def test_runtime_image_excludes_authoring_transport_and_test_tools():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for excluded in ("api/scripts/", "api/tests/", "tests/", "docs/"):
        assert excluded in dockerignore
    for forbidden in ("WhisperModel", "WHISPER_CACHE_PATH", "ffmpeg", "docs/sdr", "/data/vault"):
        assert forbidden not in dockerfile


def test_other_domain_modules_are_not_shipped_in_runtime_source():
    forbidden_files = (
        "api/routes/agent_harness.py",
        "api/routes/qa_contract.py",
        "api/services/agent_harness.py",
        "api/services/agent_harness_repository.py",
        "api/services/agent_harness_tools.py",
        "api/services/campaigns_service.py",
        "api/services/graph_document_publisher.py",
        "api/services/graph_json_importer.py",
        "api/services/knowledge_lifecycle.py",
        "api/services/knowledge_rag_intake.py",
        "api/services/sofia_faq_tool.py",
        "api/services/sofia_orchestrator.py",
        "api/services/vault_sync.py",
        "api/services/whatsapp_outbox.py",
        "api/services/media_ingest.py",
        "api/services/conversation_graph.py",
        "api/services/asset_graph_contract.py",
        "api/services/approved_knowledge_snapshots.py",
        "api/services/embedded_markdown.py",
    )
    assert [path for path in forbidden_files if (ROOT / path).exists()] == []


def test_only_versioned_internal_journey_paths_are_service_authenticated():
    assert is_public_path("/internal/v1/agents/leads/42/journey-events") is True
    assert is_public_path("/internal/v1/agents/leads/42/journey-state") is True
    assert is_public_path("/internal/agents/leads/42/journey-events") is False
    assert is_public_path("/internal/v1/runtime/leads/42/resume") is True
    assert is_public_path("/internal/runtime/leads/42/resume") is False


def _jwt_for_role(role: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"role": role}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_database_jwt_is_restricted_to_manifest_role(monkeypatch):
    expected = _jwt_for_role("brain_runtime")
    monkeypatch.setenv("BRAIN_DB_JWT", expected)
    assert supabase_client._validated_db_jwt() == expected

    monkeypatch.setenv("BRAIN_DB_JWT", _jwt_for_role("service_role"))
    with pytest.raises(RuntimeError, match="brain_runtime"):
        supabase_client._validated_db_jwt()


def test_readiness_uses_image_schema_requirement_and_build_metadata(monkeypatch):
    from routes import health

    monkeypatch.setenv("CURRENT_SCHEMA_VERSION", "131")
    monkeypatch.setenv("REQUIRED_SCHEMA_VERSION", "131")
    monkeypatch.setenv("SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("BUILD_DIGEST", "sha256:image")
    monkeypatch.setattr(health.supabase_client, "ping_supabase", lambda: (True, "ok"))

    result = health.health_ready()

    assert result["status"] == "ready"
    assert result["required_schema_version"] == 131
    assert result["source_sha"] == "a" * 40
    assert result["build_digest"] == "sha256:image"


def test_legacy_database_module_is_runtime_repository_alias():
    assert supabase_client is runtime_repository


def test_runtime_repository_has_only_the_reachable_domain_surface():
    source = (ROOT / "api" / "repositories" / "runtime.py").read_text(encoding="utf-8")
    functions = {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert len(functions) == 147
    assert "complete_whatsapp_buffer" not in functions
    assert functions.isdisjoint({
        "claim_pending_media_assets",
        "claim_whatsapp_buffer",
        "list_public_site_formats",
        "update_persona_config",
        "create_campaign",
        "activate_graph_projection_v2",
        "commit_graph_version_v2",
        "upsert_kb_entry",
    })


def test_internal_lead_decoration_authenticates_and_stays_runtime_owned(monkeypatch):
    from routes import leads

    calls = []
    monkeypatch.setattr(leads.internal_auth, "authorize_webhook_token", calls.append)
    monkeypatch.setattr(
        leads.lead_qualification,
        "filter_validation_scope",
        lambda rows, scope: rows if scope == "exclude" else [],
    )
    monkeypatch.setattr(
        leads.journey_outcome,
        "decorate_leads",
        lambda rows, persona_id: [{**row, "business_model": "sales"} for row in rows],
    )
    body = leads.InternalLeadDecorationBody(
        leads=[{"id": 42}], persona_id="persona-1", validation_scope="exclude"
    )

    result = leads.decorate_leads_internal(body, "internal-token")

    assert calls == ["internal-token"]
    assert result == {"items": [{"id": 42, "business_model": "sales"}]}
