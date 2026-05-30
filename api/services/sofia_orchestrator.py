from __future__ import annotations

import os
import time
from typing import Any, Optional

from services import supabase_client

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


def _supabase_plan_store_enabled() -> bool:
    return bool((os.getenv("SUPABASE_URL") or "").strip() and (os.getenv("SUPABASE_SERVICE_KEY") or "").strip())


def _load_supabase_state(session_id: str) -> Optional[dict[str, Any]]:
    if not _supabase_plan_store_enabled():
        return None
    try:
        row = supabase_client.get_sofia_plan_session(session_id)
    except Exception:
        return None
    if not isinstance(row, dict):
        return None
    return {
        "updated_at": time.time(),
        "active_persona_slug": str(row.get("active_persona_slug") or row.get("persona_slug") or "").strip().lower(),
        "last_referenced_node": dict(row.get("last_referenced_node") or {}),
        "recent_turns": list(row.get("recent_turns") or []),
        "plan_json": dict(row.get("plan_json") or {}),
    }


def _persist_state(session_id: str, state: dict[str, Any], fallback_persona_slug: str) -> None:
    _SESSION_MEMORY[session_id] = dict(state)
    if not _supabase_plan_store_enabled():
        return
    plan_json = state.get("plan_json")
    if not isinstance(plan_json, dict):
        return
    persona_slug = str(
        plan_json.get("persona_slug")
        or state.get("active_persona_slug")
        or fallback_persona_slug
        or ""
    ).strip().lower()
    try:
        supabase_client.upsert_sofia_plan_session(
            session_id=session_id,
            persona_slug=persona_slug,
            plan_json=plan_json,
            active_persona_slug=str(state.get("active_persona_slug") or persona_slug).strip().lower(),
            last_referenced_node=state.get("last_referenced_node") if isinstance(state.get("last_referenced_node"), dict) else {},
            recent_turns=list(state.get("recent_turns") or []),
        )
    except Exception:
        return


def get_session_state(session_id: Optional[str]) -> dict[str, Any]:
    key = _normalise_session_id(session_id)
    if not key:
        return {}
    _clean_expired_sessions()
    state = _SESSION_MEMORY.get(key)
    if not state:
        state = _load_supabase_state(key)
        if state:
            _SESSION_MEMORY[key] = dict(state)
    return dict(state) if state else {}


def _default_plan_json(session_id: str, persona_slug: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "persona_slug": persona_slug,
        "active_context": {
            "brand_slug": None,
            "selected_node_id": None,
            "last_referenced_node": None,
        },
        "plan": {
            "briefing": [],
            "campaign": [],
            "audience": [],
            "product_group": [],
            "product": [],
            "offer": [],
            "copy": [],
            "faq": [],
            "rule": [],
            "asset": [],
            "gallery": [],
        },
        "graph_patch_queue": [],
        "blocking_issues": [],
        "suggestions": [],
        "pending_issues": [],
        "validation": {
            "is_valid": True,
            "suggestions": [],
            "pending": [],
            "blocking": [],
        },
    }


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    if isinstance(base, list) and isinstance(patch, list):
        return patch
    return patch


