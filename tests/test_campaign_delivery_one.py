from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_policy_precedence_normalization_and_checksum():
    from services import campaigns_service as service

    persona = {"config": {"contact_policy": {"daily_send_limit": 80, "hourly_send_limit": 30}}}
    audience = {"metadata": {"contact_policy": {"daily_send_limit": 50}}}
    policy, checksum = service.resolve_contact_policy(
        persona=persona,
        audience=audience,
        campaign_overrides={"daily_send_limit": 20, "max_total_sends": 10, "max_unique_leads": 99},
        campaign_kind="promotional",
        purpose="ofertas_e_novidades",
    )

    assert policy["daily_send_limit"] == 20
    assert policy["hourly_send_limit"] == 20
    assert policy["max_unique_leads"] == 10
    assert policy["campaign_kind"] == "promotional"
    assert checksum == service._canonical_checksum(policy)


def test_policy_rejects_unknown_fields():
    from services import campaigns_service as service

    with pytest.raises(HTTPException) as error:
        service.normalize_contact_policy({"invented_limit": 10})
    assert error.value.status_code == 422


def test_revocation_does_not_expire_but_grant_does():
    from services import campaigns_service as service

    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    revoked = {1: {"id": "revoked", "status": "revoked", "valid_until": expired}}
    granted = {1: {"id": "granted", "status": "granted", "valid_until": expired}}

    assert service.resolve_applicable_consent(revoked, 1) == ("revoked", "revoked")
    assert service.resolve_applicable_consent(granted, 1) == ("unknown", "granted")


def test_eligibility_keeps_persona_consent_and_provider_blocks_distinct():
    from services import campaigns_service as service

    lead = {"id": 7, "persona_id": "p1", "telefone": "+55 51 99999-0000"}
    base = {
        "lead": lead,
        "selected_audience_id": "a1",
        "semantic_audience_id": "a1",
        "campaign_kind": "promotional",
        "consent_status": "granted",
        "provider_ready": True,
        "persona_id": "p1",
    }
    assert service.evaluate_recipient_eligibility(**base) == (True, None, "none", "valid")
    assert service.evaluate_recipient_eligibility(**{**base, "persona_id": "p2"})[1] == "persona_mismatch"
    assert service.evaluate_recipient_eligibility(**{**base, "consent_status": "revoked"})[1] == "consent_revoked_or_refused"
    assert service.evaluate_recipient_eligibility(**{**base, "provider_ready": False})[1] == "provider_unavailable"


def test_meta_mock_is_qa_only_and_requires_an_active_meta_binding(monkeypatch):
    from services import campaigns_service as service

    binding = {
        "provider": "meta_cloud",
        "connection_status": "connected",
        "provider_secret_ciphertext": None,
        "whatsapp_phone_number_id": None,
    }
    monkeypatch.setenv("ENVIRONMENT", "qa")
    monkeypatch.setenv("AI_BRAIN_META_MOCK", "true")
    assert service.meta_mock_enabled() is True
    assert service.meta_provider_ready(binding) is True
    assert service.meta_provider_ready({**binding, "provider": "other"}) is True
    assert service.meta_provider_ready(None) is True

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert service.meta_mock_enabled() is False
    assert service.meta_provider_ready(binding) is False


class _Query:
    def __init__(self, table: str):
        self.table = table

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: self


class _Client:
    def table(self, name: str) -> _Query:
        return _Query(name)


def test_preview_deduplicates_imports_and_freezes_a_stable_checksum(monkeypatch):
    from services import campaigns_service as service

    monkeypatch.setenv("BULK_CAMPAIGNS_ROLLOUT1_ENABLED", "true")

    persona = {"id": "p1", "slug": "persona-1", "config": {}}
    audience = {"id": "a1", "persona_id": "p1", "slug": "grupo", "name": "Grupo", "metadata": {"kind": "semantic_group"}}
    batches = [
        {"id": "b1", "persona_id": "p1", "status": "completed"},
        {"id": "b2", "persona_id": "p1", "status": "completed"},
    ]
    leads = [
        {"id": 1, "persona_id": "p1", "telefone": "5551999990001", "nome": "Um"},
        {"id": 2, "persona_id": "p1", "telefone": "5551999990002", "nome": "Dois"},
    ]

    monkeypatch.setattr(service.supabase_client, "get_persona_by_id", lambda _id: persona)
    monkeypatch.setattr(service.supabase_client, "get_audience", lambda _id: audience)
    monkeypatch.setattr(service.supabase_client, "get_client", lambda: _Client())
    monkeypatch.setattr(service.supabase_client, "get_active_whatsapp_binding", lambda _id: {
        "provider": "meta_cloud", "connection_status": "connected",
        "provider_secret_ciphertext": "cipher", "whatsapp_phone_number_id": "123",
    })
    monkeypatch.setattr(service, "_rows", lambda query: batches if query.table == "lead_import_batches" else [])
    monkeypatch.setattr(service, "_campaign_leads", lambda _ids: (leads, {1: {"b1", "b2"}, 2: {"b2"}}))
    monkeypatch.setattr(service, "_semantic_membership_map", lambda _persona, _leads: {1: "a1", 2: "a1"})
    monkeypatch.setattr(service, "_latest_consents", lambda **_kwargs: {
        2: {"id": "c2", "status": "revoked"},
    })

    payload = {
        "persona_id": "p1", "audience_id": "a1", "import_batch_ids": ["b1", "b2"],
        "campaign_kind": "consent_request", "purpose": "ofertas_e_novidades",
        "provider": "meta_cloud", "template_name": "consentimento_v1",
    }
    first = service.preview_campaign(payload)
    second = service.preview_campaign(payload)

    assert first["counts"] == {
        "selected_unique": 2, "eligible": 1, "blocked": 1, "duplicate_rows_removed": 1,
    }
    assert first["blocked_reasons"] == {"consent_revoked_or_refused": 1}
    assert first["preview_checksum"] == second["preview_checksum"]


def test_migration_models_separate_campaign_dimensions_and_backend_only_access():
    sql = (ROOT / "supabase" / "migrations" / "087_campaign_delivery_one.sql").read_text(encoding="utf-8").lower()

    for table in (
        "lead_import_batches", "lead_import_rows", "contact_consents",
        "campaign_revisions", "campaign_revision_imports", "campaign_recipients",
    ):
        assert f"create table if not exists public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql

    assert "response_received_at" in sql
    assert "response_attributed_at" in sql
    assert "retries_stopped_at" in sql
    assert "consent_response_status" in sql
    assert "provider_attempt_count" in sql
    assert "commercial_attempt_count" in sql
    assert "create_campaign_draft_v1" in sql
    assert "record_contact_consent_v1" in sql
    assert "replace_lead_semantic_group_v1" in sql
    assert "message_origin <> 'campaign'" in sql


def test_compose_grant_finalizer_does_not_reopen_campaign_tables():
    grant_runner = (ROOT / "scripts" / "apply_migrations.py").read_text(encoding="utf-8").lower()

    for table in (
        "lead_import_batches",
        "lead_import_rows",
        "contact_consents",
        "campaign_revisions",
        "campaign_revision_imports",
        "campaign_recipients",
    ):
        assert (
            f"revoke all on table public.{table} from public, anon, authenticated;"
            in grant_runner
        )
