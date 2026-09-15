"""Provision one persona-scoped model credential and canonical n8n workflow."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from services import event_emitter, n8n_client


def _resolve_conversation_template_path() -> Path:
    configured = (os.environ.get("BRAIN_CONVERSATION_TEMPLATE_PATH") or "").strip()
    if configured:
        return Path(configured)

    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "n8n" / "persona-conversation-template.json",
            parent
            / "apps"
            / "conversation-runtime"
            / "n8n"
            / "persona-conversation-template.json",
        ):
            if candidate.is_file():
                return candidate

    return Path("/opt/brain/n8n/persona-conversation-template.json")


_TEMPLATE = _resolve_conversation_template_path()
_TEMPLATE_VERSION = "graph_agentic_v3"
_STRUCTURED_OUTPUT_MODES = {"json_object", "json_schema"}
_REQUIRED_MODEL_STAGES = {"understanding", "reply", "single_pass", "repair"}
_PLACEHOLDER_PATTERN = re.compile(r"__[A-Z][A-Z0-9_]*__")


def _credential_bound_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return nodes that explicitly opt into the conversation-model credential."""
    return [
        node
        for node in workflow.get("nodes") or []
        if (node.get("meta") or {}).get("credential_binding")
        == "conversation_model"
    ]


def _assert_no_placeholders(value: Any, *, path: str = "workflow") -> None:
    """Fail provisioning before literal template bindings can reach n8n."""
    if isinstance(value, str) and _PLACEHOLDER_PATTERN.search(value):
        raise ValueError(f"unresolved workflow placeholder at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_no_placeholders(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_placeholders(child, path=f"{path}[{index}]")


def _validate_workflow_topology(workflow: dict[str, Any]) -> None:
    """Reject dangling n8n connections before a workflow can be published."""
    nodes = workflow.get("nodes") or []
    names = [str(node.get("name") or "").strip() for node in nodes]
    if not names or any(not name for name in names):
        raise ValueError("conversation workflow contains an unnamed node")
    if len(names) != len(set(names)):
        raise ValueError("conversation workflow node names must be unique")
    known = set(names)
    for source_name, outputs in (workflow.get("connections") or {}).items():
        if source_name not in known:
            raise ValueError(
                f"conversation workflow connection source is missing: {source_name}"
            )
        for channel_outputs in (outputs or {}).values():
            for branch in channel_outputs or []:
                for connection in branch or []:
                    target_name = str(connection.get("node") or "").strip()
                    if target_name not in known:
                        raise ValueError(
                            "conversation workflow connection target is missing: "
                            f"{source_name} -> {target_name or '<empty>'}"
                        )
    stages = {
        str((node.get("meta") or {}).get("model_call_stage") or "")
        for node in _credential_bound_nodes(workflow)
    }
    missing_stages = sorted(_REQUIRED_MODEL_STAGES - stages)
    if missing_stages:
        raise ValueError(
            "conversation workflow is missing model stages: "
            + ", ".join(missing_stages)
        )


def _workflow_checksum(workflow: dict[str, Any]) -> str:
    payload = n8n_client.workflow_checksum_payload(workflow)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _emit(
    persona: dict[str, Any],
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    persona_id = str(persona.get("id") or "") or None
    event_emitter.emit(
        event_type,
        entity_type="persona",
        entity_id=persona_id or str(persona.get("slug") or ""),
        persona_id=persona_id,
        payload={
            "persona_slug": str(persona.get("slug") or ""),
            "template": _TEMPLATE_VERSION,
            **(payload or {}),
        },
        level=level,
        source="services.conversation_workflow_service",
    )


def _workflow_for_persona(
    persona: dict[str, Any],
    *,
    credential_id: str,
    credential_name: str,
    model_binding: dict[str, Any] | None = None,
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
    configured_model = dict(model_binding or {})
    model = str(configured_model.get("model") or "").strip()
    endpoint = str(configured_model.get("endpoint") or "").strip()
    reply_source = str(configured_model.get("reply_source") or model).strip()
    structured_output_mode = str(
        configured_model.get("structured_output_mode") or "json_object"
    ).strip()
    if not model or not endpoint.startswith("https://"):
        raise ValueError("conversation model binding requires model and HTTPS endpoint")
    if structured_output_mode not in _STRUCTURED_OUTPUT_MODES:
        raise ValueError("unsupported structured_output_mode")
    template = json.loads(_TEMPLATE.read_text(encoding="utf-8"))
    webhook_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"brain-ai:{slug}:conversation"))
    serialized = json.dumps(template, ensure_ascii=False)
    for placeholder, value in {
        "__PERSONA_SLUG__": slug,
        "__PERSONA_NAME__": str(persona.get("name") or slug),
        "__AGENT_SLUG__": agent_slug,
        "__WEBHOOK_ID__": webhook_id,
        "__MODEL__": model,
        "__MODEL_ENDPOINT__": endpoint,
        "__REPLY_SOURCE__": reply_source,
        "__STRUCTURED_OUTPUT_MODE__": structured_output_mode,
    }.items():
        serialized = serialized.replace(placeholder, value)
    workflow = json.loads(serialized)
    workflow["active"] = False
    for node in _credential_bound_nodes(workflow):
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
        "pipeline_contract": "conversation_v3",
        "runtime_version": "graph_agent_runtime_v3",
        "reply_source": reply_source,
        "model_required": True,
        "model": model,
        "endpoint": endpoint,
        "structured_output_mode": structured_output_mode,
    }
    _validate_workflow_topology(workflow)
    _assert_no_placeholders(workflow)
    return workflow


