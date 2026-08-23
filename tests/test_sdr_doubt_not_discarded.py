"""O turno produz a resposta certa -- e o runtime nao pode joga-la fora.

Regressao do travamento observado em producao (Aurora, lead 10, 2026-08-17).
O cliente comprou do jeito que as pessoas compram: perguntando. "Como funciona
o ppf?" nomeia um servico dentro de uma pergunta, e o contrato -- corretamente
-- nao deixa uma mencao informativa ativar galho. O que estava errado era o que
vinha depois:

- a copy de confirmacao de servico sobrescrevia `reply` inteiro, levando junto
  a resposta do FAQ que o turno ja tinha resolvido;
- cada pergunta dessas gastava o orcamento de repeticao, entao duas duvidas
  legitimas marcavam `servico` como `unknown/ignored_twice` e disparavam
  handoff incompleto;
- quando a copy repetia algo recente, a protecao antirrepeticao zerava o
  outbound e o cliente ficava em silencio absoluto.
"""
from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import ContextCard, ConversationContext
from services import graph_agent_runtime_v3, graph_compiler_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000001", "slug": "generic"}
ANSWER = "O PPF e uma pelicula aplicada sobre a pintura."


def node(index: int, stable_id: str, *, parent_type: str = "knowledge", data=None):
    return {
        "id": f"20000000-0000-0000-0000-{index:012d}",
        "node_type": parent_type,
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


def _fixture(monkeypatch):
    """A forma da Aurora: dois servicos de catalogo e um FAQ factual do PPF."""
    root = node(1, "persona:generic", parent_type="persona", data={
        "conversation_policy": {
            "question_repetition": {"max_attempts": 1},
            "doubt_handling": {
                "answer_before_qualification": "Respondo primeiro.",
                "continue_with_first_missing_field": "Seguimos com o campo pendente.",
                "deferred_response": "A equipe explica esse detalhe publicado.",
            },
            "qualification": {
                "summary_template": "Resumo: {informed_fields}.",
                "completion_message": "A equipe continua.",
                "incomplete_handoff_template": (
                    "Confirmado: {informed_fields}. Nao confirmado: {missing_fields}."
                ),
            },
        },
        "appointment_policy": {
            "required_fields": ["servico"],
            "field_labels": {"servico": "servico"},
            "confirmation_templates": {
                "service_selection": "Quer seguir com {candidate}?",
                "service_addition": "Quer adicionar {candidate}?",
                "service_switch": "Quer trocar para {candidate}?",
                "service_removal": "Quer remover {candidate}?",
                "name": "Confirma {candidate}?",
            },
        },
    })
    ppf = node(2, "branch:ppf", data={"capabilities": {"branch_anchor": True}})
    ppf["title"] = "PPF"
    vitrificacao = node(3, "branch:vitrificacao", data={
        "capabilities": {"branch_anchor": True},
    })
    vitrificacao["title"] = "Vitrificacao"
    q_servico = node(4, "q:servico", parent_type="faq", data={
        "question": "Qual servico te interessa?",
    })
    global_root = node(5, "context:global", data={
        "capabilities": {"global_context": True},
    })
    faq_ppf = node(6, "faq:ppf-how", parent_type="faq", data={
        "question": "Como funciona o PPF?",
        "answer": ANSWER,
        "claims": [{
            "claim_type": "other", "policy": {"mode": "informational"},
            "evidence_node_ids": ["faq:ppf-how"],
        }],
    })
    for anchor in (ppf, vitrificacao):
        anchor["metadata"]["qualification"] = {"fields": [{
            "key": "servico", "question_node_id": "q:servico", "required": True,
            "accepted_statuses": ["known", "needs_confirmation"],
            "value_schema": {"type": "string", "minLength": 1},
            "owner_node_id": anchor["metadata"]["graph_json_node_id"],
            "scope": "branch",
        }]}
    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[root, ppf, vitrificacao, q_servico, global_root, faq_ppf],
        edge_rows=[
            edge(1, root, ppf), edge(2, root, vitrificacao),
            edge(3, root, q_servico), edge(4, root, global_root),
            edge(5, global_root, faq_ppf),
        ],
    )
    pub = {
        "id": "40000000-0000-0000-0000-000000000001",
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


def _context(document, pub, *, message_id, asked, history=()):
    message = "Como funciona o PPF?"
    return ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[
            *history,
            {"message_id": message_id, "role": "user", "content": message},
        ],
        cart={"facts": {}, "facts_by_key": {}, "asked_question_node_ids": asked},
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        # A FAQ global foi recuperada -- e o que autoriza a evidencia.
        context_cards=[ContextCard(
            id="faq:ppf-how", node_type="faq", slug="faq-ppf-how",
            title="Como funciona o PPF?", rendered_content=ANSWER,
            content_checksum="sha256:card", revision=1, graph_version=1,
            graph_checksum=document["checksum"],
            context_role="doubt_answer", position=0,
        )],
        rag_chunks=[{"chunk_id": "chunk:ppf-how", "source_node_id": "faq:ppf-how"}],
        active_branch_node_id=None, active_branch_node_ids=[],
        retrieval_trace={
            "selected_faq_node_id": "faq:ppf-how",
            "selected_faq_chunk_id": "chunk:ppf-how",
            "faq_selection_method": "exact_normalized",
            "interrogative_clause": message,
        },
    )


