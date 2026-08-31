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
from repositories import control_plane as control_plane_repository
from services import supabase_client
from workers.runner import WORKERS


ROOT = Path(__file__).resolve().parents[2]


FORBIDDEN_PREFIXES = (
    "/agents",
    "/wa-validator",
    "/webhooks",
    "/messages",
    "/process",
)


def test_service_identity_and_readiness_surface():
    assert main.app.title == "Brain Control Plane"
    paths = set(main.app.openapi()["paths"])
    assert "/health" in paths
    assert "/health/ready" in paths
    assert "/messaging/campaigns" in paths
    assert "/messaging/campaigns/{campaign_id}/send" in paths
    assert "/internal/v1/control-plane/assets/{asset_id}/attach-inbound-graph" in paths
    assert "/agent-harness/sessions" in paths
    assert "/sofia/graph-command" in paths
    assert "/qa/reset-destructive" in paths


def test_worker_group_is_domain_scoped():
    assert set(WORKERS) == {
        "flow_validator",
        "health_check",
        "kb_sync",
        "n8n_mirror",
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


def test_control_plane_image_excludes_tests_and_one_time_scripts():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for excluded in ("api/scripts/*", "api/tests/", "tests/"):
        assert excluded in dockerignore
    assert "!api/scripts/resync_graph_agent_workflows.py" in dockerignore


def test_runtime_and_transport_engines_are_absent_from_control_plane():
    forbidden = (
        "api/services/conversation_runtime.py",
        "api/services/media_ingest.py",
        "api/services/wa_validator_service.py",
        "api/services/asset_graph_contract.py",
        "api/services/graph_agent_runtime_v3.py",
        "api/services/graph_proof_checker_v3.py",
        "api/services/journey_outcome.py",
        "api/services/lead_qualification.py",
        "api/services/whatsapp_providers",
        "api/services/whatsapp_outbox.py",
    )
    assert [
        path for path in forbidden
        if (ROOT / path).is_file()
        or ((ROOT / path).is_dir() and any((ROOT / path).rglob("*.py")))
    ] == []


def _jwt_for_role(role: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"role": role}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_database_jwt_is_restricted_to_manifest_role(monkeypatch):
    expected = _jwt_for_role("brain_control_plane")
    monkeypatch.setenv("BRAIN_DB_JWT", expected)
    assert supabase_client._validated_db_jwt() == expected

    monkeypatch.setenv("BRAIN_DB_JWT", _jwt_for_role("service_role"))
    with pytest.raises(RuntimeError, match="brain_control_plane"):
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


def test_legacy_database_module_is_control_plane_repository_alias():
    assert supabase_client is control_plane_repository


def test_control_plane_repository_has_only_the_reachable_domain_surface():
    source = (ROOT / "api" / "repositories" / "control_plane.py").read_text(encoding="utf-8")
    functions = {
        node.name
        for node in ast.parse(source).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert len(functions) == 199
    assert functions.isdisjoint({
        "claim_conversation_commit",
        "claim_pending_media_assets",
        "claim_whatsapp_buffer",
        "commit_graph_turn_and_outbox_v4",
        "enqueue_whatsapp_message",
        "requeue_waiting_human_whatsapp_buffer",
    })


def test_internal_inbound_asset_graph_command_is_authenticated(monkeypatch):
    from routes import internal_assets

    calls = []
    monkeypatch.setattr(internal_assets.internal_auth, "authorize_webhook_token", calls.append)
    monkeypatch.setattr(
        internal_assets.inbound_media_graph,
        "attach",
        lambda asset_id: {"attached": True, "asset_id": asset_id},
    )

    result = internal_assets.attach_inbound_graph("asset-1", "internal-token")

    assert calls == ["internal-token"]
    assert result == {"attached": True, "asset_id": "asset-1"}
