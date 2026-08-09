# -*- coding: utf-8 -*-
"""
Agents (per-persona bots) and role assignments (sdr / closer / followup).

Schema lives in supabase/migrations/007_agents_routing.sql:
  - agents (one row per bot, scoped per persona)
  - persona_role_assignments (which agent — or NULL=human — handles each role)

This module is the single source of truth for resolving "who handles this
lead now?". /process calls resolve_for_stage(persona_id, funnel_stage) and
either runs the resolved agent or pauses the AI for human handoff.
"""
from __future__ import annotations

import logging
from typing import Optional

from services import graph_agent_runtime_v3, supabase_client

logger = logging.getLogger("agents_service")

VALID_ROLES = ("sdr", "closer", "followup")
_ROLE_ASSIGNMENTS_TABLE_MISSING = False

# Funnel stage → role.
# Conservative defaults: most stages map to SDR; fechamento/oportunidade →
# closer; pos_venda / follow_up → followup.
_STAGE_TO_ROLE = {
    "novo":          "sdr",
    "contato":       "sdr",
    "qualificacao":  "sdr",
    "qualificado":   "sdr",
    "interessado":   "sdr",
    "oportunidade":  "closer",
    "negociacao":    "closer",
    "fechamento":    "closer",
    "fechado":       "closer",
    "pos_venda":     "followup",
    "follow_up":     "followup",
    "follow-up":     "followup",
}


def role_for_stage(funnel_stage: Optional[str]) -> str:
    return _STAGE_TO_ROLE.get((funnel_stage or "").lower(), "sdr")


# ── agents CRUD ──────────────────────────────────────────────────

def list_agents(persona_id: Optional[str] = None, include_inactive: bool = False) -> list:
    client = supabase_client.get_client()
    try:
        q = client.table("agents").select("*").order("created_at", desc=False)
        if persona_id:
            q = q.eq("persona_id", persona_id)
        if not include_inactive:
            q = q.eq("active", True)
        return supabase_client._q(q)
    except Exception as exc:
        logger.warning("list_agents failed: %s", exc)
        return []


def get_agent(agent_id: str) -> Optional[dict]:
    if not agent_id:
        return None
    client = supabase_client.get_client()
    return supabase_client._one(
        client.table("agents").select("*").eq("id", agent_id).maybe_single()
    )


def create_agent(data: dict) -> dict:
    client = supabase_client.get_client()
    return supabase_client._insert_one(client.table("agents").insert(data))


def update_agent(agent_id: str, data: dict) -> Optional[dict]:
    client = supabase_client.get_client()
    try:
        result = client.table("agents").update(data).eq("id", agent_id).execute()
        if result and result.data:
            return result.data[0]
    except Exception as exc:
        logger.warning("update_agent failed: %s", exc)
    return None


def deactivate_agent(agent_id: str) -> bool:
    return update_agent(agent_id, {"active": False}) is not None


# ── role assignments ─────────────────────────────────────────────

