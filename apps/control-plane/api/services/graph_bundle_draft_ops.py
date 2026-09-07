"""Pure GraphBundle draft operations.

Drafts intentionally accept pending and rejected nodes. Publishability belongs
to ``graph_bundle.build_publication_plan``; this module only creates a stable,
auditable candidate and never reads or writes production state.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from schemas.graph_bundle_drafts import GraphBundleDraftOperation
from services import graph_compiler_v3


PROTECTED_NODE_TYPES = {"persona", "embed", "embedded", "gallery"}
FAQ_PUBLISH_RELATION = "publishes_to"


class GraphBundleDraftOperationError(ValueError):
    pass


class GraphBundleDraftConflict(GraphBundleDraftOperationError):
    def __init__(
        self,
        *,
        expected_revision: int,
        actual_revision: int,
        expected_checksum: str,
        actual_checksum: str,
    ) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        self.expected_checksum = expected_checksum
        self.actual_checksum = actual_checksum
        super().__init__("draft_cas_conflict")


def canonicalize_draft(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise GraphBundleDraftOperationError("draft_bundle_invalid")
    candidate = deepcopy(bundle)
    if not isinstance(candidate.get("persona"), dict):
        raise GraphBundleDraftOperationError("draft_persona_required")
    if not isinstance(candidate.get("nodes"), list):
        raise GraphBundleDraftOperationError("draft_nodes_required")
    if not isinstance(candidate.get("edges"), list):
        raise GraphBundleDraftOperationError("draft_edges_required")
    candidate["metadata"] = (
        candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    )
    node_ids: set[str] = set()
    persona_nodes: list[dict[str, Any]] = []
    for node in candidate["nodes"]:
        if not isinstance(node, dict) or not str(node.get("id") or "").strip():
            raise GraphBundleDraftOperationError("draft_node_id_required")
        node_id = str(node["id"]).strip()
        if node_id in node_ids:
            raise GraphBundleDraftOperationError(f"draft_duplicate_node_id:{node_id}")
        node_ids.add(node_id)
        node["id"] = node_id
        node_type = str(node.get("node_type") or "").strip().lower()
        if not node_type:
            raise GraphBundleDraftOperationError(f"draft_node_type_required:{node_id}")
        node["node_type"] = node_type
        node["slug"] = str(node.get("slug") or "").strip()
        if not node["slug"]:
            raise GraphBundleDraftOperationError(f"draft_node_slug_required:{node_id}")
        if node_type == "persona":
            persona_nodes.append(node)
        node["data"] = node.get("data") if isinstance(node.get("data"), dict) else {}
        node["status"] = str(node.get("status") or "pending_validation").lower()
        node["data"].setdefault("source", "pending_source")
        node["tags"] = sorted({str(tag) for tag in node.get("tags") or [] if str(tag)})
    if len(persona_nodes) != 1:
        raise GraphBundleDraftOperationError(
            f"draft_requires_one_persona_node:{len(persona_nodes)}"
        )
    persona_slug = str(candidate["persona"].get("slug") or "").strip()
    if not persona_slug:
        raise GraphBundleDraftOperationError("draft_persona_slug_required")
    if str(persona_nodes[0]["slug"]) != persona_slug:
        raise GraphBundleDraftOperationError("draft_persona_slug_mismatch")

    edge_ids: set[str] = set()
    logical_edges: set[tuple[str, str, str]] = set()
    for edge in candidate["edges"]:
        if not isinstance(edge, dict) or not str(edge.get("id") or "").strip():
            raise GraphBundleDraftOperationError("draft_edge_id_required")
        edge_id = str(edge["id"]).strip()
        if edge_id in edge_ids:
            raise GraphBundleDraftOperationError(f"draft_duplicate_edge_id:{edge_id}")
        edge_ids.add(edge_id)
        edge["id"] = edge_id
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in node_ids:
            raise GraphBundleDraftOperationError(
                f"draft_edge_source_missing:{edge_id}:{source}"
            )
        if target not in node_ids:
            raise GraphBundleDraftOperationError(
                f"draft_edge_target_missing:{edge_id}:{target}"
            )
        edge["source"] = source
        edge["target"] = target
        edge["relation_type"] = str(
            edge.get("relation_type") or "contains"
        ).strip()
        logical_key = _edge_logical_key(edge)
        if logical_key in logical_edges:
            raise GraphBundleDraftOperationError(
                "draft_duplicate_logical_edge:"
                f"{logical_key[0]}:{logical_key[1]}:{logical_key[2]}"
            )
        logical_edges.add(logical_key)
        edge["metadata"] = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
    candidate["nodes"] = sorted(candidate["nodes"], key=lambda row: str(row["id"]))
    candidate["edges"] = sorted(candidate["edges"], key=lambda row: str(row["id"]))
    return candidate


def draft_checksum(bundle: dict[str, Any]) -> str:
    return graph_compiler_v3.canonical_checksum(canonicalize_draft(bundle))


def _set_path(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    current = target
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = deepcopy(value)


def _node_by_id(bundle: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = next((row for row in bundle["nodes"] if str(row.get("id")) == node_id), None)
    if node is None:
        raise GraphBundleDraftOperationError(f"draft_node_not_found:{node_id}")
    return node


def _edge_logical_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(edge.get("source") or ""),
        str(edge.get("target") or ""),
        str(edge.get("relation_type") or "contains"),
    )


def _require_single_embedded(bundle: dict[str, Any]) -> dict[str, Any]:
    embedded = [
        node for node in bundle["nodes"]
        if str(node.get("node_type") or "").lower() in {"embed", "embedded"}
        and str(node.get("status") or "").lower() != "archived"
    ]
    if len(embedded) != 1:
        raise GraphBundleDraftOperationError(
            f"draft_requires_one_embedded_node:{len(embedded)}"
        )
    return embedded[0]


def _approve_faq(bundle: dict[str, Any], node_id: str) -> bool:
    node = _node_by_id(bundle, node_id)
    if str(node.get("node_type") or "").lower() != "faq":
        raise GraphBundleDraftOperationError(f"draft_node_is_not_faq:{node_id}")
    source = str((node.get("data") or {}).get("source") or "").strip().lower()
    if not source or source == "pending_source":
        raise GraphBundleDraftOperationError(f"draft_faq_source_required:{node_id}")
    embedded = _require_single_embedded(bundle)
    target_id = str(embedded["id"])
    matches = [
        edge for edge in bundle["edges"]
        if _edge_logical_key(edge) == (node_id, target_id, FAQ_PUBLISH_RELATION)
    ]
    if len(matches) > 1:
        raise GraphBundleDraftOperationError(f"draft_duplicate_faq_projection:{node_id}")
    changed = str(node.get("status") or "").lower() != "validated"
    node["status"] = "validated"
    node.setdefault("data", {})["status"] = "validated"
    node["data"]["validation_status"] = "validated"
    if not matches:
        edge_id = f"edge:{node_id}:publishes_to:{target_id}"
        if any(str(edge.get("id")) == edge_id for edge in bundle["edges"]):
            raise GraphBundleDraftOperationError(f"draft_edge_id_conflict:{edge_id}")
        bundle["edges"].append({
            "id": edge_id,
            "source": node_id,
            "target": target_id,
            "relation_type": FAQ_PUBLISH_RELATION,
            "weight": 1.0,
            "metadata": {"active": True, "human_approved": True},
        })
        changed = True
    return changed


def _reject_faq(bundle: dict[str, Any], node_id: str) -> bool:
    node = _node_by_id(bundle, node_id)
    if str(node.get("node_type") or "").lower() != "faq":
        raise GraphBundleDraftOperationError(f"draft_node_is_not_faq:{node_id}")
    node["status"] = "rejected"
    node.setdefault("data", {})["status"] = "rejected"
    node["data"]["validation_status"] = "rejected"
    bundle["edges"] = [
        edge for edge in bundle["edges"]
        if not (
            str(edge.get("source") or "") == node_id
            and str(edge.get("relation_type") or "") == FAQ_PUBLISH_RELATION
        )
    ]
    return True


def _invalidate_derived_faqs(bundle: dict[str, Any], changed_node_id: str) -> list[str]:
    """Return approved derived FAQs to review after one factual node changes."""
    invalidated: list[str] = []
    for node in bundle["nodes"]:
        if str(node.get("node_type") or "").lower() != "faq":
            continue
        data = node.get("data") or {}
        provenance = {
            str(data.get("source_node_id") or ""),
            *(str(item) for item in data.get("branch_path") or []),
        }
        if changed_node_id not in provenance:
            continue
        if str(node.get("status") or "").lower() not in {
            "validated", "approved", "active", "ativo",
        }:
            continue
        node["status"] = "pending_validation"
        node.setdefault("data", {})["status"] = "pending_validation"
        node["data"]["validation_status"] = "pending_validation"
        invalidated.append(str(node["id"]))
    if invalidated:
        invalidated_set = set(invalidated)
        bundle["edges"] = [
            edge for edge in bundle["edges"]
            if not (
                str(edge.get("source") or "") in invalidated_set
                and str(edge.get("relation_type") or "") == FAQ_PUBLISH_RELATION
            )
        ]
    return invalidated


def faq_impact(bundle: dict[str, Any], changed_node_ids: Iterable[str]) -> dict[str, Any]:
    """Find only FAQs whose recorded factual provenance intersects a change."""
    changed = {str(node_id) for node_id in changed_node_ids if str(node_id)}
    known = {str(node.get("id") or "") for node in bundle.get("nodes") or []}
    missing = sorted(changed - known)
    if missing:
        raise GraphBundleDraftOperationError(
            "draft_node_not_found:" + ",".join(missing)
        )
    affected: list[str] = []
    for node in bundle.get("nodes") or []:
        if str(node.get("node_type") or "").lower() != "faq":
            continue
        data = node.get("data") or {}
        provenance = {
            str(data.get("source_node_id") or ""),
            *(str(item) for item in data.get("branch_path") or []),
        }
        if changed.intersection(provenance):
            affected.append(str(node.get("id") or ""))
    return {
        "changed_node_ids": sorted(changed),
        "affected_faq_node_ids": sorted(affected),
        "affected_count": len(affected),
    }


def apply_operations(
    bundle: dict[str, Any], operations: Iterable[GraphBundleDraftOperation]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    candidate = canonicalize_draft(bundle)
    changed_nodes: set[str] = set()
    changed_edges: set[str] = set()
    invalidated_faqs: set[str] = set()

    for operation in operations:
        payload = operation.model_dump(mode="python")
        op = payload["op"]
        if op == "update_node":
            node = _node_by_id(candidate, payload["node_id"])
            node_type = str(node.get("node_type") or "").lower()
            requested_status = str(payload["patch"].get("status") or "").lower()
            if (
                node_type in PROTECTED_NODE_TYPES
                and requested_status
                in {"archived", "deleted", "inactive"}
            ):
                raise GraphBundleDraftOperationError(
                    f"draft_protected_node:{payload['node_id']}"
                )
            if node_type == "faq" and requested_status in {"validated", "approved", "active", "ativo"}:
                raise GraphBundleDraftOperationError(
                    f"draft_faq_requires_approve_operation:{payload['node_id']}"
                )
            faq_content_changed = node_type == "faq" and any(
                key in {"title", "summary", "data.question", "data.answer", "data.content"}
                for key in payload["patch"]
            )
            for key, value in payload["patch"].items():
                _set_path(node, key, value)
                if key == "status":
                    node.setdefault("data", {})["status"] = str(value).lower()
            changed_nodes.add(payload["node_id"])
            if faq_content_changed:
                node["status"] = "pending_validation"
                node.setdefault("data", {})["status"] = "pending_validation"
                node["data"]["validation_status"] = "pending_validation"
                candidate["edges"] = [
                    edge for edge in candidate["edges"]
                    if not (
                        str(edge.get("source") or "") == payload["node_id"]
                        and str(edge.get("relation_type") or "") == FAQ_PUBLISH_RELATION
                    )
                ]
                changed_edges.add(f"faq_projection:{payload['node_id']}")
            elif node_type != "faq":
                invalidated = _invalidate_derived_faqs(candidate, payload["node_id"])
                invalidated_faqs.update(invalidated)
                changed_nodes.update(invalidated)
                changed_edges.update(f"faq_projection:{item}" for item in invalidated)
        elif op == "add_node":
            node = deepcopy(payload["node"])
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                raise GraphBundleDraftOperationError("draft_node_id_required")
            if any(str(row.get("id")) == node_id for row in candidate["nodes"]):
                raise GraphBundleDraftOperationError(f"draft_node_id_conflict:{node_id}")
            if str(node.get("node_type") or "").lower() in PROTECTED_NODE_TYPES:
                raise GraphBundleDraftOperationError(
                    f"draft_protected_node_creation:{node_id}"
                )
            candidate["nodes"].append(node)
            changed_nodes.add(node_id)
        elif op == "archive_node":
            node = _node_by_id(candidate, payload["node_id"])
            if str(node.get("node_type") or "").lower() in PROTECTED_NODE_TYPES:
                raise GraphBundleDraftOperationError(
                    f"draft_protected_node:{payload['node_id']}"
                )
            node["status"] = "archived"
            node.setdefault("data", {})["status"] = "archived"
            changed_nodes.add(payload["node_id"])
        elif op == "add_edge":
            edge = deepcopy(payload["edge"])
            edge_id = str(edge.get("id") or "").strip()
            if not edge_id:
                raise GraphBundleDraftOperationError("draft_edge_id_required")
            if any(str(row.get("id")) == edge_id for row in candidate["edges"]):
                raise GraphBundleDraftOperationError(f"draft_edge_id_conflict:{edge_id}")
            if any(_edge_logical_key(row) == _edge_logical_key(edge) for row in candidate["edges"]):
                raise GraphBundleDraftOperationError("draft_logical_edge_conflict")
            source_node = _node_by_id(candidate, str(edge.get("source") or ""))
            target_node = _node_by_id(candidate, str(edge.get("target") or ""))
            source_type = str(source_node.get("node_type") or "").lower()
            target_type = str(target_node.get("node_type") or "").lower()
            relation = str(edge.get("relation_type") or "")
            if source_type in {"embed", "embedded", "gallery"}:
                raise GraphBundleDraftOperationError("draft_terminal_node_cannot_emit")
            if target_type == "persona":
                raise GraphBundleDraftOperationError("draft_persona_cannot_receive")
            if target_type in {"embed", "embedded"}:
                raise GraphBundleDraftOperationError("draft_embed_requires_approve_faq")
            if target_type == "gallery":
                expected = "gallery_asset" if source_type == "asset" else "publishes_to"
                if relation != expected:
                    raise GraphBundleDraftOperationError(
                        f"draft_gallery_relation_required:{expected}"
                    )
            candidate["edges"].append(edge)
            changed_edges.add(edge_id)
        elif op == "revoke_edge":
            before = len(candidate["edges"])
            candidate["edges"] = [
                edge for edge in candidate["edges"]
                if str(edge.get("id")) != payload["edge_id"]
            ]
            if before == len(candidate["edges"]):
                raise GraphBundleDraftOperationError(
                    f"draft_edge_not_found:{payload['edge_id']}"
                )
            changed_edges.add(payload["edge_id"])
        elif op == "approve_faq":
            if _approve_faq(candidate, payload["node_id"]):
                changed_nodes.add(payload["node_id"])
                changed_edges.add(f"faq_projection:{payload['node_id']}")
        elif op == "reject_faq":
            _reject_faq(candidate, payload["node_id"])
            changed_nodes.add(payload["node_id"])
            changed_edges.add(f"faq_projection:{payload['node_id']}")
        elif op == "add_faq_proposal":
            node_id = payload["node_id"]
            if any(str(row.get("id")) == node_id for row in candidate["nodes"]):
                raise GraphBundleDraftOperationError(f"draft_node_id_conflict:{node_id}")
            source_node = _node_by_id(candidate, payload["source_node_id"])
            if str(source_node.get("node_type") or "") != payload["source_node_type"].lower():
                raise GraphBundleDraftOperationError(
                    f"draft_faq_source_type_mismatch:{node_id}"
                )
            if payload["source_node_id"] not in payload["branch_path"]:
                raise GraphBundleDraftOperationError(
                    f"draft_faq_branch_path_mismatch:{node_id}"
                )
            candidate["nodes"].append({
                "id": node_id,
                "node_type": "faq",
                "slug": payload["slug"],
                "title": payload["question"],
                "summary": payload["answer"],
                "status": "pending_validation",
                "tags": [],
                "data": {
                    "question": payload["question"],
                    "question_aliases": payload["question_aliases"],
                    "answer": payload["answer"],
                    "source": payload["source"],
                    "source_node_id": payload["source_node_id"],
                    "source_node_type": payload["source_node_type"].lower(),
                    "branch_path": (
                        payload["branch_path"]
                        if payload["branch_path"][-1] == node_id
                        else [*payload["branch_path"], node_id]
                    ),
                    "validation_status": "pending_validation",
                    "generator": payload["generator"],
                    "generation_batch_id": payload["generation_batch_id"],
                },
            })
            edge_id = f"edge:{payload['source_node_id']}:contains:{node_id}"
            edge = {
                "id": edge_id, "source": payload["source_node_id"],
                "target": node_id, "relation_type": "contains", "weight": 1.0,
                "metadata": {"active": True, "proposal": True},
            }
            if any(_edge_logical_key(row) == _edge_logical_key(edge) for row in candidate["edges"]):
                raise GraphBundleDraftOperationError("draft_logical_edge_conflict")
            candidate["edges"].append(edge)
            changed_nodes.add(node_id)
            changed_edges.add(edge_id)
        else:  # pragma: no cover - discriminated schema makes this unreachable
            raise GraphBundleDraftOperationError(f"draft_operation_unsupported:{op}")

    candidate = canonicalize_draft(candidate)
    return candidate, {
        "nodes_changed": sorted(changed_nodes),
        "edges_changed": sorted(changed_edges),
        "faq_nodes_requiring_review": sorted(invalidated_faqs),
    }


def apply_operations_with_cas(
    bundle: dict[str, Any],
    *,
    actual_revision: int,
    expected_revision: int,
    expected_checksum: str,
    operations: Iterable[GraphBundleDraftOperation],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one atomic patch only when both revision and checksum still match."""
    actual_checksum = draft_checksum(bundle)
    if (
        expected_revision != actual_revision
        or expected_checksum != actual_checksum
    ):
        raise GraphBundleDraftConflict(
            expected_revision=expected_revision,
            actual_revision=actual_revision,
            expected_checksum=expected_checksum,
            actual_checksum=actual_checksum,
        )
    candidate, change_summary = apply_operations(bundle, operations)
    next_checksum = draft_checksum(candidate)
    return candidate, {
        **change_summary,
        "previous_revision": actual_revision,
        "revision": actual_revision + 1,
        "previous_checksum": actual_checksum,
        "draft_checksum": next_checksum,
    }
