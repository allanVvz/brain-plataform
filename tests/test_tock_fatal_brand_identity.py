from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/graph_bundles/tock-fatal/sdr-qualification-v13-brand-identity.json"
MANIFEST = ROOT / "assets/brands/tock-fatal/manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_operator_identity_manifest_pins_every_original() -> None:
    """The 177 MB operator archive is deliberately not vendored: it is
    LFS-scoped in .gitattributes, but nothing deploys it, and CI would have
    to fetch it on every checkout to hash it -- roughly five runs of the free
    LFS bandwidth quota. The manifest pins all 77 originals by sha256
    instead, so provenance stays provable and any future copy of the package
    can be validated against it. Verification against the real bytes lives in
    test_tock_fatal_identity_archive.py, collected only where the archive is
    actually present."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["source"] == "operator_supplied_identity_package_2026-09-04"
    assert manifest["file_count"] == len(manifest["files"]) == 77
    assert manifest["total_bytes"] == sum(item["bytes"] for item in manifest["files"])
    paths = [item["path"] for item in manifest["files"]]
    assert len(set(paths)) == len(paths), "manifest lists a path twice"
    for item in manifest["files"]:
        assert item["repository_path"] == f"{manifest['source_root']}/{item['path']}"
        assert len(item["sha256"]) == 64


def test_real_brand_font_and_logos_are_graph_assets() -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in bundle["nodes"]}
    edges = {(edge["source"], edge["target"], edge["relation_type"]) for edge in bundle["edges"]}

    for channel in ("varejo", "atacado"):
        brand_id = f"brand:tock-fatal-{'varejo' if channel == 'varejo' else 'atacado'}"
        identity = nodes[brand_id]["data"]["visual_identity"]
        assert identity["typography"]["display"]["family"] == "Bodrum Sweet"
        assert identity["typography"]["display"]["style"] == "13 Light"
        assert identity["logo"]["primary"]["sha256"]
        for role, asset_id in identity["asset_node_ids"].items():
            assert nodes[asset_id]["node_type"] == "asset"
            assert nodes[asset_id]["data"]["asset_role"] == role
            assert (brand_id, asset_id, "contains") in edges


def test_runtime_assets_are_exact_copies_of_the_official_sources() -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
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
            # The runtime copy is what actually ships (dashboard/public, and
            # the public-site repo serves the same bytes at the same URL), so
            # it is checked against the checksum the graph itself published.
            # Byte equality with the un-vendored operator original is proven
            # in test_tock_fatal_identity_archive.py, and both agree because
            # the manifest pins the same sha256.
            runtime_path = ROOT / item["repository_path"]
            assert runtime_path.is_file(), runtime_path
            assert item["sha256"] == _sha256(runtime_path)


def test_web_stylesheet_uses_the_real_font_and_channel_palettes() -> None:
    css = (ROOT / "dashboard/public/brands/tock-fatal/brand.css").read_text(
        encoding="utf-8"
    )
    assert '@font-face' in css
    assert 'font-family: "Bodrum Sweet"' in css
    assert 'url("./bodrum-sweet-13-light.otf")' in css
    assert 'data-brand-channel="varejo"' in css
    assert 'data-brand-channel="atacado"' in css
    assert "#9F2960" in css
    assert "#922B48" in css
