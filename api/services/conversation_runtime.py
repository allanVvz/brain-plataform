"""Graph-backed Vitoria conversation runtime used by persona n8n workflows."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from schemas.conversation import (
    AgentResponse,
    CartAction,
    ConversationContext,
    ConversationDecision,
    ConversationRoute,
)
from services import graph_json_v2_store, supabase_client
from services.model_router import get_router
from services.deterministic_sdr import (
    DeterministicSDR,
    _quantity,
    catalog_from_graph,
)


STAGES = ("novo", "contatado", "engajado", "qualificado", "oportunidade")
INTENT_ACTIONS = {
    "add_item": CartAction.ADD_ITEM,
    "change_quantity": CartAction.CHANGE_QUANTITY,
    "remove_item": CartAction.REMOVE_ITEM,
    "consult_price": CartAction.SHOW_TOTAL,
    "confirm_order": CartAction.CONFIRM_ORDER,
    "deny_order": CartAction.CANCEL_ORDER,
}
CLOSER_INTENTS = {
    "add_item",
    "change_quantity",
    "remove_item",
    "provide_name",
    "provide_address",
    "confirm_order",
    "deny_order",
}


class PublishedGraphUnavailable(RuntimeError):
    pass


class ModelDecisionError(RuntimeError):
    pass


def _json_object(raw: str) -> dict[str, Any]:
    start = (raw or "").find("{")
    end = (raw or "").rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model output does not contain a JSON object")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output must be an object")
    return parsed


def strict_model_decision(
    context: ConversationContext,
    *,
    router: Any | None = None,
    model: str | None = None,
) -> ConversationDecision:
    """Validate strict model JSON, allowing exactly one correction attempt."""
    router = router or get_router()
    model = model or os.environ.get("CONVERSATION_CLASSIFIER_MODEL") or ""
    if not model:
        raise ModelDecisionError("conversation classifier model is not configured")
    evidence = [
        {
            "id": node.get("id"),
            "node_type": node.get("node_type"),
            "slug": node.get("slug"),
            "title": node.get("title"),
        }
        for node in context.rag_nodes
    ]
    schema = ConversationDecision.model_json_schema()
    prompt = (
        "Classifique a conversa usando apenas os IDs de evidência fornecidos. "
        "Não calcule preço ou total e não altere o carrinho. Responda somente "
        "com JSON compatível com o schema.\n"
        f"SCHEMA={json.dumps(schema, ensure_ascii=False)}\n"
        f"MESSAGES={json.dumps(context.messages[-20:], ensure_ascii=False)}\n"
        f"CART={json.dumps(context.cart, ensure_ascii=False)}\n"
        f"EVIDENCE={json.dumps(evidence, ensure_ascii=False)}"
    )
    error = ""
    for attempt in range(2):
        request = prompt
        if attempt:
            request += (
                "\nA saída anterior foi inválida. Corrija uma única vez. "
                f"ERRO={error}"
            )
        try:
            raw = router.chat(model, request, max_tokens=700)
            decision = ConversationDecision.model_validate(_json_object(raw))
            allowed_ids = {
                str(node.get("id")) for node in context.rag_nodes if node.get("id")
            }
            if not set(decision.evidence_node_ids).issubset(allowed_ids):
                raise ValueError("model referenced evidence outside context")
            return decision
        except Exception as exc:
            error = str(exc)[:1000]
    raise ModelDecisionError(error or "invalid model decision")


def _norm(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _node_path(graph: Any, node_id: str) -> list[str]:
    by_id = {node.id: node for node in graph.nodes}
    result: list[str] = []
    current = by_id.get(node_id)
    seen: set[str] = set()
    while current and current.id not in seen:
        seen.add(current.id)
        result.insert(0, current.id)
        current = by_id.get(current.parent_id or "")
    return result


def _current_graph(persona_slug: str) -> tuple[int, str, Any]:
    current = graph_json_v2_store.load_current(persona_slug)
    if not current:
        raise PublishedGraphUnavailable(
            f"No published Graph JSON v2 for {persona_slug}"
        )
    version, graph = current
    event = graph_json_v2_store.latest_event(persona_slug) or {}
    checksum = str(
        ((event.get("payload") or {}).get("checksum"))
        or graph_json_v2_store.checksum_graph(graph)
    )
    if graph.status != "published" or not graph.validation.is_valid:
        raise PublishedGraphUnavailable(
            f"Published graph is not valid for {persona_slug}"
        )
    return version, checksum, graph


def _relevant_nodes(graph: Any, query: str, *, limit: int = 30) -> list[Any]:
    terms = {term for term in _norm(query).split() if len(term) > 1}
    mandatory = {"persona", "brand", "tone", "rule", "briefing"}
    scored: list[tuple[int, Any]] = []
    for node in graph.nodes:
        data = node.data or {}
        if data.get("active", True) is False:
            continue
        if str(data.get("status") or "").lower() not in {
            "approved",
            "validated",
            "active",
            "ativo",
        }:
            continue
        haystack = _norm(
            " ".join(
                (
                    node.slug,
                    node.label,
                    str(data.get("markdown") or ""),
                    " ".join(str(alias) for alias in data.get("aliases") or []),
                )
            )
        )
        score = sum(1 for term in terms if term in haystack)
        if node.node_type in mandatory:
            score += 100
        if score:
            scored.append((score, node))
    scored.sort(key=lambda item: (item[0], item[1].id), reverse=True)
    selected: dict[str, Any] = {
        node.id: node for _, node in scored[:limit]
    }
    by_id = {node.id: node for node in graph.nodes}
    for node in list(selected.values()):
        for path_id in _node_path(graph, node.id):
            if path_id in by_id:
                selected[path_id] = by_id[path_id]
    return list(selected.values())


def build_context(
    *,
    persona_slug: str,
    lead_ref: int,
    message: str,
    message_id: str | None = None,
) -> ConversationContext:
    version, checksum, graph = _current_graph(persona_slug)
    lead = supabase_client.get_lead_by_ref(lead_ref) or {}
    if lead.get("persona_id"):
        persona = supabase_client.get_persona(persona_slug) or {}
        if persona.get("id") and persona["id"] != lead["persona_id"]:
            raise PermissionError("lead does not belong to requested persona")
    messages = supabase_client.get_messages(str(lead_ref), limit=20) or []
    if message and not any(
        str(row.get("message_id") or row.get("external_message_id") or "")
        == str(message_id or "")
        for row in messages
    ):
        messages.append(
            {
                "message_id": message_id,
                "sender_type": "lead",
                "role": "user",
                "texto": message,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    messages = messages[-20:]
    lead_metadata = lead.get("metadata") or {}
    cart = dict(lead_metadata.get("vitoria_state") or {})
    prior_runtime = lead_metadata.get("conversation_runtime") or {}
    prior_version = prior_runtime.get("graph_version")
    prior_checksum = prior_runtime.get("graph_checksum")
    # A cart is evidence-bound.  It cannot be silently carried into a new
    # publication because product aliases, prices, or availability may have
    # changed.  The next decision will atomically hand the conversation over.
    try:
        graph_changed = bool(prior_version) and (
            int(prior_version) != version
            or str(prior_checksum or "") != checksum
        )
    except (TypeError, ValueError):
        graph_changed = True
    if graph_changed:
        cart = {
            "_lead_stage": lead.get("stage") or "novo",
            "_graph_changed": True,
            "_previous_graph_version": prior_version,
            "_previous_graph_checksum": prior_checksum,
        }
    cart.setdefault("_lead_stage", lead.get("stage") or "novo")
    nodes = _relevant_nodes(graph, message)
    agent_slug = next(
        (
            str((node.data or {}).get("metadata", {}).get("agent_slug"))
            for node in graph.nodes
            if (node.data or {}).get("metadata", {}).get("agent_slug")
        ),
        str(
            (
                next(
                    (
                        (node.data or {}).get("metadata", {})
                        for node in graph.nodes
                        if node.node_type == "persona"
                    ),
                    {},
                )
            ).get("public_agent_slug")
            or "agent"
        ),
    )
    return ConversationContext(
        persona_slug=persona_slug,
        agent_slug=agent_slug,
        graph_version=version,
        graph_checksum=checksum,
        messages=messages,
        cart=cart,
        rag_nodes=[
            {
                "id": node.id,
                "node_type": node.node_type,
                "slug": node.slug,
                "title": node.label,
                "status": (node.data or {}).get("status"),
                "source": (node.data or {}).get("source"),
                "data": node.data or {},
            }
            for node in nodes
        ],
        rag_paths=[_node_path(graph, node.id) for node in nodes],
    )


def _message(context: ConversationContext) -> str:
    for message in reversed(context.messages):
        role = str(
            message.get("role") or message.get("sender_type") or ""
        ).lower()
        if role in {"user", "lead", "client", "cliente"}:
            return str(
                message.get("texto")
                or message.get("content")
                or message.get("text")
                or ""
            )
    return ""


def _stage(current: str, intent: str, route: ConversationRoute) -> str:
    try:
        index = STAGES.index(current)
    except ValueError:
        index = 0
    target = {
        ConversationRoute.SDR: 1,
        ConversationRoute.CLOSER: 3,
        ConversationRoute.HUMAN: index,
    }[route]
    if intent in {"consult_product", "consult_price", "consult_category"}:
        target = max(target, 2)
    if intent in {"provide_name", "provide_address", "confirm_order"}:
        target = 4
    return STAGES[max(index, target)]


def decide(
    context: ConversationContext,
) -> tuple[ConversationDecision, AgentResponse]:
    version, checksum, graph = _current_graph(context.persona_slug)
    if version != context.graph_version or checksum != context.graph_checksum:
        decision = ConversationDecision(
            intent="stale_graph",
            route=ConversationRoute.HUMAN,
            confidence=0,
            lead_stage=str(context.cart.get("_lead_stage") or "novo"),
            handoff_reason="graph_version_changed",
            evidence_node_ids=[],
        )
        response = AgentResponse(
            reply_text=None,
            role=ConversationRoute.HUMAN,
            evidence_node_ids=[],
            cart_state=context.cart,
            handoff_required=True,
        )
        return decision, response

    message = _message(context)
    normalized = _norm(message)
    state = dict(context.cart)
    current_stage = str(state.pop("_lead_stage", "novo"))
    graph_changed = bool(state.pop("_graph_changed", False))
    catalog = catalog_from_graph(graph)
    engine = DeterministicSDR(catalog)
    product = catalog.find_product(message)
    if not product:
        last_slug = next(
            (
                item.get("product_slug")
                for item in reversed(state.get("items") or [])
                if item.get("product_slug")
            ),
            None,
        )
        product = next(
            (item for item in catalog.products if item.slug == last_slug),
            None,
        )

    explicit_human = any(
        value in normalized
        for value in (
            "atendimento humano",
            "falar com alguem",
            "falar com uma pessoa",
            "atendente",
            "humano",
        )
    )
    exceptional = any(
        value in normalized
        for value in (
            "reclamacao",
            "reclamar",
            "problema",
            "suporte",
            "negociar",
            "desconto especial",
        )
    )
    if graph_changed:
        intent = "stale_graph"
        route = ConversationRoute.HUMAN
        confidence = 0.0
        handoff_reason = "graph_version_changed"
        state["conversation_state"] = "handoff"
        result = {
            "reply": "Vou encaminhar para o atendimento revisar seu pedido com a versão atual do cardápio.",
            "state": state,
            "handoff": True,
        }
    elif explicit_human or exceptional:
        intent = "request_human" if explicit_human else "exceptional_support"
        route = ConversationRoute.HUMAN
        confidence = 1.0
        state["conversation_state"] = "handoff"
        result = {
            "reply": "Vou encaminhar sua conversa para o atendimento humano.",
            "state": state,
            "handoff": True,
        }
        handoff_reason = intent
    else:
        result = engine.handle(
            message,
            state=state,
            history=context.messages,
        )
        state = result["state"]
        intent = str(result.get("intent") or "ununderstood")
        route = (
            ConversationRoute.HUMAN
            if result.get("handoff")
            else (
                ConversationRoute.CLOSER
                if intent in CLOSER_INTENTS
                else ConversationRoute.SDR
            )
        )
        confidence = 1.0 if intent != "ununderstood" else 0.7
        handoff_reason = None
        if intent == "ununderstood":
            attempts = int(state.get("clarification_attempts") or 0) + 1
            state["clarification_attempts"] = attempts
            if attempts > 1:
                route = ConversationRoute.HUMAN
                confidence = 0.0
                handoff_reason = "missing_approved_evidence"
                state["conversation_state"] = "handoff"
                result["reply"] = (
                    "Não encontrei evidência aprovada para responder. "
                    "Vou encaminhar ao atendimento humano."
                )
                result["handoff"] = True
        else:
            state["clarification_attempts"] = 0
        if intent == "confirm_order":
            route = ConversationRoute.HUMAN
            handoff_reason = "confirmed_pending_human"

    if not product:
        resolved_slug = next(
            (
                item.get("product_slug")
                for item in reversed(state.get("items") or [])
                if item.get("product_slug")
            ),
            None,
        )
        product = next(
            (item for item in catalog.products if item.slug == resolved_slug),
            None,
        )

    evidence_node_ids: list[str] = []
    if product:
        product_id = next(
            (
                node.id
                for node in graph.nodes
                if node.node_type == "product" and node.slug == product.slug
            ),
            None,
        )
        if product_id:
            evidence_node_ids.extend(_node_path(graph, product_id))
    for item in context.rag_nodes:
        if item.get("node_type") in {"persona", "brand", "tone", "rule", "briefing"}:
            evidence_node_ids.append(str(item["id"]))
    evidence_node_ids = list(dict.fromkeys(evidence_node_ids))
    if not evidence_node_ids:
        route = ConversationRoute.HUMAN
        confidence = 0.0
        handoff_reason = "missing_approved_evidence"
        result["handoff"] = True
        result["reply"] = None

    decision = ConversationDecision(
        intent=intent,
        route=route,
        confidence=confidence,
        cart_action=INTENT_ACTIONS.get(intent, CartAction.NONE),
        product_slug=product.slug if product else None,
        quantity=_quantity(message) if product else None,
        lead_stage=_stage(current_stage, intent, route),
        handoff_reason=handoff_reason,
        evidence_node_ids=evidence_node_ids,
    )
    response = AgentResponse(
        reply_text=result.get("reply"),
        role=route,
        evidence_node_ids=evidence_node_ids,
        cart_state=state,
        handoff_required=route == ConversationRoute.HUMAN,
    )
    return decision, response


def commit(
    *,
    lead_ref: int,
    context: ConversationContext,
    decision: ConversationDecision,
    response: AgentResponse,
    correlation_id: str,
    phone_number_id: str | None,
    inbound_buffer_id: str | None = None,
) -> dict[str, Any]:
    lead = supabase_client.get_lead_by_ref(lead_ref) or {}
    metadata = {
        **(lead.get("metadata") or {}),
        "vitoria_state": response.cart_state,
        "conversation_runtime": {
            "agent_slug": context.agent_slug,
            "graph_version": context.graph_version,
            "graph_checksum": context.graph_checksum,
            "last_intent": decision.intent,
            "last_route": decision.route.value,
            "evidence_node_ids": decision.evidence_node_ids,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    if response.handoff_required:
        supabase_client.handoff_whatsapp_lead_state(
            lead_ref,
            metadata=metadata,
            stage=decision.lead_stage,
        )
    else:
        supabase_client.update_lead(
            lead_ref,
            {"metadata": metadata, "stage": decision.lead_stage},
        )

    persona = supabase_client.get_persona(context.persona_slug) or {}
    supabase_client.insert_agent_log(
        {
            "lead_id": str(lead_ref),
            "persona_id": persona.get("id"),
            "agent_type": context.agent_slug,
            "action": "[INFO] conversation decision committed",
            "decision": decision.model_dump_json(),
            "metadata": {
                "level": "INFO",
                "component": "conversation_runtime",
                "correlation_id": correlation_id,
                "graph_version": context.graph_version,
                "graph_checksum": context.graph_checksum,
                "route": decision.route.value,
                "role": response.role.value,
                "intent": decision.intent,
                "evidence_node_ids": decision.evidence_node_ids,
            },
            "input": {"messages": context.messages[-20:]},
            "output": {
                "decision": decision.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            },
        }
    )

    message_id = f"ai:{correlation_id}"
    buffer = None
    if response.reply_text:
        try:
            supabase_client.insert_message(
                {
                "lead_ref": lead_ref,
                "message_id": message_id,
                "sender_type": "agent",
                "role": "assistant",
                "canal": "whatsapp",
                "texto": response.reply_text,
                "direction": "outbound",
                "status": "pending",
                "whatsapp_phone_number_id": phone_number_id,
                "correlation_id": correlation_id,
                "metadata": {
                    "agent_slug": context.agent_slug,
                    "role": response.role.value,
                    "intent": decision.intent,
                    "graph_version": context.graph_version,
                    "graph_checksum": context.graph_checksum,
                    "evidence_node_ids": decision.evidence_node_ids,
                },
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            duplicate = any(
                marker in str(exc).lower()
                for marker in ("duplicate", "unique", "already exists")
            )
            if not duplicate:
                raise
        if persona.get("id") and phone_number_id:
            buffer = supabase_client.enqueue_whatsapp_message(
                {
                    "persona_id": persona["id"],
                    "lead_ref": lead_ref,
                    "whatsapp_phone_number_id": phone_number_id,
                    "direction": "outbound",
                    "payload": {
                        "text": response.reply_text,
                        "sender_type": "ai",
                        "role": response.role.value,
                    },
                    "status": "pending_send",
                    "batch_key": f"{persona['id']}:{lead_ref}",
                    "idempotency_key": message_id,
                    "correlation_id": correlation_id,
                }
            )

    supabase_client.insert_event(
        {
            "event_type": "conversation.decision_committed",
            "entity_type": "lead",
            "entity_id": str(lead_ref),
            "persona_id": persona.get("id"),
            "payload": {
                "correlation_id": correlation_id,
                "inbound_buffer_id": inbound_buffer_id,
                "decision": decision.model_dump(mode="json"),
                "response_role": response.role.value,
                "handoff": response.handoff_required,
                "graph_version": context.graph_version,
                "graph_checksum": context.graph_checksum,
                "outbound_buffer_id": (buffer or {}).get("id"),
            },
        },
        source="conversation_runtime",
    )
    return {
        "ok": True,
        "message_id": message_id if response.reply_text else None,
        "outbound_buffer_id": (buffer or {}).get("id"),
        "handoff": response.handoff_required,
        "ai_paused": response.handoff_required,
        "route": decision.route.value,
        "role": response.role.value,
        "intent": decision.intent,
        "reply_text": response.reply_text,
        "classifier": decision.classifier,
        "evidence_node_ids": decision.evidence_node_ids,
        "graph_version": context.graph_version,
        "graph_checksum": context.graph_checksum,
    }


def execute_pipeline(
    *,
    persona_slug: str,
    lead_ref: int,
    message: str,
    message_id: str | None,
    correlation_id: str,
    phone_number_id: str | None,
    inbound_buffer_id: str | None = None,
) -> dict[str, Any]:
    """Run the same context -> classify -> commit contract used by n8n."""
    context = build_context(
        persona_slug=persona_slug,
        lead_ref=lead_ref,
        message=message,
        message_id=message_id,
    )
    decision, response = decide(context)
    result = commit(
        lead_ref=lead_ref,
        context=context,
        decision=decision,
        response=response,
        correlation_id=correlation_id,
        phone_number_id=phone_number_id,
        inbound_buffer_id=inbound_buffer_id,
    )
    return {
        **result,
        "pipeline_contract": "conversation_v1",
        "classifier": decision.classifier,
        "context": {
            "graph_version": context.graph_version,
            "graph_checksum": context.graph_checksum,
        },
    }
