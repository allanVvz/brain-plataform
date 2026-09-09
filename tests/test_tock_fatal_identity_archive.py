"""Verification against the real bytes of the operator identity archive.

The archive itself is not vendored (177 MB, 77 files -- see
test_tock_fatal_brand_identity.test_operator_identity_manifest_pins_every_original
for why). These tests are collected only where it is actually present, which
tests/conftest.py decides, so the default suite stays hermetic and reports no
conditional skips.

To run them, place the operator package at the manifest's `source_root`
(assets/brands/tock-fatal/source) -- .gitattributes already routes that path
to LFS if it is ever vendored.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v13-brand-identity.json"
MANIFEST = ROOT / "assets/brands/tock-fatal/manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_archive_matches_the_manifest_exactly() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_root = ROOT / manifest["source_root"]
    actual = sorted(path for path in source_root.rglob("*") if path.is_file())

    assert manifest["file_count"] == len(actual) == 77
    assert manifest["total_bytes"] == sum(path.stat().st_size for path in actual)
    assert {item["path"] for item in manifest["files"]} == {
        path.relative_to(source_root).as_posix() for path in actual
    }
    for item in manifest["files"]:
        path = ROOT / item["repository_path"]
        assert path.is_file()
        assert item["sha256"] == _sha256(path)


def test_runtime_assets_are_exact_copies_of_the_official_sources() -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    checked = 0
    for node in bundle["nodes"]:
        if node.get("node_type") != "brand" or "tock-fatal" not in str(node.get("id")):
            continue
        identity = (node.get("data") or {}).get("visual_identity") or {}
        if not identity:
            continue
        media = [
            identity["logo"]["primary"],
            identity["logo"]["round"],
            identity["logo"]["reverse"],
            identity["typography"]["display"],
        ]
        for item in media:
            runtime_path = ROOT / item["repository_path"]
            source_path = ROOT / item["source_repository_path"]
            assert runtime_path.read_bytes() == source_path.read_bytes()
            assert item["sha256"] == _sha256(runtime_path)
            checked += 1
    assert checked, "no brand media was verified"