def provision(
    *,
    persona: dict[str, Any],
    api_key: str,
    previous_config: dict[str, Any] | None = None,
    model_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = dict(previous_config or {})
    slug = str(persona.get("slug") or "")
    credential_name = f"Brain Conversation Model — {slug}"
    step = "create_credential"
    credential_id = ""
    _emit(persona, "n8n.workflow_provision.started")
    try:
        created = n8n_client.create_credential(
            name=credential_name,
            credential_type="httpHeaderAuth",
            data={"name": "Authorization", "value": f"Bearer {api_key}"},
        )
        credential_id = str(created.get("id") or "")
        if not credential_id:
            raise RuntimeError("n8n did not return a credential id")
        _emit(
            persona,
            "n8n.workflow_provision.credential_created",
            payload={"credential_id": credential_id},
        )
        step = "render_template"
        effective_model_binding = {
            **{
                key: value
                for key, value in previous.items()
                if key in {
                    "model", "endpoint", "reply_source", "structured_output_mode"
                } and value
            },
            **{
                key: value
                for key, value in dict(model_binding or {}).items()
                if key in {
                    "model", "endpoint", "reply_source", "structured_output_mode"
                } and value
            },
        }
        workflow = _workflow_for_persona(
            persona,
            credential_id=credential_id,
            credential_name=credential_name,
            model_binding=effective_model_binding,
        )
        workflow_checksum = _workflow_checksum(workflow)
        existing_workflow_id = str(previous.get("n8n_workflow_id") or "")
        step = "save_workflow"
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
        # Provisioning creates an auditable inactive workflow. Selecting the
        # persona's n8n mode later performs validation and explicit activation.
    except Exception as exc:
        if credential_id:
            n8n_client.delete_credential(credential_id)
        _emit(
            persona,
            "n8n.workflow_provision.failed",
            payload={"step": step, "error": str(exc)[:2000]},
            level="error",
        )
        raise

    old_credential_id = str(previous.get("n8n_credential_id") or "")
    if old_credential_id and old_credential_id != credential_id:
        n8n_client.delete_credential(old_credential_id)
    result = {
        "n8n_credential_id": credential_id,
        "n8n_workflow_id": workflow_id,
        "conversation_webhook_path": f"{slug}/conversation",
        "model": workflow["meta"]["binding"]["model"],
        "endpoint": workflow["meta"]["binding"]["endpoint"],
        "reply_source": workflow["meta"]["binding"]["reply_source"],
        "structured_output_mode": workflow["meta"]["binding"]["structured_output_mode"],
        "fingerprint": hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12],
        "persona_id": str(persona.get("id") or ""),
        "persona_slug": slug,
        "workflow_template": _TEMPLATE_VERSION,
        "workflow_checksum": workflow_checksum,
        "runtime_version": "graph_agent_runtime_v3",
        "pipeline_contract": "conversation_v3",
    }
    _emit(
        persona,
        "n8n.workflow_provision.succeeded",
        payload={
            "workflow_id": workflow_id,
            "workflow_checksum": workflow_checksum,
            "webhook_path": result["conversation_webhook_path"],
        },
    )
    return result


