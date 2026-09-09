"""Rebuild a GraphBundle candidate from an authenticated active export.

This is a local, read-only production planning tool.  It never connects to the
database and never stages, publishes or activates a graph.  The active export
must carry publication identity so the candidate can be guarded by CAS instead
of being based on a historical bundle that merely looks current.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PLANE_API_DIR = REPO_ROOT / "apps" / "control-plane" / "api"
if str(CONTROL_PLANE_API_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE_API_DIR))

from services import graph_compiler_v3  # noqa: E402
from services.graph_bundle import (  # noqa: E402
    GraphBundleError,
    build_publication_plan,
    compile_bundle,
    normalize_bundle,
)


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CandidatePreparationError(ValueError):
    """A deterministic gate rejected the candidate before plan generation."""

    def __init__(self, errors: list[str] | str):
        values = [errors] if isinstance(errors, str) else errors
        self.errors = list(dict.fromkeys(str(value) for value in values if value))
        super().__init__("; ".join(self.errors))


def _json_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise CandidatePreparationError(f"json_object_expected:{path}")
    return value


def _publication_envelope(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return publication metadata and document from supported export envelopes."""
    publication = payload.get("publication")
    if isinstance(publication, dict):
        document = payload.get("document_json") or payload.get("document")
        if not isinstance(document, dict):
            document = publication.get("document_json")
        metadata = publication
    else:
        document = payload.get("document_json")
        metadata = payload
    if not isinstance(document, dict):
        raise CandidatePreparationError("active_export_envelope_required")
    return metadata, document


