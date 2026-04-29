import logging
import re
import time
from fastapi import APIRouter
from schemas.events import LeadEvent
from core import context_builder, classifier, decision_engine, insight_engine
from agents.sdr import SDRAgent
from agents.closer import CloserAgent
from services import supabase_client
from datetime import datetime, timezone

router = APIRouter(tags=["process"])
logger = logging.getLogger("process")

_AGENTS = {
    "SDR": SDRAgent,
    "CLOSER": CloserAgent,
}


@router.post("/process")
async def process(event: LeadEvent):
    t0 = time.monotonic()

    ctx = context_builder.build(event)

    try:
        classification = classifier.classify(ctx)
    except Exception as exc:
        logger.warning("classifier failed, using SDR defaults: %s", exc)
        classification = {
            "intent": "duvida_geral",
            "interest_level": "medio",
            "urgency": "baixa",
            "fit": "neutro",
            "objections": [],
            "summary": "classifier unavailable",
            "route_hint": "SDR",
        }
    ctx.classification = classification

    score, tags, funnel_stage = decision_engine.compute_score(ctx)
    ctx.score = score
    ctx.tags = tags
    ctx.funnel_stage = funnel_stage

    route = decision_engine.decide(ctx)
    ctx.route_hint = route

    agent_result: dict = {"reply": None, "agent": route, "detected_fields": {}}

    agent_cls = _AGENTS.get(route) or _AGENTS.get("SDR")
    if agent_cls:
        try:
            agent_result = await agent_cls().run(ctx)
        except Exception as e:
            print(f"[process] agent error: {e}")

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Resolve lead_ref: Supabase row id when available, otherwise WA phone number as int
    resolved_lead_ref: int | None = ctx.lead.ref
    if resolved_lead_ref is None:
        try:
            digits = re.sub(r"\D", "", ctx.lead.id or "")
            if digits:
                resolved_lead_ref = int(digits)
        except Exception:
            pass

    if agent_result.get("reply"):
        try:
            supabase_client.insert_message({
                "lead_ref": resolved_lead_ref,
                "message_id": f"ai_{int(time.time() * 1000)}_{resolved_lead_ref}",
                "sender_type": "agent",
                "canal": ctx.lead.canal,
                "texto": agent_result["reply"],
                "direction": "Outbounding",
                "Lead_Stage": funnel_stage,
                "nome": ctx.lead.nome,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.warning("insert_message failed (non-fatal): %s", exc)

        if ctx.lead.ref:
            try:
                update = {"stage": funnel_stage, "ultima_mensagem": ctx.mensagem}
                df = agent_result.get("detected_fields", {}) or {}
                if df.get("produto"):
                    update["interesse_produto"] = df["produto"]
                if df.get("cidade"):
                    update["cidade"] = df["cidade"]
                if df.get("cep"):
                    update["cep"] = df["cep"]
                if df.get("nome"):
                    update["nome"] = df["nome"]
                supabase_client.update_lead(ctx.lead.ref, update)
            except Exception as exc:
                logger.warning("update_lead failed (non-fatal): %s", exc)

    insight_engine.record(ctx, agent_result, latency_ms)

    return {
        "reply": agent_result.get("reply"),
        "stage_update": funnel_stage,
        "agent_used": route,
        "score": score,
        "detected_fields": agent_result.get("detected_fields", {}),
        "latency_ms": latency_ms,
    }
