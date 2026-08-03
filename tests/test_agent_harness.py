from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from schemas.agent_harness import CardDraft, ToolEffect, ToolGrant, ToolResult, ToolRisk
from services.agent_harness import MAX_DELEGATION_DEPTH, MAX_STEPS_PER_RUN, SofiaAgentHarness, validate_delegation
from services.agent_harness_repository import redact
from services.agent_harness_tools import HARNESS_TOOL_REGISTRY, parse_contacts
from services.agent_tool_registry import ToolManifest, ToolRegistry
from services.model_router import _messages_for_anthropic, _messages_for_openai


def test_manifest_registry_has_unique_typed_capabilities_and_no_deprecated_tools():
    HARNESS_TOOL_REGISTRY.validate()
    tools = HARNESS_TOOL_REGISTRY.all(model_visible_only=True)
    names = [tool.name for tool in tools]
    assert len(names) == len(set(names))
    assert "contacts.parse_list" in names
    assert "campaigns.cancel" in names
    assert "graph.publish_patch" in names
    assert all(tool.handler and tool.schema_checksum for tool in tools)
    assert all(tool.input_model.model_json_schema()["type"] == "object" for tool in tools)


def test_manifest_rejects_invalid_arguments_and_invalid_return():
    parse_manifest = HARNESS_TOOL_REGISTRY.get("contacts.parse_list")
    assert parse_manifest is not None
    with pytest.raises(ValidationError):
        parse_manifest.invoke({}, {"raw_text": ""})

    class StrictInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int

    manifest = ToolManifest(
        name="test.invalid-output", version="1.0.0", owner_agent="qa_validator",
        description="test", input_model=StrictInput, output_model=ToolResult,
        effect=ToolEffect.READ, risk=ToolRisk.LOW, permission="view",
        persona_scoped=False, timeout_seconds=1, idempotent=True,
        handler=lambda _context, **_args: {"summary": "missing ok"},
    )
    with pytest.raises(ValidationError):
        manifest.invoke({}, {"value": 1})


def test_registry_rejects_duplicate_names_and_non_idempotent_write():
    manifest = HARNESS_TOOL_REGISTRY.get("contacts.parse_list")
    assert manifest is not None
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([manifest, manifest])

    invalid = ToolManifest(
        name="test.write", version="1", owner_agent="x", description="x",
        input_model=manifest.input_model, output_model=ToolResult,
        effect=ToolEffect.WRITE, risk=ToolRisk.HIGH, permission="edit",
        persona_scoped=True, timeout_seconds=1, idempotent=False,
        handler=lambda _context, **_args: {"ok": True},
    )
    with pytest.raises(ValueError, match="idempotency"):
        ToolRegistry([invalid]).validate()


def test_phone_list_normalizes_and_deduplicates_baita_numbers():
    result = parse_contacts({}, raw_text="51982608510, 51 98260-8510; 51985557065")
    assert result["counts"] == {
        "input_candidates": 3,
        "valid_unique": 2,
        "duplicates_removed": 1,
        "invalid": 0,
    }
    assert [item["phone"] for item in result["contacts"]] == ["5551982608510", "5551985557065"]


def test_redaction_removes_phone_email_and_sensitive_collections():
    redacted = redact({
        "message": "ligar +55 51 98260-8510 para pessoa@empresa.com",
        "contacts": [{"phone": "5551982608510"}],
        "counts": {"valid_unique": 1},
    })
    assert "98260" not in redacted["message"]
    assert "pessoa@" not in redacted["message"]
    assert redacted["contacts"] == {"redacted": True, "count": 1}
    assert redacted["counts"] == {"valid_unique": 1}
    assert redact("b4cfffa3-9735-4bb9-831e-d3718a5e7b67") == "b4cfffa3-9735-4bb9-831e-d3718a5e7b67"


def test_grant_is_bound_to_user_persona_tool_version_schema_and_expiry_contract():
    manifest = HARNESS_TOOL_REGISTRY.get("imports.create")
    assert manifest is not None
    now = datetime.now(timezone.utc)
    grant = ToolGrant(
        tool_name=manifest.name, tool_version=manifest.version,
        schema_checksum=manifest.schema_checksum, granted_by="user-1",
        granted_at=now, expires_at=now + timedelta(hours=1), reason="Teste controlado",
    )
    assert grant.is_valid(now=now, tool_name=manifest.name, version=manifest.version, checksum=manifest.schema_checksum)
    assert not grant.is_valid(now=now, tool_name=manifest.name, version="2.0.0", checksum=manifest.schema_checksum)
    assert not grant.model_copy(update={"revoked_at": now}).is_valid(
        now=now, tool_name=manifest.name, version=manifest.version, checksum=manifest.schema_checksum,
    )


