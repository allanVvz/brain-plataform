"""Desfecho comercial da jornada, derivado em um lugar so.

`delivered`, `service_completed` e `cancelled` nao sao estados: os tres colapsam
em `state='closed'` e so se distinguem por `metadata.closing_event`. A UI precisa
de um valor unico e estavel por lead, entao a leitura vive aqui e nao espalhada
por rota, componente e query.
"""
from __future__ import annotations

from typing import Any, Optional

from services import supabase_client

QUALIFICADO = "qualificado"
CONVERTIDO = "convertido"
VENDIDO = "vendido"
ENTREGUE = "entregue"
CANCELADO = "cancelado"

OUTCOMES = (QUALIFICADO, CONVERTIDO, VENDIDO, ENTREGUE, CANCELADO)

# Estados em que a qualificacao ja foi concluida mas nada comercial aconteceu.
_QUALIFIED_STATES = {"qualified_confirmed", "handed_off"}
_COMPLETION_EVENTS = {"delivered", "service_completed"}


def derive(journey: dict[str, Any] | None) -> Optional[str]:
    """Desfecho de uma jornada, ou None quando ainda nao ha nenhum.

    O terminal vence: uma jornada vendida e depois cancelada le `cancelado`,
    e uma vendida e entregue le `entregue`.
    """
    if not journey:
        return None
    state = str(journey.get("state") or "").strip().lower()
    metadata = journey.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    if state == "closed":
        closing = str(metadata.get("closing_event") or "").strip().lower()
        if closing == "cancelled":
            return CANCELADO
        if closing in _COMPLETION_EVENTS:
            return ENTREGUE
        return None
    if state == "converted":
        return VENDIDO if metadata.get("sold") else CONVERTIDO
    if state in _QUALIFIED_STATES:
        return QUALIFICADO
    return None


def outcomes_for_leads(persona_id: str, lead_refs: list[int]) -> dict[int, Optional[str]]:
    """Desfecho corrente de varios leads numa leitura so.

    A lista de conversas pinta todos os itens de uma vez -- uma consulta por
    lead transformaria a tela em N+1.
    """
    refs = sorted({int(ref) for ref in lead_refs if ref})
    if not persona_id or not refs:
        return {}
    outcomes: dict[int, Optional[str]] = {}
    for journey in supabase_client.get_current_journeys_by_lead_refs(persona_id, refs):
        ref = journey.get("lead_ref")
        if ref is None:
            continue
        outcomes[int(ref)] = derive(journey)
    return outcomes


def decorate_leads(rows: list[dict[str, Any]], persona_id: str | None = None) -> list[dict[str, Any]]:
    """Anexa `journey_outcome` a cada lead ja decorado pela qualificacao.

    `stage` continua sendo o funil manual: o desfecho e um eixo novo e
    independente, nunca uma reescrita do estagio.
    """
    if not rows:
        return rows
    grouped: dict[str, list[int]] = {}
    for row in rows:
        pid = str(persona_id or row.get("persona_id") or "")
        ref = row.get("id")
        if not pid or ref is None:
            continue
        grouped.setdefault(pid, []).append(int(ref))

    outcomes: dict[tuple[str, int], Optional[str]] = {}
    for pid, refs in grouped.items():
        for ref, outcome in outcomes_for_leads(pid, refs).items():
            outcomes[(pid, ref)] = outcome

    for row in rows:
        pid = str(persona_id or row.get("persona_id") or "")
        ref = row.get("id")
        row["journey_outcome"] = (
            outcomes.get((pid, int(ref))) if pid and ref is not None else None
        )
    return rows
