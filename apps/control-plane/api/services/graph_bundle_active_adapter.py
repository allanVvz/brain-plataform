"""Reconstruct an editable GraphBundle from one active runtime publication."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from services import graph_bundle, graph_bundle_draft_ops, graph_compiler_v3


class ActivePublicationAdapterError(ValueError):
    pass


def _verified_document_checksum(document: dict[str, Any]) -> str:
    declared = str(document.get("checksum") or "")
    unsigned = deepcopy(document)
    unsigned.pop("checksum", None)
    actual = graph_compiler_v3.canonical_checksum(unsigned)
    if not declared or declared != actual:
        raise ActivePublicationAdapterError("active_publication_checksum_invalid")
    return declared


def active_document_to_draft(
    document: dict[str, Any],
    *,
    expected_persona_slug: str,
    expected_runtime_checksum: str | None = None,
) -> dict[str, Any]:
    """Convert an immutable v3 document without changing its runtime meaning."""
    if not isinstance(document, dict) or document.get("schema_version") != "3.0":
        raise ActivePublicationAdapterError("active_publication_v3_required")
    runtime_checksum = _verified_document_checksum(document)
    if expected_runtime_checksum and runtime_checksum != expected_runtime_checksum:
        raise ActivePublicationAdapterError("active_publication_checksum_mismatch")

    persona = document.get("persona")
    if not isinstance(persona, dict):
        raise ActivePublicationAdapterError("active_publication_persona_required")
    persona_slug = str(persona.get("slug") or "")
    if persona_slug != expected_persona_slug:
        raise ActivePublicationAdapterError("active_publication_persona_mismatch")

    manifest = document.get("projection_manifest")
    if not isinstance(manifest, dict):
        raise ActivePublicationAdapterError("active_publication_manifest_required")
    raw_nodes = document.get("nodes")
    raw_edges = document.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ActivePublicationAdapterError("active_publication_graph_required")

    bundle = {
        "bundle_version": graph_bundle.BUNDLE_VERSION,
        "persona": {
            "id": str(persona.get("id") or ""),
            "slug": persona_slug,
        },
        "metadata": {
            "base_runtime_checksum": runtime_checksum,
            "embedding_profile": {
                "embedding_provider": manifest.get("embedding_provider"),
                "embedding_model": manifest.get("embedding_model"),
                "embedding_dimension": manifest.get("embedding_dimension"),
            },
        },
        "nodes": [
            {
                key: deepcopy(node.get(key))
                for key in (
                    "id", "projection_node_id", "node_type", "slug", "title",
                    "summary", "tags", "status", "data",
                )
            }
            for node in raw_nodes
            if isinstance(node, dict)
        ],
        "edges": [
            {
                key: deepcopy(edge.get(key))
                for key in (
                    "id", "source", "target", "relation_type", "weight", "metadata",
                )
            }
            for edge in raw_edges
            if isinstance(edge, dict)
        ],
    }
    candidate = graph_bundle_draft_ops.canonicalize_draft(bundle)
    recompiled = graph_bundle.compile_bundle(candidate)
    if recompiled.get("checksum") != runtime_checksum:
        raise ActivePublicationAdapterError(
            "active_publication_roundtrip_checksum_mismatch"
        )
    return candidate
