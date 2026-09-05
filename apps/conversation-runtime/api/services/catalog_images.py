"""Published image references for model context; images never become RAG text."""
from brain_contracts.catalog_media import CATALOG_TYPES, resolve_catalog_media, validate_image_selection


def context_images(document, publication, *, scoped_ids, retrieved_ids):
    nodes = document.get("nodes") or []
    by_id = {n["id"]: n for n in nodes}
    owners = set(retrieved_ids) & set(scoped_ids)
    # Retrieved FAQs/copies may reference the catalog subject on their path.
    for node_id in list(owners):
        parent = (document.get("parents") or {}).get(node_id)
        seen = set()
        while parent and parent in scoped_ids and parent not in seen:
            seen.add(parent)
            if by_id.get(parent, {}).get("node_type") in CATALOG_TYPES:
                owners.add(parent)
            parent = (document.get("parents") or {}).get(parent)
    identity = {key: publication[key] for key in ("id", "version", "checksum")}
    result, seen = [], set()
    for owner in sorted(owners):
        if by_id.get(owner, {}).get("node_type") not in CATALOG_TYPES:
            continue
        resolved = resolve_catalog_media(nodes, document.get("edges") or [],
            persona_id=document["persona"]["id"], scoped_ids=scoped_ids,
            owner_id=owner, publication=identity)
        for image in resolved["assets"]:
            if image["asset_node_id"] not in seen:
                seen.add(image["asset_node_id"])
                result.append(image)
    return result


def validate(context, choices):
    return validate_image_selection(choices, context.catalog_images,
        publication={"id": context.publication_id, "version": context.graph_version,
                     "checksum": context.graph_checksum}, max_images=context.max_response_images)
