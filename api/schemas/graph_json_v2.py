"""Pydantic schema for graph_json v2 — the single canonical knowledge-graph doc.

Tracks `ai-brain/docs/architecture/graph-json-canonical-architecture.md` §5 and
`agents/ai_brain_regras_negocio_grafo.md` (graph law).

This is the ONE source of truth for the knowledge graph. It replaces the three
historical shapes that used to diverge:
  * `knowledge_plan` / `normalized_plan` (Sofia Criar draft) — now converted to
    GraphJson before save via `graph_json_importer.normalized_plan_to_graph_json`.
  * `plan_json` (Sofia Orquestrar session) — now a thin wrapper around GraphJson
    (see `sofia_orchestrator.plan_json_to_graph_json` / `graph_json_to_plan_json`).
  * `graph_patch` (`nodes_upsert`/`edges_upsert`) — replaced by `Patch` below.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Node(BaseModel):
    """A graph node. `data` is the flexible payload (no new DB tables — AGENTS.md).

    Conventions enforced by `graph_json_v2_validator` / consumed by the importer:
      * data.source                      — provenance ("pending_source" when unknown)
      * data.status / data.validation_status — draft|pending_validation|approved|...
      * data.summary / data.markdown / data.content — node body (markdown is canonical)
      * data.tags                        — list[str]
    FAQ-specific (required for node_type == "faq"):
      * data.branch_path                 — ordered path persona→anchor
      * data.source_node_id / data.source_node_type — the anchor the FAQ answers
      * data.markdown_document (bool) + data.question_count (int>=1) — grouped FAQ doc
      * data.grouped_faq / data.scope    — marks a general (non product-specific) FAQ
    """

    id: str
    node_type: str
    slug: str
    label: str
    parent_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    primary_tree: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class Layout(BaseModel):
    engine: str = "top-down-canonical"
    positions: dict[str, list[float]] = Field(default_factory=dict)


class Validation(BaseModel):
    is_valid: bool = True
    errors: list[str] = Field(default_factory=list)


class GraphJson(BaseModel):
    schema_version: str = "2.0"
    graph_id: str
    tenant: str
    persona_slug: str
    brand_slug: str | None = None
    status: str = "draft"
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    layout: Layout = Field(default_factory=Layout)
    validation: Validation = Field(default_factory=Validation)


class PatchOperation(BaseModel):
    """One step in a Sofia-generated patch."""

    op: str  # add_node | remove_node | add_edge | remove_edge | update_node | set_status
    node: Node | None = None
    edge: Edge | None = None
    id: str | None = None
    value: Any | None = None


class Patch(BaseModel):
    description: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    operations: list[PatchOperation] = Field(default_factory=list)
