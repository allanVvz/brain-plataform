import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migration_service_grants",
    ROOT / "ops" / "microservices" / "validate-migration-service-grants.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_current_post_cutover_rpc_inventory_has_owner_grants():
    assert MODULE.validate(ROOT / "supabase" / "migrations") == []


def test_validator_rejects_rpc_without_isolated_role_or_cache_reload(tmp_path):
    (tmp_path / "138_new_rpc.sql").write_text(
        "CREATE FUNCTION public.new_rpc() RETURNS void LANGUAGE sql AS 'select';",
        encoding="utf-8",
    )
    assert MODULE.validate(tmp_path) == [
        "public RPC new_rpc has no isolated microservice grant",
        "public RPC migrations do not reload the PostgREST schema cache",
    ]


def test_internal_activation_must_deny_external_roles(tmp_path):
    declaration = "CREATE FUNCTION public.activate_graph_publication_v3(uuid) RETURNS jsonb LANGUAGE sql AS 'select';\n"
    (tmp_path / "163_internal.sql").write_text(declaration + "NOTIFY pgrst, 'reload schema';\n")
    assert MODULE.validate(tmp_path) == ["internal function activate_graph_publication_v3 lacks explicit denial to external roles"]
    (tmp_path / "163_internal.sql").write_text(declaration + "REVOKE ALL ON FUNCTION public.activate_graph_publication_v3(uuid) FROM PUBLIC, anon, authenticated, service_role, brain_control_plane, brain_runtime, brain_transport, brain_gateway;\nNOTIFY pgrst, 'reload schema';\n")
    assert MODULE.validate(tmp_path) == []
