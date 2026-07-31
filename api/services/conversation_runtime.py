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
from services import (
    graph_json_v2_store,
    lead_qualification,
    supabase_client,
    whatsapp_outbox,
)
from services.model_router import get_router
from services.deterministic_sdr import (
    DeterministicSDR,
    _quantity,
    catalog_from_graph,
)
from services.deterministic_appointment import DeterministicAppointment


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


def _business_model(graph: Any) -> str:
    persona = next(
        (node for node in graph.nodes if node.node_type == "persona"),
        None,
    )
    data = (persona.data or {}) if persona else {}
    metadata = data.get("metadata") or {}
    return str(
        data.get("business_model")
        or metadata.get("business_model")
        or "sales"
    ).strip().lower()


def _appointment_policy(graph: Any) -> dict[str, Any]:
    persona = next(
        (node for node in graph.nodes if node.node_type == "persona"),
        None,
    )
    data = (persona.data or {}) if persona else {}
    return dict(data.get("appointment_policy") or {})


def _approved_faq_match(graph: Any, message: str) -> Any | None:
    """Match only an exact, validated FAQ question.

    Exact normalization keeps graph answers authoritative without introducing
    fuzzy guesses. FAQ interruptions must not discard an in-progress
    appointment request; the caller preserves the cart state unchanged.
    """
    query = _norm(message)
    if not query:
        return None
    for node in graph.nodes:
        if node.node_type != "faq":
            continue
        data = node.data or {}
        if str(data.get("status") or "").lower() not in {
            "approved",
            "validated",
            "active",
            "ativo",
        }:
            continue
        questions = (
            str(data.get("question") or ""),
            str(node.label or ""),
        )
        if any(query == _norm(question) for question in questions if question):
            return node
    return None


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
    cart = dict(
        lead_metadata.get("conversation_state")
        or lead_metadata.get("vitoria_state")
        or {}
    )
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