def get_role_assignments(persona_id: str) -> dict:
    """Return {role: agent_id_or_None}. Always includes all VALID_ROLES."""
    global _ROLE_ASSIGNMENTS_TABLE_MISSING
    out = {role: None for role in VALID_ROLES}
    if not persona_id:
        return out
    if _ROLE_ASSIGNMENTS_TABLE_MISSING:
        return out
    client = supabase_client.get_client()
    try:
        result = (
            client.table("persona_role_assignments")
            .select("role,agent_id,active")
            .eq("persona_id", persona_id)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            if row.get("role") in VALID_ROLES and row.get("active", True):
                out[row["role"]] = row.get("agent_id")
    except Exception as exc:
        if _is_missing_role_assignments_table(exc):
            _ROLE_ASSIGNMENTS_TABLE_MISSING = True
            logger.warning(
                "persona_role_assignments table is missing; falling back to human handoff until migration 007 is applied"
            )
            return out
        logger.warning("get_role_assignments failed: %s", exc)
    return out


def set_role_assignment(persona_id: str, role: str, agent_id: Optional[str]) -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    client = supabase_client.get_client()
    payload = {
        "persona_id": persona_id,
        "role": role,
        "agent_id": agent_id,
        "active": True,
    }
    try:
        result = (
            client.table("persona_role_assignments")
            .upsert(payload, on_conflict="persona_id,role")
            .execute()
        )
        return (result.data or [{}])[0]
    except Exception as exc:
        logger.warning("set_role_assignment failed: %s", exc)
        return {}


def _is_missing_role_assignments_table(exc: Exception) -> bool:
    text = str(exc)
    return (
        "persona_role_assignments" in text
        and ("PGRST205" in text or "schema cache" in text or "Could not find the table" in text)
    )


# ── runtime resolver ─────────────────────────────────────────────

def resolve_for_stage(
    persona_slug_or_id: str, funnel_stage: str
) -> tuple[Optional[dict], str]:
    """Resolve the agent that should answer for (persona, funnel_stage).

    Args:
        persona_slug_or_id: persona slug ("tock-fatal") or UUID.
        funnel_stage: lead's current funnel stage.

    Returns:
        (agent_record_or_None, role)
        - agent_record None  →  human handles this role for this persona.
        - empty role assignment row missing  →  also returns None (human).
    """
    role = role_for_stage(funnel_stage)
    persona_id = _resolve_persona_id(persona_slug_or_id)
    if not persona_id:
        return None, role

    assignments = get_role_assignments(persona_id)
    agent_id = assignments.get(role)
    if not agent_id:
        return None, role
    return get_agent(agent_id), role


def _resolve_persona_id(persona_slug_or_id: str) -> Optional[str]:
    if not persona_slug_or_id:
        return None
    # Looks like UUID (36 chars with dashes) — pass through.
    if len(persona_slug_or_id) == 36 and persona_slug_or_id.count("-") == 4:
        return persona_slug_or_id
    persona = supabase_client.get_persona(persona_slug_or_id)
    return persona.get("id") if persona else None


# ── lead pause/resume ────────────────────────────────────────────

def pause_lead(lead_ref: int) -> bool:
    try:
        supabase_client.update_lead(lead_ref, {"handoff_level": "full"})
        return True
    except Exception as exc:
        logger.warning("pause_lead failed: %s", exc)
        return False


def acknowledge_partial_handoff(lead_ref: int) -> bool:
    """Clear a 'partial' handoff flag once a human has reviewed it.

    Unlike resume_lead, a partial handoff never stopped the AI or parked
    lead_buffer rows as waiting_human, so there's nothing to reset or
    requeue here — just clear the flag.
    """
    try:
        supabase_client.update_lead(lead_ref, {"handoff_level": "none"})
        return True
    except Exception as exc:
        logger.warning("acknowledge_partial_handoff failed: %s", exc)
        return False


def _cleared_conversation_state_metadata(lead: dict) -> Optional[dict]:
    """Clear a lead's sticky "handoff" flag so /process actually retries.

    conversation_runtime persists the deterministic engines' working state
    under metadata.conversation_state (or metadata.vitoria_state for legacy
    Baita leads — same fallback conversation_runtime._build_context uses).
    Both DeterministicAppointment and DeterministicSDR short-circuit with an
    empty reply the moment that state's own "conversation_state" field is
    "handoff", regardless of handoff_level. Left untouched, resuming a lead
    just makes it silently re-pause on the next inbound message instead of
    trying to answer. Only the sticky flag and the stale clarification
    counter are reset here — collected fields (appointment_request, items,
    etc.) must survive the resume. This is the legacy engines' format only
    — v3's equivalent sticky state lives in conversation_ledgers and is
    handled separately by _reset_v3_ledger_if_applicable.
    """
    metadata = dict(lead.get("metadata") or {})
    for key in ("conversation_state", "vitoria_state"):
        cart_state = metadata.get(key)
        if isinstance(cart_state, dict) and cart_state.get("conversation_state") == "handoff":
            cart_state = dict(cart_state)
            cart_state["conversation_state"] = ""
            cart_state["clarification_attempts"] = 0
            metadata = {**metadata, key: cart_state}
            return metadata
    return None


def _reset_v3_ledger_if_applicable(lead_ref: int, lead: dict) -> None:
    """Clear the v3 branch anchor so a resumed lead re-classifies fresh.

    conversation_facts (name, vehicle model, etc.) are left untouched --
    only conversation_ledgers.active_branch_node_id and
    asked_question_node_ids are cleared. Without this, a branch whose
    handoff_rule keeps matching (e.g. qualification_complete stays true
    because the facts are still there) would re-authorize handoff on the
    very next inbound message, immediately re-pausing the lead right after
    "Reativar IA".
    """
    persona_id = lead.get("persona_id")
    if not persona_id:
        return
    try:
        binding = supabase_client.get_workflow_binding_by_id(lead.get("channel_binding_id"))
        if not graph_agent_runtime_v3.binding_uses_v3(binding):
            return
        supabase_client.reset_conversation_ledger_branch_v3(
            persona_id=persona_id, lead_ref=lead_ref
        )
    except Exception as exc:
        logger.warning("resume_lead v3 ledger reset failed: %s", exc)


def resume_lead(lead_ref: int) -> bool:
    update_payload: dict = {"handoff_level": "none"}
    lead: Optional[dict] = None
    try:
        lead = supabase_client.get_lead_by_ref(lead_ref)
    except Exception as exc:
        # Best-effort: a lookup failure must not block the resume itself,
        # it just means the sticky flag (if any) won't be cleared this time.
        logger.warning("resume_lead lead lookup failed: %s", exc)
    if lead:
        try:
            metadata = _cleared_conversation_state_metadata(lead)
            if metadata is None:
                metadata = dict(lead.get("metadata") or {})
            # A resumed lead may still be leaning on facts collected before
            # this pause (name, vehicle, service) that could be stale by
            # now -- the next reply must confirm them instead of silently
            # assuming they still hold. Consumed and cleared by
            # graph_agent_runtime_v3.build_context on the next turn.
            metadata["pending_reconfirmation"] = True
            update_payload["metadata"] = metadata
        except Exception as exc:
            logger.warning("resume_lead conversation-state clearing failed: %s", exc)
        _reset_v3_ledger_if_applicable(lead_ref, lead)
    try:
        supabase_client.update_lead(lead_ref, update_payload)
    except Exception as exc:
        logger.warning("resume_lead failed: %s", exc)
        return False
    try:
        requeued = supabase_client.requeue_waiting_human_whatsapp_buffer(lead_ref)
        if requeued:
            logger.info("resume_lead requeued %d waiting_human message(s)", requeued)
    except Exception as exc:
        # handoff_level is already cleared; a requeue failure must not be
        # reported as a failed resume, just logged for follow-up.
        logger.warning("resume_lead requeue failed: %s", exc)
    return True
