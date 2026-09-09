"""Real-Postgres tests for supabase/migrations/136_business_hours_release_queue.sql.

Same rationale and fixture shape as tests/test_whatsapp_sql_functions.py (see
its module docstring): mocking Postgres would hide the exact class of bug
this feature exists to prevent -- a burst of real customer sends firing the
instant a paused channel or worker comes back. These tests call the actual
next_business_hours_slot / register_release_batch_v1 /
set_release_item_override_v1 plpgsql functions.

Collected only when tests/conftest.py has a non-production Postgres DSN
(AI_BRAIN_TEST_POSTGRES_DSN) or in CI -- see the collect_ignore list there.
"""
from __future__ import annotations

import datetime
import json
import uuid

import psycopg2.extras
import pytest


# ── fixture helpers (duplicated from test_whatsapp_sql_functions.py; no
# shared helper module exists in this suite yet) ────────────────────────

def _insert_persona(cur) -> str:
    persona_id = str(uuid.uuid4())
    cur.execute(
        "insert into public.personas (id, slug, name) values (%s, %s, %s)",
        (persona_id, f"test-persona-{persona_id[:8]}", "Test Persona"),
    )
    return persona_id


def _insert_binding(
    cur,
    persona_id: str,
    *,
    connection_status: str = "connected",
    safety_paused: bool = False,
    active: bool = True,
) -> str:
    binding_id = str(uuid.uuid4())
    metadata = {
        "decision_owner": "deterministic",
        "conversation_mode": "deterministic",
        "transport_mode": "provider_direct",
        "pipeline_contract": "conversation_v1",
        "safety_paused": safety_paused,
    }
    instance_key = f"instance-{uuid.uuid4().hex[:12]}"
    workflow_name = f"Test binding {uuid.uuid4().hex[:8]}"
    cur.execute(
        """
        insert into public.workflow_bindings (
            id, persona_id, workflow_name, channel, provider,
            provider_instance_key, provider_secret_ciphertext,
            connection_status, active, metadata
        ) values (%s, %s, %s, 'whatsapp', 'evolution_baileys', %s, %s, %s, %s, %s)
        """,
        (
            binding_id, persona_id, workflow_name,
            instance_key, "secret-ciphertext",
            connection_status, active, json.dumps(metadata),
        ),
    )
    return binding_id


def _insert_lead(cur, persona_id: str, binding_id: str | None = None) -> int:
    cur.execute(
        "insert into public.leads (nome, persona_id, channel_binding_id) "
        "values (%s, %s, %s) returning id",
        ("Test Lead", persona_id, binding_id),
    )
    return cur.fetchone()["id"]


def _enqueue(cur, *, persona_id, lead_ref, binding_id, idempotency_key=None):
    idempotency_key = idempotency_key or f"test:{uuid.uuid4()}"
    buffer = {
        "persona_id": persona_id,
        "lead_ref": lead_ref,
        "channel_binding_id": binding_id,
        "direction": "inbound",
        "payload": {"text": "oi"},
        "status": "buffered",
        "batch_key": f"{persona_id}:{lead_ref}:{idempotency_key}",
        "idempotency_key": idempotency_key,
        "correlation_id": idempotency_key,
    }
    message = {
        "lead_id": lead_ref,
        "role": "user",
        "content": "oi",
        "direction": "inbound",
        "status": "buffered",
        "channel": "whatsapp",
        "sender_id": idempotency_key,
        "channel_binding_id": binding_id,
        "correlation_id": idempotency_key,
    }
    cur.execute(
        "select public.enqueue_whatsapp_envelope(%s::jsonb, %s::jsonb) as result",
        (json.dumps(buffer), json.dumps(message)),
    )
    return cur.fetchone()["result"]["buffer_id"]


def _set_status(cur, buffer_id, *, status, available_at=None, created_at_offset_seconds=None):
    fields = ["status = %s"]
    params: list = [status]
    if available_at is not None:
        fields.append("available_at = %s")
        params.append(available_at)
    if created_at_offset_seconds is not None:
        fields.append("created_at = now() - make_interval(secs => %s)")
        params.append(created_at_offset_seconds)
    params.append(buffer_id)
    cur.execute(f"update public.lead_buffer set {', '.join(fields)} where id = %s", params)


def _lead_buffer_row(cur, buffer_id):
    cur.execute("select * from public.lead_buffer where id = %s", (buffer_id,))
    return cur.fetchone()


