import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import agents_service, event_emitter, n8n_client, supabase_client

router = APIRouter(prefix="/messages", tags=["messages"])
logger = logging.getLogger("messages")


class SendMessageBody(BaseModel):
    lead_ref: int
    agent_id: str | None = None  # Resolved from lead.persona if omitted
    texto: str
    sender_id: str | None = None  # operator email/handle
    nome: str | None = None       # display name (operator name)


@router.post("/send")
def send_message(body: SendMessageBody) -> dict:
    """Operator sends a message into a lead's conversation.

    1. INSERT a row in `messages` with sender_type='human'.
    2. Resolve the agent for this lead and POST to its n8n webhook (so the
       n8n SDR/Closer flow sees the human reply and can keep state in sync).
    3. Emit SSE event `message.new` for the dashboard.
    """
    if not (body.texto or "").strip():
        raise HTTPException(status_code=400, detail="texto vazio")

    # Find the agent. Prefer the explicit agent_id; otherwise resolve via
    # the lead's persona+stage so the message is correctly tagged with
    # whoever is on the role for this conversation.
    lead = supabase_client.get_lead_by_ref(body.lead_ref) or {}
    persona_id = lead.get("persona_id")
    whatsapp_phone_number_id = lead.get("whatsapp_phone_number_id") or supabase_client.get_default_whatsapp_phone_number_id(persona_id)
    persona_routing: dict | None = None
    if persona_id:
        # Resolve persona slug to load the per-persona outbound webhook
        # config (used in BOTH internal and n8n routing modes — the operator
        # reply always goes out through this hook).
        try:
            personas = supabase_client.get_personas() or []
            persona_row = next((p for p in personas if p.get("id") == persona_id), None)
            if persona_row and persona_row.get("slug"):
                persona_routing = supabase_client.get_persona_routing(persona_row["slug"])
        except Exception as exc:
            logger.warning("persona routing lookup failed in send: %s", exc)

    agent: dict | None = None
    if body.agent_id:
        agent = agents_service.get_agent(body.agent_id)
    else:
        stage = lead.get("stage") or lead.get("funnel_stage") or "novo"
        if persona_id:
            try:
                agent, _role = agents_service.resolve_for_stage(persona_id, stage)
            except Exception as exc:
                logger.warning("resolve_for_stage failed in send: %s", exc)

    msg_payload = {
        "lead_ref": body.lead_ref,
        "message_id": f"hum_{int(time.time() * 1000)}_{body.lead_ref}",
        "sender_type": "human",
        "sender_id": body.sender_id,
        "canal": "whatsapp",
        "texto": body.texto,
        "direction": "Outbounding",
        "nome": body.nome or body.sender_id or "Operador",
        "status": "pending",
        "whatsapp_phone_number_id": whatsapp_phone_number_id,
        "metadata": {"agent_id": agent.get("id") if agent else None,
                     "bot_name": agent.get("bot_name") if agent else None},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase_client.insert_message(msg_payload)
    except Exception as exc:
        logger.error("insert_message failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"insert_message failed: {exc}")

    # Outbound webhook precedence:
    #   1) persona.outbound_webhook_url (preferred — works for both
    #      process_modes; configured per-persona in the dashboard).
    #   2) agent.n8n_webhook_url (legacy fallback for personas that haven't
    #      been migrated to per-persona webhook config yet).
    outbound_url: str | None = None
    outbound_secret: str | None = None
    if persona_routing and persona_routing.get("outbound_webhook_url"):
        outbound_url = persona_routing["outbound_webhook_url"]
        outbound_secret = persona_routing.get("outbound_webhook_secret")
    elif agent and agent.get("n8n_webhook_url"):
        outbound_url = agent["n8n_webhook_url"]
        outbound_secret = agent.get("n8n_webhook_secret")

    webhook_status: int | None = None
    webhook_error: str | None = None
    if outbound_url:
        webhook_payload = {
            "lead_ref": body.lead_ref,
            "agent_id": agent.get("id") if agent else None,
            "bot_name": agent.get("bot_name") if agent else None,
            "persona_id": persona_id,
            "lead_id": lead.get("lead_id"),
            "telefone": lead.get("telefone"),
            "whatsapp_phone_number_id": whatsapp_phone_number_id,
            "from": "human",
            "sender_id": body.sender_id,
            "texto": body.texto,
            "message_id": msg_payload["message_id"],
        }
        try:
            webhook_status, _ = n8n_client.send_to_webhook(
                outbound_url,
                webhook_payload,
                secret=outbound_secret,
            )
            msg_payload["status"] = "sent" if 200 <= webhook_status < 300 else "failed"
        except Exception as exc:
            webhook_error = str(exc)
            msg_payload["status"] = "failed"
            logger.warning("webhook delivery failed: %s", exc)
    else:
        # No webhook configured — message is in DB but won't be sent out.
        msg_payload["status"] = "draft"

    event_emitter.emit(
        "message.new",
        entity_type="message",
        entity_id=msg_payload["message_id"],
        payload={
            "lead_ref": body.lead_ref,
            "sender_type": "human",
            "agent_id": agent.get("id") if agent else None,
            "webhook_status": webhook_status,
        },
        source="messages.send",
    )

    return {
        "ok": webhook_error is None,
        "message_id": msg_payload["message_id"],
        "status": msg_payload["status"],
        "webhook_status": webhook_status,
        "webhook_error": webhook_error,
    }


@router.get("/conversations")
def get_conversations(hours: int = Query(168, le=720), persona_id: str | None = Query(None)):
    """
    Returns one entry per conversation (grouped by lead_ref first),
    sorted by most-recent message. Used by the Mensagens sidebar.
    """
    return supabase_client.get_conversations(hours=hours, persona_id=persona_id)


@router.get("/by-ref/{lead_ref}")
def get_messages_by_ref(lead_ref: int, limit: int = Query(200, le=500)):
    """Fetch messages by integer lead_ref — the canonical way."""
    return supabase_client.get_messages(str(lead_ref), limit=limit)


@router.get("/{lead_id}")
def get_messages(lead_id: str, limit: int = Query(200, le=500)):
    return supabase_client.get_messages(lead_id, limit=limit)


@router.get("")
def recent_messages(
    hours: int = Query(24, le=168),
    persona_id: str | None = Query(None),
):
    """Returns all recent messages without status filtering."""
    return supabase_client.get_recent_messages(hours=hours, limit=500, persona_id=persona_id)
