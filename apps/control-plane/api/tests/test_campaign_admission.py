from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from services import campaigns_service as service


@pytest.mark.parametrize("change", [
    {"persona_id": "other"},
    {"provider": "evolution_baileys"},
    {"status": "archived"},
    {"meta_approval_status": "pending"},
    {"meta_template_id": None},
])
def test_meta_template_must_match_scope_and_approval(change):
    template = {
        "persona_id": "persona-1", "provider": "meta_cloud", "status": "active",
        "meta_approval_status": "approved", "meta_template_id": "meta-1",
        **change,
    }
    with pytest.raises(HTTPException) as error:
        service.validate_campaign_template(
            template, template_id="template-1", persona_id="persona-1", provider="meta_cloud"
        )
    assert error.value.status_code == 409


def test_approved_template_is_accepted_and_missing_row_is_rejected():
    template = {
        "persona_id": "persona-1", "provider": "meta_cloud", "status": "active",
        "meta_approval_status": "approved", "meta_template_id": "meta-1",
    }
    service.validate_campaign_template(
        template, template_id="template-1", persona_id="persona-1", provider="meta_cloud"
    )
    with pytest.raises(HTTPException):
        service.validate_campaign_template(
            None, template_id="template-1", persona_id="persona-1", provider="meta_cloud"
        )


def test_send_admission_rechecks_approval_at_meta(monkeypatch):
    template = {"meta_template_id": "meta-1"}
    monkeypatch.setattr(service.transport_client, "get_meta_template_status",
                        lambda *args, **kwargs: {"status": "PAUSED"})
    with pytest.raises(HTTPException) as error:
        service.verify_meta_template_approval(template, "persona-1")
    assert error.value.status_code == 409
    monkeypatch.setattr(service.transport_client, "get_meta_template_status",
                        lambda *args, **kwargs: {"status": "APPROVED"})
    service.verify_meta_template_approval(template, "persona-1")


def test_meta_campaign_without_template_never_resolves_to_plain_text():
    result = service.resolve_send_payload(
        provider="meta_cloud", send_mode="controlled_test",
        revision_content={"message": "plain text"}, template=None,
        lead={"id": 1}, persona_id="persona-1",
    )
    assert result == {"mode": "blocked", "reason": "template_required"}


def test_semantic_group_source_deduplicates_and_rejects_foreign_persona(monkeypatch):
    filters = []

    class Query:
        def __init__(self, table):
            self.table = table
            self.ids = []

        def select(self, *_args): return self
        def eq(self, *args):
            filters.append(args)
            return self
        def order(self, *_args): return self
        def in_(self, _field, ids):
            self.ids = ids
            return self
        def limit(self, *_args): return self
        def range(self, start, end):
            self.start, self.end = start, end
            return self

    class Client:
        def table(self, name): return Query(name)

    def rows(query):
        if query.table == "lead_audience_memberships":
            return [{"lead_id": 1}, {"lead_id": 1}, {"lead_id": 2}]
        return [{"id": 1, "persona_id": "persona-1"}]

    monkeypatch.setattr(service.supabase_client, "get_client", lambda: Client())
    monkeypatch.setattr(service, "_rows", rows)
    leads, provenance = service._semantic_group_leads("persona-1", "group-1")
    assert [row["id"] for row in leads] == [1]
    assert provenance == {1: set()}
    assert ("persona_id", "persona-1") in filters


def test_selected_semantic_membership_survives_membership_in_another_group(monkeypatch):
    class Query:
        def __init__(self, table):
            self.table = table
            self.filters = []

        def select(self, *_args): return self
        def eq(self, key, value):
            self.filters.append((key, value))
            return self
        def in_(self, *_args): return self
        def limit(self, *_args): return self

    class Client:
        def table(self, name): return Query(name)

    def rows(query):
        if query.table == "audiences":
            return [{"id": "selected", "metadata": {"kind": "semantic_group"}}]
        assert ("audience_id", "selected") in query.filters
        return [{"lead_id": 1, "audience_id": "selected"}]

    monkeypatch.setattr(service.supabase_client, "get_client", lambda: Client())
    monkeypatch.setattr(service, "_rows", rows)
    assert service._semantic_membership_map("persona-1", [1], "selected") == {1: "selected"}


def test_preview_overlap_blocks_pending_reactivation_and_prior_campaign(monkeypatch):
    now = datetime.now(timezone.utc)

    class Query:
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def in_(self, *_args): return self
        def order(self, *_args): return self
        def range(self, *_args): return self

    class Client:
        def table(self, _name): return Query()

    monkeypatch.setattr(service.supabase_client, "get_client", lambda: Client())
    monkeypatch.setattr(service, "_rows", lambda _query: [
        {"id": "b1", "lead_ref": 1, "message_origin": "proactive",
         "status": "preview_ready", "created_at": (now - timedelta(days=2)).isoformat()},
        {"id": "b2", "lead_ref": 2, "message_origin": "proactive",
         "status": "sent", "created_at": now.isoformat()},
        {"id": "b3", "lead_ref": 3, "message_origin": "campaign",
         "status": "sent", "created_at": (now - timedelta(days=30)).isoformat()},
    ])
    assert service._campaign_overlaps("persona-1", [1, 2, 3], 24) == {
        1: "reactivation_pending", 2: "reactivation_pending",
        3: "campaign_already_contacted",
    }
