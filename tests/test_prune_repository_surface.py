import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/microservices/prune-repository-surface.py"
SPEC = importlib.util.spec_from_file_location("prune_repository_surface", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _fixture(tmp_path: Path) -> Path:
    api = tmp_path / "api"
    (api / "repositories").mkdir(parents=True)
    (api / "services").mkdir()
    (api / "workers").mkdir()
    (api / "main.py").write_text("from services import active\n")
    (api / "workers" / "runner.py").write_text("")
    (api / "services" / "__init__.py").write_text("")
    (api / "services" / "supabase_client.py").write_text(
        "from repositories.domain import *\n"
    )
    (api / "services" / "active.py").write_text(
        "from services import supabase_client\n\ndef run():\n    return supabase_client.used()\n"
    )
    (api / "repositories" / "__init__.py").write_text("")
    (api / "repositories" / "domain.py").write_text(
        "CONSTANT = 1\n\ndef helper():\n    return CONSTANT\n\ndef used():\n    return helper()\n\ndef dead():\n    return 0\n"
    )
    return api


def test_pruner_is_dry_run_by_default(tmp_path):
    api = _fixture(tmp_path)
    path = api / "repositories/domain.py"
    before = path.read_text()
    result = MODULE.prune(api, "repositories.domain")
    assert result["removed_functions"] == ["dead"]
    assert path.read_text() == before


def test_pruner_preserves_reachable_helpers_and_top_level_state(tmp_path):
    api = _fixture(tmp_path)
    result = MODULE.prune(api, "repositories.domain", apply=True)
    source = (api / "repositories/domain.py").read_text()
    assert result["applied"] is True
    assert "CONSTANT = 1" in source
    assert "def helper" in source
    assert "def used" in source
    assert "def dead" not in source


def test_audit_includes_direct_database_objects_outside_repository(tmp_path):
    api = _fixture(tmp_path)
    (api / "services" / "active.py").write_text(
        "from services import supabase_client\n"
        "def run():\n"
        "    supabase_client.get_client().table('direct_table').select('*').execute()\n"
        "    supabase_client.get_client().rpc('direct_rpc', {}).execute()\n"
        "    return supabase_client.used()\n"
    )

    audit = MODULE._auditor().audit(api, "repositories.domain")

    assert "direct_table" in audit["production_literal_tables"]
    assert "direct_rpc" in audit["production_literal_rpcs"]
