"""Internal read-only delivery policy resolved from the active GraphBundle."""

from fastapi import APIRouter, Header, HTTPException

from services import business_hours, internal_auth, supabase_client


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
    if not publication:
        raise HTTPException(409, "Persona sem publicacao ativa.")
    hours = business_hours.effective(persona, publication)
    # No window (or one switched off on the Agentes screen) means replies are
    # not time-restricted; appointment confirmation remains a separate business
    # decision owned by the graph and a human attendant.
    if not hours["enabled"]:
        if hours["switched_off"]:
            return {
                "published_business_hours": None,
                "graph_version": publication.get("version"),
                "graph_checksum": publication.get("checksum"),
            }
        raise HTTPException(409, "Persona sem politica publicada de horario comercial.")
    return {"published_business_hours": {
        "timezone": hours["timezone"],
        "start": hours["start"],
        "end": hours["end"],
        "graph_version": publication.get("version"),
        "graph_checksum": publication.get("checksum"),
    }}
