"""O campo de selecao de galho precisa aceitar `needs_confirmation`.

Regressao do travamento observado em producao (Aurora, lead 9, 2026-08-17):

O runtime so promove o servico a `known` com evidencia exata; uma resolucao
aproximada grava `needs_confirmation` ate o cliente confirmar. A publicacao
ativa autorizava apenas `["known"]` para esse campo, entao o fato ficava num
limbo que travava a conversa inteira:

- nao e `known`  -> nenhum galho ativo -> toda proposta do modelo com
  `branch_action: "keep"` era rejeitada (`keep_without_active_branch`), e sem
  galho a claim `service_detail` tambem nao era autorizada. O modelo tentava
  explicar o servico e era descartado, caindo no fallback legado;
- nao esta faltando -> `missing_fields` vazio -> a qualificacao parecia
  completa e o agente emitia o resumo com um unico campo.

`nome_cliente` ja recebia esse tratamento por `semantic_type=human_full_name`.
O campo de servico nao recebia nenhum.
"""
from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_compiler_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000001", "slug": "aurora"}


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


def _campo(key: str, question: str, owner: str, scope: str | None = None):
    campo = {
        "key": key, "question_node_id": question, "required": True,
        "accepted_statuses": ["known"],
        "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": owner,
    }
    # Dono por galho so e aceito com escopo local declarado -- e assim que o
    # grafo vivo da Aurora declara o `servico`.
    if scope:
        campo["scope"] = scope
    return campo


def _grafo_aurora():
    """Duas ofertas, cada uma dona do proprio `servico`; nome e da persona."""
    root = node(1, "persona:aurora", parent_type="persona", data={
        "appointment_policy": {"required_fields": ["nome_cliente", "servico"]},
    })
    ppf = node(2, "product:ppf", parent_type="product",
               data={"capabilities": {"branch_anchor": True}})
    chapeacao = node(3, "product:chapeacao", parent_type="product",
                     data={"capabilities": {"branch_anchor": True}})
    q_nome = node(4, "question:nome", parent_type="faq",
                  data={"question": "Qual e o seu nome e sobrenome?"})
    q_servico = node(5, "question:servico", parent_type="faq",
                     data={"question": "Qual servico te interessa?"})

    for galho in (ppf, chapeacao):
        galho["metadata"]["qualification"] = {"fields": [
            _campo("nome_cliente", "question:nome", "persona:aurora"),
            # dono e o proprio galho: e isso que faz dele o campo seletor
            _campo("servico", "question:servico",
                   galho["metadata"]["graph_json_node_id"], scope="branch"),
        ]}

    rows = [root, ppf, chapeacao, q_nome, q_servico]
    edges = [
        edge(1, root, ppf), edge(2, root, chapeacao),
        edge(3, root, q_nome), edge(4, root, q_servico),
    ]
    return graph_compiler_v3.compile_graph(
        persona=PERSONA, node_rows=rows, edge_rows=edges,
    )


def _campo_por_chave(fields, key):
    return next((f for f in fields if str(f.get("key") or "") == key), None)


def test_campo_seletor_e_identificado_sem_hardcode_de_nome():
    """Nenhum nome de campo entra no codigo: o seletor e o unico que todo
    galho declara e que pertence ao proprio galho."""
    documento = _grafo_aurora()
    contratos = documento["branch_contracts"]
    assert graph_compiler_v3.branch_selection_field_key(
        contratos, next(n for n in documento["nodes"] if n["node_type"] == "persona"),
    ) == "servico"


def test_contrato_de_galho_aceita_confirmacao_pendente_do_servico():
    """O fato de servico e escrito com o galho como dono -- e o contrato de
    galho que valida o status."""
    documento = _grafo_aurora()
    for anchor, contrato in documento["branch_contracts"].items():
        servico = _campo_por_chave(contrato["fields"], "servico")
        assert servico is not None, anchor
        assert "needs_confirmation" in servico["accepted_statuses"], (
            f"{anchor}: {servico['accepted_statuses']}"
        )
        assert "known" in servico["accepted_statuses"]