def _observation_value(value: Any, *, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip(" .,")
    return normalized[:limit] if len(normalized) >= 2 else None


def _apply_model_fields(
    state: dict[str, Any],
    observation: dict[str, Any] | None,
    *,
    business_model: str,
) -> dict[str, Any]:
    """Append model-extracted facts without granting it business authority."""
    fields = (observation or {}).get("fields")
    if not isinstance(fields, dict):
        return state
    merged = dict(state)
    if business_model == "appointment":
        request = dict(merged.get("appointment_request") or {})
        for field in (
            "customer_name",
            "vehicle_model",
            "vehicle_size",
            "condition",
            "desired_date",
            "time_window",
        ):
            value = _observation_value(fields.get(field))
            if value and not request.get(field):
                request[field] = value
        merged["appointment_request"] = request
        return merged

    name = _observation_value(fields.get("customer_name"))
    if name and not merged.get("customer_name"):
        merged["customer_name"] = name
    address = fields.get("delivery_address")
    if isinstance(address, dict):
        current_address = dict(merged.get("address") or {})
        for field in (
            "street",
            "number",
            "complement",
            "neighborhood",
            "city",
            "state",
            "zip",
        ):
            value = _observation_value(address.get(field), limit=100)
            if value and not current_address.get(field):
                current_address[field] = value
        if current_address:
            merged["address"] = current_address
    return merged


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


def _appointment_stage(current: str, intent: str) -> str:
    try:
        index = STAGES.index(current)
    except ValueError:
        index = 0
    if intent in {"greeting", "list_services"}:
        target = 1
    elif intent in {"consult_service", "consult_price"}:
        target = 2
    elif intent in {
        "request_quote",
        "request_booking",
        "provide_vehicle",
        "provide_condition",
        "provide_date",
        "provide_time_window",
    }:
        target = 3
    elif intent == "complete_booking_request":
        target = 4
    else:
        target = index
    return STAGES[max(index, target)]


def _appointment_evidence(
    graph: Any,
    *,
    product_slug: str | None,
    include_all_products: bool = False,
) -> list[str]:
    by_id = {node.id: node for node in graph.nodes}
    evidence: list[str] = []
    product_node = next(
        (
            node
            for node in graph.nodes
            if node.node_type == "product" and node.slug == product_slug
        ),
        None,
    )
    product_nodes = (
        [product_node]
        if product_node
        else [node for node in graph.nodes if node.node_type == "product"]
        if include_all_products
        else []
    )
    for selected_product in product_nodes:
        evidence.extend(_node_path(graph, selected_product.id))
        evidence.append(selected_product.id)
        for node in graph.nodes:
            data = node.data or {}
            if (
                node.node_type == "faq"
                and data.get("source_node_id") == selected_product.id
            ):
                evidence.append(node.id)
    for node in graph.nodes:
        if node.node_type in {"persona", "brand", "briefing", "rule", "tone"}:
            status = str((node.data or {}).get("status") or "").lower()
            if status in {"approved", "validated", "active", "ativo"}:
                evidence.extend(_node_path(graph, node.id))
                evidence.append(node.id)
    return [node_id for node_id in dict.fromkeys(evidence) if node_id in by_id]


def _decide_appointment(
    context: ConversationContext,
    graph: Any,
    *,
    graph_changed: bool,
    current_stage: str,
    state: dict[str, Any],
    message: str,
) -> tuple[ConversationDecision, AgentResponse]:
    if graph_changed:
        state["conversation_state"] = "handoff"
        decision = ConversationDecision(
            classifier="deterministic_appointment_v1",
            intent="stale_graph",
            route=ConversationRoute.HUMAN,
            confidence=0,
            lead_stage=current_stage,
            handoff_reason="graph_version_changed",
            evidence_node_ids=[],
        )
        return decision, AgentResponse(
            reply_text=(
                "Vou encaminhar para a equipe revisar sua solicitação com as "
                "informações atuais."
            ),
            role=ConversationRoute.HUMAN,
            evidence_node_ids=[],
            cart_state=state,
            handoff_required=True,
        )

    faq = _approved_faq_match(graph, message)
    if faq:
        answer = str((faq.data or {}).get("answer") or "").strip()
        if answer:
            evidence = list(dict.fromkeys([*_node_path(graph, faq.id), faq.id]))
            state["clarification_attempts"] = 0
            decision = ConversationDecision(
                classifier="deterministic_appointment_v1",
                intent="answer_faq",
                route=ConversationRoute.SDR,
                confidence=1.0,
                lead_stage=current_stage,
                evidence_node_ids=evidence,
            )
            return decision, AgentResponse(
                reply_text=answer,
                role=ConversationRoute.SDR,
                evidence_node_ids=evidence,
                cart_state=state,
                handoff_required=False,
            )

    catalog = catalog_from_graph(graph)
    result = DeterministicAppointment(
        catalog,
        policy=_appointment_policy(graph),
    ).handle(message, state=state)
    evidence = _appointment_evidence(
        graph,
        product_slug=result.product.slug if result.product else None,
        include_all_products=result.intent == "list_services",
    )
    route = ConversationRoute.HUMAN if result.handoff else ConversationRoute.SDR
    confidence = 1.0 if result.intent != "ununderstood" else (0.0 if result.handoff else 0.7)
    if not evidence:
        route = ConversationRoute.HUMAN
        confidence = 0.0
        result.handoff = True
        result.handoff_reason = "missing_approved_evidence"
        result.reply = None
        result.state["conversation_state"] = "handoff"
    decision = ConversationDecision(
        classifier="deterministic_appointment_v1",
        intent=result.intent,
        route=route,
        confidence=confidence,
        product_slug=result.product.slug if result.product else None,
        lead_stage=_appointment_stage(current_stage, result.intent),
        handoff_reason=result.handoff_reason,
        evidence_node_ids=evidence,
    )
    response = AgentResponse(
        reply_text=result.reply,
        role=route,
        evidence_node_ids=evidence,
        cart_state=result.state,
        handoff_required=result.handoff,
    )
    return decision, response


def decide(
    context: ConversationContext,
    *,
    model_observation: dict[str, Any] | None = None,
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
    business_model = _business_model(graph)
    state = _apply_model_fields(
        dict(context.cart),
        model_observation,
        business_model=business_model,
    )
    current_stage = str(state.pop("_lead_stage", "novo"))
    graph_changed = bool(state.pop("_graph_changed", False))
    if business_model == "appointment":
        return _decide_appointment(
            context,
            graph,
            graph_changed=graph_changed,
            current_stage=current_stage,
            state=state,
            message=message,
        )
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


_UNSAFE_CONFIRMATION_VERB = re.compile(
    r"confirmad[oa]|confirmo\b|fechad[oa]|reservad[oa]|"
    r"agendad[oa]\s+para|marcad[oa]\s+para",
    re.IGNORECASE,
)
_UNSAFE_MONEY_TOKEN = re.compile(r"r\$\s?\d", re.IGNORECASE)
_UNSAFE_SCHEDULE_TOKEN = re.compile(
    r"\b\d{1,2}[:h]\d{0,2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
)


def _reply_confirms_price_or_schedule(text: str | None) -> bool:
    """A reply must never both use confirmation language and state a price
    or a date/time in the same breath — only a human may finalize those.

    Informational replies (FAQ prices, durations) are unaffected because they
    never pair a confirmation verb with the figure; this only catches a
    reply that actually claims something is booked or settled.
    """
    if not text:
        return False
    if not _UNSAFE_CONFIRMATION_VERB.search(text):
        return False
    return bool(_UNSAFE_MONEY_TOKEN.search(text) or _UNSAFE_SCHEDULE_TOKEN.search(text))


def commit(
    *,
    lead_ref: int,
    context: ConversationContext,
    decision: ConversationDecision,
    response: AgentResponse,
    correlation_id: str,
    phone_number_id: str | None,
    channel_binding_id: str,
    inbound_buffer_id: str | None = None,
    expected_decision_owner: str | None = None,
) -> dict[str, Any]:
    if _reply_confirms_price_or_schedule(response.reply_text):
        decision = decision.model_copy(
            update={
                "route": ConversationRoute.HUMAN,
                "handoff_reason": decision.handoff_reason
                or "unsafe_reply_blocked_price_or_schedule_confirmation",
            }
        )
        response = response.model_copy(
            update={
                "reply_text": (
                    "Vou encaminhar sua conversa para a equipe confirmar "
                    "os detalhes."
                ),
                "role": ConversationRoute.HUMAN,
                "handoff_required": True,
            }
        )

    lead = supabase_client.get_lead_by_ref(lead_ref) or {}
    if not lead:
        raise LookupError("lead not found")
    # A commit cannot choose transport.  The persisted lead binding is the
    # authority and also protects n8n from committing to another persona.
    persisted_binding_id = lead.get("channel_binding_id")
    if not persisted_binding_id:
        raise RuntimeError("lead has no explicit channel binding")
    if channel_binding_id != persisted_binding_id:
        raise PermissionError("channel binding does not match lead")
    binding = supabase_client.get_workflow_binding_by_id(persisted_binding_id) or {}
    if not binding or binding.get("persona_id") != lead.get("persona_id"):
        raise PermissionError("channel binding does not match lead persona")
    if not binding.get("active"):
        raise RuntimeError("channel binding is inactive")
    binding_metadata = binding.get("metadata") or {}
    if (
        expected_decision_owner
        and binding_metadata.get("decision_owner") != expected_decision_owner
    ):
        raise RuntimeError(
            "binding decision owner does not authorize this commit path"
        )
    if (
        binding_metadata.get("safety_paused")
        or binding.get("connection_status") == "safety_paused"
    ):
        raise RuntimeError("channel binding is safety paused")
    channel_binding_id = persisted_binding_id
    phone_number_id = binding.get("whatsapp_phone_number_id")
    persona = supabase_client.get_persona(context.persona_slug) or {}
    if not persona or persona.get("id") != lead.get("persona_id"):
        raise PermissionError("conversation context does not match lead persona")

    if expected_decision_owner and not inbound_buffer_id:
        raise RuntimeError("inbound buffer id is required for a decision commit")
    commit_claim = None
    if inbound_buffer_id:
        commit_claim = supabase_client.claim_conversation_commit(
            inbound_buffer_id=inbound_buffer_id,
            binding_id=channel_binding_id,
            lead_ref=lead_ref,
            correlation_id=correlation_id,
        )
        claim_state = commit_claim.get("state")
        if claim_state == "completed":
            stored_result = commit_claim.get("result") or {}
            if not isinstance(stored_result, dict):
                raise RuntimeError("stored conversation commit result is invalid")
            return {
                **stored_result,
                "ok": True,
                "deduplicated": True,
            }
        if claim_state == "processing":
            supabase_client.record_whatsapp_safety_violation(
                binding_id=channel_binding_id,
                lead_ref=lead_ref,
                violation_key=f"conversation_commit_reentry:{inbound_buffer_id}",
                reason="compromised conversation commit re-execution",
            )
            raise RuntimeError("conversation commit is already processing")
        if claim_state != "claimed":
            raise RuntimeError("conversation commit claim returned an invalid state")

    message_id = f"ai:{correlation_id}"
    existing_outbound = (
        supabase_client.get_whatsapp_buffer_by_idempotency(message_id)
        if response.reply_text
        else None
    )
    if existing_outbound:
        result = {
            "ok": True,
            "message_id": message_id,
            "outbound_buffer_id": existing_outbound.get("id"),
            "deduplicated": True,
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
            "qualification": (lead.get("metadata") or {}).get("qualification") or {},
            "stage": lead.get("stage") or decision.lead_stage,
        }
        if inbound_buffer_id:
            supabase_client.complete_conversation_commit(
                inbound_buffer_id=inbound_buffer_id,
                binding_id=channel_binding_id,
                lead_ref=lead_ref,
                correlation_id=correlation_id,
                result_payload=result,
            )
        return result
    previous_metadata = dict(lead.get("metadata") or {})
    qualification, qualified_stage = lead_qualification.calculate(
        previous=previous_metadata.get("qualification"),
        business_model=str(
            response.cart_state.get("business_model") or "sales"
        ).lower(),
        intent=decision.intent,
        state={
            **response.cart_state,
            "_decision_product_slug": decision.product_slug,
        },
        current_stage=lead.get("stage") or decision.lead_stage,
        evidence_node_ids=decision.evidence_node_ids,
        update_stage=True,
    )
    metadata = {
        **previous_metadata,
        "conversation_state": response.cart_state,
        "qualification": qualification,
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
    if response.cart_state.get("business_model") != "appointment":
        # Backward-compatible mirror for Baita conversations already consumed
        # by the legacy deterministic/n8n flow.
        metadata["vitoria_state"] = response.cart_state
    appointment_request = dict(
        response.cart_state.get("appointment_request") or {}
    )
    commercial_note = dict(metadata.get("commercial_note") or {})
    if response.cart_state.get("business_model") == "appointment":
        if appointment_request.get("vehicle_model"):
            commercial_note["vehicle_model"] = appointment_request["vehicle_model"]
        for field in ("vehicle_size", "condition", "desired_date", "time_window"):
            if appointment_request.get(field):
                commercial_note[field] = appointment_request[field]
        if commercial_note:
            commercial_note["updated_at"] = datetime.now(timezone.utc).isoformat()
            metadata["commercial_note"] = commercial_note
    lead_update = {"metadata": metadata, "stage": qualified_stage}
    customer_name = (
        appointment_request.get("customer_name")
        if response.cart_state.get("business_model") == "appointment"
        else response.cart_state.get("customer_name")
    )
    service_interest = appointment_request.get("service_slug") or decision.product_slug
    if customer_name:
        lead_update["nome"] = str(customer_name).strip()
    if service_interest:
        lead_update["interesse_produto"] = str(service_interest).strip()
    if response.handoff_required:
        supabase_client.handoff_whatsapp_lead_state(
            lead_ref,
            metadata=metadata,
            stage=qualified_stage,
        )
        if customer_name or service_interest:
            supabase_client.update_lead(lead_ref, lead_update)
    else:
        supabase_client.update_lead(lead_ref, lead_update)

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
                "qualification": qualification,
            },
        }
    )

    buffer = None
    if response.reply_text:
        envelope = whatsapp_outbox.enqueue_outbound(
            lead=lead,
            text=response.reply_text,
            sender_type="agent",
            message_id=message_id,
            correlation_id=correlation_id,
            idempotency_key=message_id,
            metadata={
                "agent_slug": context.agent_slug,
                "role": response.role.value,
                "intent": decision.intent,
                "graph_version": context.graph_version,
                "graph_checksum": context.graph_checksum,
                "evidence_node_ids": decision.evidence_node_ids,
            },
        )
        buffer = {
            "id": envelope.get("buffer_id"),
            "status": envelope.get("status"),
        }

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
                "qualification": qualification,
            },
        },
        source="conversation_runtime",
    )
    result = {
        "ok": True,
        "message_id": message_id if response.reply_text else None,
        "outbound_buffer_id": (buffer or {}).get("id"),
        "deduplicated": False,
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
        "qualification": qualification,
        "stage": qualified_stage,
    }
    if inbound_buffer_id:
        supabase_client.complete_conversation_commit(
            inbound_buffer_id=inbound_buffer_id,
            binding_id=channel_binding_id,
            lead_ref=lead_ref,
            correlation_id=correlation_id,
            result_payload=result,
        )
    return result


def execute_pipeline(
    *,
    persona_slug: str,
    lead_ref: int,
    message: str,
    message_id: str | None,
    correlation_id: str,
    phone_number_id: str | None,
    channel_binding_id: str | None = None,
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
        channel_binding_id=channel_binding_id,
        inbound_buffer_id=inbound_buffer_id,
        expected_decision_owner="deterministic",
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
