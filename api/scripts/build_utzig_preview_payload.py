"""Render a static public-site preview from the active menu and GraphBundle draft.

This is a read-only local transformation. It never publishes the candidate.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

CONTROL_API = Path(__file__).resolve().parents[2] / "apps" / "control-plane" / "api"
sys.path.insert(0, str(CONTROL_API))
from services.graph_bundle import compile_bundle, normalize_bundle  # noqa: E402


def build_payload(active_menu: dict, candidate_bundle: dict) -> dict:
    baseline = candidate_bundle["metadata"]["baseline_publication"]
    if (active_menu["publication_id"] != baseline["publication_id"]
            or active_menu["graph_checksum"] != baseline["checksum"]
            or active_menu["graph_version"] != baseline["version"]):
        raise ValueError("active_menu_and_candidate_baseline_mismatch")
    document = compile_bundle(normalize_bundle(candidate_bundle))
    if document["persona"]["slug"] != active_menu["persona"]["slug"]:
        raise ValueError("candidate_persona_mismatch")
    nodes = {node["id"]: node for node in document["nodes"]}
    result = deepcopy(active_menu)
    result["publication_id"] = f"preview:{document['checksum']}"
    result["graph_version"] = baseline["version"] + 1
    result["graph_checksum"] = document["checksum"]
    home = next(page for page in result["site"]["pages"] if page["kind"] == "linktree")
    home["actions"] = nodes["campaign:home"]["data"]["page"]["actions"]
    prior_home_blocks = {block["id"]: block for block in home["blocks"]}
    home["blocks"] = [
        {**prior_home_blocks.get(authored["id"], {}), **authored,
         "assets": prior_home_blocks.get(authored["id"], {}).get("assets", []),
         "items": prior_home_blocks.get(authored["id"], {}).get("items", []),
         "campaigns": prior_home_blocks.get(authored["id"], {}).get("campaigns", [])}
        for authored in nodes["campaign:home"]["data"]["page"]["blocks"]
    ]
    landing = next(page for page in result["site"]["pages"] if page["kind"] == "landing_page")
    authored_page = nodes["campaign:automotive-detailing"]["data"]["page"]
    landing["title"] = authored_page["title"]
    landing["description"] = authored_page["description"]
    prior_blocks = {block["id"]: block for block in landing["blocks"]}
    blocks = []
    for authored in authored_page["blocks"]:
        block = {**prior_blocks.get(authored["id"], {}), **authored}
        block.setdefault("assets", [])
        block.setdefault("asset_node_ids", [])
        block.setdefault("items", [])
        block.setdefault("campaigns", [])
        if block["kind"] == "campaign_showcase":
            campaigns = []
            for campaign_id in block["node_ids"]:
                node = nodes[campaign_id]
                matches = sorted(
                    (edge for edge in document["edges"]
                     if edge["target"] == campaign_id and edge["relation_type"] == "part_of_campaign"),
                    key=lambda edge: int((edge.get("metadata") or {}).get("position") or 0),
                )
                campaigns.append({
                    "node_id": campaign_id, "title": node["title"],
                    "summary": node.get("summary"),
                    "position": int(node["data"]["public_site"]["position"]),
                    "product_node_ids": [edge["source"] for edge in matches],
                })
            block["campaigns"] = campaigns
        blocks.append(block)
    landing["blocks"] = blocks
    result["site"]["audiences"] = [
        {
            "node_id": node_id,
            "label": nodes[node_id]["data"]["audience"]["label"],
            "summary": nodes[node_id]["summary"],
            "message_template": nodes[node_id]["data"]["audience"]["message_template"],
            "position": nodes[node_id]["data"]["audience"]["position"],
            "related_campaign_node_ids": [edge["target"] for edge in document["edges"]
                                          if edge["source"] == node_id and edge["relation_type"] == "same_topic_as"],
        }
        for ref in nodes["persona:utzig-garage"]["data"]["public_site"]["audiences"]
        for node_id in [ref["node_id"]]
    ]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("active_menu", type=Path)
    parser.add_argument("candidate_bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_payload(json.loads(args.active_menu.read_text(encoding="utf-8")),
                           json.loads(args.candidate_bundle.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"candidate_checksum": result["graph_checksum"],
                      "catalog_groups": len(result["persona"]["collections"][0]["categories"]),
                      "catalog_products": sum(len(group["products"]) for group in result["persona"]["collections"][0]["categories"]),
                      "editorial_campaigns": len(next(block for block in result["site"]["pages"][1]["blocks"]
                                                       if block["kind"] == "campaign_showcase")["campaigns"])}))


if __name__ == "__main__":
    main()
