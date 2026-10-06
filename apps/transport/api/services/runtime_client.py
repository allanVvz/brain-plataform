"""Authenticated client for conversation decisions owned by runtime."""

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
        raise RuntimeError("conversation runtime is not configured")
    return base_url, token


def execute_inbound(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one canonical inbound; runtime owns commit idempotency."""
    base_url, token = _configuration()
    try:
        with httpx.Client(timeout=45, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + "/internal/v1/conversations/execute",
                json=payload,
                headers={"X-Webhook-Token": token},
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("conversation runtime is unavailable") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(
            str(detail or f"conversation runtime returned HTTP {response.status_code}")
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("conversation runtime returned an invalid response") from exc
    if not isinstance(result, dict):
        raise RuntimeError("conversation runtime returned an invalid response")
    return result


def execute_agentic_inbound(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the graph-owned two-stage turn directly in conversation-runtime."""
    base_url, token = _configuration()
    try:
        with httpx.Client(timeout=135, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + "/internal/v1/conversations/execute-agentic",
                json=payload,
                headers={"X-Webhook-Token": token},
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("conversation runtime is unavailable") from exc
    if response.status_code >= 400:
        raise RuntimeError(
            f"conversation runtime returned HTTP {response.status_code}"
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("conversation runtime returned an invalid response") from exc
    if not isinstance(result, dict) or not any(
        key in result for key in ("ok", "technical_failure", "handoff", "message_id")
    ):
        raise RuntimeError("conversation runtime returned an invalid result contract")
    return result


def authorize_catalog_response(response_buffer_id: str, persona_id: str) -> dict:
    base_url, token = _configuration()
    with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
        response = client.post(base_url + "/internal/v1/conversations/authorize-catalog-response",
            json={"response_buffer_id": response_buffer_id, "persona_id": persona_id},
            headers={"X-Webhook-Token": token})
    response.raise_for_status()
    return response.json()


def pause_ai(lead_ref: int) -> dict[str, Any]:
    """Pause the canonical runtime before a Chatwoot human reply is queued."""
    base_url, token = _configuration()
    with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
        response = client.post(
            f"{base_url}/internal/v1/runtime/leads/{int(lead_ref)}/handoff",
            headers={"X-Webhook-Token": token},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"conversation runtime rejected pause (HTTP {response.status_code})")
    result = response.json()
    if not isinstance(result, dict) or result.get("ai_paused") is not True:
        raise RuntimeError("conversation runtime returned an invalid pause result")
    return result


def resume_ai(lead_ref: int) -> dict[str, Any]:
    """Resume only after an explicit private Chatwoot command."""
    base_url, token = _configuration()
    with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
        response = client.post(
            f"{base_url}/internal/v1/runtime/leads/{int(lead_ref)}/resume",
            headers={"X-Webhook-Token": token},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"conversation runtime rejected resume (HTTP {response.status_code})")
    result = response.json()
    if not isinstance(result, dict) or result.get("ai_paused") is not False:
        raise RuntimeError("conversation runtime returned an invalid resume result")
    return result


def decorate_leads(
    leads: list[dict[str, Any]],
    *,
    persona_id: str | None = None,
    validation_scope: str = "all",
) -> list[dict[str, Any]]:
    base_url, token = _configuration()
    try:
        with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + "/internal/v1/runtime/leads/decorate",
                json={"leads": leads, "persona_id": persona_id, "validation_scope": validation_scope},
                headers={"X-Webhook-Token": token},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Conversation runtime is unavailable.") from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code, "Conversation runtime rejected lead decoration.")
    try:
        items = response.json().get("items")
    except (ValueError, AttributeError) as exc:
        raise HTTPException(502, "Conversation runtime returned invalid lead decorations.") from exc
    if not isinstance(items, list):
        raise HTTPException(502, "Conversation runtime returned invalid lead decorations.")
    return [item for item in items if isinstance(item, dict)]
