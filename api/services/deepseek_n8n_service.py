"""Provision a persona-scoped DeepSeek credential and canonical n8n workflow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services import n8n_client


_TEMPLATE = Path(__file__).resolve().parents[1] / "n8n-workflows" / "baita-vitoria.json"


def _workflow_for_persona(
    persona: dict[str, Any],
    *,
    credential_id: str,
    credential_name: str,
) -> dict[str, Any]:
    template = json.loads(_TEMPLATE.read_text(encoding="utf-8"))
    slug = str(persona.get("slug") or "").strip()
    if not slug:
        raise ValueError("persona slug is required")
    config = persona.get("config") or {}
    agent_slug = str(
        config.get("agent_slug")
        or (config.get("automation") or {}).get("agent_slug")
        or "assistant"
    )
    serialized = json.dumps(template, ensure_ascii=False)
    serialized = serialized.replace("baita-conveniencia", slug)
    workflow = json.loads(serialized)
    workflow["name"] = f"Brain — {persona.get('name') or slug} — Conversação"
    workflow["active"] = False
    for node in workflow.get("nodes") or []:
        if node.get("id") == "binding":
            code = str((node.get("parameters") or {}).get("jsCode") or "")
            node["parameters"]["jsCode"] = code.replace(
                "agent_slug: 'vitoria'",
                f"agent_slug: {json.dumps(agent_slug)}",
            )
        if node.get("id") == "deepseek":
            node["credentials"] = {
                "httpHeaderAuth": {
                    "id": credential_id,
                    "name": credential_name,
                }
            }
    workflow.setdefault("settings", {})
    workflow["settings"].update({
        "saveDataErrorExecution": "none",
        "saveDataSuccessExecution": "none",
    })
    workflow.setdefault("meta", {})
    workflow["meta"]["binding"] = {
        "persona_slug": slug,
        "agent_slug": agent_slug,
        "decision_owner": "n8n_agents",
        "pipeline_contract": "conversation_v1",
        "classifier": "deterministic_v1",
        "field_extractor": "deepseek-v4-flash",
        "model_required": True,
        "model": "deepseek-v4-flash",
    }
    return workflow


def provision(
    *,
    persona: dict[str, Any],
    api_key: str,
    previous_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = dict(previous_config or {})
    slug = str(persona.get("slug") or "")
    credential_name = f"Brain DeepSeek — {slug}"
    created = n8n_client.create_credential(
        name=credential_name,
        credential_type="httpHeaderAuth",
        data={"name": "Authorization", "value": f"Bearer {api_key}"},
    )
    credential_id = str(created.get("id") or "")
    if not credential_id:
        raise RuntimeError("n8n did not return a credential id")
    try:
        workflow = _workflow_for_persona(
            persona,
            credential_id=credential_id,
            credential_name=credential_name,
        )
        existing_workflow_id = str(previous.get("n8n_workflow_id") or "")
        if existing_workflow_id:
            saved = n8n_client.update_workflow(existing_workflow_id, workflow)
        else:
            match = next(
                (
                    row for row in n8n_client.get_workflows()
                    if row.get("name") == workflow["name"]
                ),
                None,
            )
            saved = (
                n8n_client.update_workflow(str(match["id"]), workflow)
                if match
                else n8n_client.create_workflow(workflow)
            )
        workflow_id = str(saved.get("id") or existing_workflow_id)
        if not workflow_id:
            raise RuntimeError("n8n did not return a workflow id")
        n8n_client.activate_workflow(workflow_id)
    except Exception:
        n8n_client.delete_credential(credential_id)
        raise

    old_credential_id = str(previous.get("n8n_credential_id") or "")
    if old_credential_id and old_credential_id != credential_id:
        n8n_client.delete_credential(old_credential_id)
    return {
        "n8n_credential_id": credential_id,
        "n8n_workflow_id": workflow_id,
        "conversation_webhook_path": f"{slug}/conversation",
        "model": "deepseek-v4-flash",
        "fingerprint": hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12],
    }


def revoke(config: dict[str, Any] | None) -> None:
    credential_id = str((config or {}).get("n8n_credential_id") or "")
    if credential_id:
        n8n_client.delete_credential(credential_id)
