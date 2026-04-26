import time
from fastapi import APIRouter
from schemas.events import LeadEvent
from core import context_builder, classifier, decision_engine, insight_engine
from agents.sdr import SDRAgent
from agents.closer import CloserAgent
from services import supabase_client
from datetime import datetime, timezone

router = APIRouter(tags=["process"])

_AGENTS = {
    "SDR": SDRAgent,
    "CLOSER": CloserAgent,
}


@router.post("/process")
async def process(event: LeadEvent):
    t0 = time.monotonic()

    ctx = context_builder.build(event)

    classification = classifier.classify(ctx)
    ctx.classification = classification

    score, tags, funnel_stage = decision_engine.compute_score(ctx)
    ctx.score = score
    ctx.tags = tags
    ctx.funnel_stage = funnel_stage

    route = decision_engine.decide(ctx)
    ctx.route_hint = route

    agent_result: dict = {"reply": None, "agent": route, "detected_fields": {}}

    agent_cls = _AGENTS.get(route)
    if agent_cls:
        try:
            agent_result = await agent_cls().run(ctx)
        except Exception as e:
            print(f"[process] agent error: {e}")

    latency_ms = int((time.monotonic() - t0) * 1000)

    if agent_result.get("reply"):
        supabase_client.insert_message({
            "lead_id": ctx.lead.id,
            "lead_ref": ctx.lead.ref,
            "message_id": f"ai_{int(time.time() * 1000)}_{ctx.lead.ref}",
            "sender_type": "agent",
            "canal": ctx.lead.canal,
            "texto": agent_result["reply"],
            "direction": "outbound",
            "Lead_Stage": funnel_stage,
            "nome": ctx.lead.nome,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        if ctx.lead.ref:
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

    insight_engine.record(ctx, agent_result, latency_ms)

    return {
        "reply": agent_result.get("reply"),
        "stage_update": funnel_stage,
        "agent_used": route,
        "score": score,
        "detected_fields": agent_result.get("detected_fields", {}),
        "latency_ms": latency_ms,
    }
