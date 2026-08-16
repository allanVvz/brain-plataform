"""Tests for cross-branch field consistency checking in graph_compiler_v3.

Regression test for 2026-08-10 bug (sdr_reclamacao_recorrente v44): agent
forgot customer name when returning after agendamento to file reclamação,
because nome_cliente diverged in owner_node_id between branches.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_compiler_v3


PERSONA = {"id": "10000000-0000-0000-0000-000000000001", "slug": "aurora"}


def node(index: int, stable_id: str, *, parent_type: str = "knowledge", data=None, status="validated"):
    return {
        "id": f"20000000-0000-0000-0000-{index:012d}",
        "node_type": parent_type,
        "slug": stable_id.replace(":", "-"),
        "title": stable_id,
        "summary": stable_id,
        "tags": [],
        "status": status,
        "metadata": {"graph_json_node_id": stable_id, **(data or {})},
    }


def edge(index: int, source: dict, target: dict, relation="contains", data=None):
    return {
        "id": f"30000000-0000-0000-0000-{index:012d}",
        "source_node_id": source["id"],
        "target_node_id": target["id"],
        "relation_type": relation,
        "weight": 1,
        "metadata": {"active": True, "graph_json_edge_id": f"edge:{index}", **(data or {})},
    }


def test_inconsistent_field_owner_across_branches_raises_error():
    """Same field key with divergent owner_node_id across branches is an error.

    Scenario: two branches (product and service) both declare "nome_cliente",
    but with different owner_node_id. This breaks the cross-branch fact linking.
    The compiler must reject this at publication time.
    """
    root = node(1, "persona:aurora", parent_type="persona")
    product_branch = node(2, "product:higienizacao", parent_type="product",
                          data={"capabilities": {"branch_anchor": True}})
    service_branch = node(3, "service:reclamacao", parent_type="service",
                          data={"capabilities": {"branch_anchor": True}})
    q_name = node(4, "question:nome", parent_type="faq",
                  data={"question": "Como você se chama?"})

    # Product branch: nome_cliente owned by persona (correct)
    product_branch["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": "persona:aurora",  # Shared owner
    }]}

    # Service branch: nome_cliente owned by itself (WRONG - diverges from product)
    service_branch["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": "service:reclamacao",  # Different owner
    }]}

    rows = [root, product_branch, service_branch, q_name]
    edges = [
        edge(1, root, product_branch),
        edge(2, root, service_branch),
        edge(3, root, q_name),
    ]

    # Compilation should reject this divergence
    with pytest.raises(graph_compiler_v3.GraphCompilationError) as exc_info:
        graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)

    errors = exc_info.value.errors
    assert any("inconsistent_field_owner" in err and "nome_cliente" in err for err in errors), \
        f"Expected inconsistent_field_owner error for nome_cliente, got: {errors}"


def test_consistent_field_owner_across_branches_passes():
    """Same field key with consistent owner_node_id across branches is valid."""
    root = node(1, "persona:aurora", parent_type="persona")
    product_branch = node(2, "product:higienizacao", parent_type="product",
                          data={"capabilities": {"branch_anchor": True}})
    service_branch = node(3, "service:reclamacao", parent_type="service",
                          data={"capabilities": {"branch_anchor": True}})
    q_name = node(4, "question:nome", parent_type="faq",
                  data={"question": "Como você se chama?"})

    # Both branches: nome_cliente owned by persona (correct, consistent)
    product_branch["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": "persona:aurora",
    }]}
    service_branch["metadata"]["qualification"] = {"fields": [{
        "key": "nome_cliente", "question_node_id": "question:nome", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        "owner_node_id": "persona:aurora",
    }]}

    rows = [root, product_branch, service_branch, q_name]
    edges = [
        edge(1, root, product_branch),
        edge(2, root, service_branch),
        edge(3, root, q_name),
    ]

    # Should compile successfully
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    assert document is not None
    assert "branch_contracts" in document
    assert "product:higienizacao" in document["branch_contracts"]
    assert "service:reclamacao" in document["branch_contracts"]


def test_branch_scoped_field_divergence_is_allowed():
    """Fields explicitly marked scope='branch' may have different owners per branch."""
    root = node(1, "persona:aurora", parent_type="persona")
    branch_a = node(2, "branch:a", parent_type="product",
                    data={"capabilities": {"branch_anchor": True}})
    branch_b = node(3, "branch:b", parent_type="product",
                    data={"capabilities": {"branch_anchor": True}})
    q_a = node(4, "question:a", parent_type="faq", data={"question": "Qual a metragem?"})
    q_b = node(5, "question:b", parent_type="faq", data={"question": "Qual a quantidade?"})

    # branch_a: custom_field owned by branch:a
    branch_a["metadata"]["qualification"] = {"fields": [{
        "key": "custom_field", "question_node_id": "question:a", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string"},
        "owner_node_id": "branch:a", "scope": "branch",
    }]}

    # branch_b: custom_field owned by branch:b (same key, different owner, but scope=branch)
    branch_b["metadata"]["qualification"] = {"fields": [{
        "key": "custom_field", "question_node_id": "question:b", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string"},
        "owner_node_id": "branch:b", "scope": "branch",
    }]}

    rows = [root, branch_a, branch_b, q_a, q_b]
    edges = [
        edge(1, root, branch_a),
        edge(2, root, branch_b),
        edge(3, branch_a, q_a),
        edge(4, branch_b, q_b),
    ]

    # Should compile successfully because both explicitly declare scope="branch"
    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    assert document is not None


def test_persona_scope_field_resolves_to_persona_node_id():
    """scope='persona' with no owner_node_id resolves to the persona node's
    stable graph id, so cross-branch consistency holds automatically."""
    root = node(1, "persona:aurora", parent_type="persona")
    product_branch = node(2, "product:higienizacao", parent_type="product",
                          data={"capabilities": {"branch_anchor": True}})
    service_branch = node(3, "service:reclamacao", parent_type="service",
                          data={"capabilities": {"branch_anchor": True}})
    q_name = node(4, "question:nome", parent_type="faq",
                  data={"question": "Como você se chama?"})

    field_decl = {
        "key": "nome_cliente", "question_node_id": "question:nome", "required": True,
        "accepted_statuses": ["known"], "value_schema": {"type": "string", "minLength": 1},
        "scope": "persona",  # no owner_node_id: compiler must resolve it
    }
    product_branch["metadata"]["qualification"] = {"fields": [dict(field_decl)]}
    service_branch["metadata"]["qualification"] = {"fields": [dict(field_decl)]}

    rows = [root, product_branch, service_branch, q_name]
    edges = [
        edge(1, root, product_branch),
        edge(2, root, service_branch),
        edge(3, root, q_name),
    ]

    document = graph_compiler_v3.compile_graph(persona=PERSONA, node_rows=rows, edge_rows=edges)
    product_field = document["branch_contracts"]["product:higienizacao"]["fields"][0]
    service_field = document["branch_contracts"]["service:reclamacao"]["fields"][0]
    assert product_field["owner_node_id"] == "persona:aurora"
    assert service_field["owner_node_id"] == "persona:aurora"


def test_declaration_scope_binds_field_to_campaign_node():
    root = node(1, "persona:aurora", parent_type="persona")
    campaign = node(2, "campaign:premium", parent_type="campaign")
    branch = node(3, "product:service", parent_type="product",
                  data={"capabilities": {"branch_anchor": True}})
    question = node(4, "question:note", parent_type="faq",
                    data={"question": "Qual detalhe desta campanha?"})
    campaign["metadata"]["qualification"] = {"fields": [{
        "key": "campaign_note", "scope": "declaration",
        "question_node_id": "question:note", "required": True,
        "value_schema": {"type": "string", "minLength": 1},
        "validation": {
            "mode": "semantic",
            "description": "Nota comercial específica desta campanha.",
            "examples": ["interesse na condição promocional"],
        },
    }]}
    rows = [root, campaign, branch, question]
    edges = [
        edge(1, root, campaign), edge(2, campaign, branch),
        edge(3, campaign, question),
    ]

    document = graph_compiler_v3.compile_graph(
        persona=PERSONA, node_rows=rows, edge_rows=edges,
    )

    field = document["branch_contracts"]["product:service"]["fields"][0]
    assert field["owner_node_id"] == "campaign:premium"


def test_declaration_scoped_field_can_have_distinct_campaign_owners():
    root = node(1, "persona:aurora", parent_type="persona")
    campaign_a = node(2, "campaign:a", parent_type="campaign")
    campaign_b = node(3, "campaign:b", parent_type="campaign")
    branch_a = node(4, "product:a", parent_type="product",
                    data={"capabilities": {"branch_anchor": True}})
    branch_b = node(5, "product:b", parent_type="product",
                    data={"capabilities": {"branch_anchor": True}})
    question_a = node(6, "question:a", parent_type="faq", data={"question": "Nota A?"})
    question_b = node(7, "question:b", parent_type="faq", data={"question": "Nota B?"})
    validation = {
        "mode": "semantic", "description": "Nota específica desta campanha.",
        "examples": ["condição comercial própria"],
    }
    campaign_a["metadata"]["qualification"] = {"fields": [{
        "key": "campaign_note", "scope": "declaration",
        "question_node_id": "question:a", "value_schema": {"type": "string"},
        "validation": validation,
    }]}
    campaign_b["metadata"]["qualification"] = {"fields": [{
        "key": "campaign_note", "scope": "declaration",
        "question_node_id": "question:b", "value_schema": {"type": "string"},
        "validation": validation,
    }]}

    document = graph_compiler_v3.compile_graph(
        persona=PERSONA,
        node_rows=[root, campaign_a, campaign_b, branch_a, branch_b, question_a, question_b],
        edge_rows=[
            edge(1, root, campaign_a), edge(2, campaign_a, branch_a),
            edge(3, campaign_a, question_a), edge(4, root, campaign_b),
            edge(5, campaign_b, branch_b), edge(6, campaign_b, question_b),
        ],
    )

    assert document["branch_contracts"]["product:a"]["fields"][0]["owner_node_id"] == "campaign:a"
    assert document["branch_contracts"]["product:b"]["fields"][0]["owner_node_id"] == "campaign:b"


def test_closed_field_without_published_values_fails_compilation():
    root = node(1, "persona:aurora", parent_type="persona")
    branch = node(2, "product:service", parent_type="product",
                  data={"capabilities": {"branch_anchor": True}})
    question = node(3, "question:objective", parent_type="faq",
                    data={"question": "Qual o objetivo?"})
    branch["metadata"]["qualification"] = {"fields": [{
        "key": "objective", "question_node_id": "question:objective",
        "value_schema": {"type": "string"},
        "validation": {"mode": "enum", "values": []},
    }]}

    with pytest.raises(graph_compiler_v3.GraphCompilationError) as exc_info:
        graph_compiler_v3.compile_graph(
            persona=PERSONA,
            node_rows=[root, branch, question],
            edge_rows=[edge(1, root, branch), edge(2, branch, question)],
        )

    assert any("field_enum_values_invalid" in error for error in exc_info.value.errors)


def test_semantic_field_without_definition_fails_compilation():
    root = node(1, "persona:aurora", parent_type="persona")
    branch = node(2, "product:service", parent_type="product",
                  data={"capabilities": {"branch_anchor": True}})
    question = node(3, "question:note", parent_type="faq",
                    data={"question": "Qual a observação?"})
    branch["metadata"]["qualification"] = {"fields": [{
        "key": "note", "question_node_id": "question:note",
        "value_schema": {"type": "string"},
        "validation": {"mode": "semantic"},
    }]}

    with pytest.raises(graph_compiler_v3.GraphCompilationError) as exc_info:
        graph_compiler_v3.compile_graph(
            persona=PERSONA,
            node_rows=[root, branch, question],
            edge_rows=[edge(1, root, branch), edge(2, branch, question)],
        )

    assert any(
        "field_semantic_definition_missing" in error
        for error in exc_info.value.errors
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
