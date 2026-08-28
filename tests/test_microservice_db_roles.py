from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/131_microservice_role_grants.sql").read_text(encoding="utf-8")


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
