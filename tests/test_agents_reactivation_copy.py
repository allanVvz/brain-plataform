"""Reabrir uma conversa nao e o mesmo que responde-la.

Passada a janela editorial, responder o inbound antigo soa como o agente
falando sozinho -- mas ficar mudo abandona a cliente, que foi exatamente o que
aconteceu com quatro leads reais da Tock Fatal em 2026-09-08/09: elas
escreveram, o canal estava pausado, o worker as engavetou em `waiting_human` e
ninguem nunca falou com elas.

Entao a retomada escolhe QUAL copy publicada usar, conforme o motivo:

  dentro da janela   -> a propria mensagem da cliente e respondida (sem aviso)
  10h a 24h          -> `stale_reengagement`: reabre pedindo desculpa
  alem de 24h        -> silencio: fora da janela do provedor so template vale
  ninguem esperando  -> `idle_return`: aviso curto

A copy continua vindo inteira do grafo. Persona que nao publica a chave
continua muda, sem texto autorado pelo runtime.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import agents_service, whatsapp_outbox  # noqa: E402


LEAD_REF = 5150
WINDOW = 36000


def _lead():
    return {
        "id": "70000000-0000-0000-0000-000000000009",
        "persona_slug": "generic",
        "handoff_level": "none",
        "metadata": {},
        "updated_at": "2026-09-09T12:00:00",
    }


def _message(direction: str, *, minutes_ago: int):
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "direction": direction,
        "created_at": sent_at.isoformat(),
        "texto": "mensagem",
    }


PUBLISHED = {
    "answer_pending_inbound_within_seconds": WINDOW,
    "reengage_pending_inbound_within_seconds": 86400,
    "manual": ["Voltei ao atendimento."],
    "stale_reengagement": ["Sua mensagem ficou sem retorno e eu peco desculpas."],
    "idle_return": ["Estou de volta. Quando quiser seguir, e so chamar."],
}


def _install(monkeypatch, messages, *, published=None):
    sent: list[dict] = []
    monkeypatch.setattr(
        agents_service.supabase_client, "get_lead_by_ref", lambda _ref: _lead()
    )
    monkeypatch.setattr(
        agents_service.supabase_client, "get_messages",
        lambda _lead_id, limit=5: list(messages),
    )
    monkeypatch.setattr(
        agents_service, "_reactivation_policy",
        lambda _lead: dict(PUBLISHED if published is None else published),
    )
    # O envio e importado dentro da funcao, entao o alvo do patch e o modulo
    # de outbox, nao um atributo de agents_service.
    monkeypatch.setattr(
        whatsapp_outbox, "enqueue_outbound",
        lambda **kwargs: sent.append(kwargs) or {"deduplicated": False},
    )
    agents_service._LAST_REQUEUED.pop(LEAD_REF, None)
    agents_service._LAST_RESUME_WINDOW.pop(LEAD_REF, None)
    return sent


def test_entre_10h_e_24h_reabre_com_a_copy_de_reengajamento(monkeypatch):
    sent = _install(monkeypatch, [_message("inbound", minutes_ago=15 * 60)])

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result["sent"] is True
    assert len(sent) == 1
    assert sent[0]["text"] == PUBLISHED["stale_reengagement"][0]


def test_alem_de_24h_nao_envia_porque_so_template_reabre(monkeypatch):
    sent = _install(monkeypatch, [_message("inbound", minutes_ago=30 * 60)])

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result == {"sent": False, "skipped": "session_window_closed"}
    assert sent == []


def test_sem_ninguem_esperando_usa_o_aviso_curto(monkeypatch):
    sent = _install(monkeypatch, [
        _message("inbound", minutes_ago=40),
        _message("outbound", minutes_ago=30),
    ])

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result["sent"] is True
    assert sent[0]["text"] == PUBLISHED["idle_return"][0]


def test_dentro_da_janela_o_aviso_cede_lugar_a_resposta(monkeypatch):
    sent = _install(monkeypatch, [_message("inbound", minutes_ago=20)])

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result == {"sent": False, "skipped": "pending_inbound_will_be_answered"}
    assert sent == []


def test_persona_sem_a_chave_publicada_continua_muda(monkeypatch):
    # A invariante que ja existia: nada de texto autorado pelo runtime.
    sent = _install(
        monkeypatch,
        [_message("inbound", minutes_ago=15 * 60)],
        published={"answer_pending_inbound_within_seconds": WINDOW},
    )

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result == {"sent": False, "skipped": "no_published_copy"}
    assert sent == []


def test_teto_publicado_menor_encurta_mas_nunca_passa_do_provedor(monkeypatch):
    published = dict(PUBLISHED, reengage_pending_inbound_within_seconds=12 * 3600)
    sent = _install(
        monkeypatch, [_message("inbound", minutes_ago=15 * 60)], published=published
    )

    result = agents_service.reactivation_notice(LEAD_REF, reason="manual")

    assert result == {"sent": False, "skipped": "session_window_closed"}
    assert sent == []

    # E o contrario nao vale: publicar 48h nao autoriza furar a janela real.
    published = dict(PUBLISHED, reengage_pending_inbound_within_seconds=48 * 3600)
    sent = _install(
        monkeypatch, [_message("inbound", minutes_ago=30 * 60)], published=published
    )

    assert agents_service.reactivation_notice(LEAD_REF, reason="manual") == {
        "sent": False, "skipped": "session_window_closed",
    }
    assert sent == []
