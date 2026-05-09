from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import gspread
import httpx
from google.oauth2.service_account import Credentials

from services import secret_store, supabase_client
from utils.tls import get_ca_bundle_path

CATALOG: list[dict[str, Any]] = [
    {
        "service": "google_sheets",
        "label": "Google Sheets",
        "description": "Planilhas usadas como fonte de conhecimento e operacao.",
        "scope": "user",
        "requires_credentials": True,
        "user_managed": True,
    },
    {
        "service": "airtable",
        "label": "Airtable",
        "description": "Base operacional para CRM e sincronizacoes estruturadas.",
        "scope": "user",
        "requires_credentials": True,
        "user_managed": True,
    },
    {
        "service": "supabase",
        "label": "Supabase",
        "description": "Banco de dados, auth e persistencia operacional.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
    {
        "service": "n8n",
        "label": "n8n",
        "description": "Automacoes e espelhamento de execucoes.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
    {
        "service": "openai",
        "label": "OpenAI",
        "description": "Modelos auxiliares e pipelines de embeddings.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
    {
        "service": "anthropic",
        "label": "Anthropic",
        "description": "Modelos Claude e classificadores operacionais.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
    {
        "service": "whatsapp",
        "label": "WhatsApp",
        "description": "Canal de entrada e saida para atendimento.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
    {
        "service": "figma_mcp",
        "label": "Figma MCP",
        "description": "Ferramentas de design e contexto visual no protocolo MCP.",
        "scope": "system",
        "requires_credentials": False,
        "user_managed": False,
    },
]

CATALOG_BY_SERVICE = {item["service"]: item for item in CATALOG}
_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_PLACEHOLDER_MARKERS = {"", "your-airtable-key", "your-api-key", "changeme", "placeholder"}


class IntegrationValidationError(ValueError):
    pass


def list_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in CATALOG]


def get_catalog_item(service: str) -> dict[str, Any]:
    item = CATALOG_BY_SERVICE.get(service)
    if not item:
        raise KeyError(service)
    return dict(item)


def is_user_managed(service: str) -> bool:
    return bool(CATALOG_BY_SERVICE.get(service, {}).get("user_managed"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_client(timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, verify=get_ca_bundle_path())


def _normalize_google_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw = payload.get("service_account_json")
    if not raw:
        raise IntegrationValidationError("service_account_json is required.")
    if isinstance(raw, dict):
        secret_payload = raw
    else:
        try:
            secret_payload = json.loads(str(raw))
        except Exception as exc:
            raise IntegrationValidationError("service_account_json must be valid JSON.") from exc
    return json.dumps(secret_payload, ensure_ascii=False), {
        "spreadsheet_id": (payload.get("spreadsheet_id") or "").strip() or None,
    }


def _normalize_airtable_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    api_key = (payload.get("api_key") or "").strip()
    base_id = (payload.get("base_id") or "").strip()
    if not api_key:
        raise IntegrationValidationError("api_key is required.")
    if not base_id:
        raise IntegrationValidationError("base_id is required.")
    return api_key, {"base_id": base_id}


def normalize_credentials(service: str, payload: Optional[dict[str, Any]]) -> tuple[Optional[str], dict[str, Any]]:
    body = dict(payload or {})
    if service == "google_sheets":
        return _normalize_google_payload(body)
    if service == "airtable":
        return _normalize_airtable_payload(body)
    return None, {}


def validate_google_sheets(service_account_json: str, spreadsheet_id: Optional[str] = None) -> tuple[str, Optional[str], Optional[int]]:
    try:
        info = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(info, scopes=_GOOGLE_SCOPES)
    except Exception as exc:
        raise IntegrationValidationError(f"Invalid Google service account JSON: {exc}") from exc

    started = time.monotonic()
    try:
        client = gspread.authorize(creds)
        if spreadsheet_id:
            client.open_by_key(spreadsheet_id)
        latency_ms = int((time.monotonic() - started) * 1000)
        return "connected", None, latency_ms
    except Exception as exc:
        raise IntegrationValidationError(f"Google Sheets validation failed: {exc}") from exc


def validate_airtable(api_key: str, base_id: str) -> tuple[str, Optional[str], Optional[int]]:
    if api_key.strip().lower() in _PLACEHOLDER_MARKERS:
        raise IntegrationValidationError("Airtable credential is a placeholder.")
    started = time.monotonic()
    try:
        with _http_client(timeout=8.0) as client:
            response = client.get(
                f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 200:
            return "connected", None, latency_ms
        if response.status_code in {401, 403}:
            raise IntegrationValidationError("Airtable rejected the credentials.")
        raise IntegrationValidationError(f"Airtable validation failed with HTTP {response.status_code}.")
    except IntegrationValidationError:
        raise
    except Exception as exc:
        raise IntegrationValidationError(f"Airtable validation failed: {exc}") from exc


def validate_credentials(service: str, *, secret_value: str, config_json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = dict(config_json or {})
    if service == "google_sheets":
        status, error, latency = validate_google_sheets(secret_value, config.get("spreadsheet_id"))
    elif service == "airtable":
        status, error, latency = validate_airtable(secret_value, str(config.get("base_id") or ""))
    else:
        raise IntegrationValidationError(f"Unsupported user-managed service: {service}")
    return {
        "status": status,
        "last_error": error,
        "last_validated_at": _utcnow(),
        "response_ms": latency,
    }


def _merge_user_integration(service: str, row: Optional[dict[str, Any]]) -> dict[str, Any]:
    catalog = get_catalog_item(service)
    connection = row or {}
    configured = bool(connection.get("secret_ciphertext"))
    enabled = bool(connection.get("enabled")) if configured else False
    status = str(connection.get("status") or ("disabled" if not enabled else "never_validated"))
    if not configured:
        status = "never_validated"
        if connection.get("enabled"):
            enabled = False
    elif not enabled and status == "connected":
        status = "disabled"
    elif not enabled and not connection.get("status"):
        status = "disabled"
    return {
        "service": service,
        "label": catalog["label"],
        "description": catalog["description"],
        "scope": catalog["scope"],
        "enabled": enabled,
        "status": status,
        "requires_credentials": True,
        "configured": configured,
        "last_validated_at": connection.get("last_validated_at"),
        "last_error": connection.get("last_error"),
    }


def _merge_system_integration(service: str, row: Optional[dict[str, Any]]) -> dict[str, Any]:
    catalog = get_catalog_item(service)
    status_row = row or {}
    status = str(status_row.get("status") or "unknown")
    configured = system_service_has_runtime_credentials(service)
    return {
        "service": service,
        "label": catalog["label"],
        "description": catalog["description"],
        "scope": catalog["scope"],
        "enabled": configured and status not in {"down", "disabled"},
        "status": status,
        "requires_credentials": False,
        "configured": configured,
        "last_validated_at": status_row.get("last_check"),
        "last_error": status_row.get("error_message"),
        "response_ms": status_row.get("response_ms"),
    }


def list_user_integrations(user_id: str) -> list[dict[str, Any]]:
    user_rows = {row["service"]: row for row in supabase_client.list_user_integration_connections(user_id)}
    system_rows = {row["service"]: row for row in supabase_client.get_integration_statuses(persona_id=None)}
    merged: list[dict[str, Any]] = []
    for item in CATALOG:
        service = item["service"]
        if item["user_managed"]:
            merged.append(_merge_user_integration(service, user_rows.get(service)))
        else:
            merged.append(_merge_system_integration(service, system_rows.get(service)))
    return merged


def get_user_integration_state(user_id: str, service: str) -> dict[str, Any]:
    if not is_user_managed(service):
        raise KeyError(service)
    return _merge_user_integration(service, supabase_client.get_user_integration_connection(user_id, service))


def _build_update_payload(
    *,
    user_id: str,
    service: str,
    existing: Optional[dict[str, Any]],
    enabled: bool,
    secret_value: Optional[str],
    config_json: Optional[dict[str, Any]],
    validation: Optional[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "service": service,
        "enabled": enabled,
        "status": (validation or {}).get("status") or ("disabled" if not enabled else existing.get("status") if existing else "never_validated"),
        "config_json": config_json if config_json is not None else (existing.get("config_json") if existing else {}),
        "secret_ciphertext": secret_store.encrypt_secret(secret_value) if secret_value is not None else (existing.get("secret_ciphertext") if existing else None),
        "last_validated_at": (validation or {}).get("last_validated_at"),
        "last_error": (validation or {}).get("last_error"),
    }
    if not enabled and payload.get("status") == "connected":
        payload["status"] = "disabled"
    return payload


def save_user_integration(
    user_id: str,
    service: str,
    *,
    enabled: bool,
    credentials: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not is_user_managed(service):
        raise KeyError(service)
    existing = supabase_client.get_user_integration_connection(user_id, service) or {}
    secret_value, config_json = normalize_credentials(service, credentials) if credentials else (None, None)

    if enabled:
        if secret_value is None:
            decrypted = secret_store.decrypt_secret(existing.get("secret_ciphertext"))
            if not decrypted:
                raise IntegrationValidationError("Credentials are required before enabling this integration.")
            secret_value = decrypted
        if config_json is None:
            config_json = existing.get("config_json") or {}
        validation = validate_credentials(service, secret_value=secret_value, config_json=config_json)
    else:
        validation = {
            "status": "disabled",
            "last_error": None,
            "last_validated_at": existing.get("last_validated_at"),
        }

    payload = _build_update_payload(
        user_id=user_id,
        service=service,
        existing=existing,
        enabled=enabled,
        secret_value=secret_value,
        config_json=config_json,
        validation=validation,
    )
    supabase_client.upsert_user_integration_connection(payload)
    return get_user_integration_state(user_id, service)


def validate_user_integration(
    user_id: str,
    service: str,
    *,
    credentials: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not is_user_managed(service):
        raise KeyError(service)
    existing = supabase_client.get_user_integration_connection(user_id, service) or {}
    secret_value, config_json = normalize_credentials(service, credentials) if credentials else (None, None)
    if secret_value is None:
        secret_value = secret_store.decrypt_secret(existing.get("secret_ciphertext"))
    if config_json is None:
        config_json = existing.get("config_json") or {}
    if not secret_value:
        raise IntegrationValidationError("Credentials are required before validation.")

    validation = validate_credentials(service, secret_value=secret_value, config_json=config_json)
    payload = _build_update_payload(
        user_id=user_id,
        service=service,
        existing=existing,
        enabled=bool(existing.get("enabled")),
        secret_value=secret_value if credentials else None,
        config_json=config_json,
        validation=validation,
    )
    supabase_client.upsert_user_integration_connection(payload)
    return get_user_integration_state(user_id, service)


def delete_user_credentials(user_id: str, service: str) -> dict[str, Any]:
    if not is_user_managed(service):
        raise KeyError(service)
    supabase_client.upsert_user_integration_connection(
        {
            "user_id": user_id,
            "service": service,
            "enabled": False,
            "status": "never_validated",
            "config_json": {},
            "secret_ciphertext": None,
            "last_validated_at": None,
            "last_error": None,
        }
    )
    return get_user_integration_state(user_id, service)


def system_service_has_runtime_credentials(service: str) -> bool:
    if service == "n8n":
        return bool((os.environ.get("N8N_BASE_URL") or "").strip() and (os.environ.get("N8N_API_KEY") or "").strip())
    if service == "supabase":
        return bool((os.environ.get("SUPABASE_URL") or "").strip() and (os.environ.get("SUPABASE_SERVICE_KEY") or "").strip())
    if service == "openai":
        return bool((os.environ.get("OPENAI_API_KEY") or "").strip())
    if service == "anthropic":
        return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    return True