def validate_active_export(
    payload: dict[str, Any],
    *,
    expected_publication_id: str,
    expected_version: int,
    expected_runtime_checksum: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate active identity, internal checksum and compiler compatibility."""
    publication, document = _publication_envelope(payload)
    errors: list[str] = []
    actual_id = str(publication.get("id") or publication.get("publication_id") or "")
    actual_status = str(publication.get("status") or "").lower()
    try:
        actual_version = int(publication.get("version"))
    except (TypeError, ValueError):
        actual_version = -1
    actual_checksum = str(publication.get("checksum") or "")
    document_checksum = str(document.get("checksum") or "")

    if actual_id != expected_publication_id:
        errors.append(
            f"baseline_publication_id_mismatch:{actual_id}:{expected_publication_id}"
        )
    if actual_version != int(expected_version):
        errors.append(
            f"baseline_publication_version_mismatch:{actual_version}:{expected_version}"
        )
    if actual_status != "active":
        errors.append(f"baseline_publication_not_active:{actual_status or 'missing'}")
    if actual_checksum != expected_runtime_checksum:
        errors.append(
            f"baseline_publication_checksum_mismatch:{actual_checksum}:{expected_runtime_checksum}"
        )
    if document_checksum != expected_runtime_checksum:
        errors.append(
            f"baseline_document_checksum_mismatch:{document_checksum}:{expected_runtime_checksum}"
        )
    unsigned = deepcopy(document)
    unsigned.pop("checksum", None)
    computed = graph_compiler_v3.canonical_checksum(unsigned)
    if computed != document_checksum:
        errors.append(f"baseline_document_integrity_error:{computed}:{document_checksum}")
    compiler_version = str(document.get("compiler_version") or "")
    if compiler_version != graph_compiler_v3.COMPILER_VERSION:
        errors.append(
            "baseline_compiler_version_mismatch:"
            f"{compiler_version}:{graph_compiler_v3.COMPILER_VERSION}"
        )
    if errors:
        raise CandidatePreparationError(errors)
    return publication, document


def reconstruct_bundle(
    publication: dict[str, Any], document: dict[str, Any]
) -> dict[str, Any]:
    """Invert a compiled document into a declarative, non-publishable bundle."""
    manifest = document.get("projection_manifest") or {}
    persona = document.get("persona") or {}
    nodes = []
    for compiled in document.get("nodes") or []:
        node = {
            key: deepcopy(compiled.get(key))
            for key in (
                "id", "projection_node_id", "node_type", "slug", "title",
                "summary", "tags", "status", "data",
            )
        }
        nodes.append(node)
    edges = [
        {
            key: deepcopy(compiled.get(key))
            for key in ("id", "source", "target", "relation_type", "weight", "metadata")
        }
        for compiled in document.get("edges") or []
    ]
    bundle = {
        "bundle_version": "1.0",
        "persona": {
            "id": str(persona.get("id") or ""),
            "slug": str(persona.get("slug") or ""),
        },
        "metadata": {
            "purpose": "active_publication_roundtrip_candidate",
            "source": "authenticated_active_graph_publication_export",
            "publication_allowed": False,
            "internal_wa_validator_test_allowed": False,
            "baseline_publication": {
                "publication_id": str(
                    publication.get("id") or publication.get("publication_id") or ""
                ),
                "version": int(publication.get("version")),
                "checksum": str(publication.get("checksum") or ""),
            },
            "embedding_profile": {
                "embedding_provider": manifest.get("embedding_provider"),
                "embedding_model": manifest.get("embedding_model"),
                "embedding_dimension": manifest.get("embedding_dimension"),
            },
        },
        "nodes": nodes,
        "edges": edges,
    }
    try:
        normalized = normalize_bundle(bundle)
    except GraphBundleError as exc:
        raise CandidatePreparationError(exc.errors) from exc
    rebuilt = compile_bundle(normalized)
    if rebuilt.get("checksum") != document.get("checksum"):
        raise CandidatePreparationError(
            "baseline_roundtrip_checksum_mismatch:"
            f"{rebuilt.get('checksum')}:{document.get('checksum')}"
        )
    return normalized


def _validate_overlay_cas(
    overlay: dict[str, Any], publication: dict[str, Any]
) -> None:
    baseline = overlay.get("base_publication") or {}
    expected = {
        "publication_id": str(
            publication.get("id") or publication.get("publication_id") or ""
        ),
        "version": int(publication.get("version")),
        "checksum": str(publication.get("checksum") or ""),
    }
    errors = [
        f"overlay_base_{key}_mismatch:{baseline.get(key)}:{value}"
        for key, value in expected.items()
        if baseline.get(key) != value
    ]
    if errors:
        raise CandidatePreparationError(errors)


def apply_overlay(
    bundle: dict[str, Any], overlay: dict[str, Any], publication: dict[str, Any]
) -> dict[str, Any]:
    """Apply an explicit full-record overlay; never remove incident edges implicitly."""
    if str(overlay.get("overlay_version") or "") != "1.0":
        raise CandidatePreparationError("unsupported_overlay_version")
    _validate_overlay_cas(overlay, publication)
    candidate = deepcopy(bundle)
    nodes = {str(node.get("id") or ""): node for node in candidate["nodes"]}
    edges = {str(edge.get("id") or ""): edge for edge in candidate["edges"]}

    for edge_id in overlay.get("remove_edge_ids") or []:
        if str(edge_id) not in edges:
            raise CandidatePreparationError(f"overlay_remove_edge_missing:{edge_id}")
        edges.pop(str(edge_id))
    for node_id in overlay.get("remove_node_ids") or []:
        node_id = str(node_id)
        if node_id not in nodes:
            raise CandidatePreparationError(f"overlay_remove_node_missing:{node_id}")
        incident = sorted(
            edge_id for edge_id, edge in edges.items()
            if node_id in {str(edge.get("source")), str(edge.get("target"))}
        )
        if incident:
            raise CandidatePreparationError(
                f"overlay_remove_node_has_incident_edges:{node_id}:{','.join(incident)}"
            )
        nodes.pop(node_id)
    for node in overlay.get("upsert_nodes") or []:
        if not isinstance(node, dict) or not str(node.get("id") or ""):
            raise CandidatePreparationError("overlay_node_invalid")
        nodes[str(node["id"])] = deepcopy(node)
    for edge in overlay.get("upsert_edges") or []:
        if not isinstance(edge, dict) or not str(edge.get("id") or ""):
            raise CandidatePreparationError("overlay_edge_invalid")
        edges[str(edge["id"])] = deepcopy(edge)

    metadata_patch = overlay.get("metadata") or {}
    if not isinstance(metadata_patch, dict):
        raise CandidatePreparationError("overlay_metadata_invalid")
    candidate["metadata"].update(deepcopy(metadata_patch))
    candidate["metadata"]["publication_allowed"] = False
    candidate["metadata"]["internal_wa_validator_test_allowed"] = False
    candidate["metadata"]["baseline_publication"] = deepcopy(
        bundle["metadata"]["baseline_publication"]
    )
    candidate["nodes"] = list(nodes.values())
    candidate["edges"] = list(edges.values())
    try:
        return normalize_bundle(candidate)
    except GraphBundleError as exc:
        raise CandidatePreparationError(exc.errors) from exc


def validate_canonical_assets(bundle: dict[str, Any]) -> None:
    """Reject shadow asset nodes and duplicate content identities."""
    errors: list[str] = []
    seen_hashes: dict[str, str] = {}
    seen_registry: dict[str, str] = {}
    seen_projection: dict[str, str] = {}
    for node in bundle.get("nodes") or []:
        node_id = str(node.get("id") or "")
        projection_id = str(node.get("projection_node_id") or "")
        prior_projection = seen_projection.get(projection_id)
        if projection_id and prior_projection and prior_projection != node_id:
            errors.append(
                f"duplicate_projection_node_id:{projection_id}:{prior_projection}:{node_id}"
            )
        elif projection_id:
            seen_projection[projection_id] = node_id
        if node.get("node_type") != "asset" or node.get("status") == "archived":
            continue
        data = node.get("data") or {}
        media = data.get("media") if isinstance(data.get("media"), dict) else {}
        content_hash = str(media.get("sha256") or data.get("content_sha256") or "").lower()
        registry_id = str(
            data.get("asset_registry_id")
            or data.get("registry_asset_id")
            or data.get("asset_id")
            or ""
        )
        if not SHA256_RE.fullmatch(content_hash):
            errors.append(f"asset_content_sha256_required:{node_id}")
        elif content_hash in seen_hashes:
            errors.append(
                "duplicate_asset_content_sha256:"
                f"{content_hash}:{seen_hashes[content_hash]}:{node_id}"
            )
        else:
            seen_hashes[content_hash] = node_id
        if not registry_id:
            errors.append(f"asset_registry_id_required:{node_id}")
        else:
            try:
                UUID(registry_id)
            except (TypeError, ValueError):
                errors.append(f"asset_registry_id_invalid:{node_id}:{registry_id}")
            if registry_id in seen_registry:
                errors.append(
                    "duplicate_asset_registry_id:"
                    f"{registry_id}:{seen_registry[registry_id]}:{node_id}"
                )
            else:
                seen_registry[registry_id] = node_id
        if registry_id and node_id != f"asset:{registry_id}":
            errors.append(f"asset_node_id_not_registry_backed:{node_id}:{registry_id}")
    if errors:
        raise CandidatePreparationError(errors)


def validate_media_manifest(
    manifest: dict[str, Any],
    bundle: dict[str, Any],
    publication: dict[str, Any],
) -> None:
    """Prove each evidence file maps once to a product and canonical asset."""
    baseline = manifest.get("baseline_publication") or {}
    expected = {
        "publication_id": str(
            publication.get("id") or publication.get("publication_id") or ""
        ),
        "version": int(publication.get("version")),
        "checksum": str(publication.get("checksum") or ""),
    }
    errors = [
        f"media_manifest_base_{key}_mismatch:{baseline.get(key)}:{value}"
        for key, value in expected.items()
        if baseline.get(key) != value
    ]
    if str(manifest.get("persona_slug") or "") != bundle["persona"]["slug"]:
        errors.append("media_manifest_persona_mismatch")
    nodes = {str(node.get("id") or ""): node for node in bundle["nodes"]}
    edges = bundle["edges"]
    hashes: set[str] = set()
    files: set[str] = set()
    for item in manifest.get("assets") or []:
        filename = str(item.get("file") or "")
        content_hash = str(item.get("sha256") or "").lower()
        product_id = str(item.get("product_node_id") or "")
        if item.get("mapping_status") != "validated":
            errors.append(f"media_mapping_not_validated:{filename}")
        if filename in files:
            errors.append(f"media_manifest_duplicate_file:{filename}")
        files.add(filename)
        if not SHA256_RE.fullmatch(content_hash) or content_hash in hashes:
            errors.append(f"media_manifest_duplicate_or_invalid_sha256:{content_hash}")
        hashes.add(content_hash)
        if (nodes.get(product_id) or {}).get("node_type") != "product":
            errors.append(f"media_product_missing:{product_id}")
            continue
        matches = [
            node for node in nodes.values()
            if node.get("node_type") == "asset"
            and str((((node.get("data") or {}).get("media") or {}).get("sha256")
                    or (node.get("data") or {}).get("content_sha256") or "")).lower()
            == content_hash
        ]
        if len(matches) != 1:
            errors.append(f"media_asset_match_count:{content_hash}:{len(matches)}")
            continue
        asset_id = str(matches[0]["id"])
        uses = [
            edge for edge in edges
            if edge.get("relation_type") == "uses_asset"
            and edge.get("source") == product_id
            and edge.get("target") == asset_id
        ]
        gallery = [
            edge for edge in edges
            if edge.get("relation_type") == "gallery_asset"
            and edge.get("source") == asset_id
            and (nodes.get(str(edge.get("target"))) or {}).get("node_type") == "gallery"
        ]
        if len(uses) != 1:
            errors.append(f"media_uses_asset_edge_count:{product_id}:{asset_id}:{len(uses)}")
        if len(gallery) != 1:
            errors.append(f"media_gallery_asset_edge_count:{asset_id}:{len(gallery)}")
    if errors:
        raise CandidatePreparationError(errors)


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct a GraphBundle from the exact active publication and "
            "generate a local dry-run PublicationPlan."
        )
    )
    parser.add_argument("active_export", help="Authenticated active publication export JSON")
    parser.add_argument("--expected-publication-id", required=True)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--expected-runtime-checksum", required=True)
    parser.add_argument("--overlay", help="Optional explicit GraphBundle overlay JSON")
    parser.add_argument("--media-manifest", help="Optional product-media evidence manifest")
    parser.add_argument("--candidate-output", required=True)
    parser.add_argument("--plan-output", required=True)
    args = parser.parse_args()

    try:
        payload = _json_file(args.active_export)
        publication, document = validate_active_export(
            payload,
            expected_publication_id=args.expected_publication_id,
            expected_version=args.expected_version,
            expected_runtime_checksum=args.expected_runtime_checksum,
        )
        candidate = reconstruct_bundle(publication, document)
        if args.overlay:
            candidate = apply_overlay(candidate, _json_file(args.overlay), publication)
            validate_canonical_assets(candidate)
        if args.media_manifest:
            if not args.overlay:
                raise CandidatePreparationError("media_manifest_requires_overlay")
            validate_media_manifest(
                _json_file(args.media_manifest), candidate, publication
            )
        plan = build_publication_plan(
            candidate,
            current_document=document,
            next_version=int(publication["version"]) + 1,
        )
        if plan.get("validation_errors"):
            raise CandidatePreparationError(plan["validation_errors"])
        if plan.get("publication_allowed") is not False:
            raise CandidatePreparationError("dry_run_must_not_allow_publication")
        printable_plan = dict(plan)
        printable_plan.pop("candidate_document", None)
        _write_json(args.candidate_output, candidate)
        _write_json(args.plan_output, printable_plan)
        print(json.dumps({
            "disposition": printable_plan["disposition"],
            "baseline_publication_id": str(
                publication.get("id") or publication.get("publication_id") or ""
            ),
            "baseline_version": int(publication["version"]),
            "baseline_runtime_checksum": str(document["checksum"]),
            "candidate_draft_checksum": printable_plan["draft_checksum"],
            "candidate_runtime_checksum": printable_plan["runtime_checksum"],
            "node_changes": printable_plan["node_changes"],
            "edge_changes": printable_plan["edge_changes"],
            "candidate_output": str(Path(args.candidate_output)),
            "plan_output": str(Path(args.plan_output)),
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        CandidatePreparationError,
        GraphBundleError,
    ) as exc:
        errors = getattr(exc, "errors", [f"input_error:{type(exc).__name__}:{exc}"])
        print(json.dumps({
            "disposition": "blocked",
            "publication_allowed": False,
            "validation_errors": errors,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
