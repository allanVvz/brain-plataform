"""O cliente responde o nome e a conversa anda -- em qualquer caixa.

Regressao do travamento observado ao vivo em 2026-08-19. O cliente digitou
"allan rodrigues", o modelo devolveu "Allan Rodrigues" com confianca alta, e
uma comparacao literal entre os dois transformou um acerto em
`needs_confirmation`. A confirmacao so aceitava um punhado de frases
literais, entao repetir o proprio nome nao resolvia nada e o mesmo template
voltava turno apos turno -- ate a supressao de repeticao reduzir a resposta a
"Entendi." isolado.

Os testes daqui dirigem `decide()` inteiro, do modelo ao ledger, porque a
falha nao estava em nenhuma funcao sozinha: estava na sequencia.
"""
from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import ConversationContext
from services import graph_agent_runtime_v3, graph_compiler_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000009", "slug": "generic"}
NAME_QUESTION = "Antes de tudo, qual e o seu nome e sobrenome?"
SERVICE_QUESTION = "Qual servico te interessa?"


def node(index: int, stable_id: str, *, node_type: str = "knowledge", data=None):
    return {
        "id": f"20000000-0000-0000-0000-{index:012d}",
        "node_type": node_type,
        "slug": stable_id.replace(":", "-"),
        "title": stable_id,
        "summary": stable_id,
        "tags": [],
        "status": "validated",
        "metadata": {"graph_json_node_id": stable_id, **(data or {})},
    }


def edge(index: int, source: dict, target: dict, relation="contains"):
    return {
        "id": f"30000000-0000-0000-0000-{index:012d}",
        "source_node_id": source["id"],
        "target_node_id": target["id"],
        "relation_type": relation,
        "weight": 1,
        "metadata": {"active": True, "graph_json_edge_id": f"edge:{index}"},
    }


def _fixture(monkeypatch, *, confirmation_policy="last_resort"):
    """Uma persona generica com nome semantico e um catalogo de dois servicos."""
    root = node(1, "persona:generic", node_type="persona", data={
        "conversation_policy": {
            "question_repetition": {"max_attempts": 1},
            "doubt_handling": {
                "answer_before_qualification": "Respondo primeiro.",
                "continue_with_first_missing_field": "Sigo com o campo pendente.",
                "deferred_response": "A equipe explica esse detalhe publicado.",
            },
            "qualification": {
                "summary_template": "Resumo: {informed_fields}.",
                "confirmation_question": "Esta tudo certo?",
                "completion_message": "A equipe continua.",
                "incomplete_handoff_template": (
                    "Confirmado: {informed_fields}. Nao confirmado: {missing_fields}."
                ),
            },
        },
        "appointment_policy": {
            "required_fields": ["nome", "servico"],
            "field_labels": {"nome": "nome", "servico": "servico"},
            "confirmation_templates": {
                "name": [
                    "Entendi. {candidate} e o seu nome completo?",
                    "So pra eu anotar certo: e {candidate} mesmo?",
                ],
                "fact": "Entendi {candidate}. Esta correto?",
                "service_selection": "Quer seguir com {candidate}?",
                "service_addition": "Quer adicionar {candidate}?",
                "service_switch": "Quer trocar para {candidate}?",
                "service_removal": "Quer remover {candidate}?",
            },
        },
    })
    ppf = node(2, "branch:ppf", data={"capabilities": {"branch_anchor": True}})
    ppf["title"] = "PPF"
    polimento = node(3, "branch:polimento", data={
        "capabilities": {"branch_anchor": True},
    })
    polimento["title"] = "Polimento"
    q_nome = node(4, "q:nome", node_type="faq", data={
        "question": NAME_QUESTION,
        "paraphrases": ["Me diz seu nome completo, por favor."],
    })
    q_servico = node(5, "q:servico", node_type="faq", data={
        "question": SERVICE_QUESTION,
        "paraphrases": ["O que voce quer melhorar no carro?"],
    })
    name_field = {
        "key": "nome",
        "question_node_id": "q:nome",
        "required": True,
        "accepted_statuses": ["known"],
        "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": "persona:generic",
        "scope": "persona",
        "priority": 1.0,
        "validation": {
            "mode": "semantic",
            "semantic_type": "human_full_name",
            "description": "Nome e sobrenome completos informados pelo cliente.",
            "examples": ["Beatriz Souza"],
            "model_confidence_min": 0.90,
            "min_tokens": 2,
            "max_tokens": 6,
            "confirmation_policy": confirmation_policy,
            "invalid_response": "Nao consegui ler esse nome com seguranca.",
        },
    }
    for anchor in (ppf, polimento):
        anchor["metadata"]["qualification"] = {"fields": [
            dict(name_field),
            {
                "key": "servico",
                "question_node_id": "q:servico",
                "required": True,
                "accepted_statuses": ["known", "needs_confirmation"],
                "value_schema": {"type": "string", "minLength": 1},
                "owner_node_id": anchor["metadata"]["graph_json_node_id"],
                "scope": "branch",
                "priority": 0.7,
                "validation": {
                    "mode": "semantic",
                    "description": "Servico publicado escolhido pelo cliente.",
                    "examples": ["PPF"],
                    "invalid_response": "Nao entendi qual servico voce quis dizer.",
                },
            },
        ]}
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[root, ppf, polimento, q_nome, q_servico],
        edge_rows=[
            edge(1, root, ppf), edge(2, root, polimento),
            edge(3, root, q_nome), edge(4, root, q_servico),
        ],
    )
    pub = {
        "id": "40000000-0000-0000-0000-000000000009",
        "version": 1,
        "checksum": document["checksum"],
        "status": "active",
        "document_json": document,
    }
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_persona",
        lambda _slug: {**PERSONA, "config": {}},
    )
    monkeypatch.setattr(
        graph_agent_runtime_v3.supabase_client, "get_active_graph_publication",
        lambda _persona_id: pub,
    )
    return document, pub


