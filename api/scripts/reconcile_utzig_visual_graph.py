"""Build the review-only Utzig visual-media reconciliation candidate.

The input is the existing approved-source draft.  This script deliberately
does not upload files, publish a GraphBundle, or contact production.
"""
from __future__ import annotations

import copy
import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data/graph_bundles/utzig-garage/site-and-appointment-v1.DRAFT.json"


def edge(edge_id, source, target, relation, *, position=0, fallback=False):
    assignment = {"active": True, "position": position, "purpose": "public_catalog"}
    if fallback:
        assignment["fallback_allowed"] = True
    slot_key = (
        f"product_image:{source.removeprefix('product:')}" if relation == "uses_asset"
        else f"product_group_cover:{source.removeprefix('group:')}" if relation == "category_has_asset"
        else "hero" if relation == "campaign_has_asset" else "asset"
    )
    return {"id": edge_id, "source": source, "target": target,
            "relation_type": relation, "weight": 1, "metadata": {
                "active": True, "primary_tree": False, "source": "utzig_visual_reconciliation_2026_09_23",
                "media_assignment": assignment,
                "page_binding": {"slot_key": slot_key, "position": position},
            }}


def main(active_export: Path | None = None) -> None:
    bundle = json.loads(PATH.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in bundle["nodes"]}

    repair_asset_id = "asset:repair-paint-representative-v1"
    repair_asset_sha = "e92dcd20548ddc32567529488ca88bac724ab1dab0628be7cd602c1feb0d56be"
    repair_registry_id = "97d1b29c-e689-5fd4-a501-bab2336b2bea"
    repair_storage_path = (
        "e7b7b2e8-859e-4185-b675-79bc0f3d846e/"
        f"{repair_asset_sha}/repair-paint-representative-v1.webp"
    )
    nodes[repair_asset_id] = {
        "id": repair_asset_id,
        "node_type": "asset",
        "slug": "repair-paint-representative-v1",
        "title": "Reparo e pintura — imagem representativa",
        "summary": "Capa editorial representativa do grupo Reparo e pintura; não é evidência de um serviço executado pela Utzig Garage.",
        "tags": ["public-site", "representative", "synthetic", "repair-paint"],
        "status": "approved",
        "projection_node_id": "0c91f50c-1b7c-59c8-9416-422d6632c7b1",
        "data": {
            "source": "openai_imagegen_operator_approved_2026_09_23",
            "validation_status": "approved",
            "asset_role": "representative_group_cover",
            "representative": True,
            "synthetic": True,
            "not_direct_evidence": True,
            "public_asset_ready": True,
            "registry_id": repair_registry_id,
            "asset_id": repair_registry_id,
            "content_sha256": repair_asset_sha,
            "local_evidence_path": "docs/public-sites/utzig-garage/media/repair-paint-representative-v1.webp",
            "web_derivative": {
                "status": "approved",
                "url": f"https://storage.vzforeal.com/storage/v1/object/public/assets-derived/{repair_storage_path}",
                "content_sha256": repair_asset_sha,
                "width": 1600,
                "height": 900,
                "mime_type": "image/webp",
                "storage_bucket": "assets-derived",
                "storage_path": repair_storage_path,
                "profile": "webp_max_1600_q82_v1",
            },
            "media": {
                "kind": "image",
                "registry_id": repair_registry_id,
                "sha256": repair_asset_sha,
                "width": 1600,
                "height": 900,
                "mime": "image/webp",
                "mime_type": "image/webp",
                "bucket": "assets-derived",
                "path": repair_storage_path,
                "filename": "repair-paint-representative-v1.webp",
            },
        },
    }

    # Five public navigation groups.  The former marketing audiences stay
    # untouched; these are catalog owners, not audience claims.
    groups = {
        "group:preservation": ("Avaliação e orientação", "assessment-guidance", "asset:process", 0),
        "group:cleaning": ("Limpeza e higienização", "cleaning-hygiene", "asset:extractor", 1),
        "group:revitalization": ("Correção e acabamento", "correction-finish", "asset:headlight-before", 2),
        "group:repair-paint": ("Reparo e pintura", "repair-paint", repair_asset_id, 3),
        "group:enhancement": ("Proteção e conservação", "protection-conservation", "asset:glass-before", 4),
    }
    template = copy.deepcopy(nodes["group:preservation"])
    for group_id, (title, slug, _, position) in groups.items():
        node = nodes.get(group_id) or copy.deepcopy(template)
        node.update({"id": group_id, "node_type": "product_group", "title": title, "slug": slug,
                     "summary": "Grupo de serviços da Utzig Garage; a capa é uma referência visual do grupo."})
        node["data"]["position"] = position
        node["data"]["media_role"] = "representative_group_cover"
        nodes[group_id] = node

    # This is a source-backed service name from the approved visual inventory;
    # its evidence is the glass cover, never a price, duration or promise.
    source_product = copy.deepcopy(nodes["product:glass-polish"])
    source_copy = copy.deepcopy(nodes["copy:glass-polish"])
    source_faq = copy.deepcopy(nodes["faq:service:glass-polish"])
    source_product.update({"id": "product:windshield-crystallization", "slug": "windshield-crystallization",
                           "title": "Cristalização de para-brisa",
                           "summary": "Serviço de cristalização de para-brisa oferecido pela Utzig Garage."})
    source_product["data"]["aliases"] = ["Cristalização de para-brisa"]
    source_product["data"]["public_site"]["cta"]["message_template"] = "Olá! Quero pedir uma avaliação para cristalização de para-brisa."
    for field in source_product["data"]["qualification"]["fields"]:
        if field.get("owner_node_id") == "product:glass-polish":
            field["owner_node_id"] = "product:windshield-crystallization"
    source_copy.update({"id": "copy:windshield-crystallization", "slug": "windshield-crystallization",
                        "title": "Cristalização de para-brisa"})
    source_copy["data"].pop("conversation_variants", None)
    source_faq.update({"id": "faq:service:windshield-crystallization", "slug": "windshield-crystallization",
                       "title": "Cristalização de para-brisa"})
    source_faq["data"]["question"] = "A Utzig Garage oferece cristalização de para-brisa?"
    source_faq["data"]["answer"] = "A disponibilidade e a avaliação da cristalização de para-brisa são confirmadas pela equipe da Utzig Garage."
    for claim in source_faq["data"].get("claims") or []:
        claim["owner_node_id"] = source_faq["id"]
        claim["evidence_node_ids"] = [source_faq["id"]]
    nodes[source_product["id"]] = source_product
    nodes[source_copy["id"]] = source_copy
    nodes[source_faq["id"]] = source_faq

    # The Gallery is the curation gate for opt-in public fallback resolution.
    nodes["gallery:utzig"]["data"].setdefault("capabilities", {})["global_context"] = True
    persona = nodes["persona:utzig-garage"]
    persona["data"]["public_site"]["catalog_media_fallback"] = {
        "enabled": True, "campaign_id": "campaign:automotive-detailing",
        "precedence": ["product", "group", "campaign"],
        "direct_assets_compatibility": True,
    }

    # Remove the old product-image guesses and the old three-group tree.  The
    # canonical Asset -> Gallery and public publication grants are retained.
    bundle["edges"] = [item for item in bundle["edges"] if not (
        item.get("id", "").startswith("edge:service-image:")
        or item.get("id", "").startswith(("edge:primary:repair-paint-representative", "edge:repair-paint-representative-gallery", "edge:public:repair-paint-representative"))
        or item.get("id", "").startswith(("edge:brand-cleaning", "edge:brand-repair-paint", "edge:primary:windshield-", "edge:windshield-crystallization-", "edge:copy-faq-windshield-", "edge:faq-embed-windshield-"))
        or item.get("metadata", {}).get("source") == "utzig_visual_reconciliation_2026_09_23"
        or (item.get("source", "").startswith("group:") and item.get("relation_type") == "contains")
        or (item.get("source", "").startswith("group:") and item.get("relation_type") == "publishes_to")
    )]
    bundle["edges"].extend([
        {"id": "edge:primary:repair-paint-representative-v1", "source": "group:repair-paint",
         "target": repair_asset_id, "relation_type": "contains", "weight": 1,
         "metadata": {"active": True, "primary_tree": True,
                      "source": "utzig_visual_reconciliation_2026_09_23"}},
        {"id": "edge:repair-paint-representative-gallery", "source": repair_asset_id,
         "target": "gallery:utzig", "relation_type": "gallery_asset", "weight": 1,
         "metadata": {"active": True, "primary_tree": False,
                      "source": "utzig_visual_reconciliation_2026_09_23"}},
        {"id": "edge:public:repair-paint-representative-v1", "source": repair_asset_id,
         "target": "gallery:utzig", "relation_type": "publishes_to", "weight": 1,
         "metadata": {"active": True, "primary_tree": False,
                      "source": "utzig_public_site_approval_2026_09_23"}},
    ])

    membership = {
        "group:preservation": ["product:evaluation"],
        "group:cleaning": ["product:detailed-wash", "product:engine-bay-wash", "product:interior-cleaning"],
        "group:revitalization": ["product:commercial-polish", "product:technical-polish", "product:glass-polish", "product:headlight-restoration"],
        "group:repair-paint": ["product:bodywork", "product:painting"],
        "group:enhancement": ["product:ppf", "product:vitrification", "product:windshield-crystallization"],
    }
    for group_id, products in membership.items():
        if group_id in {"group:cleaning", "group:repair-paint"}:
            bundle["edges"].append({"id": f"edge:brand-{group_id.removeprefix('group:')}",
                                    "source": "brand:utzig-garage", "target": group_id,
                                    "relation_type": "contains", "weight": 1, "metadata": {"primary_tree": True}})
        for index, product_id in enumerate(products):
            bundle["edges"].append({"id": f"edge:{group_id.removeprefix('group:')}-{product_id.removeprefix('product:')}",
                                    "source": group_id, "target": product_id, "relation_type": "contains",
                                    "weight": 1, "metadata": {"primary_tree": True, "position": index}})
        _, _, asset_id, position = groups[group_id]
        bundle["edges"].append(edge(f"edge:group-cover:{group_id.removeprefix('group:')}", group_id, asset_id,
                                    "category_has_asset", position=position, fallback=True))
        bundle["edges"].append({"id": f"edge:public-group:{group_id.removeprefix('group:')}", "source": group_id,
                                "target": "gallery:utzig", "relation_type": "publishes_to", "weight": 1,
                                "metadata": {"active": True, "primary_tree": False,
                                             "source": "utzig_visual_reconciliation_2026_09_23"}})

    # Evidence may be direct only where the approved visual actually depicts
    # that service.  Everything else resolves to a marked representative cover.
    direct = {
        "product:engine-bay-wash": "asset:engine-wash",
        "product:interior-cleaning": "asset:interior",
        "product:technical-polish": "asset:work-polish",
        "product:glass-polish": "asset:glass-before-after",
        "product:headlight-restoration": "asset:headlight-ready",
        "product:windshield-crystallization": "asset:glass-before",
    }
    for product_id, asset_id in direct.items():
        bundle["edges"].append(edge(f"edge:direct-evidence:{product_id.removeprefix('product:')}", product_id, asset_id,
                                    "uses_asset", position=0))
    bundle["edges"].extend([
        {"id": "edge:primary:windshield-crystallization-copy", "source": "product:windshield-crystallization",
         "target": "copy:windshield-crystallization", "relation_type": "contains", "weight": 1, "metadata": {"primary_tree": True}},
        {"id": "edge:primary:windshield-crystallization-faq", "source": "copy:windshield-crystallization",
         "target": "faq:service:windshield-crystallization", "relation_type": "contains", "weight": 1, "metadata": {"primary_tree": True}},
        {"id": "edge:windshield-crystallization-copy", "source": "product:windshield-crystallization",
         "target": "copy:windshield-crystallization", "relation_type": "supports_copy", "weight": 1, "metadata": {}},
        {"id": "edge:copy-faq-windshield-crystallization", "source": "copy:windshield-crystallization",
         "target": "faq:service:windshield-crystallization", "relation_type": "answers_question", "weight": 1, "metadata": {}},
        {"id": "edge:faq-embed-windshield-crystallization", "source": "faq:service:windshield-crystallization",
         "target": "embedded:utzig", "relation_type": "publishes_to", "weight": 1, "metadata": {"primary_tree": False}},
    ])
    bundle["edges"].append(edge("edge:campaign-fallback:automotive-detailing", "campaign:automotive-detailing",
                                "asset:process", "campaign_has_asset", position=0, fallback=True))

    # Public grants are compatible with the existing projector; Gallery remains
    # the canonical Asset endpoint and is not replaced by these assignments.
    bundle["edges"].append({"id": "edge:public-product:windshield-crystallization",
                            "source": "product:windshield-crystallization", "target": "gallery:utzig",
                            "relation_type": "publishes_to", "weight": 1,
                            "metadata": {"active": True, "primary_tree": False,
                                         "source": "utzig_visual_reconciliation_2026_09_23"}})

    page = nodes["campaign:automotive-detailing"]["data"]["page"]
    catalog = next(block for block in page["blocks"] if block["id"] == "lp-services")
    catalog["node_ids"] = list(groups) + [item for values in membership.values() for item in values]
    bundle["metadata"]["purpose"] = "utzig_visual_media_reconciliation_candidate"
    bundle["metadata"]["visual_media_reconciliation"] = {
        "status": "operator_review_required", "source": "approved_utzig_drive_folder",
        "pending_validation": ["EDIÇÃO assets are excluded from public media and RAG"],
        "direct_evidence_services": sorted(direct),
        "representative_only_services": ["product:ppf", "product:vitrification", "product:bodywork", "product:painting", "product:commercial-polish", "product:detailed-wash", "product:evaluation"],
    }
    if active_export:
        active = json.loads(active_export.read_text(encoding="utf-8"))
        active_nodes = active.get("nodes") or list((active.get("node_by_id") or {}).values())
        active_by_id = {str(node.get("id")): node for node in active_nodes if node.get("id")}
        # Preserve active FAQ coverage.  The visual reconciliation must not
        # silently become a content deletion or alter the RAG contract.
        missing_faq_ids = {
            node_id for node_id, node in active_by_id.items()
            if node.get("node_type") == "faq" and node_id not in nodes
        }
        for node_id in sorted(missing_faq_ids):
            nodes[node_id] = copy.deepcopy(active_by_id[node_id])
        known = set(nodes)
        existing_edge_ids = {str(item.get("id")) for item in bundle["edges"]}
        for item in active.get("edges") or []:
            if (str(item.get("target")) in missing_faq_ids
                    or str(item.get("source")) in missing_faq_ids) and item.get("source") in known and item.get("target") in known:
                if str(item.get("id")) not in existing_edge_ids:
                    bundle["edges"].append(copy.deepcopy(item))
                    existing_edge_ids.add(str(item.get("id")))
        # GraphBundle replacement is append-safe in the authoring tables. Keep
        # every obsolete logical relation in the approved metadata so the
        # publication workflow can soft-disable it before staging. Tombstones
        # stay outside `edges`: older active publishers can compile the same
        # candidate while the workflow still has an exact reviewed removal set.
        desired_logical_edges = {
            (str(item.get("source")), str(item.get("target")), str(item.get("relation_type")))
            for item in bundle["edges"]
        }
        soft_disabled_edges = []
        for item in active.get("edges") or []:
            logical_edge = (
                str(item.get("source")),
                str(item.get("target")),
                str(item.get("relation_type")),
            )
            if (
                logical_edge in desired_logical_edges
                or item.get("source") not in known
                or item.get("target") not in known
                or str(item.get("id")) in existing_edge_ids
            ):
                continue
            soft_disabled_edges.append({
                "id": str(item.get("id")),
                "source": str(item.get("source")),
                "target": str(item.get("target")),
                "relation_type": str(item.get("relation_type")),
                "removal_reason": "utzig_visual_media_reconciliation_2026_09_23",
            })
        bundle["metadata"]["visual_media_reconciliation"]["preserved_active_faq_count"] = len(missing_faq_ids)
        bundle["metadata"]["visual_media_reconciliation"]["soft_disabled_edges"] = soft_disabled_edges
        bundle["metadata"]["visual_media_reconciliation"]["soft_disabled_edge_count"] = len(soft_disabled_edges)
    bundle["nodes"] = list(nodes.values())
    PATH.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-export", type=Path)
    args = parser.parse_args()
    main(args.active_export)
