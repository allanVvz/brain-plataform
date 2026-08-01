"""Strict contracts shared by Brain and persona n8n workflows."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationRoute(StrEnum):
    SDR = "SDR"
    CLOSER = "CLOSER"
    HUMAN = "HUMAN"


class CartAction(StrEnum):
    NONE = "none"
    ADD_ITEM = "add_item"
    CHANGE_QUANTITY = "change_quantity"
    REMOVE_ITEM = "remove_item"
    SHOW_TOTAL = "show_total"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER = "cancel_order"


class ConversationContext(StrictModel):
    persona_slug: str
    agent_slug: str
    graph_version: int = Field(ge=1)
    graph_checksum: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    cart: dict[str, Any]
    rag_nodes: list[dict[str, Any]]
    rag_paths: list[list[str]]
    rag_chunks: list[dict[str, Any]] = Field(default_factory=list)
    system_prompt: str = ""


class ConversationDecision(StrictModel):
    classifier: str = "deterministic_v1"
    intent: str
    route: ConversationRoute
    confidence: float = Field(ge=0, le=1)
    cart_action: CartAction = CartAction.NONE
    product_slug: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    lead_stage: str
    handoff_reason: str | None = None
    evidence_node_ids: list[str] = Field(default_factory=list)


class AgentResponse(StrictModel):
    reply_text: str | None
    role: ConversationRoute
    evidence_node_ids: list[str] = Field(default_factory=list)
    cart_state: dict[str, Any]
    handoff_required: bool = False
    extracted_fields: dict[str, str] = Field(default_factory=dict)
