"""Deterministic media projection over an already authorized graph snapshot.

No I/O or cross-service imports. Callers supply publication branch membership
and an availability predicate backed by their storage boundary.
"""
from datetime import datetime, timezone
from urllib.parse import urlsplit

GROUP_TYPES = {"product_group", "category"}
CATALOG_TYPES = GROUP_TYPES | {"product"}
ASSET_RELATIONS = {"contains", "uses_asset", "product_image", "product_has_asset", "category_has_asset"}


def active(row):
    metadata = row.get("metadata") or {}
    return (metadata.get("active") is not False
            and metadata.get("status") not in {"deleted", "inactive", "archived"}
            and row.get("status") not in {"deleted", "inactive", "archived"}
            and (row.get("lifecycle") or {}).get("status") not in {"deleted", "inactive", "archived"})


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def _media(node):
    data = node.get("data") or node.get("metadata") or {}
    media = data.get("media") or {}
    mime = str(media.get("mime") or data.get("mime_type") or "")
    kind = str(data.get("asset_type") or media.get("type") or "")
    function = str(data.get("asset_function") or "")
    if (not active(node) or data.get("available") is False or media.get("available") is False
            or data.get("source") in {"whatsapp", "whatsapp_inbound", "media_ingest"}
            or data.get("upload_context") in {"conversation", "whatsapp_inbound"}
            or data.get("conversation_id") or data.get("lead_ref")
            or function in {"brand_logo", "brand_font", "font", "logo"}
            or (mime and not mime.startswith("image/"))
            or (kind and kind != "image" and not kind.startswith("image/"))):
        return None
    url = media.get("url") or data.get("public_url")
    if url:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            url = None
    bucket = media.get("bucket") or data.get("storage_bucket")
    path = media.get("path") or data.get("storage_path")
    if not url and not (bucket and path):
        return None
    return {"node_id": node["id"], "asset_node_id": node["id"],
            "alt": node.get("title") or node.get("label") or "",
            "bucket": bucket, "path": path, "url": url, "mime": mime or None}


def resolve_catalog_media(nodes, edges, *, persona_id, scoped_ids, owner_id,
                          publication=None, available=None):
    """Pin > latest direct assignment > latest eligible catalog descendant.

    Pins only apply to the requested owner. Timestamp order never uses upload
    time or mutable node update time. Legacy edges use their creation time.
    """
    by_id = {str(n["id"]): n for n in nodes}
    allowed = {str(i) for i in scoped_ids if str(i) in by_id
               and str(by_id[str(i)].get("persona_id") or persona_id) == str(persona_id)}
    if owner_id not in allowed or by_id[owner_id].get("node_type") not in CATALOG_TYPES:
        return {"assets": [], "cover": None, "cover_origin": None}
    children, assignments = {}, {}
    for edge in edges:
        source = str(edge.get("source") or edge.get("source_node_id") or "")
        target = str(edge.get("target") or edge.get("target_node_id") or "")
        relation = edge.get("relation_type") or edge.get("relation")
        if (not active(edge) or source not in allowed or target not in allowed
                or str(edge.get("persona_id") or persona_id) != str(persona_id)):
            continue
        if (relation == "contains" and by_id[source].get("node_type") in CATALOG_TYPES
                and by_id[target].get("node_type") in CATALOG_TYPES):
            children.setdefault(source, []).append(target)
        if relation in ASSET_RELATIONS and by_id[target].get("node_type") == "asset":
            candidate = _media(by_id[target])
            if candidate is None or (available and not available(candidate)):
                continue
            metadata = edge.get("metadata") or {}
            assignment = metadata.get("media_assignment") or {}
            if assignment.get("active") is False:
                continue
            candidate.update({"edge_id": edge.get("id"), "owner_node_id": source,
                              "assigned_at": assignment.get("assigned_at") or edge.get("created_at"),
                              "pinned": assignment.get("pinned") is True,
                              "publication": publication})
            assignments.setdefault(source, []).append(candidate)
    direct = assignments.get(owner_id, [])
    inherited = []
    if not direct and by_id[owner_id].get("node_type") in GROUP_TYPES:
        pending, seen = list(children.get(owner_id, [])), {owner_id}
        while pending:
            child = pending.pop()
            if child in seen:
                continue
            seen.add(child)
            inherited.extend(assignments.get(child, []))
            pending.extend(children.get(child, []))
    ordered = sorted(direct or inherited, key=lambda a: (
        a["pinned"] if direct else False, _timestamp(a["assigned_at"]),
        a["asset_node_id"], str(a["edge_id"] or "")), reverse=True)
    unique, seen = [], set()
    for item in ordered:
        if item["asset_node_id"] not in seen:
            seen.add(item["asset_node_id"])
            unique.append(item)
    cover = unique[0] if unique else None
    return {"assets": unique, "cover": cover, "cover_origin": (
        {"kind": "pinned" if direct and cover["pinned"] else "direct" if direct else "inherited",
         "owner_node_id": cover["owner_node_id"], "edge_id": cover["edge_id"]} if cover else None)}


def validate_image_selection(selection, eligible, *, publication, max_images=3):
    """Resolve model IDs against trusted context; never accept model URLs."""
    limit = min(3, max(0, int(max_images)))
    if not isinstance(selection, list) or len(selection) > limit:
        raise ValueError("image_selection_limit")
    by_id = {item["asset_node_id"]: item for item in eligible}
    result, seen = [], set()
    for choice in selection:
        node_id = choice.get("asset_node_id") if isinstance(choice, dict) else None
        item = by_id.get(node_id)
        if not item or node_id in seen or item.get("publication") != publication:
            raise ValueError("image_reference_invalid_or_stale")
        caption = choice.get("caption", "")
        if not isinstance(caption, str) or len(caption) > 1024:
            raise ValueError("image_caption_invalid")
        seen.add(node_id)
        result.append({**item, "caption": caption})
    return result
