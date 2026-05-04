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

from services import supabase_client

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
        supabase_client.update_lead(lead_ref, {"ai_paused": True})
        return True
    except Exception as exc:
        logger.warning("pause_lead failed: %s", exc)
        return False


def resume_lead(lead_ref: int) -> bool:
    try:
        supabase_client.update_lead(lead_ref, {"ai_paused": False})
        return True
    except Exception as exc:
        logger.warning("resume_lead failed: %s", exc)
        return False
