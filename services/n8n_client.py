import os
import httpx
from typing import Optional


def _headers() -> dict:
    return {"X-N8N-API-KEY": os.environ["N8N_API_KEY"]}


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
