"""Real-Postgres tests for the WhatsApp lead_buffer SQL function state machine.

Every test here calls the actual plpgsql functions (via psycopg2, see
tests/conftest.py) instead of mocking the Postgres layer — the gap that let
today's `record_whatsapp_safety_violation` text=uuid cast bug reach
production undetected (nothing exercised the real function body).

Table shapes referenced below (personas, workflow_bindings, leads,
lead_buffer, messages) were read directly off a migrated throwaway
database with `information_schema.columns`, not guessed from the
migrations.

No test commits: pg_conn (tests/conftest.py) wraps each test in one
transaction rolled back at teardown, and a connection always sees its own
uncommitted writes, so committing mid-test would only leak state (and
provider_instance_key's unique index made that leak fail loudly the first
time this file was written with stray commit() calls).
"""
from __future__ import annotations

import json
import uuid

import psycopg2.extras
import pytest


# ── fixture helpers ──────────────────────────────────────────────────────

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
    provider: str = "evolution_baileys",
    decision_owner: str = "deterministic",
    metadata_extra: dict | None = None,
    connection_status: str = "connected",
    active: bool = True,
) -> str:
    binding_id = str(uuid.uuid4())
    metadata = {
        "decision_owner": decision_owner,
        "conversation_mode": "n8n_agents" if decision_owner == "n8n_agents" else "deterministic",
        "transport_mode": "provider_direct",
        "pipeline_contract": "conversation_v1",
        **(metadata_extra or {}),
    }
    n8n_workflow_id = None
    if decision_owner == "n8n_agents":
        n8n_workflow_id = "wf-123"
        metadata["conversation_webhook_url"] = "https://n8n.example/webhook/agentic"
    instance_key = f"instance-{uuid.uuid4().hex[:12]}" if provider == "evolution_baileys" else None
    workflow_name = f"Test binding {uuid.uuid4().hex[:8]}"
    cur.execute(
        """
        insert into public.workflow_bindings (
            id, persona_id, workflow_name, channel, provider,
            provider_instance_key, provider_secret_ciphertext,
            connection_status, active, metadata, n8n_workflow_id
        ) values (%s, %s, %s, 'whatsapp', %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            binding_id, persona_id, workflow_name, provider,
            instance_key, "secret-ciphertext",
            connection_status, active, json.dumps(metadata), n8n_workflow_id,
        ),
    )
    if provider == "meta_cloud":
        cur.execute(
            "update public.workflow_bindings set whatsapp_phone_number_id = %s where id = %s",
            ("15550001111", binding_id),
        )
    return binding_id


def _insert_lead(cur, persona_id: str, binding_id: str | None = None) -> int:
    cur.execute(
        "insert into public.leads (nome, persona_id, channel_binding_id) "
        "values (%s, %s, %s) returning id",
        ("Test Lead", persona_id, binding_id),
    )
    return cur.fetchone()["id"]


def _enqueue(cur, *, persona_id, lead_ref, binding_id, direction="inbound",
             idempotency_key=None, available_at=None, correlation_id=None,
             external_message_id=None):
    idempotency_key = idempotency_key or f"test:{uuid.uuid4()}"
    correlation_id = correlation_id or idempotency_key
    buffer = {
        "persona_id": persona_id,
        "lead_ref": lead_ref,
        "channel_binding_id": binding_id,
        "direction": direction,
        "payload": {"text": "oi"},
        "status": "buffered",
        "batch_key": f"{persona_id}:{lead_ref}",
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
        "external_message_id": external_message_id,
    }
    if available_at:
        buffer["available_at"] = available_at.isoformat()
    message = {
        "lead_id": lead_ref,
        "role": "user",
        "content": "oi",
        "direction": direction,
        "status": "buffered",
        "channel": "whatsapp",
        "sender_id": external_message_id or idempotency_key,
        "channel_binding_id": binding_id,
        "correlation_id": correlation_id,
    }
    cur.execute(
        "select public.enqueue_whatsapp_envelope(%s::jsonb, %s::jsonb) as result",
        (json.dumps(buffer), json.dumps(message)),
    )
    return cur.fetchone()["result"]


@pytest.fixture()
def cur(pg_conn):
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        yield cursor


@pytest.fixture()
def scenario(cur):
    """A ready-to-use persona + evolution binding + lead."""
    persona_id = _insert_persona(cur)
    binding_id = _insert_binding(cur, persona_id)
    lead_ref = _insert_lead(cur, persona_id, binding_id)
    return {"persona_id": persona_id, "binding_id": binding_id, "lead_ref": lead_ref}


# ── enqueue_whatsapp_envelope ────────────────────────────────────────────

class TestEnqueueWhatsappEnvelope:
    def test_inserts_buffer_and_message(self, cur, scenario):
        result = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )
        assert result["deduplicated"] is False
        assert result["buffer_id"]
        assert result["status"] == "buffered"

    def test_same_idempotency_key_is_deduplicated(self, cur, scenario):
        key = f"dup:{uuid.uuid4()}"
        first = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], idempotency_key=key,
        )
        second = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], idempotency_key=key,
        )
        assert first["deduplicated"] is False
        assert second["deduplicated"] is True
        assert second["buffer_id"] == first["buffer_id"]

    def test_missing_idempotency_key_raises(self, pg_conn, cur, scenario):
        buffer = {
            "persona_id": scenario["persona_id"],
            "lead_ref": scenario["lead_ref"],
            "channel_binding_id": scenario["binding_id"],
            "direction": "inbound",
        }
        message = {"lead_id": scenario["lead_ref"], "direction": "inbound"}
        with pytest.raises(Exception, match="idempotency_key is required"):
            cur.execute(
                "select public.enqueue_whatsapp_envelope(%s::jsonb, %s::jsonb)",
                (json.dumps(buffer), json.dumps(message)),
            )
        pg_conn.rollback()


# ── claim_whatsapp_buffer ────────────────────────────────────────────────

class TestClaimWhatsappBuffer:
    def test_claims_buffered_rows_and_locks_them(self, cur, scenario):
        _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )

        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        claimed = cur.fetchall()
        assert len(claimed) == 1
        assert claimed[0]["status"] == "processing"
        assert claimed[0]["locked_by"] == "worker-1"

    def test_does_not_claim_rows_before_available_at(self, cur, scenario):
        import datetime
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30)
        _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], available_at=future,
        )

        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        assert cur.fetchall() == []

    def test_second_worker_cannot_claim_already_processing_row(self, cur, scenario):
        _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )

        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        assert len(cur.fetchall()) == 1

        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-2",))
        assert cur.fetchall() == []


# ── mark_whatsapp_attempt ────────────────────────────────────────────────

class TestMarkWhatsappAttempt:
    def test_marks_attempt_for_owning_worker(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        cur.fetchall()

        cur.execute(
            "select public.mark_whatsapp_attempt(%s, %s, %s) as result",
            (buffer_id, "worker-1", "decision"),
        )
        assert cur.fetchone()["result"] is True

    def test_wrong_worker_cannot_mark_attempt(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        cur.fetchall()

        cur.execute(
            "select public.mark_whatsapp_attempt(%s, %s, %s) as result",
            (buffer_id, "worker-2", "decision"),
        )
        assert cur.fetchone()["result"] is False

    def test_invalid_kind_raises(self, pg_conn, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        with pytest.raises(Exception, match="invalid WhatsApp attempt kind"):
            cur.execute(
                "select public.mark_whatsapp_attempt(%s, %s, %s)",
                (buffer_id, "worker-1", "bogus"),
            )
        pg_conn.rollback()


# ── record_whatsapp_safety_violation — the 2026-08-01 regression ────────

class TestRecordWhatsappSafetyViolation:
    def test_records_violation_without_type_error(self, cur, scenario):
        """Migration 073 regression test.

        Before the fix, this raised `operator does not exist: text = uuid`
        because entity_id (text) was compared to p_binding_id (uuid)
        without a cast — which crash-looped the dispatch worker for every
        persona, not just the one that triggered it.
        """
        cur.execute(
            "select public.record_whatsapp_safety_violation(%s, %s, %s, %s) as result",
            (scenario["binding_id"], scenario["lead_ref"], "test-violation", "test reason"),
        )
        result = cur.fetchone()["result"]
        assert result["violation_count"] == 1
        assert result["safety_paused"] is False

    def test_pauses_lead_and_lead_buffer(self, cur, scenario):
        _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )

        cur.execute(
            "select public.record_whatsapp_safety_violation(%s, %s, %s, %s)",
            (scenario["binding_id"], scenario["lead_ref"], "test-violation", "test reason"),
        )
        cur.fetchone()

        cur.execute("select ai_paused from public.leads where id = %s", (scenario["lead_ref"],))
        assert cur.fetchone()["ai_paused"] is True

        cur.execute(
            "select status from public.lead_buffer where lead_ref = %s", (scenario["lead_ref"],)
        )
        assert cur.fetchone()["status"] == "waiting_human"

    def test_three_violations_in_five_minutes_pauses_binding(self, cur, scenario):
        result = None
        for i in range(3):
            cur.execute(
                "select public.record_whatsapp_safety_violation(%s, %s, %s, %s) as result",
                (scenario["binding_id"], scenario["lead_ref"], f"violation-{i}", "test reason"),
            )
            result = cur.fetchone()["result"]
        assert result["safety_paused"] is True

        cur.execute(
            "select connection_status, metadata->>'safety_paused' as sp "
            "from public.workflow_bindings where id = %s",
            (scenario["binding_id"],),
        )
        row = cur.fetchone()
        assert row["connection_status"] == "safety_paused"
        assert row["sp"] == "true"


# ── quarantine_expired_whatsapp_attempts ─────────────────────────────────

class TestQuarantineExpiredAttempts:
    def test_moves_expired_ambiguous_attempt_to_waiting_human(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        cur.fetchall()
        cur.execute(
            "select public.mark_whatsapp_attempt(%s, %s, %s)",
            (buffer_id, "worker-1", "provider"),
        )
        cur.fetchone()
        # Force the lease to look expired.
        cur.execute(
            "update public.lead_buffer set locked_at = now() - interval '10 minutes' "
            "where id = %s",
            (buffer_id,),
        )

        cur.execute("select public.quarantine_expired_whatsapp_attempts(60) as result")
        assert cur.fetchone()["result"] == 1

        cur.execute("select status from public.lead_buffer where id = %s", (buffer_id,))
        assert cur.fetchone()["status"] == "waiting_human"

    def test_does_not_touch_fresh_processing_rows(self, cur, scenario):
        _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )
        cur.execute("select * from public.claim_whatsapp_buffer(%s, 10, 60)", ("worker-1",))
        cur.fetchall()

        cur.execute("select public.quarantine_expired_whatsapp_attempts(60) as result")
        assert cur.fetchone()["result"] == 0


# ── activate_persona_whatsapp_binding — the migration 067/074 regression ─

class TestActivatePersonaWhatsappBinding:
    def test_accepts_deterministic_binding(self, cur, scenario):
        cur.execute(
            "select public.activate_persona_whatsapp_binding(%s, %s, %s, %s) as result",
            (scenario["persona_id"], scenario["binding_id"], "evolution_baileys", "test"),
        )
        result = cur.fetchone()["result"]
        assert result["ok"] is True
        assert result["decision_owner"] == "deterministic"

    def test_accepts_and_preserves_n8n_agents_binding(self, cur):
        """Migration 074 regression test.

        Before the fix, activate_persona_whatsapp_binding hardcoded
        `decision_owner = 'deterministic'` on both the guard *and* the
        final UPDATE — silently reverting any n8n_agents (agentic SDR)
        binding back to the deterministic engine on every reconnect.
        """
        persona_id = _insert_persona(cur)
        binding_id = _insert_binding(cur, persona_id, decision_owner="n8n_agents")

        cur.execute(
            "select public.activate_persona_whatsapp_binding(%s, %s, %s, %s) as result",
            (persona_id, binding_id, "evolution_baileys", "test"),
        )
        result = cur.fetchone()["result"]
        assert result["ok"] is True
        assert result["decision_owner"] == "n8n_agents"

        cur.execute(
            "select metadata->>'decision_owner' as decision_owner "
            "from public.workflow_bindings where id = %s",
            (binding_id,),
        )
        assert cur.fetchone()["decision_owner"] == "n8n_agents"

    def test_rejects_unknown_decision_owner(self, pg_conn, cur):
        # active=False: an *active* row with a bad decision_owner is already
        # rejected at INSERT time by enforce_whatsapp_provider_direct_contract
        # (migration 072's trigger). This test targets
        # activate_persona_whatsapp_binding's own guard, exercised the way
        # it happens for real: a draft/inactive binding someone then tries
        # to activate.
        persona_id = _insert_persona(cur)
        binding_id = _insert_binding(
            cur, persona_id, active=False,
            metadata_extra={"decision_owner": "some_other_owner"},
        )
        with pytest.raises(Exception, match="approved decision owner"):
            cur.execute(
                "select public.activate_persona_whatsapp_binding(%s, %s, %s, %s)",
                (persona_id, binding_id, "evolution_baileys", "test"),
            )
        pg_conn.rollback()

    def test_deactivates_previous_active_binding_for_persona(self, cur, scenario):
        cur.execute(
            "select public.activate_persona_whatsapp_binding(%s, %s, %s, %s)",
            (scenario["persona_id"], scenario["binding_id"], "evolution_baileys", "test"),
        )
        cur.fetchone()

        # A partial unique index allows only one *active* WhatsApp binding
        # per persona — matches the real portal.py flow, where a
        # newly-provisioned binding starts inactive/"provisioning" and only
        # activate_persona_whatsapp_binding flips it active while
        # deactivating the old one.
        second_binding_id = _insert_binding(cur, scenario["persona_id"], active=False)
        cur.execute(
            "select public.activate_persona_whatsapp_binding(%s, %s, %s, %s)",
            (scenario["persona_id"], second_binding_id, "evolution_baileys", "test"),
        )
        cur.fetchone()

        cur.execute(
            "select active from public.workflow_bindings where id = %s", (scenario["binding_id"],)
        )
        assert cur.fetchone()["active"] is False


# ── requeue_waiting_human_whatsapp_buffer — the 2026-08-01 dead-end fix ──

class TestRequeueWaitingHumanBuffer:
    def test_requeues_inbound_waiting_human_rows(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        cur.execute(
            "update public.lead_buffer set status = 'waiting_human' where id = %s",
            (buffer_id,),
        )

        cur.execute(
            "select public.requeue_waiting_human_whatsapp_buffer(%s) as result",
            (scenario["lead_ref"],),
        )
        assert cur.fetchone()["result"] == 1

        cur.execute("select status from public.lead_buffer where id = %s", (buffer_id,))
        assert cur.fetchone()["status"] == "retry"

    def test_does_not_requeue_outbound_waiting_human_rows(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], direction="outbound",
        )["buffer_id"]
        cur.execute(
            "update public.lead_buffer set status = 'waiting_human' where id = %s",
            (buffer_id,),
        )

        cur.execute(
            "select public.requeue_waiting_human_whatsapp_buffer(%s) as result",
            (scenario["lead_ref"],),
        )
        assert cur.fetchone()["result"] == 0

        cur.execute("select status from public.lead_buffer where id = %s", (buffer_id,))
        assert cur.fetchone()["status"] == "waiting_human"


# ── handoff_whatsapp_lead / handoff_whatsapp_lead_state ──────────────────

class TestHandoffWhatsappLead:
    def test_pauses_lead_and_drains_in_flight_buffer(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]

        cur.execute("select public.handoff_whatsapp_lead(%s)", (scenario["lead_ref"],))

        cur.execute("select ai_paused from public.leads where id = %s", (scenario["lead_ref"],))
        assert cur.fetchone()["ai_paused"] is True
        cur.execute("select status from public.lead_buffer where id = %s", (buffer_id,))
        assert cur.fetchone()["status"] == "waiting_human"

    def test_state_variant_updates_stage_and_metadata(self, cur, scenario):
        cur.execute(
            "select public.handoff_whatsapp_lead_state(%s, %s::jsonb, %s)",
            (scenario["lead_ref"], json.dumps({"qualified": True}), "fechamento"),
        )
        cur.execute(
            "select ai_paused, stage, metadata from public.leads where id = %s",
            (scenario["lead_ref"],),
        )
        row = cur.fetchone()
        assert row["ai_paused"] is True
        assert row["stage"] == "fechamento"
        assert row["metadata"] == {"qualified": True}

    def test_state_variant_raises_for_unknown_lead(self, pg_conn, cur):
        with pytest.raises(Exception, match="lead not found"):
            cur.execute(
                "select public.handoff_whatsapp_lead_state(%s, %s::jsonb, %s)",
                (999999999, json.dumps({}), "fechamento"),
            )
        pg_conn.rollback()


# ── claim_conversation_commit / complete_conversation_commit ─────────────

class TestConversationCommit:
    def test_claim_then_complete_is_idempotent(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        correlation_id = f"commit:{uuid.uuid4()}"
        cur.execute(
            "update public.lead_buffer set correlation_id = %s where id = %s",
            (correlation_id, buffer_id),
        )

        cur.execute(
            "select public.claim_conversation_commit(%s, %s, %s, %s) as result",
            (buffer_id, scenario["binding_id"], scenario["lead_ref"], correlation_id),
        )
        assert cur.fetchone()["result"]["state"] == "claimed"

        # A second claim attempt (e.g. a retried n8n execution) must not
        # re-run the decision — it should see the in-flight commit.
        cur.execute(
            "select public.claim_conversation_commit(%s, %s, %s, %s) as result",
            (buffer_id, scenario["binding_id"], scenario["lead_ref"], correlation_id),
        )
        assert cur.fetchone()["result"]["state"] == "processing"

        cur.execute(
            "select public.complete_conversation_commit(%s, %s, %s, %s, %s::jsonb) as result",
            (buffer_id, scenario["binding_id"], scenario["lead_ref"], correlation_id,
             json.dumps({"reply": "ok"})),
        )
        assert cur.fetchone()["result"] == {"reply": "ok"}

        # Completing again (duplicate delivery) returns the same result
        # instead of re-running the side effects.
        cur.execute(
            "select public.complete_conversation_commit(%s, %s, %s, %s, %s::jsonb) as result",
            (buffer_id, scenario["binding_id"], scenario["lead_ref"], correlation_id,
             json.dumps({"reply": "should not overwrite"})),
        )
        assert cur.fetchone()["result"] == {"reply": "ok"}

    def test_complete_without_claim_raises(self, pg_conn, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"],
        )["buffer_id"]
        correlation_id = f"commit:{uuid.uuid4()}"
        cur.execute(
            "update public.lead_buffer set correlation_id = %s where id = %s",
            (correlation_id, buffer_id),
        )

        with pytest.raises(Exception, match="conversation commit was not claimed"):
            cur.execute(
                "select public.complete_conversation_commit(%s, %s, %s, %s, %s::jsonb)",
                (buffer_id, scenario["binding_id"], scenario["lead_ref"], correlation_id,
                 json.dumps({"reply": "ok"})),
            )
        pg_conn.rollback()


# ── complete_whatsapp_outbound_result ────────────────────────────────────

class TestCompleteWhatsappOutboundResult:
    def test_success_marks_sent(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], direction="outbound",
        )["buffer_id"]
        cur.execute("select correlation_id from public.lead_buffer where id = %s", (buffer_id,))
        correlation_id = cur.fetchone()["correlation_id"]

        cur.execute(
            "select public.complete_whatsapp_outbound_result(%s, %s, %s, %s, %s, %s, %s) as result",
            (buffer_id, scenario["binding_id"], correlation_id, "wamid.123", True, None, "exec-1"),
        )
        result = cur.fetchone()["result"]
        assert result["ok"] is True
        assert result["status"] == "sent"
        assert result["deduplicated"] is False

    def test_failure_marks_waiting_human(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], direction="outbound",
        )["buffer_id"]
        cur.execute("select correlation_id from public.lead_buffer where id = %s", (buffer_id,))
        correlation_id = cur.fetchone()["correlation_id"]

        cur.execute(
            "select public.complete_whatsapp_outbound_result(%s, %s, %s, %s, %s, %s, %s) as result",
            (buffer_id, scenario["binding_id"], correlation_id, None, False, "provider timeout", "exec-1"),
        )
        result = cur.fetchone()["result"]
        assert result["status"] == "waiting_human"

    def test_duplicate_success_callback_is_deduplicated(self, cur, scenario):
        buffer_id = _enqueue(
            cur, persona_id=scenario["persona_id"], lead_ref=scenario["lead_ref"],
            binding_id=scenario["binding_id"], direction="outbound",
        )["buffer_id"]
        cur.execute("select correlation_id from public.lead_buffer where id = %s", (buffer_id,))
        correlation_id = cur.fetchone()["correlation_id"]

        cur.execute(
            "select public.complete_whatsapp_outbound_result(%s, %s, %s, %s, %s, %s, %s)",
            (buffer_id, scenario["binding_id"], correlation_id, "wamid.123", True, None, "exec-1"),
        )
        cur.fetchone()

        cur.execute(
            "select public.complete_whatsapp_outbound_result(%s, %s, %s, %s, %s, %s, %s) as result",
            (buffer_id, scenario["binding_id"], correlation_id, "wamid.123", True, None, "exec-2"),
        )
        result = cur.fetchone()["result"]
        assert result["deduplicated"] is True