def _context(document, pub, message, *, asked=("q:nome",), facts_by_key=None,
             history=(), message_id="msg:1"):
    return ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[
            *history,
            {"message_id": message_id, "role": "user", "content": message},
        ],
        cart={
            "facts": {},
            "facts_by_key": facts_by_key or {},
            "asked_question_node_ids": list(asked),
        },
        rag_nodes=[], rag_paths=[],
        graph_contract=document["common_contract"],
        active_branch_node_id=None, active_branch_node_ids=[],
        journey_id="50000000-0000-0000-0000-000000000009",
        retrieval_trace={},
    )


def _name_proposal(
    value, evidence, *, confidence=0.95,
    reply=f"Entendi. {SERVICE_QUESTION}",
):
    return {
        "branch_action": "none",
        "branch_anchor_node_id": None,
        "branch_path_checksum": None,
        "branch_evidence_span": "",
        "extracted_facts": [{
            "field_key": "nome", "owner_node_id": "persona:generic",
            "status": "known", "value": value, "source_message_id": "msg:1",
            "evidence_span": evidence, "confidence": confidence,
        }],
        "claims": [],
        "next_question_node_id": "q:servico",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": reply,
        "qualification_complete": False, "handoff_requested": False,
    }


def _decide(context, proposal):
    return graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": proposal},
    )


def test_nome_em_minusculas_e_aceito_e_a_conversa_segue_para_o_servico(monkeypatch):
    document, pub = _fixture(monkeypatch)
    context = _context(document, pub, "allan rodrigues")

    _decision, response = _decide(
        context, _name_proposal("Allan Rodrigues", "allan rodrigues"),
    )

    fact = next(
        item for item in response.proof["accepted_facts"]
        if item["field_key"] == "nome"
    )
    assert fact["status"] == "known"
    assert fact["value"] == "Allan Rodrigues"
    # O recorte guardado e o do cliente, nao o do modelo.
    assert fact["evidence_span"] == "allan rodrigues"
    # E o turno pergunta o proximo campo, nao repete o nome.
    assert response.proof["next_question_node_id"] == "q:servico"
    assert SERVICE_QUESTION in (response.reply_text or "")


