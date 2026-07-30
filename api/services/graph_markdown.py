"""Canonical Markdown normalization for Graph JSON v2 factual nodes."""
from __future__ import annotations

import json
from typing import Any

from schemas.graph_json_v2 import GraphJson, Node


FACTUAL_NODE_TYPES = {
    "persona", "brand", "briefing", "campaign", "audience", "product_group",
    "product", "copy", "rule", "tone", "faq",
}
VALIDATED_STATUSES = {"approved", "validated", "active", "ativo", "embedded"}
_NON_FACTUAL_KEYS = {
    "active", "branch_path", "content_hash", "empty", "file_path",
    "graph_checksum", "graph_id", "graph_json_id", "graph_json_import",
    "graph_json_node_id", "graph_json_parent_id", "graph_version",
    "knowledge_item_id", "knowledge_node_id", "language", "markdown",
    "markdown_document", "metadata", "parent_id", "protected", "question",
    "question_count", "schema_version", "session_id", "source",
    "source_node_id", "source_node_type", "status", "summary", "tags",
    "validation_status",
}


class GraphMarkdownError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("Factual Markdown validation failed")
        self.errors = errors


def _heading(value: str) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


def _render_value(key: str, value: Any, *, depth: int = 2) -> list[str]:
    if value is None or value == "" or value == [] or value == {}:
        return []
    title = _heading(key)
    prefix = "#" * min(6, depth)
    if isinstance(value, dict):
        lines = [f"{prefix} {title}", ""]
        for child_key, child_value in value.items():
            if isinstance(child_value, (dict, list)):
                rendered = _render_value(child_key, child_value, depth=depth + 1)
                if rendered:
                    lines.extend(rendered)
                    lines.append("")
            elif child_value is not None and child_value != "":
                lines.append(f"- **{_heading(child_key)}:** {child_value}")
        return lines
    if isinstance(value, list):
        lines = [f"{prefix} {title}", ""]
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"- `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`")
            else:
                lines.append(f"- {item}")
        return lines
    return [f"{prefix} {title}", "", str(value)]


def markdown_for_node(node: Node) -> str:
    """Return a factual Markdown body without fabricating missing facts."""
    data = dict(node.data or {})
    existing = str(data.get("markdown") or "").strip()
    if existing:
        return existing

    title = node.label or node.slug
    if node.node_type == "faq":
        question = str(data.get("question") or title).strip()
        answer = str(data.get("answer") or data.get("content") or "").strip()
        if not question or not answer:
            return ""
        return (
            f"# {title}\n\n"
            f"## Pergunta\n\n{question}\n\n"
            f"## Resposta\n\n{answer}"
        )

    body = str(data.get("content") or data.get("summary") or "").strip()
    lines = [f"# {title}"]
    if body:
        lines.extend(["", body])
    for key, value in data.items():
        if key in _NON_FACTUAL_KEYS or key == "content":
            continue
        rendered = _render_value(key, value)
        if rendered:
            lines.extend(["", *rendered])
    return "\n".join(lines).strip() if len(lines) > 1 else ""


def canonicalize_graph(graph: GraphJson) -> GraphJson:
    """Clone and normalize factual nodes, rejecting empty validated facts."""
    normalized = GraphJson.model_validate(graph.model_dump())
    errors: list[str] = []
    for node in normalized.nodes:
        if node.node_type not in FACTUAL_NODE_TYPES:
            continue
        markdown = markdown_for_node(node)
        status = str(
            (node.data or {}).get("validation_status")
            or (node.data or {}).get("status")
            or ""
        ).strip().lower()
        if not markdown:
            if status in VALIDATED_STATUSES:
                errors.append(f"validated factual node {node.id} has insufficient content")
            continue
        node.data = {**(node.data or {}), "markdown": markdown}
        if node.node_type == "faq":
            node.data["markdown_document"] = True
            node.data["question_count"] = max(
                1, int((node.data or {}).get("question_count") or 1)
            )
    if errors:
        raise GraphMarkdownError(errors)
    return normalized
