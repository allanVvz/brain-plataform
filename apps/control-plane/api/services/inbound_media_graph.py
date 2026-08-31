from __future__ import annotations

import logging

from services import knowledge_graph, supabase_client


logger = logging.getLogger("services.inbound_media_graph")


def _audience_node(persona_id: str, recipient_id: str | None) -> dict | None:
    if not recipient_id:
        return None
    client = supabase_client.get_client()
    try:
        recipients = client.table("campaign_recipients").select(
            "campaign_revision_id"
        ).eq("id", recipient_id).limit(1).execute().data or []
        if not recipients:
            return None
        revisions = client.table("campaign_revisions").select("audience_id").eq(
            "id", recipients[0].get("campaign_revision_id")
        ).limit(1).execute().data or []
        audience_id = (revisions[0] if revisions else {}).get("audience_id")
        if not audience_id:
            return None
    except Exception as exc:
        logger.warning("audience lookup failed recipient=%s: %s", recipient_id, exc)
        return None
    node = supabase_client.get_knowledge_node_for_source(
        "audiences", str(audience_id), persona_id=persona_id
    )
    if node:
        return node
    audience = supabase_client.get_audience(str(audience_id))
    return supabase_client.sync_audience_node(audience) if audience else None


def _conversation_node(persona_id: str, lead: dict, audience: dict | None) -> dict | None:
    lead_id = lead.get("id")
    if not lead_id:
        return None
    display = lead.get("nome") or lead.get("name") or lead.get("external_contact_id") or f"lead {lead_id}"
    node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id, "source_table": "leads", "node_type": "conversation",
        "slug": f"conversa-{lead_id}", "title": f"Conversa — {display}",
        "summary": f"Thread de WhatsApp com {display}.", "tags": ["conversa", "whatsapp"],
        "metadata": {"lead_id": lead_id, "audience_node_id": (audience or {}).get("id"), "open_url": "/messages", "rag_eligible": False},
        "status": "active", "level": 106, "importance": 0.5, "confidence": 1.0,
    })
    if node and node.get("id") and audience and audience.get("id"):
        supabase_client.upsert_knowledge_edge(
            audience["id"], node["id"], "contains", persona_id=persona_id,
            weight=0.7, metadata={"created_from": "whatsapp_media_ingest", "primary_tree": True, "direction": "audience_to_conversation"},
        )
    return node


def attach(asset_id: str) -> dict:
    asset = supabase_client.get_asset(asset_id)
    if not asset:
        return {"attached": False, "reason": "asset_not_found"}
    persona_id, lead_id = asset.get("persona_id"), asset.get("lead_id")
    if not persona_id or not lead_id:
        return {"attached": False, "reason": "missing_persona_or_lead"}
    audience = _audience_node(str(persona_id), asset.get("campaign_recipient_id"))
    conversation = _conversation_node(
        str(persona_id), supabase_client.get_lead(str(lead_id)) or {"id": lead_id}, audience
    )
    if not conversation or not conversation.get("id"):
        return {"attached": False, "reason": "conversation_node_failed"}
    metadata = asset.get("metadata") or {}
    existing = supabase_client.get_knowledge_node_for_source("assets", asset_id, persona_id=str(persona_id))
    asset_node = existing or supabase_client.upsert_knowledge_node({
        "persona_id": str(persona_id), "source_table": "assets", "source_id": asset_id,
        "node_type": "asset", "slug": f"{knowledge_graph._slugify(asset.get('original_filename') or asset_id)[:60]}-{asset_id[:8]}",
        "title": asset.get("name") or asset.get("original_filename") or "Midia recebida",
        "summary": (metadata.get("descriptor_text") or metadata.get("visual_summary") or "")[:400] or None,
        "tags": ["whatsapp", "recebido", str((metadata.get("media") or {}).get("kind") or "midia")],
        "metadata": {**metadata, "asset_id": asset_id, "storage_bucket": asset.get("storage_bucket"), "storage_path": asset.get("storage_path"), "parent_node_id": conversation["id"], "parent_slug": conversation.get("slug"), "parent_type": "conversation"},
        "status": "active", "level": 108, "importance": 0.64, "confidence": 1.0,
    })
    parent_edge = supabase_client.upsert_knowledge_edge(
        conversation["id"], asset_node["id"], "uses_asset", persona_id=str(persona_id),
        weight=0.85, metadata={"created_from": "whatsapp_media_ingest", "primary_tree": True, "direction": "conversation_to_asset"},
    )
    gallery = supabase_client.ensure_gallery_node(str(persona_id))
    gallery_edge = supabase_client.upsert_knowledge_edge(
        asset_node["id"], gallery["id"], "gallery_asset", persona_id=str(persona_id),
        weight=0.9, metadata={"graph_layer": "auxiliary", "primary_tree": False, "created_from": "whatsapp_media_ingest", "direction": "asset_to_gallery"},
    )
    supabase_client.update_asset_graph_refs(
        asset_id, knowledge_node_id=asset_node["id"], gallery_edge_id=gallery_edge["id"],
        parent_node_id=conversation["id"], parent_edge_id=parent_edge["id"],
    )
    return {"attached": True, "conversation_node_id": conversation["id"], "asset_node_id": asset_node["id"], "gallery_node_id": gallery["id"]}
