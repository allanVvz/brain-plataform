"""Reviewable media edits; activation stays with GraphBundle publication."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from brain_contracts.catalog_media import CATALOG_TYPES, ASSET_RELATIONS, active
from services import graph_bundle
from services import supabase_client


def uploaded_asset_plan(asset, parent, *, actor_id):
    publication = supabase_client.get_active_graph_publication(str(asset["persona_id"]))
    if not publication:
        raise ValueError("catalog_media_active_publication_required")
    document = publication["document_json"]
    bundle = {"bundle_version": "1.0", "persona": document["persona"],
              "nodes": deepcopy(document["nodes"]), "edges": deepcopy(document["edges"]),
              "metadata": {"publication_allowed": True}}
    owner = next((n for n in bundle["nodes"] if n["slug"] == parent["slug"]
                  and (n["node_type"] == parent["node_type"] or
                       {n["node_type"], parent["node_type"]} <= {"product_group", "category"})), None)
    if not owner:
        raise ValueError("catalog_media_parent_not_published")
    data = asset.get("metadata") or {}
    node_id = f"asset:{asset['id']}"
    node = next((n for n in bundle["nodes"] if (n.get("data") or {}).get("asset_id") == asset["id"]), None)
    if node is None:
        node = {"id": node_id, "slug": f"asset-{asset['id']}", "node_type": "asset",
                "title": asset.get("name") or data.get("original_filename") or node_id,
                "summary": "Operator-uploaded catalog image", "status": "validated", "tags": [],
                "data": {"source": "operator_upload", "status": "validated", "asset_id": asset["id"],
                         "approved_by": actor_id, "asset_type": asset.get("type"),
                         "asset_function": data.get("asset_function"),
                         "media": {"bucket": asset.get("storage_bucket"), "path": asset.get("storage_path"),
                                   "mime": asset.get("mime_type"), "sha256": data.get("sha256")}}}
        bundle["nodes"].append(node)
        bundle["edges"].append({"id": f"edge:catalog-parent:{asset['id']}", "source": owner["id"],
                                "target": node["id"], "relation_type": "contains", "metadata": {"primary_tree": True}})
    assigned_at = asset.get("created_at") or data.get("assigned_at")
    if not assigned_at:
        raise ValueError("catalog_media_assignment_time_required")
    candidate = edit_bundle(bundle, [{"operation_id": f"upload:{asset['id']}:{owner['id']}",
        "owner_node_id": owner["id"], "asset_node_id": node["id"], "action": "assign",
        "assigned_at": assigned_at}], actor_id=actor_id)
    return {"bundle": candidate, "plan": graph_bundle.build_publication_plan(candidate,
            current_document=document, next_version=int(publication["version"]) + 1),
            "activation_pending": True, "base_publication": {k: publication[k] for k in ("id", "version", "checksum")}}


def edit_bundle(bundle, operations, *, actor_id):
    result = deepcopy(bundle)
    nodes = {n["id"]: n for n in result["nodes"]}
    for operation in operations:
        owner = nodes.get(operation["owner_node_id"])
        asset = nodes.get(operation["asset_node_id"])
        if not owner or owner["node_type"] not in CATALOG_TYPES or not asset or asset["node_type"] != "asset":
            raise ValueError("catalog_media_target_invalid")
        persona_id = str(result["persona"]["id"])
        if any(str(n.get("persona_id") or persona_id) != persona_id for n in (owner, asset)):
            raise ValueError("catalog_media_persona_mismatch")
        data = asset.get("data") or {}
        if data.get("lead_ref") or data.get("conversation_id") or data.get("upload_context") == "whatsapp_inbound":
            raise ValueError("catalog_media_requires_explicit_promotion")
        relationships = [e for e in result["edges"] if e["source"] == owner["id"]
                         and e["target"] == asset["id"] and e["relation_type"] in ASSET_RELATIONS]
        edge = next((e for e in relationships if e["relation_type"] == "uses_asset"), None)
        edge = edge or next(iter(relationships), None)
        if edge is None:
            if operation["action"] != "assign":
                raise ValueError("catalog_media_assignment_missing")
            edge = {"id": str(uuid5(NAMESPACE_URL, f"{persona_id}:{owner['id']}:{asset['id']}:uses_asset")),
                    "source": owner["id"], "target": asset["id"], "relation_type": "uses_asset",
                    "weight": 1, "metadata": {}}
            result["edges"].append(edge)
            relationships.append(edge)
        metadata = edge.setdefault("metadata", {})
        assignment = metadata.setdefault("media_assignment", {})
        history = assignment.setdefault("operations", [])
        if operation["operation_id"] in history:
            continue
        action = operation["action"]
        if action == "assign":
            # Reassigning an existing active relationship is an idempotent no-op.
            if assignment.get("assigned_at") is None or assignment.get("active") is False:
                assignment.update({"assigned_at": operation["assigned_at"], "assigned_by": actor_id,
                                   "active": True, "destination_node_id": owner["id"],
                                   "function": "product_image" if owner["node_type"] == "product" else "category_cover"})
            metadata["active"] = True
        elif action == "unlink":
            # Keep structural contains edges, nodes, files and historical grants.
            for relation in relationships:
                relation.setdefault("metadata", {}).setdefault("media_assignment", {})["active"] = False
        elif action in {"pin", "unpin"}:
            if assignment.get("active") is False or not active(edge):
                raise ValueError("catalog_media_assignment_inactive")
            if action == "pin":
                for other in result["edges"]:
                    if other["source"] == owner["id"]:
                        other.setdefault("metadata", {}).setdefault("media_assignment", {})["pinned"] = False
            assignment["pinned"] = action == "pin"
        else:
            raise ValueError("catalog_media_action_invalid")
        history.append(operation["operation_id"])
        assignment.update({"updated_by": actor_id, "updated_at": operation["assigned_at"]})
    return result


def plan(bundle, operations, *, actor_id):
    candidate = edit_bundle(bundle, operations, actor_id=actor_id)
    return {"bundle": candidate, "plan": graph_bundle.build_publication_plan(candidate),
            "activation_pending": True}