def test_delegation_depth_and_cycles_are_blocked():
    assert validate_delegation(["sofia"], "campaign_operator") == ["sofia", "campaign_operator"]
    assert validate_delegation(["sofia", "campaign_operator"], "qa_validator") == ["sofia", "campaign_operator", "qa_validator"]
    with pytest.raises(Exception, match="Ciclo"):
        validate_delegation(["sofia", "campaign_operator"], "sofia")
    with pytest.raises(Exception, match="Profundidade"):
        validate_delegation(["sofia", "campaign_operator", "qa_validator"], "fourth")
    assert MAX_DELEGATION_DEPTH == 2
    assert MAX_STEPS_PER_RUN == 12


class _FakeRepository:
    def __init__(self, grants: list[ToolGrant]):
        self._steps = []
        self._grants = grants

    def list_steps(self, _run_id):
        return list(self._steps)

    def grants(self, _user_id, _persona_id):
        return self._grants

    def create_step(self, payload):
        row = {"id": f"step-{len(self._steps) + 1}", **payload}
        self._steps.append(row)
        return row

    def update_step(self, step_id, changes):
        row = next(item for item in self._steps if item["id"] == step_id)
        row.update(changes)
        return row

    def audit(self, *_args, **_kwargs):
        return None


def test_destructive_tool_requires_point_confirmation_even_with_persistent_grant():
    manifest = HARNESS_TOOL_REGISTRY.get("campaigns.cancel")
    assert manifest is not None
    now = datetime.now(timezone.utc)
    grant = ToolGrant(
        tool_name=manifest.name, tool_version=manifest.version,
        schema_checksum=manifest.schema_checksum, granted_by="admin",
        granted_at=now, expires_at=now + timedelta(hours=1), reason="Grant de teste",
    )
    repository = _FakeRepository([grant])
    harness = SofiaAgentHarness(repository)  # type: ignore[arg-type]
    result = harness.execute_tool(
        run={"id": "run-1"},
        session={"id": "session-1", "persona_id": "persona-1"},
        user_id="user-1", tool_name=manifest.name,
        arguments={
            "campaign_id": "campaign-1", "expected_revision": 1,
            "idempotency_key": "cancel-key-123", "reason": "Cancelar teste",
        },
        idempotency_key="step-key-123", one_time_approval=False,
    )
    assert result["status"] == "awaiting_approval"
    assert repository._steps[0]["tool_name"] == "campaigns.cancel"


def test_native_openai_tool_transcript_preserves_call_id():
    canonical = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_123", "name": "x", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "call_123", "name": "x", "content": {"ok": True}},
    ]
    converted = _messages_for_openai(canonical)
    assert converted[0]["tool_calls"][0]["id"] == "call_123"
    assert converted[1]["role"] == "tool"
    assert converted[1]["tool_call_id"] == "call_123"


def test_native_anthropic_tool_transcript_preserves_call_id():
    canonical = [
        {"role": "assistant", "content": "vou consultar", "tool_calls": [{"id": "toolu_123", "name": "x", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "toolu_123", "name": "x", "content": {"ok": True}},
    ]
    converted = _messages_for_anthropic(canonical)
    assert converted[0]["content"][1]["id"] == "toolu_123"
    assert converted[1]["role"] == "user"
    assert converted[1]["content"][0]["tool_use_id"] == "toolu_123"


def test_card_draft_requires_source_and_content_contract():
    card = CardDraft(
        node_type="faq", slug="faq-preco", title="Quanto custa?",
        content={"pergunta": "Quanto custa?", "resposta": "Pendente."},
    )
    assert card.source == "pending_source"
    assert card.status == "pending_validation"
    with pytest.raises(ValidationError):
        CardDraft(node_type="product", slug="produto", title="Produto")


def test_migration_is_service_only_and_contains_conservative_backfill():
    sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "088_sofia_agent_harness.sql").read_text(encoding="utf-8").lower()
    for table in ("agent_sessions", "agent_runs", "agent_run_steps"):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    assert "from public.sofia_plan_sessions" in sql
    assert "agent_tool_grants" in sql
    assert "graph_card_specialist" in sql
    assert "campaign_operator" in sql
    assert "qa_validator" in sql


def test_semantic_group_replay_checks_existing_membership_before_insert():
    sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "089_fix_semantic_group_replay.sql").read_text(encoding="utf-8").lower()
    lookup = "select * into v_membership"
    insert = "insert into public.lead_audience_memberships"
    assert lookup in sql
    assert insert in sql
    assert sql.index(lookup) < sql.index(insert)
    assert "if v_membership.id is null" in sql