def _parse_ts(value) -> datetime.datetime:
    """The RPCs return jsonb, so a timestamptz field comes back as an ISO
    string, not a native datetime -- unlike a plain table column read
    through RealDictCursor. Normalize before comparing the two."""
    return datetime.datetime.fromisoformat(value) if isinstance(value, str) else value


# psycopg2 returns timestamptz as an aware datetime in whatever offset the
# session reports (not necessarily -03:00), so comparisons below use
# datetime equality (instant-based, tzinfo-representation-agnostic) instead
# of string/isoformat matching.
BRT = datetime.timezone(datetime.timedelta(hours=-3))


@pytest.fixture()
def cur(pg_conn):
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        yield cursor


@pytest.fixture()
def scenario(cur):
    persona_id = _insert_persona(cur)
    binding_id = _insert_binding(cur, persona_id)
    lead_ref = _insert_lead(cur, persona_id, binding_id)
    return {"persona_id": persona_id, "binding_id": binding_id, "lead_ref": lead_ref}


# ── next_business_hours_slot ─────────────────────────────────────────────

class TestNextBusinessHoursSlot:
    def test_before_window_anchors_to_todays_window_start(self, cur):
        cur.execute(
            "select public.next_business_hours_slot("
            "'2026-09-09 03:00:00-03'::timestamptz, 0, 4, '08:00', '20:00', "
            "'America/Sao_Paulo') as slot"
        )
        slot = cur.fetchone()["slot"]
        assert slot == datetime.datetime(2026, 9, 9, 8, 0, 0, tzinfo=BRT)

    def test_after_window_rolls_to_tomorrows_window_start(self, cur):
        cur.execute(
            "select public.next_business_hours_slot("
            "'2026-09-09 23:00:00-03'::timestamptz, 0, 4, '08:00', '20:00', "
            "'America/Sao_Paulo') as slot"
        )
        slot = cur.fetchone()["slot"]
        assert slot == datetime.datetime(2026, 9, 10, 8, 0, 0, tzinfo=BRT)

    def test_inside_window_keeps_the_same_moment_at_index_zero(self, cur):
        cur.execute(
            "select public.next_business_hours_slot("
            "'2026-09-09 12:00:00-03'::timestamptz, 0, 4, '08:00', '20:00', "
            "'America/Sao_Paulo') as slot"
        )
        slot = cur.fetchone()["slot"]
        assert slot == datetime.datetime(2026, 9, 9, 12, 0, 0, tzinfo=BRT)

    def test_stagger_past_window_end_rolls_to_next_day(self, cur):
        # 19:59:58 + index 3 * 4s = 12s past today's window -> next day 08:00:10
        cur.execute(
            "select public.next_business_hours_slot("
            "'2026-09-09 19:59:58-03'::timestamptz, 3, 4, '08:00', '20:00', "
            "'America/Sao_Paulo') as slot"
        )
        slot = cur.fetchone()["slot"]
        assert slot == datetime.datetime(2026, 9, 10, 8, 0, 10, tzinfo=BRT)

    def test_rejects_inverted_window(self, pg_conn, cur):
        with pytest.raises(Exception, match="p_window_start must be before p_window_end"):
            cur.execute(
                "select public.next_business_hours_slot("
                "now(), 0, 4, '20:00', '08:00', 'America/Sao_Paulo')"
            )
        pg_conn.rollback()


# ── register_release_batch_v1 ────────────────────────────────────────────

