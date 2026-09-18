"""Internal read-only delivery policy resolved from the active GraphBundle."""

from fastapi import APIRouter, Header, HTTPException

from services import context_cards, internal_auth, supabase_client


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
    try:
        version, checksum, graph = context_cards.current_graph(slug)
    except Exception as exc:
        raise HTTPException(409, "Persona sem GraphBundle publicado.") from exc
    persona_node = next((node for node in graph.nodes if node.node_type == "persona"), None)
    policy = ((persona_node.data if persona_node else {}) or {}).get("conversation_policy", {}).get("business_hours")
    if not isinstance(policy, dict) or policy.get("enabled") is False:
        raise HTTPException(409, "Persona sem politica publicada de horario comercial.")
    return {"published_business_hours": {
        "timezone": policy.get("timezone"),
        "start": policy.get("start"),
        "end": policy.get("end"),
        "graph_version": version,
        "graph_checksum": checksum,
    }}
