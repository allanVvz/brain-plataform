"""Meta template lifecycle: local draft -> submit -> edit resubmits -> sync.

Covers the pure component-normalization logic (`_to_meta_wire_component`,
`_meta_wire_components`) and the service functions that gate identity
changes, submission, and status sync -- against a minimal in-memory fake of
the ``message_templates`` table, following the ``_FakeQuery`` pattern used by
``test_product_collection_nodes_query.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import campaigns_service


class _FakeTable:
    def __init__(self, store: dict):
        self.store = store
        self._filters: dict = {}
        self._op: str | None = None
        self._payload: dict | None = None

    def select(self, *_a, **_k):
        self._op = self._op or "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def _matches(self, row):
        return all(row.get(key) == value for key, value in self._filters.items())

    def execute(self):
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"tpl-{len(self.store) + 1}")
            row.setdefault("revision", 1)
            self.store[row["id"]] = row
            return SimpleNamespace(data=[row])
        matched = [row for row in self.store.values() if self._matches(row)]
        if self._op == "update":
            for row in matched:
                row.update(self._payload)
            return SimpleNamespace(data=matched)
        return SimpleNamespace(data=matched)


class _FakeClient:
    def __init__(self, store: dict):
        self.store = store

    def table(self, _name):
        return _FakeTable(self.store)


@pytest.fixture
def store():
    return {}


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch, store):
    monkeypatch.setattr(campaigns_service.supabase_client, "get_client", lambda: _FakeClient(store))
    monkeypatch.setattr(campaigns_service.event_emitter, "emit", lambda *_a, **_k: None)


def _seed(store, **overrides) -> dict:
    row = {
        "id": "tpl-1",
        "persona_id": "persona-1",
        "provider": "meta_cloud",
        "template_key": "boas_vindas",
        "status": "active",
        "meta_template_name": "boas_vindas",
        "meta_template_language": "pt_BR",
        "meta_template_category": "MARKETING",
        "meta_component_schema": [{"type": "BODY", "text": "Ola!"}],
        "meta_template_id": None,
        "meta_approval_status": "draft",
        "revision": 1,
        **overrides,
    }
    store[row["id"]] = row
    return row


# -- component normalization -------------------------------------------------

def test_body_only_component_round_trips():
    wire = campaigns_service._meta_wire_components([{"type": "body", "text": "Ola!"}])
    assert wire == [{"type": "BODY", "text": "Ola!"}]


def test_missing_text_is_rejected():
    with pytest.raises(ValueError, match="body_component_requires_text"):
        campaigns_service._meta_wire_components([{"type": "BODY", "text": "  "}])


def test_positional_variable_requires_example():
    with pytest.raises(ValueError, match="body_missing_example_for_variables:1"):
        campaigns_service._meta_wire_components([{"type": "BODY", "text": "Ola {{1}}!"}])


def test_named_variable_is_rejected_even_with_example():
    with pytest.raises(ValueError, match="only_positional_variables_supported"):
        campaigns_service._meta_wire_components(
            [{"type": "BODY", "text": "Ola {{nome}}!", "example_values": {"nome": "Ana"}}]
        )


def test_positional_variable_with_example_builds_meta_example_block():
    wire = campaigns_service._meta_wire_components(
        [{"type": "BODY", "text": "Ola {{1}}!", "example_values": {"1": "Ana"}}]
    )
    assert wire == [{"type": "BODY", "text": "Ola {{1}}!", "example": {"body_text": [["Ana"]]}}]


def test_header_footer_and_buttons_all_supported_together():
    wire = campaigns_service._meta_wire_components([
        {"type": "HEADER", "text": "Bem-vindo"},
        {"type": "BODY", "text": "Ola!"},
        {"type": "FOOTER", "text": "VZ Lupas"},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Ver catalogo"}]},
    ])
    assert [c["type"] for c in wire] == ["HEADER", "BODY", "FOOTER", "BUTTONS"]


def test_empty_schema_is_rejected():
    with pytest.raises(ValueError, match="template_has_no_components"):
        campaigns_service._meta_wire_components([])


# -- create_message_template --------------------------------------------------

def test_create_meta_template_wraps_flat_body_into_single_component(store):
    row = campaigns_service.create_message_template(
        {"persona_id": "persona-1", "provider": "meta_cloud", "template_key": "k1",
         "body": "Ola!", "meta_template_name": "k1"},
        actor_user_id=None,
    )
    assert row["meta_component_schema"] == [{"type": "BODY", "text": "Ola!"}]


def test_create_meta_template_requires_meta_name():
    with pytest.raises(HTTPException) as exc:
        campaigns_service.create_message_template(
            {"persona_id": "persona-1", "provider": "meta_cloud", "template_key": "k1", "body": "Ola!"},
            actor_user_id=None,
        )
    assert exc.value.status_code == 422


# -- submit_message_template --------------------------------------------------

def test_submit_creates_at_meta_and_stores_id_and_status(store, monkeypatch):
    _seed(store)
    monkeypatch.setattr(
        campaigns_service.transport_client, "create_meta_template",
        lambda *_a, **_k: {"id": "meta-tpl-1", "status": "PENDING"},
    )

    result = campaigns_service.submit_message_template(
        "tpl-1", expected_revision=1, idempotency_key="key-1", reason="lancamento",
        actor_user_id=None,
    )

    assert result["meta_template_id"] == "meta-tpl-1"
    assert result["meta_approval_status"] == "pending"
    assert result["revision"] == 2


def test_submit_blocks_double_submission(store):
    _seed(store, meta_template_id="already-there")
    with pytest.raises(HTTPException) as exc:
        campaigns_service.submit_message_template(
            "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
            actor_user_id=None,
        )
    assert exc.value.status_code == 409


def test_submit_rejects_stale_revision(store):
    _seed(store, revision=2)
    with pytest.raises(HTTPException) as exc:
        campaigns_service.submit_message_template(
            "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
            actor_user_id=None,
        )
    assert exc.value.status_code == 409


def test_submit_rejects_evolution_provider(store):
    _seed(store, provider="evolution_baileys")
    with pytest.raises(HTTPException) as exc:
        campaigns_service.submit_message_template(
            "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
            actor_user_id=None,
        )
    assert exc.value.status_code == 422


# -- edit_message_template -----------------------------------------------------

def test_edit_blocks_identity_field_changes(store):
    _seed(store)
    with pytest.raises(HTTPException) as exc:
        campaigns_service.edit_message_template(
            "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
            patch={"meta_template_name": "novo_nome"}, actor_user_id=None,
        )
    assert exc.value.status_code == 422


def test_edit_before_submission_only_writes_locally(store, monkeypatch):
    _seed(store)
    called = []
    monkeypatch.setattr(
        campaigns_service.transport_client, "update_meta_template",
        lambda *_a, **_k: called.append(1),
    )

    result = campaigns_service.edit_message_template(
        "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
        patch={"components": [{"type": "BODY", "text": "Novo texto"}]}, actor_user_id=None,
    )

    assert not called
    assert result["meta_component_schema"] == [{"type": "BODY", "text": "Novo texto"}]


def test_edit_after_submission_resubmits_and_resets_status_to_pending(store, monkeypatch):
    _seed(store, meta_template_id="meta-tpl-1", meta_approval_status="approved")
    monkeypatch.setattr(
        campaigns_service.transport_client, "update_meta_template",
        lambda *_a, **_k: {"success": True},
    )

    result = campaigns_service.edit_message_template(
        "tpl-1", expected_revision=1, idempotency_key="key-1", reason="r",
        patch={"components": [{"type": "BODY", "text": "Novo texto"}]}, actor_user_id=None,
    )

    assert result["meta_approval_status"] == "pending"


# -- sync_message_template_status ----------------------------------------------

def test_sync_requires_prior_submission(store):
    _seed(store)
    with pytest.raises(HTTPException) as exc:
        campaigns_service.sync_message_template_status("tpl-1")
    assert exc.value.status_code == 422


def test_sync_maps_meta_status_and_records_rejection_reason(store, monkeypatch):
    _seed(store, meta_template_id="meta-tpl-1", meta_approval_status="pending")
    monkeypatch.setattr(
        campaigns_service.transport_client, "get_meta_template_status",
        lambda *_a, **_k: {"status": "REJECTED", "rejected_reason": "INVALID_FORMAT"},
    )

    result = campaigns_service.sync_message_template_status("tpl-1")

    assert result["meta_approval_status"] == "rejected"
    assert result["meta_rejection_reason"] == "INVALID_FORMAT"
