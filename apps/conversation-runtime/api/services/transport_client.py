"""Authenticated client for commands owned by the transport service."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException
from brain_contracts import CanonicalInboundEnvelope

from utils.tls import get_ca_bundle_path


def _configuration() -> tuple[str, str]:
    base_url = (os.environ.get("BRAIN_TRANSPORT_URL") or "").strip().rstrip("/")
    token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
    if not base_url or not token:
        raise HTTPException(503, "Transport service is not configured.")
    return base_url, token


def _post(path: str, payload: dict[str, Any]) -> dict:
    base_url, token = _configuration()
    try:
        with httpx.Client(timeout=15, verify=get_ca_bundle_path()) as client:
            response = client.post(
                base_url + path,
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
        raise HTTPException(response.status_code, detail or "Transport rejected the operation.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Transport returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Transport returned an invalid response.")
    return result


def prepare_outbound(**payload: Any) -> dict:
    return _post("/internal/v1/transport/messages/prepare-outbound", payload)


def enqueue_outbound(**payload: Any) -> dict:
    return _post("/internal/v1/transport/messages/outbound", payload)


def store_validator_media(**payload: Any) -> dict:
    return _post("/internal/v1/transport/messages/validator-media", payload)


def enqueue_validator_inbound(**payload: Any) -> dict:
    envelope = CanonicalInboundEnvelope(**payload)
    return _post(
        "/internal/v1/transport/messages/validator-inbound",
        envelope.model_dump(mode="json"),
    )


def complete_validator_inbound(session_id: str, turn: int) -> dict:
    return _post(
        f"/internal/v1/transport/messages/validator-inbound/{session_id}/{turn}/complete",
        {},
    )


def quarantine_inbound_technical_failure(
    buffer_id: str, lead_ref: int, error: str
) -> dict:
    return _post(
        f"/internal/v1/transport/messages/inbound/{buffer_id}/technical-failure",
        {"lead_ref": lead_ref, "error": error},
    )
