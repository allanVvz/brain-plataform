import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/160_fix_operator_preview_generated_column.sql").read_text(encoding="utf-8").lower()
# The file documents the broken statement it replaces, so the generated-column
# scan below has to look at executable SQL only, not at the explanation.
EXECUTABLE_SQL = re.sub(r"--[^\n]*", "", SQL)


def _body(name: str) -> str:
    body = SQL.split(f"create or replace function public.{name}", 1)[1]
    return body.split("create or replace function public.", 1)[0]


def test_no_function_writes_the_generated_ai_paused_column():
    # leads.ai_paused is GENERATED ALWAYS AS (handoff_level = 'full'); writing
    # it raises 428C9 and rolls the whole claim back. Reading it for the audit
    # payload is fine, which is why this asserts on assignment shapes only.
    for forbidden in ("ai_paused=false", "ai_paused=true", "ai_paused=coalesce", "set ai_paused"):
        assert forbidden not in EXECUTABLE_SQL, f"generated column written: {forbidden}"


def test_operator_claim_clears_the_pause_through_handoff_level():
    claim = _body("claim_queue_operator_preview_v1")
    assert "update public.leads set handoff_level='none'" in claim
    assert "pending_reconfirmation" in claim
    assert "messaging.queue.operator_preview_claimed" in claim


def test_operator_release_restores_the_prior_handoff_level():
    release = _body("release_queue_operator_preview_claim_v1")
    assert "handoff_level=coalesce(v_row.payload->>'operator_preview_prior_handoff_level','none')" in release
    assert "conversation_turn_proofs" in release
    assert "messaging.queue.operator_preview_failed" in release


def test_both_claims_release_a_stale_commit_through_the_shared_primitive():
    claim = _body("claim_queue_operator_preview_v1")
    ordinary = _body("claim_queue_preview_v1")
    assert "release_conversation_commit_for_retry_v1" in claim
    assert "release_conversation_commit_for_retry_v1" in ordinary


def test_ordinary_claim_refuses_a_fresh_commit_and_releases_only_a_stale_one():
    ordinary = _body("claim_queue_preview_v1")
    assert "interval '5 minutes'" in ordinary
    assert "canonical inbound conversation commit is still processing" in ordinary
    assert "canonical inbound already has a conversation commit" in ordinary
    # The proof/outbound guard must still run before anything is released.
    assert "canonical inbound already has a decision or outbound" in ordinary


def test_operator_claim_keeps_every_safety_invariant():
    claim = _body("claim_queue_operator_preview_v1")
    assert "inbound is superseded by a newer customer message" in claim
    assert "inbound already has a decision or outbound" in claim
    assert "inbound is paused in the operational queue" in claim
    assert "inbound worker claim is still processing" in claim
    assert "inbound conversation commit is still processing" in claim


def test_no_new_table_or_destructive_statement():
    for forbidden in ("create table", "drop table", "delete from", "truncate"):
        assert forbidden not in SQL


def test_future_migrations_never_write_the_generated_ai_paused_column_again():
    """Forward-looking guard: this bug shipped twice.

    Migration 152 fixed claim_queue_preview_v1 for writing the generated
    leads.ai_paused column; migration 157 reintroduced the identical mistake
    in the operator-replay pair and it went unnoticed until 2026-09-21,
    because nothing failed until the function was actually executed against
    production. Migrations up to 160 are immutable history, so this scans
    everything newer instead.
    """
    offenders = []
    for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        if int(path.name[:3]) <= 160:
            continue
        executable = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8").lower())
        if re.search(r"set\s+[^;]*\bai_paused\s*=", executable):
            offenders.append(path.name)
    assert not offenders, (
        "leads.ai_paused is generated from handoff_level; write handoff_level "
        f"instead in: {', '.join(offenders)}"
    )
