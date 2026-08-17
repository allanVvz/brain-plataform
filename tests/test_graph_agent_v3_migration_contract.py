from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = "\n".join(
    (ROOT / "supabase" / "migrations" / name).read_text(encoding="utf-8").lower()
    for name in (
        "093_graph_agent_runtime_v3.sql",
        "094_graph_rag_ready_projection_status.sql",
        "095_graph_rag_projection_manifest.sql",
        "096_graph_turn_publication_invalidation.sql",
        "097_graph_json_publication_grants_to_embed.sql",
        "098_recover_uncommitted_graph_inbound.sql",
        "099_recover_unsent_committed_outbound.sql",
        "100_reconcile_committed_graph_inbound.sql",
        "120_graphrag_faq_projection_v1.sql",
        "127_sdr_name_service_confirmation.sql",
    )
)


def test_v3_schema_has_immutable_publication_and_exactly_once_proof():
    for table in (
        "graph_publications", "graph_node_coordinates", "graph_branch_memberships",
        "graph_branch_contracts", "conversation_ledgers", "conversation_facts",
        "conversation_turn_proofs",
    ):
        assert f"create table if not exists public.{table}" in SQL
    assert "canonical_inbound_id text not null unique" in SQL
    assert "compiled graph publication content is immutable" in SQL
    assert "for update" in SQL
    assert "pg_advisory_xact_lock" in SQL


def test_v3_retrieval_is_postgres_branch_scoped_and_indexed():
    assert "graph_hybrid_search_v3" in SQL
    assert "c.persona_id = p_persona_id" in SQL
    assert "c.publication_id = p_publication_id" in SQL
    assert "c.branch_anchor_node_id = p_branch_node_id" in SQL
    assert "using gin(search_document)" in SQL
    assert "using hnsw (embedding vector_cosine_ops)" in SQL
    assert "graph_branch_memberships m" in SQL


def test_activation_requires_contracts_and_embeddings_and_has_rollback():
    assert "required embeddings are incomplete" in SQL
    assert "rag entries are incomplete" in SQL
    assert "graph coordinates are incomplete" in SQL
    assert "branch memberships are incomplete" in SQL
    assert "branch contracts are incomplete" in SQL
    assert "activate_graph_publication_v3" in SQL
    assert "rollback_graph_publication_v3" in SQL
    assert "faq projections are incomplete" in SQL
    assert "faq_projection_contract" in SQL


def test_faq_search_is_internal_branch_and_persona_scoped():
    assert "graph_faq_search_v3" in SQL
    assert "c.persona_id = p_persona_id" in SQL
    assert "c.publication_id = p_publication_id" in SQL
    assert "c.branch_anchor_node_id = p_branch_node_id" in SQL
    assert "c.source_graph_node_id = any" in SQL
    assert "p.status = 'active'" in SQL
    assert "eligible_faq_node_ids" in SQL
    assert "revoke all on function public.graph_faq_search_v3" in SQL
    assert "from public, anon, authenticated" in SQL


def test_only_validated_graph_publication_can_grant_protected_embed_edges():
    assert "relation_type = 'publishes_to'" in SQL
    assert "src_status in ('approved', 'validated', 'active', 'ativo')" in SQL
    assert "new.metadata->>'graph_json_id' = src_graph_id" in SQL
    assert "new.metadata->>'graph_json_id' = tgt_graph_id" in SQL
    assert "same-document graph json publication grant" in SQL


def test_technical_recovery_requires_no_proof_commit_or_outbound():
    assert "recover_uncommitted_graph_inbound" in SQL
    assert "conversation_turn_proofs" in SQL
    assert "conversation_commit" in SQL
    assert "inbound already has an outbound side effect" in SQL
    assert "conversation.uncommitted_inbound_recovered" in SQL


def test_outbound_recovery_requires_one_proof_and_zero_provider_attempts():
    assert "recover_unsent_committed_outbound" in SQL
    assert "provider_attempt_count <> 0" in SQL
    assert "outbound must belong to exactly one valid turn proof" in SQL
    assert "conversation.unsent_committed_outbound_recovered" in SQL


def test_committed_inbound_reconciliation_never_replays_model_or_transport():
    assert "reconcile_committed_graph_inbound" in SQL
    assert "conversation_commit,status" in SQL
    assert "v_proof_count <> 1 or v_valid_proof_count <> 1" in SQL
    assert "outbound_message_is_not_unique" in SQL
    assert "conversation.committed_inbound_reconciled" in SQL
    assert "status = 'sent'" in SQL


def test_name_and_service_confirmation_migration_is_metadata_and_cas_safe():
    assert "add column if not exists metadata jsonb" in SQL
    assert "coalesce(v_fact->'metadata','{}'::jsonb)" in SQL
    assert "graph_service_rank_v3" in SQL
    assert "c.source_graph_node_id=c.branch_anchor_node_id" in SQL
    assert "c.projection_status in ('ready','published')" in SQL
    assert "conversation_carry_over_facts_v1" in SQL
    assert "f.status='known'" in SQL
    assert "repair_sdr_false_service_fact_v1" in SQL
    assert "p_apply boolean default false" in SQL
    assert "ledger revision conflict" in SQL
    assert "authorized_service_evidence" in SQL
    assert "deterministic_graph_match" in SQL
    assert "sdr_false_service_fact_repaired" in SQL
    assert "p_proof_result->'next_active_branch_node_ids'" in SQL
    assert "branch focus invariant failed" in SQL
    assert "branch_anchor_node_id<>all(v_proven_active)" in SQL
