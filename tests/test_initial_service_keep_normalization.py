from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from schemas.conversation import BranchAction, ConversationContext, ConversationProposal, ServiceOperation
from services.graph_agent_runtime_v3 import _normalize_initial_service_keep


def _context(message: str) -> ConversationContext:
    return ConversationContext(
        persona_slug="generic",
        agent_slug="agent",
        graph_version=1,
        graph_checksum="sha256:fixture",
        messages=[{"role": "user", "content": message}],
        cart={},
        rag_nodes=[],
        rag_paths=[],
    )


def test_literal_first_service_keep_becomes_select_and_add():
    proposal = ConversationProposal(
        branch_action=BranchAction.KEEP,
        branch_anchor_node_id="branch:vitrificacao",
        branch_path_checksum="sha256:path",
        service_operations=[ServiceOperation(
            action="keep",
            branch_anchor_node_id="branch:vitrificacao",
            branch_path_checksum="sha256:path",
            evidence_span="vitrificação",
        )],
        reply="A vitrificação cria proteção química.",
    )

    normalized = _normalize_initial_service_keep(
        proposal, context=_context("como funciona vitrificação?")
    )

    assert normalized.branch_action is BranchAction.SELECT
    assert normalized.branch_evidence_span == "vitrificação"
    assert normalized.service_operations[0].action.value == "add"


def test_unsubstantiated_first_service_keep_is_not_promoted():
    proposal = ConversationProposal(
        branch_action=BranchAction.KEEP,
        branch_anchor_node_id="branch:vitrificacao",
        branch_path_checksum="sha256:path",
        service_operations=[ServiceOperation(
            action="keep",
            branch_anchor_node_id="branch:vitrificacao",
            branch_path_checksum="sha256:path",
            evidence_span="vitrificação",
        )],
    )

    normalized = _normalize_initial_service_keep(
        proposal, context=_context("quero entender melhor")
    )

    assert normalized.branch_action is BranchAction.KEEP
    assert normalized.service_operations[0].action.value == "keep"
