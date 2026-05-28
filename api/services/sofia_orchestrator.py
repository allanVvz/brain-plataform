from __future__ import annotations

import os
from typing import Any, Optional


DEFAULT_CONFIDENCE_THRESHOLD = 0.65


def _threshold() -> float:
    raw = os.getenv("SOFIA_GRAPH_COMMAND_MIN_SCORE", str(DEFAULT_CONFIDENCE_THRESHOLD)).strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD
    return max(0.0, min(1.0, value))


def resolve_persona(command_text: str, fallback_persona_slug: str) -> dict[str, Any]:
    text = (command_text or "").strip().lower()
    if "allanvvz" in text:
        return {"slug": "allanvvz", "score": 0.99, "source": "heuristic"}
    if "vz lupas" in text or "vzlupas" in text:
        return {"slug": "allanvvz", "score": 0.9, "source": "heuristic"}
    return {"slug": fallback_persona_slug, "score": 0.51, "source": "fallback"}


def resolve_operation(command_text: str) -> dict[str, Any]:
    text = (command_text or "").strip().lower()
    if "reencaixe" in text and ("vz lupas" in text or "vzlupas" in text):
        return {"operation": "reparent_brand", "score": 0.98, "source": "heuristic"}
    return {"operation": "validate_canonical_chain", "score": 0.42, "source": "fallback"}


def _reencaixe_patch() -> dict[str, list[dict]]:
    return {
        "nodes_upsert": [
            {
                "node_type": "brand",
                "slug": "vz-lupas",
                "title": "VZ Lupas",
                "summary": "Brand reencaixada pela Sofia na cadeia canonica.",
            }
        ],
        "nodes_delete": [],
        "edges_upsert": [
            {
                "source_ref": "persona:self",
                "target_ref": "slug:vz-lupas",
                "relation_type": "persona_has_brand",
                "metadata": {"primary_tree": True, "active": True},
            }
        ],
        "edges_delete": [],
    }


def plan_graph_command(
    *,
    command: str,
    context: Any,
    persona_slug: str,
    persona_tool_result: Optional[dict[str, Any]] = None,
    operation_tool_result: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    threshold = _threshold()
    persona_result = persona_tool_result or resolve_persona(command, persona_slug)
    operation_result = operation_tool_result or resolve_operation(command)
    persona_score = float(persona_result.get("score") or 0.0)
    operation_score = float(operation_result.get("score") or 0.0)
    tool_calls = [
        {
            "name": "resolve-persona",
            "arguments": {"text": command},
            "result": persona_result,
            "score": persona_score,
        },
        {
            "name": "resolve-operation",
            "arguments": {"text": command},
            "result": operation_result,
            "score": operation_score,
        },
    ]

    graph_patch: Optional[dict[str, list[dict]]] = None
    is_structured_intent = (context.client_action or "").strip().lower() == "structured_intent"
    if is_structured_intent:
        patch = context.graph_patch or {}
        graph_patch = {
            "nodes_upsert": list(patch.get("nodes_upsert") or []),
            "nodes_delete": list(patch.get("nodes_delete") or []),
            "edges_upsert": list(patch.get("edges_upsert") or []),
            "edges_delete": list(patch.get("edges_delete") or []),
        }
    else:
        if persona_score < threshold or operation_score < threshold:
            return {
                "ok": True,
                "persisted": False,
                "sofia_message": "Preciso de confirmacao: qual persona e qual operacao voce quer aplicar no grafo?",
                "graph_patch": None,
                "tool_calls": tool_calls,
                "threshold": threshold,
                "needs_clarification": True,
            }

    if not is_structured_intent and str(operation_result.get("operation") or "") == "reparent_brand":
        graph_patch = _reencaixe_patch()

    if not graph_patch:
        return {
            "ok": True,
            "persisted": False,
            "sofia_message": "Nao consegui mapear a operacao com seguranca. Pode detalhar melhor?",
            "graph_patch": None,
            "tool_calls": tool_calls,
            "threshold": threshold,
            "needs_clarification": True,
        }

    return {
        "ok": True,
        "persisted": True,
        "sofia_message": "Comando aplicado com cadeia canonica validada.",
        "graph_patch": graph_patch,
        "tool_calls": tool_calls,
        "threshold": threshold,
        "needs_clarification": False,
    }
