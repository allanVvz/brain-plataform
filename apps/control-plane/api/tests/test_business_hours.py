"""Agent business hours: bundle default + the value saved on the Agentes screen."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import internal_outbound_policy, personas
from services import business_hours

TOCK_BUNDLE = {
    "enabled": True, "start": "08:00", "end": "20:00", "timezone": "America/Sao_Paulo",
    "rule_node_id": "rule:tock-business-hours",
}


def _publication(hours=TOCK_BUNDLE):
    policy = {"business_hours": hours} if hours is not None else {}
    return {
        "id": "pub-1", "version": 38, "checksum": "sha256:published",
        "document_json": {"nodes": [{"node_type": "persona", "data": {"conversation_policy": policy}}]},
    }


def test_bundle_hours_are_the_default():
    result = business_hours.effective({"config": {}}, _publication())
    assert result["enabled"] is True and result["source"] == "bundle"
    assert (result["start"], result["end"], result["timezone"]) == ("08:00", "20:00", "America/Sao_Paulo")


def test_screen_values_override_the_bundle_field_by_field():
    persona = {"config": {"business_hours": {"end": "22:00"}}}
    result = business_hours.effective(persona, _publication())
    assert (result["start"], result["end"]) == ("08:00", "22:00")
    assert result["source"] == "agent" and result["enabled"] is True


def test_switching_off_on_the_screen_beats_an_enabled_bundle():
    result = business_hours.effective({"config": {"business_hours": {"enabled": False}}}, _publication())
    assert result["enabled"] is False and result["switched_off"] is True


def test_persona_without_any_hours_is_unrestricted_and_can_be_given_some():
    assert business_hours.effective({"config": {}}, _publication(None))["switched_off"] is True
    given = {"config": {"business_hours": {
        "enabled": True, "start": "09:00", "end": "18:00", "timezone": "America/Sao_Paulo"}}}
    assert business_hours.effective(given, _publication(None))["enabled"] is True


@pytest.mark.parametrize("patch", [{"start": "8h"}, {"end": "25:99"}, {"timezone": "Mars/Base"}])
def test_invalid_values_are_rejected(patch):
    with pytest.raises(business_hours.InvalidBusinessHours):
        business_hours.validate_patch(patch)


def _setup_patch(monkeypatch, config=None, publication=None):
    row = {"value": {
        "slug": "tock", "id": "persona-1", "process_mode": "internal", "config": config or {},
        "migration_applied": True, "routing_source": "persona_columns",
    }}
    saved, events = [], []
    monkeypatch.setattr(personas.supabase_client, "get_persona_routing", lambda _s: row["value"])
    monkeypatch.setattr(personas.supabase_client, "get_workflow_bindings", lambda _i: [])
    monkeypatch.setattr(personas.supabase_client, "get_active_graph_publication", lambda _i: publication or _publication())

    def update_config(slug, cfg, **_k):
        saved.append(cfg)
        row["value"] = {**row["value"], "config": cfg}

    monkeypatch.setattr(personas.supabase_client, "update_persona_config", update_config)
    monkeypatch.setattr(personas.supabase_client, "insert_event", lambda event, **_k: events.append(event))
    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _u: True)
    monkeypatch.setattr(personas.auth_service, "current_user", lambda _r: {"id": "admin-1"})
    return saved, events


def _request():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "admin-1", "role": "admin"}))


def test_admin_saves_hours_from_the_screen_and_reads_them_back(monkeypatch):
    saved, events = _setup_patch(monkeypatch, config={"keep": "me"})
    result = personas.update_routing(
        "tock", personas.RoutingUpdate(business_hours={"start": "09:00", "end": "21:00"}), _request(),
    )
    assert saved[0]["keep"] == "me"
    assert saved[0]["business_hours"] == {"start": "09:00", "end": "21:00"}
    assert result["business_hours"]["source"] == "agent"
    assert (result["business_hours"]["start"], result["business_hours"]["end"]) == ("09:00", "21:00")
    assert events[0]["event_type"] == "persona.business_hours_updated"
    assert events[0]["payload"]["after"] == {"start": "09:00", "end": "21:00"}


def test_switching_off_keeps_the_saved_times(monkeypatch):
    saved, _ = _setup_patch(monkeypatch, config={"business_hours": {"start": "09:00"}})
    result = personas.update_routing(
        "tock", personas.RoutingUpdate(business_hours={"enabled": False}), _request(),
    )
    assert saved[0]["business_hours"] == {"start": "09:00", "enabled": False}
    assert result["business_hours"]["enabled"] is False


@pytest.mark.parametrize("patch", [{"start": "21:00", "end": "08:00"}, {"timezone": "Nope/Zone"}, {"end": "07:00"}])
def test_bad_hours_are_a_400_and_nothing_is_saved(monkeypatch, patch):
    saved, _ = _setup_patch(monkeypatch)
    with pytest.raises(HTTPException) as bad:
        personas.update_routing("tock", personas.RoutingUpdate(business_hours=patch), _request())
    assert bad.value.status_code == 400 and saved == []


def test_turning_hours_on_for_a_persona_without_any_requires_all_fields(monkeypatch):
    saved, _ = _setup_patch(monkeypatch, publication=_publication(None))
    with pytest.raises(HTTPException) as incomplete:
        personas.update_routing("tock", personas.RoutingUpdate(business_hours={"enabled": True}), _request())
    assert incomplete.value.status_code == 400 and saved == []
    personas.update_routing(
        "tock",
        personas.RoutingUpdate(business_hours={
            "enabled": True, "start": "09:00", "end": "18:00", "timezone": "America/Sao_Paulo"}),
        _request(),
    )
    assert saved[0]["business_hours"]["enabled"] is True


def test_non_admin_cannot_change_hours(monkeypatch):
    _setup_patch(monkeypatch)
    monkeypatch.setattr(personas.auth_service, "is_admin", lambda _u: False)
    with pytest.raises(HTTPException) as denied:
        personas.update_routing("tock", personas.RoutingUpdate(business_hours={"enabled": False}), _request())
    assert denied.value.status_code == 403


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, {"timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00"}),
        ({"business_hours": {"end": "22:00"}}, {"timezone": "America/Sao_Paulo", "start": "08:00", "end": "22:00"}),
        ({"business_hours": {"enabled": False}}, None),
    ],
)
def test_outbound_policy_serves_the_effective_hours(monkeypatch, config, expected):
    monkeypatch.setattr(internal_outbound_policy.internal_auth, "authorize_webhook_token", lambda _t: None)
    monkeypatch.setattr(
        internal_outbound_policy.supabase_client, "get_persona_by_id",
        lambda _i: {"slug": "tock", "config": config},
    )
    monkeypatch.setattr(internal_outbound_policy.supabase_client, "get_active_graph_publication", lambda _i: _publication())
    result = internal_outbound_policy.published_outbound_policy("persona-1", "token")
    if expected is None:
        assert result["published_business_hours"] is None
    else:
        assert result["published_business_hours"] == {**expected, "graph_version": 38, "graph_checksum": "sha256:published"}
