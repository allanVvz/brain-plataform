"""Provision a persona-scoped DeepSeek credential and canonical n8n workflow."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from services import n8n_client


_TEMPLATE = Path(__file__).resolve().parents[1] / "n8n-workflows" / "baita-vitoria.json"
_AGENTIC_TEMPLATE = Path(__file__).resolve().parents[1] / "n8n-workflows" / "aurora-conversation.json"
_AGENTIC_BUSINESS_MODELS = {"appointment"}


def _uses_agentic_reply_template(persona: dict[str, Any]) -> bool:
    """Appointment-style businesses get a model-authored reply (SDR script),
    still gated by the deterministic engine for route/handoff/missing fields.
    Everything else keeps the original field-extraction-only template."""
    config = persona.get("config") or {}
    business_model = str((config.get("portal") or {}).get("business_model") or "")
    return business_model in _AGENTIC_BUSINESS_MODELS


def _workflow_for_persona(
    persona: dict[str, Any],
    *,
    credential_id: str,
    credential_name: str,
) -> dict[str, Any]:
    slug = str(persona.get("slug") or "").strip()
    if not slug:
        raise ValueError("persona slug is required")
    config = persona.get("config") or {}
    agent_slug = str(
        config.get("agent_slug")
        or (config.get("automation") or {}).get("agent_slug")
        or "assistant"
    )
    agentic = _uses_agentic_reply_template(persona)
    template_path = _AGENTIC_TEMPLATE if agentic else _TEMPLATE
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template_slug = str(template["meta"]["binding"]["persona_slug"])
    template_agent_slug = str(template["meta"]["binding"]["agent_slug"])
    serialized = json.dumps(template, ensure_ascii=False)
    serialized = serialized.replace(template_slug, slug)
    workflow = json.loads(serialized)
    workflow["name"] = f"Brain — {persona.get('name') or slug} — Conversação"
    workflow["active"] = False
    # Webhook ids are global in n8n. Keep each persona clone isolated while
    # remaining stable across reprovisioning.
    webhook_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"brain-ai:{slug}:conversation"))
    for node in workflow.get("nodes") or []:
        if node.get("id") == "inbound":
            node["webhookId"] = webhook_id
        if node.get("id") == "binding":
            code = str((node.get("parameters") or {}).get("jsCode") or "")
            code = code.replace(
                f"agent_slug: '{template_agent_slug}'",
                f"agent_slug: {json.dumps(agent_slug)}",
            )
            node["parameters"]["jsCode"] = code
        url = str((node.get("parameters") or {}).get("url") or "")
        if node.get("type") == "n8n-nodes-base.httpRequest" and "api.deepseek.com" in url:
            node["credentials"] = {
                "httpHeaderAuth": {
                    "id": credential_id,
                    "name": credential_name,
                }
            }
    workflow.setdefault("settings", {})
    workflow.setdefault("meta", {})
    workflow["meta"]["binding"] = {
        **(workflow["meta"].get("binding") or {}),
        "persona_slug": slug,
        "agent_slug": agent_slug,
        "decision_owner": "n8n_agents",
        "pipeline_contract": "conversation_v1",
        "classifier": "deterministic_v1",
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


def resync_workflow_for_persona(
    persona: dict[str, Any],
    deepseek_config: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild this persona's n8n workflow from the current template/graph
    and publish it, reusing the DeepSeek credential already provisioned —
    creating the workflow if it doesn't exist yet.

    Called whenever the operator switches (or re-confirms) n8n_agents mode
    from the settings UI, so the live n8n workflow always matches what's on
    disk without a manual SSH resync — the same steps that were previously
    run by hand for every persona-level change.

    The credential is only ever reused, never recreated: once a DeepSeek
    key is saved, its raw value isn't retrievable from our own storage
    again (the only place it still lives is inside the n8n credential
    object itself), so a genuinely first-time setup — no credential at all
    — still requires the operator to (re)enter the key in Ferramentas. But
    a persona that already has a credential and simply never got (or lost)
    its workflow — the exact gap that made switching to n8n error out
    instead of just working — gets one built here from the template, no
    key re-entry needed.

    Returns the config dict with n8n_workflow_id (and conversation_webhook_
    path) filled in, so the caller can persist it back onto the persona's
    integration record.
    """
    credential_id = str(deepseek_config.get("n8n_credential_id") or "")
    if not credential_id:
        raise RuntimeError("DeepSeek nao provisionado para esta persona")
    credential_name = f"Brain DeepSeek — {persona.get('slug') or ''}"
    workflow = _workflow_for_persona(
        persona,
        credential_id=credential_id,
        credential_name=credential_name,
    )
    workflow_id = str(deepseek_config.get("n8n_workflow_id") or "")
    if workflow_id:
        n8n_client.update_workflow(workflow_id, workflow)
    else:
        created = n8n_client.create_workflow(workflow)
        workflow_id = str(created.get("id") or "")
        if not workflow_id:
            raise RuntimeError("n8n nao retornou um workflow id")
    n8n_client.activate_workflow(workflow_id)
    slug = str(persona.get("slug") or "")
    return {
        **deepseek_config,
        "n8n_workflow_id": workflow_id,
        "conversation_webhook_path": f"{slug}/conversation",
    }


def revoke(config: dict[str, Any] | None) -> None:
    credential_id = str((config or {}).get("n8n_credential_id") or "")
    if credential_id:
        n8n_client.delete_credential(credential_id)
