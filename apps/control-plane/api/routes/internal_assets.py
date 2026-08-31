from fastapi import APIRouter, Header

from services import inbound_media_graph, internal_auth


router = APIRouter(prefix="/internal/v1/control-plane/assets", tags=["internal-assets"])


@router.post("/{asset_id}/attach-inbound-graph")
def attach_inbound_graph(
    asset_id: str,
    x_webhook_token: str | None = Header(None, alias="X-Webhook-Token"),
) -> dict:
    internal_auth.authorize_webhook_token(x_webhook_token)
    return inbound_media_graph.attach(asset_id)
