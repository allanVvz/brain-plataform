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


def list_unified_queue(
    *, persona_ids: list[str] | None, origin: str | None = None,
    status: str | None = None, offset: int = 0, limit: int = 50,
) -> dict[str, Any]:
    """Return the global active projection from its database source of truth.

    The RPC calculates visibility before paging, so stale transcript rows can
    never displace a real queued message.  Persona authorization is resolved
    by the route and passed as an immutable allowed-id set.
    """
    if persona_ids == []:
        return {"items": [], "next_offset": None}
    data = supabase_client.get_client().rpc("list_actionable_message_queue_v1", {
        "p_persona_ids": persona_ids,
        "p_origin": origin,
        "p_status": status,
        "p_offset": offset,
        "p_limit": limit,
    }).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        raise HTTPException(502, "A fila operacional retornou uma resposta invalida.")
    return data


def _lead_is_in_scope(lead_ref: int, persona_ids: list[str] | None, persona_id: str | None) -> bool:
    lead = _one(
        supabase_client.get_client().table("leads").select("id,persona_id")
        .eq("id", lead_ref).maybe_single()
    )
    if not lead:
        return False
    if persona_id:
        return lead.get("persona_id") == persona_id
    return persona_ids is None or lead.get("persona_id") in set(persona_ids)


def _queue_actions(buffer_ids: list[str]) -> dict[str, list[dict]]:
    if not buffer_ids:
        return {}
    events = _rows(
        supabase_client.get_client().table("system_events")
        .select("event_type,entity_id,payload,created_at,level,source")
        .eq("entity_type", "lead_buffer").like("event_type", "messaging.queue.%")
        .in_("entity_id", buffer_ids).order("created_at", desc=True).range(0, 499)
    )
    result: dict[str, list[dict]] = {}
    for event in events:
        result.setdefault(str(event.get("entity_id")), []).append(event)
    return result


def _queue_history(
    *, persona_ids: list[str] | None, persona_id: str | None, lead_ref: int | None,
    reprocessed_only: bool, offset: int, limit: int,
) -> list[dict]:
    """Return audit history constrained by its immutable persona scope.

    A lead-specific history resolves only that lead's already-scoped buffer
    identities; a global history filters `system_events.persona_id` directly.
    """
    query = (
        supabase_client.get_client().table("system_events")
        .select("event_type,entity_type,entity_id,persona_id,payload,created_at,level,source")
        .eq("entity_type", "lead_buffer").like("event_type", "messaging.queue.%")
        .order("created_at", desc=True)
    )
    if persona_id:
        query = query.eq("persona_id", persona_id)
    elif persona_ids is not None:
        if not persona_ids:
            return []
        query = query.in_("persona_id", persona_ids)
    if lead_ref is not None:
        scoped_buffers = supabase_client.get_client().table("lead_buffer").select("id")
        if persona_id:
            scoped_buffers = scoped_buffers.eq("persona_id", persona_id)
        elif persona_ids is not None:
            scoped_buffers = scoped_buffers.in_("persona_id", persona_ids)
        ids = [str(row["id"]) for row in _rows(scoped_buffers.eq("lead_ref", lead_ref))]
        if not ids:
            return []
        query = query.in_("entity_id", ids)
    if reprocessed_only:
        query = query.eq("event_type", "messaging.queue.reprocess")
    return _rows(query.range(offset, offset + limit - 1))


def next_reprocessable_queue_item(lead_ref: int) -> dict | None:
    """Return the earliest technical inbound that can create a fresh preview."""
    rows = _rows(
        supabase_client.get_client().table("lead_buffer").select("id,persona_id,status,direction,payload,created_at")
        .eq("lead_ref", lead_ref).eq("direction", "inbound")
        .eq("status", "waiting_human").order("created_at").range(0, 49)
    )
    for row in rows:
        payload = row.get("payload") or {}
        if payload.get("queue_pause"):
            continue
        if (payload.get("conversation_commit") or {}).get("status") == "completed":
            continue
        proof = _one(
            supabase_client.get_client().table("conversation_turn_proofs").select("id")
            .eq("canonical_inbound_id", str(row["id"])).limit(1).maybe_single()
        )
        technical_event = _one(
            supabase_client.get_client().table("system_events").select("id")
            .eq("entity_type", "lead_buffer").eq("entity_id", str(row["id"]))
            .in_("event_type", ["conversation.technical_failure", "conversation.technical_handoff"])
            .limit(1).maybe_single()
        )
        if not proof and technical_event:
            return row
    return None


def control_unified_queue(
    *, buffer_ids: list[str], action: str, actor_user_id: str | None,
) -> dict[str, Any]:
    return supabase_client.get_client().rpc("control_message_queue_v2", {
        "p_buffer_ids": buffer_ids,
        "p_action": action,
        "p_actor_user_id": _uuid_or_none(actor_user_id),
    }).execute().data


