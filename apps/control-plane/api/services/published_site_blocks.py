"""Public blocks read only the active publication and explicit page bindings."""
import json
from urllib.parse import quote

from services import site_blocks, supabase_client


class PageNotFound(LookupError):
    pass


def load_page(page_slug):
    # Page aliases are configuration, never inferred from a commercial name.
    rows = supabase_client.get_client().table("personas").select("id,slug,config").execute().data or []
    matches = []
    for persona in rows:
        site = (persona.get("config") or {}).get("public_site") or {}
        pages = [site, *(site.get("pages") or [])]
        for page in pages:
            if page.get("site_slug") == page_slug and page.get("branch_node_id"):
                matches.append((persona, {**site, **page}))
    if len(matches) != 1:
        raise PageNotFound("public_page_not_found")
    persona, config = matches[0]
    publication = supabase_client.get_active_graph_publication(str(persona["id"]))
    if not publication or str(publication.get("persona_id")) != str(persona["id"]):
        raise PageNotFound("public_page_not_published")
    document = publication.get("document_json") or {}
    if isinstance(document, str):
        document = json.loads(document)
    if str((document.get("persona") or {}).get("id")) != str(persona["id"]):
        raise PageNotFound("public_page_not_published")
    identity = {k: publication[k] for k in ("id", "version", "checksum")}
    # Never copy arbitrary config into the public response.
    site = {k: config.get(k) for k in ("site_slug", "site_name", "format_key",
            "whatsapp_phone", "whatsapp_message_template")}
    requested_template = config.get("format_key") or "landing_page"
    template_key = requested_template if requested_template in site_blocks.TEMPLATES else "landing_page"
    payload = site_blocks.resolve_blocks({**document, "publication": identity},
        template_key=template_key,
        scope=config["branch_node_id"], site=site)
    payload["format_key"] = requested_template
    return payload


def media_references(payload):
    refs = {}
    for block in payload["blocks"]:
        for group in block["data"].get("groups", []):
            for owner in [group, *group.get("products", [])]:
                for asset in owner.get("assets", []):
                    refs[asset["asset_node_id"]] = asset
    return refs


def public_payload(page_slug):
    payload = load_page(page_slug)
    for asset in media_references(payload).values():
        if asset.get("bucket") and asset.get("path"):
            asset["url"] = (f"/api/menu/{quote(page_slug, safe='')}/media/"
                            f"{quote(asset['asset_node_id'], safe='')}"
                            f"?publication={quote(str(payload['publication']['id']), safe='')}")
    # Each owner has its own projection object; update every occurrence.
    refs = media_references(payload)
    for block in payload["blocks"]:
        for group in block["data"].get("groups", []):
            for owner in [group, *group.get("products", [])]:
                for asset in owner.get("assets", []):
                    asset["url"] = refs[asset["asset_node_id"]]["url"]
    return payload
