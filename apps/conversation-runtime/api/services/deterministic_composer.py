"""Text composition owned exclusively by the deterministic engine.

The agentic runtime must never import this module. Deterministic bindings keep
their graph-authored question sequencing while model bindings retain the
model's public reply verbatim.
"""
from __future__ import annotations

from typing import Any

from schemas.conversation import ConversationContext


def next_field_question(
    cart_state: dict[str, Any], context: ConversationContext
) -> str | None:
    """Return the graph-authored question for the deterministic next field."""
    if cart_state.get("business_model") != "appointment":
        return None
    missing = list(cart_state.get("missing_fields") or [])
    if not missing:
        return None
    persona_node = next(
        (item for item in context.rag_nodes if item.get("node_type") == "persona"),
        None,
    )
    questions = (
        (persona_node or {})
        .get("data", {})
        .get("appointment_policy", {})
        .get("field_questions")
        or {}
    )
    question = questions.get(missing[0])
    if not isinstance(question, str) or not question.strip():
        raise ValueError(
            "published graph appointment_policy.field_questions is missing "
            f"required field {missing[0]}"
        )
    return question.strip()


def ensure_trailing_question(
    reply_text: str | None,
    cart_state: dict[str, Any],
    context: ConversationContext,
) -> str | None:
    """Append graph copy only for the deterministic engine."""
    if reply_text is None:
        return None
    text = reply_text.strip()
    if text.endswith("?"):
        return reply_text
    question = next_field_question(cart_state, context)
    if not question:
        return reply_text
    return question if not text else f"{text} {question}"