def generate_queue_previews(*, buffer_ids: list[str], actor_user_id: str | None) -> dict[str, Any]:
    """Claim each technical inbound, then ask runtime for an inert preview."""
    results: list[dict[str, Any]] = []
    actor_id = _uuid_or_none(actor_user_id)
    for buffer_id in buffer_ids:
        claimed: dict[str, Any] | None = None
        try:
            value = supabase_client.get_client().rpc("claim_queue_preview_v1", {
                "p_buffer_id": buffer_id, "p_actor_user_id": actor_id,
            }).execute().data
            claimed = value[0] if isinstance(value, list) and value else value
            if not isinstance(claimed, dict):
                raise RuntimeError("preview claim returned an invalid payload")
            persona = _one(
                supabase_client.get_client().table("personas").select("slug")
                .eq("id", claimed["persona_id"]).maybe_single()
            ) or {}
            result = runtime_client.generate_queue_preview({
                "persona_slug": persona.get("slug"), "lead_ref": claimed["lead_ref"],
                "message": claimed.get("text"), "message_id": str(buffer_id),
                # Older technical rows can predate inbound correlation ids.
                # A stable synthetic identity preserves idempotency for that
                # one canonical inbound without reviving an old delivery.
                "correlation_id": claimed.get("correlation_id") or f"queue-preview:{buffer_id}",
                "channel_binding_id": claimed.get("channel_binding_id"),
                "inbound_buffer_id": str(buffer_id),
            }, actor_user_id=actor_id)
            results.append({"buffer_id": buffer_id, "result": "preview_gerado", "preview": result.get("reply_text")})
        except Exception as exc:
            if claimed:
                try:
                    supabase_client.get_client().rpc("release_queue_preview_claim_v1", {
                        "p_buffer_id": buffer_id, "p_error": str(exc)[:1000],
                    }).execute()
                except Exception:
                    pass
            results.append({"buffer_id": buffer_id, "result": "bloqueado", "reason": str(exc)[:300]})
    return {"items": results}


def generate_reactivation_previews(
    *, buffer_ids: list[str], actor_user_id: str | None, regenerate: bool = False,
) -> dict[str, Any]:
    """Create one independent proactive preview for each delivered outbound.

    Eligibility is deliberately checked again by transport in the final
    transaction.  This read exists only to resolve the authorized persona slug
    for runtime; it never authorizes a send from the dashboard.
    """
    results: list[dict[str, Any]] = []
    for buffer_id in buffer_ids:
        try:
            line = _one(
                supabase_client.get_client().table("lead_buffer")
                .select("id,persona_id,lead_ref,direction,status,payload,queue_parent_buffer_id")
                .eq("id", buffer_id).maybe_single()
            ) or {}
            if line.get("direction") != "outbound":
                raise RuntimeError("mensagem nao esta elegivel para reativacao")
            payload = line.get("payload") or {}
            source_id = payload.get("reactivation_source_buffer_id") or line.get("queue_parent_buffer_id") or buffer_id
            source = line
            if str(source_id) != str(buffer_id):
                source = _one(
                    supabase_client.get_client().table("lead_buffer")
                    .select("id,persona_id,lead_ref,direction,status")
                    .eq("id", source_id).maybe_single()
                ) or {}
                if (
                    line.get("status") != "preview_ready"
                    or source.get("direction") != "outbound"
                    or source.get("status") not in {"sent", "delivered", "read"}
                    or source.get("persona_id") != line.get("persona_id")
                    or source.get("lead_ref") != line.get("lead_ref")
                ):
                    raise RuntimeError("preview de reativacao ou fonte nao esta elegivel")
            elif source.get("status") not in {"sent", "delivered", "read"}:
                raise RuntimeError("mensagem nao esta elegivel para reativacao")
            persona = _one(
                supabase_client.get_client().table("personas").select("slug")
                .eq("id", line.get("persona_id")).maybe_single()
            ) or {}
            result = runtime_client.generate_reactivation_pair({
                "persona_slug": persona.get("slug"),
                "lead_ref": line.get("lead_ref"),
                "source_buffer_id": str(source_id),
                "regenerate": regenerate,
            }, actor_user_id=actor_user_id)
            results.append({
                "buffer_id": buffer_id,
                "result": "preview_reativacao_gerado",
                "preview_buffer_id": (result.get("lines") or [{}])[0].get("buffer_id"),
                "deduplicated": bool(result.get("deduplicated")),
            })
        except Exception as exc:
            results.append({"buffer_id": buffer_id, "result": "bloqueado", "reason": str(exc)[:300]})
    return {"items": results}


def handoff_reactivation_lines(*, buffer_ids: list[str], actor_user_id: str | None) -> dict[str, Any]:
    """Pause the lead and invalidate the whole pair with an operational reason."""
    return supabase_client.get_client().rpc("handoff_reactivation_lines_v1", {
        "p_buffer_ids": buffer_ids,
        "p_actor_user_id": _uuid_or_none(actor_user_id),
        "p_reason": "handoff_operacional_fila_reativacao",
    }).execute().data
