#!/usr/bin/env python3
"""Validate a compiled GraphBundle plan without touching publication state."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
PERSONA_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_public_site_projection(bundle: dict) -> None:
    """Reject an unprojectable public site before any production pause."""
    nodes = {
        str(node.get("id")): node
        for node in bundle.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }
    is_public_site = any(
        node.get("node_type") == "campaign"
        and (node.get("data") or {}).get("campaign_subtype") == "public_site_page"
        for node in nodes.values()
    )
    if not is_public_site:
        return
    galleries = {
        node_id for node_id, node in nodes.items()
        if node.get("node_type") == "gallery"
    }
    _require(
        len(galleries) == 1,
        f"public site requires exactly one Gallery; found {len(galleries)}",
    )
    published = {
        str(edge.get("source"))
        for edge in bundle.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("relation_type") == "publishes_to"
        and str(edge.get("target")) in galleries
        and (edge.get("metadata") or {}).get("active", True) is not False
    }
    published_brands = {
        node_id for node_id in published
        if (nodes.get(node_id) or {}).get("node_type") == "brand"
    }
    _require(
        len(published_brands) == 1,
        f"public site requires exactly one published Brand; found {len(published_brands)}",
    )
    all_groups = {
        node_id for node_id, node in nodes.items()
        if node.get("node_type") == "product_group"
    }
    published_groups = all_groups & published
    if all_groups:
        _require(
            published_groups == all_groups,
            "public site must publish every ProductGroup; missing "
            + ",".join(sorted(all_groups - published_groups)),
        )
    published_assets = {
        node_id for node_id in published
        if (nodes.get(node_id) or {}).get("node_type") == "asset"
    }
    gallery_assets = {
        str(edge.get("source"))
        for edge in bundle.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("relation_type") == "gallery_asset"
        and str(edge.get("target")) in galleries
        and (edge.get("metadata") or {}).get("active", True) is not False
    }
    _require(
        published_assets <= gallery_assets,
        "published Assets must also use canonical gallery_asset edges; missing "
        + ",".join(sorted(published_assets - gallery_assets)),
    )
    image_products = {
        str(edge.get("source"))
        for edge in bundle.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("relation_type") == "uses_asset"
        and (nodes.get(str(edge.get("source"))) or {}).get("node_type") == "product"
        and str(edge.get("target")) in published_assets
        and (
            (edge.get("metadata") or {}).get("role") == "product_image"
            or str(((edge.get("metadata") or {}).get("page_binding") or {}).get("slot_key") or "").startswith("product_image")
        )
    }
    published_products = {
        node_id for node_id in published
        if (nodes.get(node_id) or {}).get("node_type") == "product"
    }
    _require(
        published_products == image_products,
        "public site Product grants must equal products with published images; "
        f"missing={','.join(sorted(image_products - published_products))};"
        f"without_image={','.join(sorted(published_products - image_products))}",
    )
    minimums = ((bundle.get("metadata") or {}).get("public_site_invariants") or {}).get("product_carousel_minimums") or {}
    for group_id, minimum in minimums.items():
        _require(group_id in all_groups, f"carousel invariant references unknown ProductGroup: {group_id}")
        group_products = {
            str(edge.get("target"))
            for edge in bundle.get("edges") or []
            if isinstance(edge, dict)
            and edge.get("source") == group_id
            and edge.get("relation_type") == "contains"
            and (nodes.get(str(edge.get("target"))) or {}).get("node_type") == "product"
        }
        visible = group_products & image_products
        _require(
            len(visible) >= int(minimum),
            f"ProductGroup {group_id} requires at least {minimum} product slides; found {len(visible)}",
        )


def validate(
    bundle_path: Path,
    plan_path: Path,
    *,
    persona_slug: str,
    approved_draft_checksum: str,
    approved_runtime_checksum: str,
    bundle_root: Path | None = None,
) -> dict:
    bundle_path = bundle_path.resolve()
    plan_path = plan_path.resolve()
    allowed_root = (bundle_root or ROOT / "data/graph_bundles").resolve()
    _require(allowed_root in bundle_path.parents, "bundle must be under data/graph_bundles")
    _require(PERSONA_SLUG.fullmatch(persona_slug) is not None, "invalid persona slug")
    _require(CHECKSUM.fullmatch(approved_draft_checksum) is not None, "invalid approved draft checksum")
    _require(CHECKSUM.fullmatch(approved_runtime_checksum) is not None, "invalid approved runtime checksum")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _require(isinstance(bundle, dict) and isinstance(plan, dict), "bundle and plan must be objects")
    _validate_public_site_projection(bundle)
    _require((bundle.get("persona") or {}).get("slug") == persona_slug, "persona scope mismatch")
    _require(plan.get("disposition") == "awaiting_approval", "plan is not awaiting approval")
    _require(plan.get("publication_allowed") is True, "bundle is not publication allowed")
    _require(plan.get("validation_errors") == [], "plan has validation errors")
    _require(plan.get("draft_checksum") == approved_draft_checksum, "approved draft checksum mismatch")
    _require(plan.get("runtime_checksum") == approved_runtime_checksum, "approved runtime checksum mismatch")
    return {
        "persona_slug": persona_slug,
        "draft_checksum": approved_draft_checksum,
        "runtime_checksum": approved_runtime_checksum,
        "next_version": plan.get("next_version"),
        "branches_affected": plan.get("branches_affected") or [],
        "breaking_contract_changes": plan.get("breaking_contract_changes") or [],
        "chunks_reused": plan.get("chunks_reused"),
        "chunks_to_embed": plan.get("chunks_to_embed"),
        "validation_errors": [],
        "disposition": "awaiting_approval",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--persona-slug", required=True)
    parser.add_argument("--approved-draft-checksum", required=True)
    parser.add_argument("--approved-runtime-checksum", required=True)
    args = parser.parse_args(argv[1:])
    try:
        summary = validate(
            Path(args.bundle), Path(args.plan), persona_slug=args.persona_slug,
            approved_draft_checksum=args.approved_draft_checksum,
            approved_runtime_checksum=args.approved_runtime_checksum,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid GraphBundle publication plan: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
