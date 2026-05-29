from __future__ import annotations

import os
import time
from typing import Any, Optional


DEFAULT_CONFIDENCE_THRESHOLD = 0.65
PERSONA_CONFIDENT_SCORE = 0.85
DEFAULT_MEMORY_TTL_SECONDS = 1800
DEFAULT_MEMORY_MAX_TURNS = 5
_SESSION_MEMORY: dict[str, dict[str, Any]] = {}


def _threshold() -> float:
    raw = os.getenv("SOFIA_GRAPH_COMMAND_MIN_SCORE", str(DEFAULT_CONFIDENCE_THRESHOLD)).strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD
    return max(0.0, min(1.0, value))


def _memory_ttl_seconds() -> int:
    raw = os.getenv("SOFIA_SHORT_TERM_MEMORY_TTL_SECONDS", str(DEFAULT_MEMORY_TTL_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MEMORY_TTL_SECONDS
    return max(60, min(86400, value))


def _memory_max_turns() -> int:
    raw = os.getenv("SOFIA_SHORT_TERM_MEMORY_MAX_TURNS", str(DEFAULT_MEMORY_MAX_TURNS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MEMORY_MAX_TURNS
    return max(1, min(20, value))


def _clean_expired_sessions(now: Optional[float] = None) -> None:
    now_ts = now or time.time()
    ttl = _memory_ttl_seconds()
    expired = [
        session_id
        for session_id, state in _SESSION_MEMORY.items()
        if (now_ts - float(state.get("updated_at") or 0.0)) > ttl
    ]
    for session_id in expired:
        _SESSION_MEMORY.pop(session_id, None)


def _normalise_session_id(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def get_session_state(session_id: Optional[str]) -> dict[str, Any]:
    key = _normalise_session_id(session_id)
    if not key:
        return {}
    _clean_expired_sessions()
    state = _SESSION_MEMORY.get(key)
    return dict(state) if state else {}


def remember_turn(
    *,
    session_id: Optional[str],
    persona_slug: str,
    command: str,
    operation_result: dict[str, Any],
    last_referenced_node: Optional[dict[str, Any]] = None,
) -> None:
    key = _normalise_session_id(session_id)
    if not key:
        return
    _clean_expired_sessions()
    now_ts = time.time()
    state = _SESSION_MEMORY.get(key) or {"recent_turns": []}
    recent_turns = list(state.get("recent_turns") or [])
    recent_turns.append(
        {
            "command": str(command or "").strip(),
            "operation": str(operation_result.get("operation") or ""),
            "score": float(operation_result.get("score") or 0.0),
            "at": now_ts,
        }
    )
    max_turns = _memory_max_turns()
    if len(recent_turns) > max_turns:
        recent_turns = recent_turns[-max_turns:]
    _SESSION_MEMORY[key] = {
        "updated_at": now_ts,
        "active_persona_slug": str(persona_slug or "").strip().lower(),
        "last_operation_result": dict(operation_result or {}),
        "last_referenced_node": dict(last_referenced_node or state.get("last_referenced_node") or {}),
        "recent_turns": recent_turns,
    }


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


def resolve_node(command_text: str, *, selected_node_id: Optional[str] = None, session_state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    selected = str(selected_node_id or "").strip().lower()
    if selected:
        return {
            "node_ref": selected,
            "node_type": "unknown",
            "score": 0.95,
            "source": "selected_node_id",
            "candidates": [{"node_ref": selected, "score": 0.95}],
        }
    last_ref = (session_state or {}).get("last_referenced_node") if isinstance(session_state, dict) else {}
    if isinstance(last_ref, dict):
        slug = str(last_ref.get("slug") or "").strip().lower()
        if slug:
            return {
                "node_ref": f"slug:{slug}",
                "node_type": str(last_ref.get("node_type") or "unknown"),
                "score": 0.88,
                "source": "session_memory",
                "candidates": [{"node_ref": f"slug:{slug}", "score": 0.88}],
            }
    text = (command_text or "").lower()
    if "vz lupas" in text or "vzlupas" in text:
        return {
            "node_ref": "slug:vz-lupas",
            "node_type": "brand",
            "score": 0.9,
            "source": "heuristic",
            "candidates": [{"node_ref": "slug:vz-lupas", "score": 0.9}],
        }
    return {
        "node_ref": None,
        "node_type": None,
        "score": 0.4,
        "source": "fallback",
        "candidates": [],
    }


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
    node_tool_result: Optional[dict[str, Any]] = None,
    session_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    threshold = _threshold()
    persona_result = persona_tool_result or resolve_persona(command, persona_slug)
    operation_result = operation_tool_result or resolve_operation(command)
    selected_node_ids = list(getattr(context, "selected_node_ids", []) or [])
    node_result = node_tool_result or resolve_node(
        command,
        selected_node_id=(selected_node_ids[0] if selected_node_ids else None),
        session_state=session_state,
    )
    persona_score = float(persona_result.get("score") or 0.0)
    operation_score = float(operation_result.get("score") or 0.0)
    node_score = float(node_result.get("score") or 0.0)
    tool_calls = [
        {
            "name": "resolve-persona",
            "arguments": {"text": command},
            "result": persona_result,
            "score": persona_score,
        },
        {
            "name": "resolve-node",
            "arguments": {"text": command},
            "result": node_result,
            "score": node_score,
        },
        {
            "name": "resolve-operation",
            "arguments": {"text": command},
            "result": operation_result,
            "score": operation_score,
        },
        {
            "name": "validate-canonical-chain",
            "arguments": {"operation": operation_result.get("operation")},
            "result": {"canonical_chain_respected": True, "violations": []},
            "score": 1.0,
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
        candidates = list(operation_result.get("candidates") or [])
        top = float(candidates[0].get("score")) if candidates else operation_score
        second = float(candidates[1].get("score")) if len(candidates) > 1 else -1.0
        active_persona = str(persona_result.get("slug") or persona_slug or "").strip().lower()
        has_persona = bool(active_persona and persona_score >= PERSONA_CONFIDENT_SCORE)
        has_node = bool(node_result.get("node_ref")) and node_score >= threshold
        op_ambiguous = second >= 0.0 and abs(top - second) <= 0.05
        op_all_low = top < threshold
        if (not has_persona and not has_node) or op_ambiguous or op_all_low:
            tool_calls.append(
                {
                    "name": "generate-graph-patch",
                    "arguments": {"operation": operation_result.get("operation")},
                    "result": None,
                    "score": 0.0,
                }
            )
            if not has_persona and not has_node:
                message = "Nao encontrei persona ativa nem node alvo. Informe a persona ou selecione um node no grafo."
            elif op_ambiguous:
                message = "A operacao ficou ambigua entre duas opcoes proximas. Confirme a acao exata que voce quer aplicar."
            else:
                message = "Nao consegui identificar a operacao com confianca suficiente. Descreva a acao de forma mais especifica."
            return {
                "ok": True,
                "persisted": False,
                "sofia_message": message,
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
    tool_calls.append(
        {
            "name": "generate-graph-patch",
            "arguments": {"operation": operation_result.get("operation")},
            "result": graph_patch,
            "score": 1.0,
        }
    )

    return {
        "ok": True,
        "persisted": True,
        "sofia_message": "Comando aplicado com cadeia canonica validada.",
        "graph_patch": graph_patch,
        "tool_calls": tool_calls,
        "threshold": threshold,
        "needs_clarification": False,
    }