def test_nome_com_caixa_alta_do_cliente_tambem_e_aceito(monkeypatch):
    document, pub = _fixture(monkeypatch)
    context = _context(document, pub, "Allan Rodrigues")

    _decision, response = _decide(
        context, _name_proposal("Allan Rodrigues", "Allan Rodrigues"),
    )

    fact = next(
        item for item in response.proof["accepted_facts"]
        if item["field_key"] == "nome"
    )
    assert fact["status"] == "known"
    assert response.proof["next_question_node_id"] == "q:servico"


def test_repetir_o_candidato_pendente_confirma_e_avanca(monkeypatch):
    document, pub = _fixture(monkeypatch)
    pending = {
        "field_key": "nome", "owner_node_id": "persona:generic",
        "status": "needs_confirmation", "value": None,
        "evidence_span": "allan rodrigues", "confidence": 0.5,
        "metadata": {"confirmation": {
            "kind": "name", "capability": "common_fact", "template_key": "name",
            "candidate": "Allan Rodrigues", "field_key": "nome",
            "owner_node_id": "persona:generic",
        }},
    }
    context = _context(
        document, pub, "allan rodrigues",
        facts_by_key={"nome": [pending]},
        history=[{
            "message_id": "msg:0", "role": "assistant",
            "content": "Entendi. Allan Rodrigues e o seu nome completo?",
        }],
        message_id="msg:2",
    ).model_copy(update={"pending_confirmation_ref": "fact:nome:persona:generic"})

    # Repeating the pending candidate value used to confirm it on its own
    # (`_restates_pending_candidate`, now dead code). Confirmation now comes
    # from the model's semantic reading of the same message, so the customer
    # restating "allan rodrigues" must surface as an explicit confirmation
    # intent bound to the pending fact's ref.
    _decision, response = graph_agent_runtime_v3.decide(
        context, model_observation={
            "interpretation": {
                "intents": [{"kind": "confirmation", "evidence_span": "allan rodrigues"}],
                "state_relation": "continue",
                "confirmation": {
                    "state": "affirm",
                    "target_ref": "fact:nome:persona:generic",
                    "evidence_span": "allan rodrigues",
                },
            },
        },
    )

    assert response.proof["mode"] == "deterministic_field_confirmation"
    fact = next(
        item for item in response.proof["accepted_facts"]
        if item["field_key"] == "nome"
    )
    assert fact["status"] == "known"
    assert fact["value"] == "Allan Rodrigues"


def test_saudacao_livre_descarta_pergunta_ainda_nao_perguntavel(monkeypatch):
    document, pub = _fixture(monkeypatch)
    reply = (
        "Oi! Que bom falar com voce. "
        "O que voce esta buscando para o seu carro?"
    )
    proposal = {
        "branch_action": "none",
        "branch_anchor_node_id": None,
        "branch_path_checksum": None,
        "branch_evidence_span": "",
        "extracted_facts": [],
        "claims": [],
        "next_question_node_id": "q:servico",
        "cited_node_ids": [], "cited_chunk_ids": [],
        "reply": reply,
        "qualification_complete": False, "handoff_requested": False,
    }
    context = _context(
        document, pub, "ooii", asked=(),
        message_id="msg:3",
    )

    _decision, response = _decide(context, proposal)

    assert response.proof["valid"], response.proof["errors"]
    assert response.reply_text == "Oi! Que bom falar com voce."
    assert response.proof["next_question_node_id"] is None
    assert response.proof["question_component_discarded"] is True


def test_nome_invalido_nao_vira_fato_e_o_turno_continua_util(monkeypatch):
    document, pub = _fixture(monkeypatch)
    context = _context(document, pub, "sou da oficina ali da esquina")

    _decision, response = _decide(
        context, _name_proposal("oficina", "oficina", confidence=0.99),
    )

    assert not [
        item for item in response.proof["accepted_facts"]
        if item["field_key"] == "nome"
    ]
    assert any(
        entry.get("errors") == ["human_full_name_invalid"]
        for entry in response.proof.get("field_validation") or []
    )
    assert (response.reply_text or "").strip()
