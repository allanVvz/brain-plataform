"""Authenticated client for operations owned by conversation runtime."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException

from utils.tls import get_ca_bundle_path


def _configuration() -> tuple[str, str]:
    base_url = (os.environ.get("BRAIN_RUNTIME_URL") or "").strip().rstrip("/")
    token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not base_url or not token:
        raise HTTPException(503, "Conversation runtime is not configured.")
    return base_url, token


def _post(
    path: str,
    payload: dict[str, Any],
    *,
    actor_user_id: str | None,
    params: dict[str, str] | None = None,
) -> dict:
    base_url, token = _configuration()
    headers = {"X-Webhook-Token": token}
    if actor_user_id:
        headers["X-Brain-Actor-Id"] = actor_user_id
    try:
        with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + path,
                json=payload,
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Conversation runtime is unavailable.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(response.status_code, detail or "Conversation runtime rejected the operation.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Conversation runtime returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Conversation runtime returned an invalid response.")
    return result


def record_journey_event(
    lead_ref: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str | None,
) -> dict:
    return _post(
        f"/internal/v1/agents/leads/{lead_ref}/journey-events",
        payload,
        actor_user_id=actor_user_id,
    )


def set_journey_state(
    lead_ref: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str | None,
    offering: str,
) -> dict:
    return _post(
        f"/internal/v1/agents/leads/{lead_ref}/journey-state",
        payload,
        actor_user_id=actor_user_id,
        params={"offering": offering},
    )


def lead_action(
    lead_ref: int,
    action: str,
    *,
    actor_user_id: str | None,
) -> dict:
    if action not in {"pause", "resume", "acknowledge-handoff", "handoff"}:
        raise ValueError(f"Unsupported runtime lead action: {action}")
    return _post(
        f"/internal/v1/runtime/leads/{lead_ref}/{action}",
        {},
        actor_user_id=actor_user_id,
    )


def decorate_leads(
    leads: list[dict[str, Any]],
    *,
    persona_id: str | None = None,
    validation_scope: str = "all",
) -> list[dict[str, Any]]:
    result = _post(
        "/internal/v1/runtime/leads/decorate",
        {
            "leads": leads,
            "persona_id": persona_id,
            "validation_scope": validation_scope,
        },
        actor_user_id=None,
    )
    items = result.get("items")
    if not isinstance(items, list):
        raise HTTPException(502, "Conversation runtime returned invalid lead decorations.")
    return [item for item in items if isinstance(item, dict)]


def process_lead(payload: dict[str, Any], *, actor_user_id: str | None) -> dict:
    """Execute a synthetic lead event through the runtime-owned decision path."""
    return _post("/process", payload, actor_user_id=actor_user_id)
