from pathlib import Path


SQL = (Path(__file__).resolve().parents[1] / "supabase/migrations/156_operational_queue_demands.sql").read_text(encoding="utf-8").lower()


def test_projection_groups_outbounds_into_demands_before_history_hydration():
    assert "create or replace function public.list_actionable_message_queue_v156" in SQL
    assert SQL.index("), page as (") < SQL.index("from public.messages m where m.lead_id=page.lead_ref")
    assert "'outbound_messages',outbound_messages" in SQL
    assert "partition by persona_id,lead_ref" in SQL
    assert "lead_demand_rank<=3" in SQL


def test_validator_is_excluded_by_canonical_transport_and_lead_metadata():
    assert "binding_provider" in SQL
    assert "coalesce(w.provider,'')<>'internal_validator'" in SQL
    assert "metadata->'validation'->>'is_validation'" in SQL
    assert "validator_session_id" in SQL
    assert "sdr_sales_branch_switch" not in SQL


def test_individual_retry_supersedes_only_the_selected_sequence():
    function = SQL.split("create or replace function public.enqueue_reactivation_line_revision_v1", 1)[1]
    function = function.split("create or replace function public.control_message_queue_v2", 1)[0]
    assert "queue_sequence=v_previous.queue_sequence" in function
    assert "where id=v_previous.id" in function
    assert "status='superseded'" in function
    assert "p_previous_buffer_id" in function
    assert "conversation_turn_proofs" not in function or "enqueue_proactive_with_proof_v1" in function


def test_ordinary_message_retry_gets_a_new_proof_without_replaying_inbound():
    function = SQL.split("create or replace function public.enqueue_queue_message_revision_v1", 1)[1]
    function = function.split("create or replace function public.control_message_queue_v2", 1)[0]
    assert "queue-retry:" in function
    assert "queue_canonical_inbound_id" in function
    assert "insert into public.conversation_turn_proofs" in function
    assert "status='superseded'" in function
    assert "status='preview_ready'" in function
    assert "status='processing'" not in function


def test_send_revalidates_proof_pause_new_inbound_publication_and_order():
    function = SQL.split("create or replace function public.control_message_queue_v2", 1)[1]
    function = function.split("create or replace function public.list_actionable_message_queue_v156", 1)[0]
    assert "proof_ou_publicacao_invalida" in function
    assert "lead_pausada_ou_em_handoff" in function
    assert "binding_pausado" in function
    assert "nova_mensagem_da_lead" in function
    assert "mensagem_1_ainda_nao_confirmada" in function
    assert "where id=v_row.id and status='preview_ready'" in function


def test_projection_never_uses_inbound_text_as_outbound_preview():
    assert "'preview_text',outbound_messages->0->>'text'" in SQL
    assert "customer_message" in SQL
    assert "last_agent_message" in SQL
    assert "recent_context" in SQL


def test_control_plane_routes_generic_retry_to_the_non_committing_runtime_path():
    service = (Path(__file__).resolve().parents[1] / "apps/control-plane/api/services/release_queue_service.py").read_text(encoding="utf-8")
    assert "runtime_client.retry_queue_message" in service
    assert '"previous_buffer_id": buffer_id' in service
    assert '"retry_revision": retry_revision' in service
