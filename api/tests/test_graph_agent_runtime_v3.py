from schemas.conversation import (
    BranchAction,
    ConversationContext,
    ConversationProposal,
    ServiceOperation,
)
from services.graph_agent_runtime_v3 import _normalize_initial_service_keep


def _context(message: str) -> ConversationContext:
    return ConversationContext(
        persona_slug="fixture",
        agent_slug="fixture-agent",
        graph_version=1,
        graph_checksum="sha256:fixture",
        messages=[{"role": "user", "content": message}],
        cart={},
        rag_nodes=[],
        rag_paths=[],
    )


def test_initial_keep_with_literal_service_is_normalized_to_select():
    proposal = ConversationProposal(
        branch_action=BranchAction.KEEP,
        branch_anchor_node_id="service:vitrificacao",
        branch_path_checksum="sha256:path",
        service_operations=[
            ServiceOperation(
                action="keep",
                branch_anchor_node_id="service:vitrificacao",
                branch_path_checksum="sha256:path",
                evidence_span="vitrificação",
            )
        ],
        reply="A vitrificação cria uma camada de proteção.",
    )

    normalized = _normalize_initial_service_keep(
        proposal, context=_context("como funciona vitrificação?")
    )

    assert normalized.branch_action is BranchAction.SELECT
    assert normalized.branch_evidence_span == "vitrificação"
    assert normalized.service_operations[0].action.value == "add"


def test_initial_keep_without_literal_evidence_remains_unchanged():
    proposal = ConversationProposal(
        branch_action=BranchAction.KEEP,
        branch_anchor_node_id="service:vitrificacao",
        branch_path_checksum="sha256:path",
        service_operations=[
            ServiceOperation(
                action="keep",
                branch_anchor_node_id="service:vitrificacao",
                branch_path_checksum="sha256:path",
                evidence_span="vitrificação",
            )
        ],
    )

    normalized = _normalize_initial_service_keep(
        proposal, context=_context("quero entender melhor")
    )

    assert normalized.branch_action is BranchAction.KEEP
    assert normalized.service_operations[0].action.value == "keep"