def _proposal(document):
    """O que o modelo realmente propoe: responde a duvida citando a FAQ.

    `branch_action=keep` sem galho ativo e o que a producao registrou -- nao ha
    acao "nenhuma" no enum, e o cliente ainda nao escolheu nada.
    """
    contract = document["branch_contracts"]["branch:ppf"]
    return {
        "branch_action": "keep", "branch_anchor_node_id": "branch:ppf",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "",
        "extracted_facts": [],
        "claims": [{
            "claim_type": "other",
            "evidence_node_ids": ["faq:ppf-how"],
            "evidence_chunk_ids": [],
        }],
        "next_question_node_id": "q:servico",
        "cited_node_ids": ["faq:ppf-how"], "cited_chunk_ids": [],
        "reply": ANSWER,
        "qualification_complete": False, "handoff_requested": False,
    }


def _decide(document, context):
    return graph_agent_runtime_v3.decide(
        context, model_observation={"proposal": _proposal(document)},
    )


def test_confirmacao_de_servico_nao_engole_a_resposta_da_duvida(monkeypatch):
    """`reply = confirmation_text` levava junto a explicacao do servico."""
    document, pub = _fixture(monkeypatch)
    _decision, response = _decide(
        document, _context(document, pub, message_id="msg:1", asked=["q:servico"]),
    )

    reply = response.reply_text or ""
    assert "pelicula" in reply, reply
    # E o contrato continua valendo: mencao informativa nao ativa galho.
    assert response.cart_state["active_branch_node_ids"] == []


def test_duvida_respondida_nao_gasta_o_orcamento_de_pergunta(monkeypatch):
    """Perguntar sobre o catalogo e como o cliente compra, nao uma recusa."""
    document, pub = _fixture(monkeypatch)
    decision, response = _decide(document, _context(
        document, pub, message_id="msg:2",
        asked=["q:servico", "q:servico"],
        history=[{"role": "assistant", "content": "Qual servico te interessa?"}],
    ))

    desistencias = [
        fact for fact in response.proof["accepted_facts"]
        if fact.get("reason") == "ignored_twice"
    ]
    assert desistencias == [], desistencias
    assert decision.route.value != "HUMAN"


def test_supressao_de_duplicata_ainda_entrega_o_conteudo_novo(monkeypatch):
    """Reter a pergunta repetida nao pode reter o turno inteiro."""
    document, pub = _fixture(monkeypatch)
    _decision, response = _decide(document, _context(
        document, pub, message_id="msg:3",
        asked=["q:servico", "q:servico"],
        history=[
            {"role": "assistant", "content": "Qual servico te interessa?"},
            {"role": "assistant", "content": "Qual servico te interessa?"},
        ],
    ))

    assert response.reply_text, "o cliente nao pode ficar sem resposta"


def test_pergunta_suprimida_nao_conta_como_feita(monkeypatch):
    """O orcamento conta entregas, nao intencoes."""
    document, pub = _fixture(monkeypatch)
    _decision, response = _decide(document, _context(
        document, pub, message_id="msg:4",
        asked=["q:servico", "q:servico"],
        history=[
            {"role": "assistant", "content": "Qual servico te interessa?"},
            {"role": "assistant", "content": "Qual servico te interessa?"},
        ],
    ))

    asked = response.cart_state["asked_question_node_ids"]
    assert asked.count("q:servico") == 2, asked


def test_o_contrato_comum_nunca_autoriza_mais_que_um_galho(monkeypatch):
    """A invariante de seguranca desta mudanca.

    O contrato comum vale antes de o cliente escolher qualquer servico, entao
    ele so pode conter claims que TODOS os galhos ja autorizavam. Nada e
    autorizado a mais -- a autoridade so passa a valer mais cedo. Preco ou
    regra declarados por um unico servico continuam exigindo aquele galho.
    """
    document, _pub = _fixture(monkeypatch)
    comuns = {
        graph_compiler_v3.canonical_checksum(claim)
        for claim in document["common_contract"].get("claims") or []
    }
    assert comuns, "sem claims comuns o agente nao responde nada na descoberta"
    for anchor, contract in document["branch_contracts"].items():
        do_galho = {
            graph_compiler_v3.canonical_checksum(claim)
            for claim in contract.get("claims") or []
        }
        assert comuns <= do_galho, anchor
