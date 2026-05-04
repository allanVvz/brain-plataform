import hashlib
import hmac
import json
import os
import time
import httpx
from typing import Optional


def _headers() -> dict:
    return {"X-N8N-API-KEY": os.environ["N8N_API_KEY"]}


def send_to_webhook(
    url: str,
    payload: dict,
    secret: Optional[str] = None,
    timeout: float = 10.0,
) -> tuple[int, str]:
    """POST a payload to an arbitrary n8n webhook URL.

    If secret is given, signs the body with HMAC-SHA256 and sends the
    signature in X-Hub-Signature-256 (GitHub-compatible format).

    Returns (status_code, body_preview). Raises httpx.HTTPError on connection
    failures so the caller can mark the message as failed.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = f"sha256={sig}"
        headers["X-Timestamp"] = str(int(time.time()))
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, content=body, headers=headers)
        return resp.status_code, (resp.text or "")[:300]


def _base() -> str:
    return os.environ["N8N_BASE_URL"].rstrip("/")


def get_executions(limit: int = 100, status: Optional[str] = None, workflow_id: Optional[str] = None) -> list:
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    if workflow_id:
        params["workflowId"] = workflow_id

    with httpx.Client(timeout=15) as client:
        response = client.get(f"{_base()}/api/v1/executions", headers=_headers(), params=params)
        response.raise_for_status()
        return response.json().get("data", [])


def get_execution(execution_id: str) -> dict:
    with httpx.Client(timeout=15) as client:
        response = client.get(f"{_base()}/api/v1/executions/{execution_id}", headers=_headers())
        response.raise_for_status()
        return response.json()


def get_workflows() -> list:
    with httpx.Client(timeout=15) as client:
        response = client.get(f"{_base()}/api/v1/workflows", headers=_headers())
        response.raise_for_status()
        return response.json().get("data", [])


def ping() -> tuple[bool, int]:
    try:
        with httpx.Client(timeout=5) as client:
            import time
            t0 = time.monotonic()
            response = client.get(f"{_base()}/api/v1/workflows", headers=_headers())
            ms = int((time.monotonic() - t0) * 1000)
            return response.status_code == 200, ms
    except Exception:
        return False, -1