class TestRegisterReleaseBatchV1:
    def test_safety_paused_scope_unpauses_binding_and_reschedules_waiting_human(self, cur, scenario):
        cur.execute(
            "update public.workflow_bindings "
            "set connection_status = 'safety_paused', "
            "metadata = metadata || '{\"safety_paused\": true}'::jsonb "
            "where id = %s",
            (scenario["binding_id"],),
        )
        first = _enqueue(cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"], binding_id=scenario["binding_id"])
        second = _enqueue(cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"], binding_id=scenario["binding_id"])
        _set_status(cur, first, status="waiting_human", created_at_offset_seconds=3600)
        _set_status(cur, second, status="waiting_human", created_at_offset_seconds=1800)

        cur.execute(
            "select public.register_release_batch_v1("
            "p_persona_id => %s, p_scope => 'safety_paused_binding', "
            "p_lead_buffer_ids => %s::uuid[],p_reason => 'test resume', "
            "p_idempotency_key => %s, p_binding_id => %s) as result",
            (scenario["persona_id"], [first, second], f"batch:{uuid.uuid4()}", scenario["binding_id"]),
        )
        result = cur.fetchone()["result"]
        assert result["deduplicated"] is False
        assert result["item_count"] == 2

        cur.execute("select connection_status, metadata from public.workflow_bindings where id = %s", (scenario["binding_id"],))
        binding = cur.fetchone()
        assert binding["connection_status"] == "connected"
        assert binding["metadata"]["safety_paused"] is False

        row1 = _lead_buffer_row(cur, first)
        row2 = _lead_buffer_row(cur, second)
        assert row1["status"] == "retry"
        assert row2["status"] == "retry"
        assert row1["available_at"] > datetime.datetime.now(datetime.timezone.utc)
        assert row2["available_at"] > datetime.datetime.now(datetime.timezone.utc)
        # Staggered by created_at,id ordering -- not simultaneous.
        assert row1["available_at"] != row2["available_at"]

        cur.execute("select * from public.release_batches where binding_id = %s", (scenario["binding_id"],))
        batch = cur.fetchone()
        assert batch["status"] == "registered"
        assert batch["item_count"] == 2
        assert batch["scope"] == "safety_paused_binding"

        cur.execute("select count(*) as n from public.release_batch_items where batch_id = %s", (batch["id"],))
        assert cur.fetchone()["n"] == 2

    def test_deploy_pause_scope_reschedules_without_changing_status_or_persona(self, cur, scenario):
        first = _enqueue(cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"], binding_id=scenario["binding_id"])
        _set_status(cur, first, status="buffered", created_at_offset_seconds=7200)

        cur.execute(
            "select public.register_release_batch_v1("
            "p_persona_id => NULL, p_scope => 'deploy_pause', "
            "p_lead_buffer_ids => %s::uuid[],p_reason => 'deploy resume test', "
            "p_idempotency_key => %s) as result",
            ([first], f"deploy-resume:{uuid.uuid4()}"),
        )
        result = cur.fetchone()["result"]
        assert result["item_count"] == 1

        row = _lead_buffer_row(cur, first)
        assert row["status"] == "buffered"
        assert row["available_at"] > datetime.datetime.now(datetime.timezone.utc)

        cur.execute("select persona_id, binding_id, scope from public.release_batches where id = %s", (result["batch_id"],))
        batch = cur.fetchone()
        assert batch["persona_id"] is None
        assert batch["binding_id"] is None
        assert batch["scope"] == "deploy_pause"

    def test_same_idempotency_key_is_deduplicated(self, cur, scenario):
        first = _enqueue(cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"], binding_id=scenario["binding_id"])
        _set_status(cur, first, status="waiting_human")
        key = f"dup-batch:{uuid.uuid4()}"

        cur.execute(
            "select public.register_release_batch_v1("
            "p_persona_id => %s, p_scope => 'safety_paused_binding', "
            "p_lead_buffer_ids => %s::uuid[],p_reason => 'r', p_idempotency_key => %s, "
            "p_binding_id => %s) as result",
            (scenario["persona_id"], [first], key, scenario["binding_id"]),
        )
        first_result = cur.fetchone()["result"]
        cur.execute(
            "select public.register_release_batch_v1("
            "p_persona_id => %s, p_scope => 'safety_paused_binding', "
            "p_lead_buffer_ids => %s::uuid[],p_reason => 'r', p_idempotency_key => %s, "
            "p_binding_id => %s) as result",
            (scenario["persona_id"], [first], key, scenario["binding_id"]),
        )
        second_result = cur.fetchone()["result"]
        assert first_result["deduplicated"] is False
        assert second_result["deduplicated"] is True
        assert second_result["batch_id"] == first_result["batch_id"]

    def test_safety_paused_scope_without_binding_id_raises(self, pg_conn, cur, scenario):
        with pytest.raises(Exception, match="safety_paused_binding scope requires p_binding_id"):
            cur.execute(
                "select public.register_release_batch_v1("
                "p_persona_id => %s, p_scope => 'safety_paused_binding', "
                "p_lead_buffer_ids => %s::uuid[],p_reason => 'r', p_idempotency_key => %s) as result",
                (scenario["persona_id"], [str(uuid.uuid4())], f"k:{uuid.uuid4()}"),
            )
        pg_conn.rollback()

    def test_empty_lead_buffer_ids_raises(self, pg_conn, cur, scenario):
        with pytest.raises(Exception, match="p_lead_buffer_ids must not be empty"):
            cur.execute(
                "select public.register_release_batch_v1("
                "p_persona_id => %s, p_scope => 'deploy_pause', "
                "p_lead_buffer_ids => ARRAY[]::uuid[], p_reason => 'r', "
                "p_idempotency_key => %s) as result",
                (scenario["persona_id"], f"k:{uuid.uuid4()}"),
            )
        pg_conn.rollback()


# ── set_release_item_override_v1 ─────────────────────────────────────────

class TestSetReleaseItemOverrideV1:
    def _register_one(self, cur, scenario):
        buffer_id = _enqueue(cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"], binding_id=scenario["binding_id"])
        _set_status(cur, buffer_id, status="waiting_human")
        cur.execute(
            "select public.register_release_batch_v1("
            "p_persona_id => %s, p_scope => 'safety_paused_binding', "
            "p_lead_buffer_ids => %s::uuid[],p_reason => 'r', p_idempotency_key => %s, "
            "p_binding_id => %s) as result",
            (scenario["persona_id"], [buffer_id], f"k:{uuid.uuid4()}", scenario["binding_id"]),
        )
        batch_result = cur.fetchone()["result"]
        cur.execute("select id from public.release_batch_items where batch_id = %s", (batch_result["batch_id"],))
        item_id = cur.fetchone()["id"]
        return buffer_id, item_id

    def test_pause_parks_the_lead_buffer_row_far_in_the_future(self, cur, scenario):
        buffer_id, item_id = self._register_one(cur, scenario)
        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'pause', p_reason => 'operator paused', "
            "p_idempotency_key => %s) as result",
            (item_id, f"k:{uuid.uuid4()}"),
        )
        result = cur.fetchone()["result"]
        assert result["deduplicated"] is False

        cur.execute("select paused from public.release_batch_items where id = %s", (item_id,))
        assert cur.fetchone()["paused"] is True
        row = _lead_buffer_row(cur, buffer_id)
        assert row["available_at"] > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)

    def test_resume_restores_the_originally_computed_slot(self, cur, scenario):
        buffer_id, item_id = self._register_one(cur, scenario)
        cur.execute("select computed_available_at from public.release_batch_items where id = %s", (item_id,))
        computed = cur.fetchone()["computed_available_at"]

        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'pause', p_reason => 'r', "
            "p_idempotency_key => %s)",
            (item_id, f"k:{uuid.uuid4()}"),
        )
        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'resume', p_reason => 'r', "
            "p_idempotency_key => %s) as result",
            (item_id, f"k:{uuid.uuid4()}"),
        )
        result = cur.fetchone()["result"]
        assert _parse_ts(result["available_at"]) == computed

        cur.execute("select paused from public.release_batch_items where id = %s", (item_id,))
        assert cur.fetchone()["paused"] is False
        row = _lead_buffer_row(cur, buffer_id)
        assert row["available_at"] == computed

    def test_reschedule_sets_an_explicit_timestamp_and_unpauses(self, cur, scenario):
        buffer_id, item_id = self._register_one(cur, scenario)
        target = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2, hours=1)
        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'reschedule', p_reason => 'r', "
            "p_idempotency_key => %s, p_new_available_at => %s) as result",
            (item_id, f"k:{uuid.uuid4()}", target),
        )
        result = cur.fetchone()["result"]
        assert _parse_ts(result["available_at"]) == target

        cur.execute("select override_available_at, paused from public.release_batch_items where id = %s", (item_id,))
        item = cur.fetchone()
        assert item["override_available_at"] == target
        assert item["paused"] is False
        row = _lead_buffer_row(cur, buffer_id)
        assert row["available_at"] == target

    def test_reschedule_without_timestamp_raises(self, pg_conn, cur, scenario):
        _buffer_id, item_id = self._register_one(cur, scenario)
        with pytest.raises(Exception, match="reschedule requires p_new_available_at"):
            cur.execute(
                "select public.set_release_item_override_v1("
                "p_item_id => %s, p_action => 'reschedule', p_reason => 'r', "
                "p_idempotency_key => %s)",
                (item_id, f"k:{uuid.uuid4()}"),
            )
        pg_conn.rollback()

    def test_same_idempotency_key_and_action_is_deduplicated(self, cur, scenario):
        _buffer_id, item_id = self._register_one(cur, scenario)
        key = f"k:{uuid.uuid4()}"
        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'pause', p_reason => 'r', "
            "p_idempotency_key => %s) as result",
            (item_id, key),
        )
        first = cur.fetchone()["result"]
        cur.execute(
            "select public.set_release_item_override_v1("
            "p_item_id => %s, p_action => 'pause', p_reason => 'r', "
            "p_idempotency_key => %s) as result",
            (item_id, key),
        )
        second = cur.fetchone()["result"]
        assert first["deduplicated"] is False
        assert second["deduplicated"] is True
