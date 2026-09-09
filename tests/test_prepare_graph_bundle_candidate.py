from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from uuid import UUID, uuid5

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "api" / "scripts" / "prepare_graph_bundle_candidate.py"
SPEC = importlib.util.spec_from_file_location("prepare_graph_bundle_candidate", SCRIPT_PATH)
assert SPEC and SPEC.loader
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def _bundle() -> dict:
    return json.loads(
        (
            REPO_ROOT
            / "data"
            / "graph_bundles"
            / "tock-fatal"
            / "sdr-qualification-v1.json"
        ).read_text(encoding="utf-8")
    )


def _active_export() -> tuple[dict, dict, dict]:
    document = prepare.compile_bundle(_bundle())
    publication = {
        "id": "publication-active",
        "persona_id": document["persona"]["id"],
        "version": 7,
        "checksum": document["checksum"],
        "status": "active",
    }
    return {"publication": publication, "document_json": document}, publication, document


def test_active_export_roundtrip_is_checksum_exact_and_has_zero_diff():
    payload, publication, document = _active_export()
    actual_publication, actual_document = prepare.validate_active_export(
        payload,
        expected_publication_id="publication-active",
        expected_version=7,
        expected_runtime_checksum=document["checksum"],
    )
    candidate = prepare.reconstruct_bundle(actual_publication, actual_document)
    plan = prepare.build_publication_plan(
        candidate, current_document=document, next_version=8
    )

    assert prepare.compile_bundle(candidate)["checksum"] == document["checksum"]
    assert plan["disposition"] == "dry_run_complete"
    assert plan["publication_allowed"] is False
    assert plan["node_changes"] == {"added": [], "changed": [], "removed": []}
    assert plan["edge_changes"] == {"added": [], "changed": [], "removed": []}
    assert candidate["metadata"]["baseline_publication"] == {
        "publication_id": publication["id"],
        "version": publication["version"],
        "checksum": publication["checksum"],
    }


@pytest.mark.parametrize(
    ("field", "expected", "error"),
    [
        ("id", "another-publication", "baseline_publication_id_mismatch"),
        ("version", 8, "baseline_publication_version_mismatch"),
        ("checksum", "sha256:" + "0" * 64, "baseline_publication_checksum_mismatch"),
    ],
)
def test_active_export_rejects_stale_cas(field: str, expected, error: str):
    payload, publication, document = _active_export()
    values = {
        "id": publication["id"],
        "version": publication["version"],
        "checksum": publication["checksum"],
    }
    values[field] = expected

    with pytest.raises(prepare.CandidatePreparationError, match=error):
        prepare.validate_active_export(
            payload,
            expected_publication_id=values["id"],
            expected_version=values["version"],
            expected_runtime_checksum=values["checksum"],
        )


def test_overlay_has_its_own_baseline_cas_and_never_enables_publication():
    _payload, publication, document = _active_export()
    candidate = prepare.reconstruct_bundle(publication, document)
    overlay = {
        "overlay_version": "1.0",
        "base_publication": {
            "publication_id": publication["id"],
            "version": publication["version"],
            "checksum": publication["checksum"],
        },
        "metadata": {"publication_allowed": True, "purpose": "test"},
        "upsert_nodes": [],
        "upsert_edges": [],
        "remove_node_ids": [],
        "remove_edge_ids": [],
    }

    overlaid = prepare.apply_overlay(candidate, overlay, publication)
    assert overlaid["metadata"]["publication_allowed"] is False

    overlay["base_publication"]["version"] = 6
    with pytest.raises(
        prepare.CandidatePreparationError, match="overlay_base_version_mismatch"
    ):
        prepare.apply_overlay(candidate, overlay, publication)


def test_overlay_refuses_implicit_deletion_of_incident_edges():
    _payload, publication, document = _active_export()
    candidate = prepare.reconstruct_bundle(publication, document)
    node_id = candidate["edges"][0]["source"]
    overlay = {
        "overlay_version": "1.0",
        "base_publication": {
            "publication_id": publication["id"],
            "version": publication["version"],
            "checksum": publication["checksum"],
        },
        "remove_node_ids": [node_id],
    }

    with pytest.raises(
        prepare.CandidatePreparationError,
        match="overlay_remove_node_has_incident_edges",
    ):
        prepare.apply_overlay(candidate, overlay, publication)


