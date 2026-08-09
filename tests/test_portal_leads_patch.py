from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from routes import portal


def request_for(user: dict, access: list[dict]):
    return SimpleNamespace(state=SimpleNamespace(user=user, persona_access=access))


AURORA_EDITOR = request_for(
    {"id": "u1", "role": "user", "account_type": "client"},
    [{"persona_id": "p1", "persona_slug": "aurora", "can_view": True, "can_edit": True, "can_manage": False}],
)


class _FakeQuery:
    def __init__(self, captured: dict):
        self._captured = captured

    def table(self, name):
        return self

    def update(self, payload):
        self._captured["payload"] = payload
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": self._captured.get("lead_id"), **self._captured["payload"]}])


def _stub_common(monkeypatch, *, lead: dict, captured: dict):
    monkeypatch.setattr(portal.supabase_client, "get_persona", lambda slug: {"id": "p1", "slug": slug})
    monkeypatch.setattr(portal.auth_service, "assert_persona_capability", lambda *a, **k: None)
    monkeypatch.setattr(portal.supabase_client, "get_lead_by_ref", lambda lead_id: lead)
    monkeypatch.setattr(portal.supabase_client, "get_client", lambda: _FakeQuery(captured))


def test_patch_stage_perdido_snapshots_score_at_perdido(monkeypatch):
    lead = {
        "id": 7,
        "persona_id": "p1",
        "stage": "engajado",
        "metadata": {
            "qualification": {
                "version": "graph_agent_runtime_v3",
                "complete": False,
                "required_field_count": 4,
                "resolved_required_count": 2,
            }
        },
    }
    captured: dict = {"lead_id": 7}
    _stub_common(monkeypatch, lead=lead, captured=captured)

    body = portal.LeadPatchBody(stage="perdido")
    portal.update_lead(7, body, AURORA_EDITOR, persona_slug="aurora")

    metadata = captured["payload"]["metadata"]
    # 2 of 4 required fields resolved -> 0-50% formula gives 25.
    assert metadata["qualification"]["score_at_perdido"] == 25


def test_patch_stage_perdido_idempotent_does_not_overwrite_snapshot(monkeypatch):
    lead = {
        "id": 7,
        "persona_id": "p1",
        "stage": "perdido",
        "metadata": {
            "qualification": {
                "version": "graph_agent_runtime_v3",
                "required_field_count": 4,
                "resolved_required_count": 4,
                "complete": True,
                "score_at_perdido": 25,
            }
        },
    }
    captured: dict = {"lead_id": 7}
    _stub_common(monkeypatch, lead=lead, captured=captured)

    body = portal.LeadPatchBody(stage="perdido")
    portal.update_lead(7, body, AURORA_EDITOR, persona_slug="aurora")

    # Already "perdido" -> no metadata write should be triggered by the
    # snapshot logic at all (stage re-PATCH is a no-op for the score).
    assert "metadata" not in captured["payload"]


def test_patch_stage_other_than_perdido_does_not_touch_qualification(monkeypatch):
    lead = {
        "id": 7,
        "persona_id": "p1",
        "stage": "engajado",
        "metadata": {"qualification": {"version": "graph_agent_runtime_v3"}},
    }
    captured: dict = {"lead_id": 7}
    _stub_common(monkeypatch, lead=lead, captured=captured)

    body = portal.LeadPatchBody(stage="qualificado")
    portal.update_lead(7, body, AURORA_EDITOR, persona_slug="aurora")

    assert "metadata" not in captured["payload"]