def test_contrato_comum_aceita_confirmacao_pendente_do_servico():
    """Antes de escolher o galho, quem valida e o `common_contract` -- foi por
    ele que o fato travado da producao passou."""
    servico = _campo_por_chave(
        _grafo_aurora()["common_contract"]["fields"], "servico",
    )
    assert servico is not None
    assert servico.get("branch_selection_field") is True
    assert "needs_confirmation" in servico["accepted_statuses"]


def test_campo_comum_que_nao_seleciona_galho_nao_ganha_o_status():
    """`needs_confirmation` no servico e sobre resolucao aproximada de
    catalogo. Um campo qualquer da persona nao herda isso -- quem precisa dele
    declara `semantic_type` proprio."""
    nome = _campo_por_chave(_grafo_aurora()["common_contract"]["fields"], "nome_cliente")
    assert nome is not None
    assert nome["accepted_statuses"] == ["known"]


def _grafo_com_galho_de_suporte():
    """A forma real da Aurora: 15 servicos de catalogo declaram `servico`,
    `atendimento-humano` e `reclamacao` nao -- eles nao sao escolhidos dizendo
    um nome de servico."""
    root = node(1, "persona:aurora", parent_type="persona", data={
        "appointment_policy": {"required_fields": ["nome_cliente", "servico"]},
    })
    ppf = node(2, "product:ppf", parent_type="product",
               data={"capabilities": {"branch_anchor": True}})
    chapeacao = node(3, "product:chapeacao", parent_type="product",
                     data={"capabilities": {"branch_anchor": True}})
    suporte = node(6, "service:atendimento-humano", parent_type="service",
                   data={"capabilities": {"branch_anchor": True}})
    q_nome = node(4, "question:nome", parent_type="faq",
                  data={"question": "Qual e o seu nome e sobrenome?"})
    q_servico = node(5, "question:servico", parent_type="faq",
                     data={"question": "Qual servico te interessa?"})

    for galho in (ppf, chapeacao):
        galho["metadata"]["qualification"] = {"fields": [
            _campo("nome_cliente", "question:nome", "persona:aurora"),
            _campo("servico", "question:servico",
                   galho["metadata"]["graph_json_node_id"], scope="branch"),
        ]}
    # o galho de suporte so pede o nome
    suporte["metadata"]["qualification"] = {"fields": [
        _campo("nome_cliente", "question:nome", "persona:aurora"),
    ]}

    rows = [root, ppf, chapeacao, suporte, q_nome, q_servico]
    edges = [
        edge(1, root, ppf), edge(2, root, chapeacao), edge(5, root, suporte),
        edge(3, root, q_nome), edge(4, root, q_servico),
    ]
    return graph_compiler_v3.compile_graph(
        persona=PERSONA, node_rows=rows, edge_rows=edges,
    )


def test_galho_de_suporte_sem_servico_nao_apaga_o_seletor():
    """Exigir que TODOS os galhos declarem o campo fazia o seletor sumir na
    Aurora real (15 de 17 declaram) -- e com ele sumia o campo de servico do
    contrato comum, deixando a qualificacao "completa" so com o nome."""
    documento = _grafo_com_galho_de_suporte()
    comum = documento["common_contract"]
    servico = _campo_por_chave(comum["fields"], "servico")
    assert servico is not None, [f.get("key") for f in comum["fields"]]
    assert servico.get("branch_selection_field") is True
    assert "needs_confirmation" in servico["accepted_statuses"]
    assert "servico" in comum["required_fields"]


def test_galho_de_suporte_nao_recebe_campo_de_servico():
    """Quem nao declara o servico continua sem ele -- o contrato de cada galho
    seve so o que aquele galho pede."""
    documento = _grafo_com_galho_de_suporte()
    suporte = next(
        contrato for anchor, contrato in documento["branch_contracts"].items()
        if "atendimento" in anchor
    )
    assert _campo_por_chave(suporte["fields"], "servico") is None
