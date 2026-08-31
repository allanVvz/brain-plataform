"""Authenticated client for transport-owned operations."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException

from utils.tls import get_ca_bundle_path


def send_portal_message(payload: dict[str, Any], *, actor_user_id: str | None) -> dict:
    base_url = (os.environ.get("BRAIN_TRANSPORT_URL") or "").strip().rstrip("/")
    token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not base_url or not token:
        raise HTTPException(503, "Transport service is not configured.")
    headers = {"X-Webhook-Token": token}
    if actor_user_id:
        headers["X-Brain-Actor-Id"] = actor_user_id
    try:
        with httpx.Client(timeout=45, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + "/internal/v1/transport/messages/send",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Transport service is unavailable.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(response.status_code, detail or "Transport rejected the message.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Transport returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Transport returned an invalid response.")
    return result


def enqueue_campaign_outbound(payload: dict[str, Any]) -> dict:
    """Send one idempotent campaign command to the transport owner."""
    base_url = (os.environ.get("BRAIN_TRANSPORT_URL") or "").strip().rstrip("/")
    token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not base_url or not token:
        raise HTTPException(503, "Transport service is not configured.")
    try:
        with httpx.Client(timeout=45, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + "/internal/v1/transport/messages/campaign-outbound",
                json=payload,
                headers={"X-Webhook-Token": token},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Transport service is unavailable.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(response.status_code, detail or "Transport rejected campaign outbound.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Transport returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Transport returned an invalid response.")
    return result


def _post_evolution(path: str, payload: dict[str, Any]) -> dict:
    base_url = (os.environ.get("BRAIN_TRANSPORT_URL") or "").strip().rstrip("/")
    token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not base_url or not token:
        raise HTTPException(503, "Transport service is not configured.")
    try:
        with httpx.Client(timeout=45, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + path, json=payload,
                headers={"X-Webhook-Token": token},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Transport service is unavailable.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(response.status_code, detail or "Transport rejected Evolution operation.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Transport returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Transport returned an invalid response.")
    return result


def provision_evolution(
    binding_id: str, *, webhook_url: str, webhook_token: str,
) -> dict:
    return _post_evolution(
        "/internal/v1/transport/whatsapp/evolution/provision",
        {"binding_id": binding_id, "webhook_url": webhook_url, "webhook_token": webhook_token},
    )


def evolution_action(
    binding_id: str,
    action: str,
    *,
    webhook_url: str | None = None,
    webhook_token: str | None = None,
) -> dict:
    return _post_evolution(
        "/internal/v1/transport/whatsapp/evolution/action",
        {
            "binding_id": binding_id, "action": action,
            "webhook_url": webhook_url, "webhook_token": webhook_token,
        },
    )
