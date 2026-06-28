from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services import auth_service

router = APIRouter(prefix="/sofia", tags=["sofia-graph"])


class SofiaGraphCommandBody(BaseModel):
    message: str = ""
    action: str = "command"
    persona_slug: Optional[str] = None
    active_persona_slug: Optional[str] = None
    selected_node_id: Optional[str] = None
    selected_node_ids: list[str] = []
    session_id: Optional[str] = None
    plan_json: Optional[dict[str, Any]] = None


def _session_id(value: Optional[str]) -> str:
    text = (value or "").strip()
    return text or str(uuid.uuid4())


def _slug(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "node"


def _default_plan_json(session_id: str, persona_slug: str, selected_node_id: Optional[str]) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "persona_slug": persona_slug,
        "active_context": {
            "selected_node_id": selected_node_id,
            "brand_slug": None,
        },
        "plan": {},
        "graph_patch_queue": [],
        "suggestions": [],
        "pending_issues": [],
        "blocking_issues": [],
    }


def _plan_json(body: SofiaGraphCommandBody, session_id: str, persona_slug: str) -> dict[str, Any]:
    plan = dict(body.plan_json or {})
    if not plan:
        plan = _default_plan_json(session_id, persona_slug, body.selected_node_id)
    plan["session_id"] = session_id
    plan["persona_slug"] = persona_slug
    ctx = plan.get("active_context") if isinstance(plan.get("active_context"), dict) else {}
    ctx["selected_node_id"] = body.selected_node_id or ctx.get("selected_node_id")
    plan["active_context"] = ctx
    plan.setdefault("graph_patch_queue", [])
    plan.setdefault("pending_issues", [])
    plan.setdefault("blocking_issues", [])
    return plan


def _patch_for_focus(node_id: str) -> dict[str, Any]:
    return {
        "operations": [],
        "nodes": [
            {
                "id": node_id,
                "data": {
                    "sofia_highlight": True,
                    "metadata": {"sofia_highlight": True},
                },
            }
        ],
    }


def _patch_for_draft_node(command: str, selected_node_id: Optional[str]) -> dict[str, Any]:
    raw_title = command
    for prefix in ("apply_patch_visual", "crie", "criar", "adicione", "adicionar"):
        raw_title = re.sub(rf"^\s*{prefix}\s*", "", raw_title, flags=re.IGNORECASE)
    title = raw_title.strip(" :.-") or "Novo node sugerido"
    node_id = f"sofia:draft:{_slug(title)}"
    edge_id = f"sofia:edge:{_slug(title)}"
    patch: dict[str, Any] = {
        "nodes": [
            {
                "id": node_id,
                "type": "knowledgeNode",
                "position": {"x": 80, "y": 80},
                "data": {
                    "label": title,
                    "node_type": "draft",
                    "slug": _slug(title),
                    "status": "pending",
                    "validated": False,
                    "metadata": {"created_from": "sofia_graph_command", "pending_visual": True},
                },
            }
        ],
        "edges": [],
    }
    if selected_node_id:
        patch["edges"].append(
            {
                "id": edge_id,
                "source": selected_node_id,
                "target": node_id,
                "type": "smoothstep",
                "data": {
                    "relation_type": "sofia_suggested",
                    "primary_tree": False,
                    "metadata": {"created_from": "sofia_graph_command", "pending_visual": True},
                },
            }
        )
    return patch


@router.post("/graph-command")
def sofia_graph_command(body: SofiaGraphCommandBody, request: Request):
    persona_slug = (body.persona_slug or body.active_persona_slug or "").strip().lower()
    if not persona_slug:
        raise HTTPException(400, "persona_slug is required")
    auth_service.assert_persona_access(request, persona_slug=persona_slug)

    session_id = _session_id(body.session_id)
    plan = _plan_json(body, session_id, persona_slug)
    action = (body.action or "command").strip().lower()
    command = (body.message or "").strip()

    if action == "confirm_pending" or command == "confirm_pending":
        plan["graph_patch_queue"] = []
        return {
            "ok": True,
            "persisted": True,
            "session_id": session_id,
            "plan_json": plan,
            "text": "Alteracoes confirmadas. O grafo foi recarregado pelo fluxo principal.",
            "tool_calls": [{"name": "confirm_pending", "args": {}}],
        }

    if action == "undo_pending" or command == "undo_pending":
        plan["graph_patch_queue"] = []
        return {
            "ok": True,
            "persisted": True,
            "session_id": session_id,
            "plan_json": plan,
            "text": "Alteracoes pendentes descartadas.",
            "tool_calls": [{"name": "undo_pending", "args": {}}],
        }

    lower = command.lower()
    tool_calls: list[dict[str, Any]] = []
    patch: Optional[dict[str, Any]] = None
    message = "Analisei o comando no contexto do Graph."

    if lower.startswith("select_node"):
        value = command.split(maxsplit=1)[1] if len(command.split(maxsplit=1)) > 1 else body.selected_node_id or ""
        tool_calls.append({"name": "select_node", "args": {"node_id": value}})
        message = "Node selecionado para revisao."
    elif lower.startswith("focus_node"):
        value = command.split(maxsplit=1)[1] if len(command.split(maxsplit=1)) > 1 else body.selected_node_id or ""
        tool_calls.append({"name": "focus_node", "args": {"node_id": value}})
        if value:
            patch = _patch_for_focus(value)
        message = "Foco ajustado para o node indicado."
    elif lower.startswith("update_layout"):
        tool_calls.append({"name": "update_layout", "args": {"mode": "semantic_tree"}})
        message = "Layout reorganizado para arvore semantica."
    elif lower.startswith("highlight_edges"):
        tool_calls.append({"name": "highlight_edges", "args": {"node_id": body.selected_node_id}})
        message = "Arestas destacadas para revisao."
    else:
        patch = _patch_for_draft_node(command, body.selected_node_id)
        tool_calls.append({"name": "apply_patch_visual", "args": {"patch": patch}})
        plan.setdefault("graph_patch_queue", []).append({"command": command, "patch": patch})
        message = "Preparei uma alteracao visual pendente. Revise e confirme para seguir."

    return {
        "ok": True,
        "persisted": False,
        "session_id": session_id,
        "plan_json": plan,
        "sofia_message": message,
        "patch": patch,
        "tool_calls": tool_calls,
    }
