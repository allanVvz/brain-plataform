from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/131_microservice_role_grants.sql").read_text(encoding="utf-8")
VECTOR_SQL = (ROOT / "supabase/migrations/132_runtime_vector_distance_grant.sql").read_text(encoding="utf-8")


def test_microservice_roles_are_isolated_and_expand_only():
    for role in ("brain_gateway", "brain_control_plane", "brain_runtime", "brain_transport"):
        assert f"'{role}'" in SQL
    assert "CREATE ROLE %I NOLOGIN NOINHERIT BYPASSRLS" in SQL
    assert "ALTER ROLE %I NOLOGIN NOINHERIT BYPASSRLS" in SQL
    assert "REVOKE service_role FROM %I" in SQL
    assert "GRANT USAGE ON SCHEMA public TO %I" in SQL
    assert "GRANT %I TO authenticator" in SQL
    assert "ALTER DEFAULT PRIVILEGES" not in SQL


def test_microservice_grants_are_explicit_not_universal():
    assert "ON ALL TABLES" not in SQL
    assert "ON ALL SEQUENCES" not in SQL
    assert "ON ALL FUNCTIONS" not in SQL
    assert "GRANT ALL ON" not in SQL
    assert "brain_gateway',\n        ARRAY" not in SQL
    assert "brain_runtime','commit_graph_turn_and_outbox_v4" in SQL
    assert "brain_transport','claim_whatsapp_buffer" in SQL


def test_domain_owned_tables_and_routines_are_present_in_role_manifest():
    for object_name in (
        "agent_runs", "agent_run_steps", "campaigns", "campaign_revisions",
        "campaign_recipients", "message_templates", "graph_branch_contracts",
        "graph_branch_memberships", "graph_node_coordinates",
    ):
        assert f"'{object_name}'" in SQL
    for routine in (
        "activate_graph_publication_v3", "create_campaign_draft_v1",
        "transition_campaign_status_v1",
    ):
        assert f"'brain_control_plane','{routine}'" in SQL
    assert "'brain_runtime','activate_graph_publication_v3'" not in SQL


def test_runtime_vector_grant_is_minimal_and_does_not_expand_table_ownership():
    assert "GRANT EXECUTE ON FUNCTION public.cosine_distance(vector, vector) TO brain_runtime" in VECTOR_SQL
    assert "lead_buffer" not in VECTOR_SQL
    assert "GRANT ALL" not in VECTOR_SQL