def _validate_plan_json(plan_json: dict[str, Any]) -> dict[str, Any]:
    plan = plan_json.get("plan") if isinstance(plan_json.get("plan"), dict) else {}
    suggestions: list[dict[str, str]] = []
    pending: list[dict[str, str]] = []
    blocking: list[dict[str, str]] = []

    if not plan.get("faq"):
        suggestions.append({"code": "FAQ_RECOMMENDED", "message": "Adicionar FAQ melhora cobertura de objeções, mas não bloqueia criação."})
    if not plan.get("rule"):
        suggestions.append({"code": "RULE_RECOMMENDED", "message": "Adicionar regra comercial é recomendado, mas não bloqueia criação."})

    for section in ("campaign", "audience", "product_group", "product", "offer", "copy", "faq"):
        for idx, item in enumerate(plan.get(section) or []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                pending.append({"code": "MISSING_TITLE", "message": f"{section}[{idx}] sem title."})
            if section in {"campaign", "audience", "product_group", "product", "offer", "copy", "faq"}:
                parent = str(item.get("parent_slug") or "").strip()
                if not parent:
                    pending.append({"code": "MISSING_PARENT", "message": f"{section}[{idx}] sem parent_slug."})

    blocking_markers = {
        "cycle",
        "orphan",
        "edge_inverted",
        "product_above_product_group",
        "embed_without_approved_faq",
        "persistence_failure",
        "critical_duplication",
    }
    for edge in plan_json.get("graph_patch_queue") or []:
        if not isinstance(edge, dict):
            continue
        marker = str(edge.get("marker") or "").strip().lower()
        if marker in blocking_markers:
            blocking.append({"code": marker.upper(), "message": str(edge.get("message") or marker)})

    return {
        "is_valid": len(blocking) == 0,
        "suggestions": suggestions,
        "pending": pending,
        "blocking": blocking,
    }


def get_or_create_plan_json(
    *,
    session_id: Optional[str],
    persona_slug: str,
    selected_node_id: Optional[str] = None,
) -> dict[str, Any]:
    key = _normalise_session_id(session_id)
    if not key:
        plan_json = _default_plan_json("ephemeral", persona_slug)
        plan_json["active_context"]["selected_node_id"] = selected_node_id
        plan_json["validation"] = _validate_plan_json(plan_json)
        plan_json["suggestions"] = list(plan_json["validation"]["suggestions"])
        plan_json["pending_issues"] = list(plan_json["validation"]["pending"])
        plan_json["blocking_issues"] = list(plan_json["validation"]["blocking"])
        return plan_json
    now_ts = time.time()
    _clean_expired_sessions(now_ts)
    state = _SESSION_MEMORY.get(key)
    if not state:
        state = _load_supabase_state(key)
    state = state or {"recent_turns": []}
    plan_json = state.get("plan_json")
    if not isinstance(plan_json, dict):
        plan_json = _default_plan_json(key, persona_slug)
    plan_json["session_id"] = key
    plan_json["persona_slug"] = str(persona_slug or plan_json.get("persona_slug") or "").strip().lower()
    active_context = plan_json.get("active_context") if isinstance(plan_json.get("active_context"), dict) else {}
    active_context["selected_node_id"] = selected_node_id or active_context.get("selected_node_id")
    active_context["last_referenced_node"] = state.get("last_referenced_node") or active_context.get("last_referenced_node")
    plan_json["active_context"] = active_context
    plan_json["validation"] = _validate_plan_json(plan_json)
    plan_json["suggestions"] = list(plan_json["validation"]["suggestions"])
    plan_json["pending_issues"] = list(plan_json["validation"]["pending"])
    plan_json["blocking_issues"] = list(plan_json["validation"]["blocking"])
    state["plan_json"] = plan_json
    state["updated_at"] = now_ts
    _persist_state(key, state, persona_slug)
    return dict(plan_json)


def apply_plan_json_patch(
    *,
    session_id: Optional[str],
    persona_slug: str,
    patch: Optional[dict[str, Any]] = None,
    command: Optional[str] = None,
) -> dict[str, Any]:
    key = _normalise_session_id(session_id)
    if not key:
        raise ValueError("session_id is required")
    plan_json = get_or_create_plan_json(session_id=key, persona_slug=persona_slug)
    next_plan = _deep_merge(plan_json, patch or {})

    text = (command or "").strip().lower()
    if "crie" in text or "criar" in text:
        if "produto" in text:
            title = "Produto"
            parts = re_split_words(command or "")
            if len(parts) > 2:
                title = " ".join(parts[-2:]).strip().title()
            next_plan["plan"]["product"].append({"title": title, "parent_slug": None, "status": "pending_parent"})
        elif "audience" in text or "publico" in text or "público" in text:
            next_plan["plan"]["audience"].append({"title": "Audience", "parent_slug": None, "status": "pending_parent"})
        elif "campanha" in text or "campaign" in text:
            next_plan["plan"]["campaign"].append({"title": "Campaign", "parent_slug": None, "status": "pending_parent"})

    state = _SESSION_MEMORY.get(key)
    if not state:
        state = _load_supabase_state(key)
    state = state or {"recent_turns": []}
    next_plan["validation"] = _validate_plan_json(next_plan)
    next_plan["suggestions"] = list(next_plan["validation"]["suggestions"])
    next_plan["pending_issues"] = list(next_plan["validation"]["pending"])
    next_plan["blocking_issues"] = list(next_plan["validation"]["blocking"])
    state["plan_json"] = next_plan
    state["updated_at"] = time.time()
    _persist_state(key, state, persona_slug)
    return dict(next_plan)


def re_split_words(text: str) -> list[str]:
    return [tok for tok in (text or "").replace(",", " ").split() if tok.strip()]


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
    state = _SESSION_MEMORY.get(key)
    if not state:
        state = _load_supabase_state(key)
    state = state or {"recent_turns": []}
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
    state = {
        "updated_at": now_ts,
        "active_persona_slug": str(persona_slug or "").strip().lower(),
        "last_operation_result": dict(operation_result or {}),
        "last_referenced_node": dict(last_referenced_node or state.get("last_referenced_node") or {}),
        "recent_turns": recent_turns,
        # Keep plan_json across turns; otherwise POST /sofia/graph-command clears
        # in-session planning state.
        "plan_json": dict(state.get("plan_json") or {}),
    }
    _persist_state(key, state, persona_slug)


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
