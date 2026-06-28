"""Canonical Graph JSON v2 schema.

Graph JSON v2 is the versioned document shape used to move the knowledge graph
from several derived tables toward one auditable document per persona.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Node(BaseModel):
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
    op: str
    node: Node | None = None
    edge: Edge | None = None
    id: str | None = None
    value: Any | None = None


class Patch(BaseModel):
    description: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    operations: list[PatchOperation] = Field(default_factory=list)
