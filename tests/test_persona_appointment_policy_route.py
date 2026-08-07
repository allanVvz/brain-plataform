"""PATCH /knowledge/personas/{persona_slug}/appointment-policy.

Monkeypatched; no live Supabase. Mirrors the pattern in
test_node_markdown_and_faq_append.py — call the route function directly
with a fake Request, mock out the service boundary calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _req():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


def _aurora_graph():
    from schemas.graph_json_v2 import GraphJson

    payload = json.loads(
        (ROOT / "api" / "scripts" / "fixtures" / "aurora_graph_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return GraphJson.model_validate(payload)


def test_update_persona_appointment_policy_patches_only_given_keys(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_capability", lambda *a, **k: None)
    monkeypatch.setattr(graph.supabase_client, "get_persona", lambda slug: {"id": "per-aurora"})
    monkeypatch.setattr(graph, "emit", lambda *a, **k: None)

    aurora_graph = _aurora_graph()
    monkeypatch.setattr(
        graph.graph_json_v2_store, "load_current", lambda slug: (2, aurora_graph)
    )
    captured = {}

    def _fake_commit(*, graph, **kwargs):
        captured["graph"] = graph
        captured["kwargs"] = kwargs
        return {"ok": True, "graph_version": 3, "checksum": "abc"}

    monkeypatch.setattr(graph.graph_document_publisher, "commit", _fake_commit)

    body = graph.AppointmentPolicyTextsBody(atendimento_humano="Vou chamar um atendente agora.")
    out = graph.update_persona_appointment_policy("aurora", body, _req())

    assert out["ok"] is True
    assert out["graph_version"] == 3
    assert out["appointment_policy"]["texts"]["atendimento_humano"] == "Vou chamar um atendente agora."
    # Untouched keys survive the patch.
    assert out["appointment_policy"]["texts"]["encaminhamento_duvida_persistente"] == (
        "Já chamei a Equipe Aurora para continuar com você. Se puder, me diga "
        "seu nome, o serviço que procura e o modelo do carro enquanto aguarda."
    )
    assert captured["kwargs"]["persona_slug"] == "aurora"
    assert captured["kwargs"]["expected_version"] == 2


def test_update_persona_appointment_policy_rejects_empty_body(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_capability", lambda *a, **k: None)

    body = graph.AppointmentPolicyTextsBody()
    with pytest.raises(HTTPException) as exc_info:
        graph.update_persona_appointment_policy("aurora", body, _req())
    assert exc_info.value.status_code == 400


def test_get_persona_appointment_policy_returns_current_texts(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_access", lambda *a, **k: None)

    aurora_graph = _aurora_graph()
    monkeypatch.setattr(
        graph.graph_json_v2_store, "load_current", lambda slug: (2, aurora_graph)
    )

    out = graph.get_persona_appointment_policy("aurora", _req())

    assert out["ok"] is True
    # Every published text ends in a question: the briefing makes "sempre
    # terminar mensagens com uma pergunta" a mandatory conduct rule.
    assert out["texts"]["atendimento_humano"] == (
        "Vou encaminhar sua conversa para a Equipe Aurora. "
        "Posso adiantar alguma informação para eles?"
    )
    assert set(out["texts"].keys()) == {
        "atendimento_humano", "encaminhamento_excepcional", "esclarecimento_duvida",
        "encaminhamento_duvida_persistente", "complemento_confirmacao", "cabecalho_servicos",
        "saudacao_abertura", "sem_comparar_concorrentes",
        "mensagem_ausencia", "preco_humano", "avaliacao_presencial", "lacuna_conhecimento",
    }


def test_update_persona_appointment_policy_404s_when_graph_missing(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_capability", lambda *a, **k: None)
    monkeypatch.setattr(graph.graph_json_v2_store, "load_current", lambda slug: None)

    body = graph.AppointmentPolicyTextsBody(atendimento_humano="Oi")
    with pytest.raises(HTTPException) as exc_info:
        graph.update_persona_appointment_policy("aurora", body, _req())
    assert exc_info.value.status_code == 404
