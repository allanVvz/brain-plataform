from services import supabase_client
from typing import Optional


def search_kb_text(query: str, persona_id: Optional[str] = None, top_k: int = 5) -> list[str]:
    if not persona_id:
        # Never allow a global fallback that could mix clients.
        return []
    try:
        rag_chunks = supabase_client.search_active_rag_chunks(
            persona_id=persona_id,
            query=query,
            limit=top_k,
        )
    except Exception:
        rag_chunks = []
    if rag_chunks:
        return [
            str(chunk.get("chunk_text") or chunk.get("chunk_summary") or "").strip()
            for chunk in rag_chunks
            if str(chunk.get("chunk_text") or chunk.get("chunk_summary") or "").strip()
        ][:top_k]

    # Temporary, auditable transition fallback.
    try:
        supabase_client.insert_event(
            {
                "event_type": "legacy_kb_fallback_used",
                "entity_type": "persona",
                "entity_id": persona_id,
                "persona_id": persona_id,
                "payload": {"query": (query or "")[:300], "top_k": top_k},
                "level": "warning",
                "source": "knowledge_service.search_kb_text",
            },
            source="knowledge_service.search_kb_text",
        )
    except Exception:
        pass
    entries = supabase_client.get_kb_entries(persona_id=persona_id)
    query_lower = query.lower()
    scored = []
    for e in entries:
        text = f"{e.get('titulo','')} {e.get('conteudo','')} {e.get('categoria','')} {e.get('produto','')}".lower()
        score = sum(1 for word in query_lower.split() if word in text)
        if score > 0:
            content = (
                f"Pergunta: {e['titulo']}\n"
                f"Resposta: {e['conteudo']}"
                + (f"\nLink: {e['link']}" if e.get("link") else "")
            )
            scored.append((score, content))

    scored.sort(reverse=True)
    return [c for _, c in scored[:top_k]]
