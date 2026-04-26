from schemas.context import Context, Lead
from schemas.events import LeadEvent
from services import supabase_client
from services.knowledge_service import search_kb_text


def build(event: LeadEvent) -> Context:
    lead_data = supabase_client.get_lead(event.lead_id) or {}

    lead = Lead(
        id=event.lead_id,
        ref=event.lead_ref or lead_data.get("id"),
        nome=event.nome or lead_data.get("nome"),
        stage=event.stage or lead_data.get("stage", "novo"),
        canal=event.canal,
        interesse_produto=event.interesse_produto or lead_data.get("interesse_produto"),
        cidade=event.cidade or lead_data.get("cidade"),
        cep=event.cep or lead_data.get("cep"),
        ai_enabled=lead_data.get("ai_enabled", True),
    )

    historico = supabase_client.get_messages(event.lead_id, limit=20)

    query = " ".join(filter(None, [event.mensagem, lead.interesse_produto, lead.stage]))
    kb_chunks = search_kb_text(query, top_k=5)

    return Context(
        lead=lead,
        mensagem=event.mensagem,
        historico=historico,
        kb_chunks=kb_chunks,
        persona_slug=event.persona_slug,
    )
