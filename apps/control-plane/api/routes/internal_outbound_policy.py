"""Internal read-only delivery policy resolved from the active GraphBundle."""

from fastapi import APIRouter, Header, HTTPException

from services import internal_auth, supabase_client


router = APIRouter(prefix="/internal/v1/control-plane", tags=["internal-policy"])


@router.get("/personas/{persona_id}/outbound-policy")
def published_outbound_policy(
    persona_id: str,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    """Return the delivery window pinned to the persona's active publication."""
    internal_auth.authorize_webhook_token(x_webhook_token)
    persona = supabase_client.get_persona_by_id(persona_id) or {}
    slug = str(persona.get("slug") or "")
    if not slug:
        raise HTTPException(404, "Persona nao encontrada.")
    # Delivery cannot depend on the Markdown projection used for chat-context.
    # The active GraphBundle document is already immutable and publication
    # validated; resolve the policy directly from that document.
    publication = supabase_client.get_active_graph_publication(str(persona_id)) or {}
    graph = publication.get("document_json") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else []
    persona_node = next((
        node for node in nodes
        if isinstance(node, dict)
        and str(node.get("node_type") or node.get("type") or "").lower() == "persona"
    ), {})
    node_data = persona_node.get("data") or persona_node.get("metadata") or {}
    policy = (node_data.get("conversation_policy") or {}).get("business_hours")
    if (
        not publication
        or not isinstance(policy, dict)
        or policy.get("enabled") is False
        or not all(str(policy.get(key) or "").strip() for key in ("timezone", "start", "end"))
    ):
        raise HTTPException(409, "Persona sem politica publicada de horario comercial.")
    return {"published_business_hours": {
        "timezone": policy.get("timezone"),
        "start": policy.get("start"),
        "end": policy.get("end"),
        "graph_version": publication.get("version"),
        "graph_checksum": publication.get("checksum"),
    }}