def _media_candidate() -> tuple[dict, dict, dict]:
    payload, publication, document = _active_export()
    del payload
    candidate = prepare.reconstruct_bundle(publication, document)
    audience = next(
        node["id"] for node in candidate["nodes"] if node["node_type"] == "audience"
    )
    gallery = next(
        node["id"] for node in candidate["nodes"] if node["node_type"] == "gallery"
    )
    namespace = UUID(candidate["persona"]["id"])
    product_id = "product:test-product"
    registry_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    asset_id = f"asset:{registry_id}"
    content_hash = "1" * 64
    candidate["nodes"].extend([
        {
            "id": product_id,
            "projection_node_id": str(uuid5(namespace, product_id)),
            "node_type": "product",
            "slug": "test-product",
            "title": "Test product",
            "summary": "Validated test product.",
            "tags": [],
            "status": "validated",
            "data": {"source": "operator_test"},
        },
        {
            "id": asset_id,
            "projection_node_id": registry_id,
            "node_type": "asset",
            "slug": "test-product-image",
            "title": "Test product image",
            "summary": "Approved image for the test product.",
            "tags": ["product-image"],
            "status": "validated",
            "data": {
                "source": "operator_test",
                "asset_registry_id": registry_id,
                "product_node_id": product_id,
                "media": {"kind": "image", "mime": "image/jpeg", "sha256": content_hash},
            },
        },
    ])
    candidate["edges"].extend([
        {
            "id": "edge:test-product-parent",
            "source": audience,
            "target": product_id,
            "relation_type": "contains",
            "weight": 1.0,
            "metadata": {},
        },
        {
            "id": "edge:test-product-image",
            "source": product_id,
            "target": asset_id,
            "relation_type": "uses_asset",
            "weight": 1.0,
            "metadata": {"page_binding": {"slot_key": "product_image:test-product"}},
        },
        {
            "id": "edge:test-product-image-parent",
            "source": product_id,
            "target": asset_id,
            "relation_type": "contains",
            "weight": 1.0,
            "metadata": {},
        },
        {
            "id": "edge:test-gallery-image",
            "source": asset_id,
            "target": gallery,
            "relation_type": "gallery_asset",
            "weight": 1.0,
            "metadata": {},
        },
    ])
    candidate = prepare.normalize_bundle(candidate)
    manifest = {
        "persona_slug": "tock-fatal",
        "baseline_publication": {
            "publication_id": publication["id"],
            "version": publication["version"],
            "checksum": publication["checksum"],
        },
        "assets": [{
            "file": "test.jpeg",
            "sha256": content_hash,
            "product_node_id": product_id,
            "mapping_status": "validated",
        }],
    }
    return candidate, manifest, publication


def test_media_manifest_requires_one_registry_backed_asset_and_both_graph_edges():
    candidate, manifest, publication = _media_candidate()

    prepare.validate_canonical_assets(candidate)
    prepare.validate_media_manifest(manifest, candidate, publication)

    duplicate = deepcopy(next(
        node for node in candidate["nodes"] if node["node_type"] == "asset"
    ))
    duplicate["id"] = "asset:bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    duplicate["projection_node_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    duplicate["data"]["asset_registry_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    candidate["nodes"].append(duplicate)

    with pytest.raises(
        prepare.CandidatePreparationError, match="duplicate_asset_content_sha256"
    ):
        prepare.validate_canonical_assets(candidate)


def test_media_manifest_blocks_unvalidated_mapping():
    candidate, manifest, publication = _media_candidate()
    manifest["assets"][0]["mapping_status"] = "pending_validation"

    with pytest.raises(
        prepare.CandidatePreparationError, match="media_mapping_not_validated"
    ):
        prepare.validate_media_manifest(manifest, candidate, publication)


def test_cli_writes_only_local_candidate_and_dry_run_plan(monkeypatch):
    payload, publication, document = _active_export()
    written: dict[str, dict] = {}
    monkeypatch.setattr(prepare, "_json_file", lambda _path: payload)
    monkeypatch.setattr(
        prepare, "_write_json", lambda path, value: written.__setitem__(str(path), value)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "active.json",
            "--expected-publication-id",
            publication["id"],
            "--expected-version",
            str(publication["version"]),
            "--expected-runtime-checksum",
            document["checksum"],
            "--candidate-output",
            "candidate.json",
            "--plan-output",
            "candidate.PLAN.json",
        ],
    )

    assert prepare.main() == 0
    candidate = written["candidate.json"]
    plan = written["candidate.PLAN.json"]
    assert prepare.compile_bundle(candidate)["checksum"] == document["checksum"]
    assert plan["disposition"] == "dry_run_complete"
    assert plan["publication_allowed"] is False
    assert "candidate_document" not in plan