def resync_workflow_for_persona(
    persona: dict[str, Any],
    model_config: dict[str, Any],
    *,
    activate_workflow: bool = True,
) -> dict[str, Any]:
    """Rebuild this persona's n8n workflow from the current template/graph
    and publish it, reusing the model credential already provisioned —
    creating the workflow if it doesn't exist yet.

    Called whenever the operator switches (or re-confirms) n8n_agents mode
    from the settings UI, so the live n8n workflow always matches what's on
    disk without a manual SSH resync — the same steps that were previously
    run by hand for every persona-level change.

    The credential is only ever reused, never recreated: once a model
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
    credential_id = str(model_config.get("n8n_credential_id") or "")
    if not credential_id:
        raise RuntimeError("Modelo de conversa nao provisionado para esta persona")
    credential_name = f"Brain Conversation Model — {persona.get('slug') or ''}"
    step = "render_template"
    workflow_id = str(model_config.get("n8n_workflow_id") or "")
    _emit(
        persona,
        "n8n.workflow_resync.started",
        payload={"workflow_id": workflow_id or None},
    )
    try:
        workflow = _workflow_for_persona(
            persona,
            credential_id=credential_id,
            credential_name=credential_name,
            model_binding={
                "model": model_config.get("model"),
                "endpoint": model_config.get("endpoint"),
                "reply_source": model_config.get("reply_source"),
                "structured_output_mode": model_config.get("structured_output_mode"),
            },
        )
        workflow_checksum = _workflow_checksum(workflow)
        step = "save_workflow"
        if workflow_id:
            n8n_client.update_workflow(workflow_id, workflow)
        else:
            created = n8n_client.create_workflow(workflow)
            workflow_id = str(created.get("id") or "")
            if not workflow_id:
                raise RuntimeError("n8n nao retornou um workflow id")
        step = "activate_workflow" if activate_workflow else "deactivate_workflow"
        if activate_workflow:
            n8n_client.activate_workflow(workflow_id)
        else:
            n8n_client.deactivate_workflow(workflow_id)
    except Exception as exc:
        _emit(
            persona,
            "n8n.workflow_resync.failed",
            payload={
                "workflow_id": workflow_id or None,
                "step": step,
                "error": str(exc)[:2000],
            },
            level="error",
        )
        raise
    slug = str(persona.get("slug") or "")
    result = {
        **model_config,
        "n8n_workflow_id": workflow_id,
        "conversation_webhook_path": f"{slug}/conversation",
        "persona_id": str(persona.get("id") or ""),
        "persona_slug": slug,
        "workflow_template": _TEMPLATE_VERSION,
        "workflow_checksum": workflow_checksum,
        "runtime_version": "graph_agent_runtime_v3",
        "pipeline_contract": "conversation_v3",
        "workflow_active": activate_workflow,
    }
    _emit(
        persona,
        "n8n.workflow_resync.succeeded",
        payload={
            "workflow_id": workflow_id,
            "workflow_checksum": workflow_checksum,
            "webhook_path": result["conversation_webhook_path"],
            "active": activate_workflow,
        },
    )
    return result


def check_workflow_wiring(model_config: dict[str, Any]) -> dict[str, Any]:
    """Ask n8n whether the persona's workflow still exists and still points
    at the credential id we have on file.

    This is the strongest check available without either exposing the raw
    provider key or triggering a live execution: n8n's public API has no
    read endpoint for credentials themselves (GET by id and list both
    return 405 — deliberately, credentials are write-only over the API).
    So a workflow node can keep referencing a credential id that was
    deleted elsewhere in n8n and this check will still report "ok" — it
    only catches the workflow being deleted or the node's own credential
    reference having drifted from what we have stored. Confirmed live
    2026-08-02: this exact class of failure (credential silently gone,
    node reference unchanged) only surfaced by actually triggering the
    workflow and reading n8n's execution error — there is no safe way to
    detect it proactively without that side effect.
    """
    workflow_id = str(model_config.get("n8n_workflow_id") or "")
    credential_id = str(model_config.get("n8n_credential_id") or "")
    diagnostics: dict[str, Any] = {
        "workflow_id": workflow_id or None,
        "template": model_config.get("workflow_template") or None,
        "checks": {},
    }
    if not workflow_id or not credential_id:
        return {
            "ok": False,
            "reason": "Modelo de conversa nao provisionado (sem workflow ou credential id).",
            "diagnostics": diagnostics,
        }
    workflow = n8n_client.get_workflow(workflow_id)
    if workflow is None:
        return {
            "ok": False,
            "reason": f"Workflow n8n {workflow_id} nao existe mais.",
            "diagnostics": diagnostics,
        }
    diagnostics["checks"]["workflow_exists"] = True
    if not workflow.get("active"):
        diagnostics["checks"]["active"] = False
        return {
            "ok": False,
            "reason": "Workflow n8n existe mas esta inativo.",
            "diagnostics": diagnostics,
        }
    diagnostics["checks"]["active"] = True
    nodes = workflow.get("nodes") or []
    model_nodes = _credential_bound_nodes(workflow)
    stages = {
        str((node.get("meta") or {}).get("model_call_stage") or "")
        for node in model_nodes
    }
    missing_stages = sorted(_REQUIRED_MODEL_STAGES - stages)
    diagnostics["checks"]["model_stages"] = not missing_stages
    diagnostics["missing_model_stages"] = missing_stages
    if missing_stages:
        return {
            "ok": False,
            "reason": "Workflow n8n nao corresponde ao template agentic canonico.",
            "diagnostics": diagnostics,
        }
    inbound = next((node for node in nodes if node.get("id") == "inbound"), {})
    live_path = str((inbound.get("parameters") or {}).get("path") or "").strip("/")
    expected_path = str(
        model_config.get("conversation_webhook_path") or ""
    ).strip("/")
    diagnostics["checks"]["webhook_path"] = not expected_path or live_path == expected_path
    diagnostics["live_webhook_path"] = live_path
    diagnostics["expected_webhook_path"] = expected_path or None
    if expected_path and live_path != expected_path:
        return {
            "ok": False,
            "reason": "Webhook do workflow n8n nao corresponde a persona configurada.",
            "diagnostics": diagnostics,
        }
    referenced_ids = {
        str((node.get("credentials") or {}).get("httpHeaderAuth", {}).get("id") or "")
        for node in model_nodes
    }
    diagnostics["checks"]["credential_reference"] = referenced_ids == {credential_id}
    if referenced_ids != {credential_id}:
        return {
            "ok": False,
            "reason": "Um node de modelo referencia credencial diferente da configurada.",
            "diagnostics": diagnostics,
        }
    expected_checksum = str(model_config.get("workflow_checksum") or "")
    live_checksum = _workflow_checksum(workflow)
    diagnostics["live_workflow_checksum"] = live_checksum
    diagnostics["expected_workflow_checksum"] = expected_checksum or None
    diagnostics["checks"]["workflow_checksum"] = (
        not expected_checksum or live_checksum == expected_checksum
    )
    if expected_checksum and live_checksum != expected_checksum:
        return {
            "ok": False,
            "reason": "Workflow n8n ativo divergiu do template publicado.",
            "diagnostics": diagnostics,
        }
    return {"ok": True, "reason": None, "diagnostics": diagnostics}


def check_binding(
    *,
    persona: dict[str, Any],
    binding: dict[str, Any],
    model_config: dict[str, Any],
    n8n_base_url: str,
) -> dict[str, Any]:
    """Validate the persisted transport binding against the provisioned workflow."""
    metadata = binding.get("metadata") or {}
    expected_workflow_id = str(model_config.get("n8n_workflow_id") or "")
    expected_path = str(
        model_config.get("conversation_webhook_path") or ""
    ).strip("/")
    expected_url = f"{n8n_base_url.rstrip('/')}/webhook/{expected_path}"
    checks = {
        "active": bool(binding.get("active")),
        "persona_id": str(binding.get("persona_id") or "")
        == str(persona.get("id") or ""),
        "decision_owner": metadata.get("decision_owner") == "n8n_agents",
        "pipeline_contract": metadata.get("pipeline_contract")
        == str(model_config.get("pipeline_contract") or "conversation_v3"),
        "runtime_version": metadata.get("runtime_version")
        == str(model_config.get("runtime_version") or "graph_agent_runtime_v3"),
        "workflow_id": str(binding.get("n8n_workflow_id") or "")
        == expected_workflow_id,
        "webhook_url": str(metadata.get("conversation_webhook_url") or "")
        == expected_url,
    }
    failed = [name for name, ok in checks.items() if not ok]
    diagnostics = {
        "binding_id": binding.get("id"),
        "workflow_id": expected_workflow_id or None,
        "expected_webhook_url": expected_url,
        "checks": checks,
        "failed_checks": failed,
    }
    if failed:
        return {
            "ok": False,
            "reason": "Binding n8n invalido: " + ", ".join(failed),
            "diagnostics": diagnostics,
        }
    return {"ok": True, "reason": None, "diagnostics": diagnostics}


def revoke(config: dict[str, Any] | None) -> None:
    credential_id = str((config or {}).get("n8n_credential_id") or "")
    if credential_id:
        n8n_client.delete_credential(credential_id)
