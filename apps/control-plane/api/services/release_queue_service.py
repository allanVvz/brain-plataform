"""Business-hours WhatsApp backlog release queue.

register_release_batch and set_item_override are thin wrappers over the
register_release_batch_v1 / set_release_item_override_v1 SQL functions
(supabase/migrations/136_business_hours_release_queue.sql) -- the scheduling
arithmetic and the atomic binding-unpause-plus-schedule live in the
database, not here. This module's job is candidate selection: building the
pre-vetted lead_buffer id list the safety_paused_binding scope requires
before the SQL function ever runs, by asking conversation-runtime's
resume_answer_window per lead so this bulk path can never resurrect a
conversation that per-lead staleness check would deliberately leave silent.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from services import runtime_client, supabase_client


def _rows(query) -> list[dict]:
    return supabase_client._q(query)


def _one(query) -> dict | None:
    return supabase_client._one(query)


def _uuid_or_none(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (TypeError, ValueError, AttributeError):
        return None


def _waiting_human_candidates(binding_id: str) -> tuple[list[dict], dict]:
    binding = _one(
        supabase_client.get_client().table("workflow_bindings").select("*")
        .eq("id", binding_id).maybe_single()
    )
    if not binding:
        raise HTTPException(404, "Binding nao encontrado.")
    rows = _rows(
        supabase_client.get_client().table("lead_buffer").select("*")
        .eq("channel_binding_id", binding_id)
        .eq("direction", "inbound")
        .eq("status", "waiting_human")
        .order("created_at")
    )
    return rows, binding


def _filter_within_answer_window(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split candidate lead_buffer rows into (eligible, skipped_stale) by
    asking conversation-runtime's resume_answer_window per lead -- the same
    per-lead staleness check /resume-ai already applies. A lead with no
    unanswered customer message left, or whose runtime call fails, is
    conservatively skipped rather than released."""
    eligible: list[dict] = []
    skipped: list[dict] = []
    decisions: dict[int, bool] = {}
    for row in rows:
        lead_ref = row.get("lead_ref")
        if lead_ref is None:
            skipped.append(row)
            continue
        if lead_ref not in decisions:
            try:
                decision = runtime_client.resume_answer_window(lead_ref)
                decisions[lead_ref] = bool(decision.get("may_speak"))
            except HTTPException:
                decisions[lead_ref] = False
        if decisions[lead_ref]:
            eligible.append(row)
        else:
            skipped.append(row)
    return eligible, skipped


def build_safety_paused_batch_candidates(binding_id: str) -> dict[str, Any]:
    rows, binding = _waiting_human_candidates(binding_id)
    eligible, skipped = _filter_within_answer_window(rows)
    return {
        "binding": binding,
        "eligible_ids": [row["id"] for row in eligible],
        "skipped_ids": [row["id"] for row in skipped],
        "candidate_count": len(rows),
    }


def register_release_batch(
    *,
    persona_id: str | None,
    scope: str,
    lead_buffer_ids: list[str],
    reason: str,
    idempotency_key: str,
    binding_id: str | None = None,
    release_sha: str | None = None,
    actor_user_id: str | None = None,
    stagger_seconds: int = 4,
    window_start: str = "08:00",
    window_end: str = "20:00",
    tz: str = "America/Sao_Paulo",
) -> dict[str, Any]:
    if scope not in {"safety_paused_binding", "deploy_pause"}:
        raise HTTPException(422, "Escopo de liberacao invalido.")
    if not lead_buffer_ids:
        raise HTTPException(422, "Nenhum item elegivel para liberar.")
    if not idempotency_key or not reason:
        raise HTTPException(422, "idempotency_key e reason sao obrigatorios.")
    return supabase_client.get_client().rpc("register_release_batch_v1", {
        "p_persona_id": persona_id,
        "p_scope": scope,
        "p_lead_buffer_ids": lead_buffer_ids,
        "p_reason": reason,
        "p_idempotency_key": idempotency_key,
        "p_binding_id": binding_id,
        "p_release_sha": release_sha,
        "p_actor_user_id": _uuid_or_none(actor_user_id),
        "p_stagger_seconds": stagger_seconds,
        "p_window_start": window_start,
        "p_window_end": window_end,
        "p_tz": tz,
    }).execute().data


def resume_safety_paused_binding_without_backlog(
    *,
    persona_id: str,
    binding_id: str,
    reason: str,
    idempotency_key: str,
    release_sha: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """Clear a persona binding pause after candidate selection returns empty.

    The database operation records a zero-item release batch and its system
    event in the same transaction as the binding update.  Stale conversations
    remain parked in waiting_human and can never become outbound work here.
    """
    if not persona_id or not binding_id:
        raise HTTPException(422, "persona_id e binding_id sao obrigatorios.")
    if not idempotency_key or not reason:
        raise HTTPException(422, "idempotency_key e reason sao obrigatorios.")
    return supabase_client.get_client().rpc(
        "resume_safety_paused_binding_v1",
        {
            "p_persona_id": persona_id,
            "p_binding_id": binding_id,
            "p_reason": reason,
            "p_idempotency_key": idempotency_key,
            "p_release_sha": release_sha,
            "p_actor_user_id": _uuid_or_none(actor_user_id),
        },
    ).execute().data


def list_release_batches(persona_id: str | None = None) -> list[dict]:
    query = supabase_client.get_client().table("release_batches").select("*").order(
        "created_at", desc=True
    )
    if persona_id:
        query = query.eq("persona_id", persona_id)
    return _rows(query)


def get_release_batch_detail(batch_id: str) -> dict[str, Any]:
    batch = _one(
        supabase_client.get_client().table("release_batches").select("*")
        .eq("id", batch_id).maybe_single()
    )
    if not batch:
        raise HTTPException(404, "Batch nao encontrado.")
    items = _rows(
        supabase_client.get_client().table("release_batch_items")
        .select("*,lead_buffer(status,available_at)")
        .eq("batch_id", batch_id)
        .order("created_at")
    )
    return {"batch": batch, "items": items}


def get_release_batch_item(item_id: str) -> dict[str, Any]:
    item = _one(
        supabase_client.get_client().table("release_batch_items").select("*")
        .eq("id", item_id).maybe_single()
    )
    if not item:
        raise HTTPException(404, "Item nao encontrado.")
    return item


def set_item_override(
    *,
    item_id: str,
    action: str,
    reason: str,
    idempotency_key: str,
    new_available_at: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    if action not in {"pause", "resume", "reschedule"}:
        raise HTTPException(422, "Acao invalida.")
    if not idempotency_key or not reason:
        raise HTTPException(422, "idempotency_key e reason sao obrigatorios.")
    if action == "reschedule" and not new_available_at:
        raise HTTPException(422, "reschedule exige new_available_at.")
    return supabase_client.get_client().rpc("set_release_item_override_v1", {
        "p_item_id": item_id,
        "p_action": action,
        "p_reason": reason,
        "p_idempotency_key": idempotency_key,
        "p_new_available_at": new_available_at,
        "p_actor_user_id": _uuid_or_none(actor_user_id),
    }).execute().data
