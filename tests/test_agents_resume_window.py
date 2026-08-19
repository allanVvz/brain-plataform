"""Religar a IA nao autoriza falar: quem decide o momento e o cliente.

Um inbound que ficou estacionado horas nao e uma conversa esperando
continuacao. Responde-lo quando um humano religa a IA soa como o agente
falando sozinho -- e, no caso concreto que motivou isto, teria respondido
quatro mensagens paradas de leads que ninguem queria reprocessar.

A janela vem publicada no grafo
(`conversation_policy.reactivation.answer_pending_inbound_within_seconds`);
o codigo so carrega um default generico.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import agents_service


LEAD_REF = 4242
WINDOW = 36000


def _lead():
    return {
        "id": "70000000-0000-0000-0000-000000000001",
        "persona_slug": "generic",
        # Ja retomado: e assim que o aviso de reativacao le a lead.
        "handoff_level": "none",
        "metadata": {},
        "updated_at": "2026-08-19T12:00:00",
    }


def _message(direction: str, *, minutes_ago: int):
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "direction": direction,
        "created_at": sent_at.isoformat(),
        "texto": "mensagem",
    }


def _install(monkeypatch, messages, *, window=WINDOW):
    requeued: list[int] = []
    monkeypatch.setattr(
        agents_service.supabase_client, "get_lead_by_ref", lambda _ref: _lead(),
    )
    monkeypatch.setattr(
        agents_service.supabase_client, "update_lead",
        lambda _ref, _payload: None,
    )
    monkeypatch.setattr(
        agents_service.supabase_client, "get_messages",
        lambda _lead_id, limit=5: list(messages),
    )
    monkeypatch.setattr(
        agents_service.supabase_client, "requeue_waiting_human_whatsapp_buffer",
        lambda ref: requeued.append(ref) or 1,
    )
    monkeypatch.setattr(
        agents_service, "_reactivation_policy",
        lambda _lead: {
            "answer_pending_inbound_within_seconds": window,
            "manual": ["Oi! Voltei, estou por aqui."],
        },
    )
    agents_service._LAST_REQUEUED.pop(LEAD_REF, None)
    agents_service._LAST_RESUME_WINDOW.pop(LEAD_REF, None)
    return requeued


def test_inbound_recente_e_respondido_ao_religar(monkeypatch):
    requeued = _install(monkeypatch, [_message("inbound", minutes_ago=20)])

    assert agents_service.resume_lead(LEAD_REF) is True
    assert requeued == [LEAD_REF]


def test_inbound_estacionado_alem_da_janela_permanece_intacto(monkeypatch):
    requeued = _install(monkeypatch, [_message("inbound", minutes_ago=15 * 60)])

    assert agents_service.resume_lead(LEAD_REF) is True
    # O buffer nao e tocado: a proxima mensagem do cliente reabre a conversa.
    assert requeued == []
    assert (
        agents_service._LAST_RESUME_WINDOW[LEAD_REF]["reason"]
        == "resume_window_expired"
    )


def test_sem_mensagem_pendente_o_agente_nao_abre_conversa(monkeypatch):
    requeued = _install(monkeypatch, [
        _message("inbound", minutes_ago=30), _message("outbound", minutes_ago=25),
    ])

    assert agents_service.resume_lead(LEAD_REF) is True
    assert requeued == []
    assert (
        agents_service._LAST_RESUME_WINDOW[LEAD_REF]["reason"]
        == "no_unanswered_customer_message"
    )


def test_aviso_de_reativacao_respeita_a_mesma_janela(monkeypatch):
    _install(monkeypatch, [_message("inbound", minutes_ago=15 * 60)])
    agents_service.resume_lead(LEAD_REF)

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result == {"sent": False, "skipped": "resume_window_expired"}


def test_a_janela_vem_do_grafo_e_nao_do_codigo(monkeypatch):
    requeued = _install(
        monkeypatch, [_message("inbound", minutes_ago=90)], window=600,
    )

    assert agents_service.resume_lead(LEAD_REF) is True
    assert requeued == []

    requeued = _install(
        monkeypatch, [_message("inbound", minutes_ago=90)], window=86400,
    )

    assert agents_service.resume_lead(LEAD_REF) is True
    assert requeued == [LEAD_REF]
