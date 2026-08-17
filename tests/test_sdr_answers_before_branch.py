"""O cliente pergunta para escolher -- responder nao pode exigir ter escolhido.

Regressao do travamento de producao da Aurora (lead 12, 2026-08-17, ledger
2c66b7fa). "como funciona o ppf?" e "como e a lavagem?" nao receberam resposta
nenhuma: o modelo escreveu a resposta certa, citando uma FAQ publicada e
recuperada, e o runtime descartou a proposta inteira com

    ["keep_without_active_branch",
     "claim_not_authorized:service_detail",
     "claim_evidence_not_authorized:service_detail"]

caindo em `published_fallback` -- que repetia palavra por palavra a pergunta ja
enviada e por isso era suprimida pelo antirrepeticao, deixando o turno mudo.

A diferenca para `test_sdr_doubt_not_discarded.py` esta na forma do grafo, e e
ela que importa: la a FAQ pendura em `global_context`, entao ela vive em TODOS
os contratos de galho e o contrato comum ja a autorizava. No grafo real da
Aurora a FAQ de um servico pendura no proprio servico -- 1 dos 17 galhos --, e o
contrato comum publicava `claims: []`. Era preciso ja ter escolhido o PPF para
poder perguntar o que e PPF.
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
ANSWER = "O PPF e uma pelicula de protecao aplicada sobre a pintura."
PRICE_ANSWER = "O PPF custa R$ 4.000."


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
    """A forma real da Aurora: a FAQ do servico pendura no servico."""
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
    # A FAQ factual e a de preco pendurando no galho do PPF -- nenhuma delas
    # existe no contrato comum, exatamente como na Aurora publicada.
    faq_ppf = node(5, "faq:ppf-how", parent_type="faq", data={
        "question": "Como funciona o PPF?",
        "answer": ANSWER,
        "claims": [{
            "claim_type": "service_detail", "policy": {"mode": "informational"},
            "evidence_node_ids": ["faq:ppf-how"],
        }],
    })
    faq_preco = node(6, "faq:ppf-price", parent_type="faq", data={
        "question": "Quanto custa o PPF?",
        "answer": PRICE_ANSWER,
        "claims": [{
            "claim_type": "price", "policy": {"mode": "informational"},
            "evidence_node_ids": ["faq:ppf-price"],
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
        node_rows=[root, ppf, vitrificacao, q_servico, faq_ppf, faq_preco],
        edge_rows=[
            edge(1, root, ppf), edge(2, root, vitrificacao),
            edge(3, root, q_servico),
            edge(4, ppf, faq_ppf), edge(5, ppf, faq_preco),
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


def _context(document, pub, *, faq_node_id="faq:ppf-how", answer=ANSWER, asked=()):
    """O turno como producao o registrou: pergunta informativa, sem galho ativo."""
    message = "Como funciona o PPF?"
    return ConversationContext(
        persona_slug="generic", agent_slug="agent", graph_version=1,
        graph_checksum=document["checksum"], publication_id=pub["id"],
        messages=[{"message_id": "msg:1", "role": "user", "content": message}],
        cart={"facts": {}, "facts_by_key": {}, "asked_question_node_ids": list(asked)},
        rag_nodes=[], rag_paths=[], graph_contract=document["common_contract"],
        context_cards=[ContextCard(
            id=faq_node_id, node_type="faq", slug=faq_node_id.replace(":", "-"),
            title="FAQ", rendered_content=answer,
            content_checksum="sha256:card", revision=1, graph_version=1,
            graph_checksum=document["checksum"],
            context_role="doubt_answer", position=0,
        )],
        rag_chunks=[{"chunk_id": "chunk:faq", "source_node_id": faq_node_id}],
        active_branch_node_id=None, active_branch_node_ids=[],
        retrieval_trace={
            "selected_faq_node_id": faq_node_id,
            "selected_faq_chunk_id": "chunk:faq",
            "faq_selection_method": "semantic_margin",
            "interrogative_clause": message,
            # O resolvedor classificou como mencao informativa: reconhece o
            # servico, mas nao o ativa. E o que producao registrou.
            "branch_candidates": [{
                "score": 1, "branch_anchor_node_id": "branch:ppf",
                "snippet": "ppf",
            }],
        },
    )


def _proposal(document, *, claim_type="service_detail",
              faq_node_id="faq:ppf-how", reply=ANSWER):
    """O rascunho real: galho certo, FAQ certa, e `keep` com span vazio.

    O SYSTEM_PROMPT diz que `service_operations` nunca autoriza mutacao, entao o
    modelo deixa a evidencia de servico fora da proposta. `keep` e o unico verbo
    disponivel para "estou falando disto sem selecionar".
    """
    contract = document["branch_contracts"]["branch:ppf"]
    return {
        "branch_action": "keep", "branch_anchor_node_id": "branch:ppf",
        "branch_path_checksum": contract["branch_path_checksum"],
        "branch_evidence_span": "",
        "extracted_facts": [],
        "service_operations": [],
        "claims": [{
            "claim_type": claim_type,
            "value": {"text": reply},
            "evidence_node_ids": [faq_node_id],
            "evidence_chunk_ids": ["chunk:faq"],
        }],
        "next_question_node_id": "q:servico",
        "cited_node_ids": [faq_node_id], "cited_chunk_ids": ["chunk:faq"],
        "reply": reply,
        "qualification_complete": False, "handoff_requested": False,
    }


def test_a_faq_do_servico_e_respondida_antes_de_o_cliente_escolher(monkeypatch):
    """O caso exato da lead 12: a resposta do modelo tem de sobreviver."""
    document, pub = _fixture(monkeypatch)

    _decision, response = graph_agent_runtime_v3.decide(
        _context(document, pub),
        model_observation={"proposal": _proposal(document)},
    )

    assert response.proof.get("mode") != "published_fallback", (
        response.proof.get("model_proposal_errors")
    )
    assert "pelicula" in (response.reply_text or ""), response.reply_text
    assert response.proof["repetition_action"] != "suppressed_duplicate_outbound"


def test_a_claim_do_galho_de_recuperacao_e_autorizada_na_descoberta(monkeypatch):
    """A causa-raiz, isolada: `claims: []` no contrato de pre-selecao."""
    document, _pub = _fixture(monkeypatch)

    contract = graph_agent_runtime_v3._preselection_contract(document, "branch:ppf")
    tipos = {str(claim.get("claim_type") or "") for claim in contract["claims"]}

    assert "service_detail" in tipos, contract["claims"]


def test_perguntar_sobre_um_servico_nao_ativa_o_galho(monkeypatch):
    """A invariante que a correcao nao pode atropelar.

    Mencao informativa reconhece o servico e oferece confirmacao -- nunca
    seleciona sozinha. Trocar o verbo para "select" aqui reintroduziria o bug
    que `keep_without_active_branch` existe para impedir.
    """
    document, pub = _fixture(monkeypatch)

    _decision, response = graph_agent_runtime_v3.decide(
        _context(document, pub),
        model_observation={"proposal": _proposal(document)},
    )

    assert response.cart_state["active_branch_node_ids"] == []
    assert response.cart_state.get("active_branch_node_id") is None


def test_preco_de_um_unico_galho_continua_exigindo_a_escolha(monkeypatch):
    """O limite da mudanca: explicar e liberado, precificar nao."""
    document, pub = _fixture(monkeypatch)

    contract = graph_agent_runtime_v3._preselection_contract(document, "branch:ppf")
    tipos = {str(claim.get("claim_type") or "") for claim in contract["claims"]}
    assert "price" not in tipos, contract["claims"]

    _decision, response = graph_agent_runtime_v3.decide(
        _context(document, pub, faq_node_id="faq:ppf-price", answer=PRICE_ANSWER),
        model_observation={"proposal": _proposal(
            document, claim_type="price",
            faq_node_id="faq:ppf-price", reply=PRICE_ANSWER,
        )},
    )

    assert "claim_not_authorized:price" in (
        response.proof.get("model_proposal_errors")
        or response.proof.get("errors") or []
    ), response.proof
