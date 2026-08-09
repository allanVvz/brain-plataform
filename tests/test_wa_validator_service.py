from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service as wv
from services import supabase_client


def test_resolve_initial_state_defaults_to_cold_for_unrequested_or_unknown():
    assert wv._resolve_initial_state(None, "sdr_qualificacao_carro") == "cold"
    assert wv._resolve_initial_state("something_else", "sdr_qualificacao_carro") == "cold"


def test_resolve_initial_state_known_name_only_applies_to_name_collecting_flows():
    assert wv._resolve_initial_state("known_name", "sdr_qualificacao_carro") == "known_name"
    assert wv._resolve_initial_state("known_name", "sdr_troca_servico") == "known_name"
    # "duvida_frete" never collects a name -- nothing to pre-seed or omit,
    # so a request for known_name degrades to cold rather than silently
    # doing nothing while claiming a state that was never applied.
    assert wv._resolve_initial_state("known_name", "duvida_frete") == "cold"


def test_resolve_initial_state_random_only_ever_returns_the_two_valid_states():
    seen = {wv._resolve_initial_state("random", "sdr_qualificacao_carro") for _ in range(40)}
    assert seen == {"cold", "known_name"}
    # Same flow with no name-collection step: "random" must not fabricate a
    # "known_name" state it can't actually seed for.
    assert wv._resolve_initial_state("random", "duvida_frete") == "cold"


def test_deterministic_script_cold_state_asks_for_the_name_as_before():
    script = wv._deterministic_script(
        "sdr_qualificacao_carro", product=None, graph_version=1, graph_checksum="sha256:x",
    )
    steps_text = [step["text"] for step in script["steps"]]
    known_name = script["expected_dialogue"]["known_name"]
    assert known_name in steps_text
    assert script["expected_dialogue"]["client_name_omitted"] is False


def test_deterministic_script_known_name_never_sends_the_name():
    script = wv._deterministic_script(
        "sdr_qualificacao_carro", product=None, graph_version=1, graph_checksum="sha256:x",
        omit_client_name=True,
    )
    steps_text = [step["text"] for step in script["steps"]]
    known_name = script["expected_dialogue"]["known_name"]
    assert known_name not in steps_text
    assert script["expected_dialogue"]["client_name_omitted"] is True
    # The opening message (service mention) and every subsequent scripted
    # step must survive untouched -- only the name step is dropped.
    assert len(steps_text) == 6


def test_deterministic_script_known_name_also_works_for_the_switch_flow():
    script = wv._deterministic_script(
        "sdr_troca_servico", product=None, graph_version=1, graph_checksum="sha256:x",
        omit_client_name=True,
    )
    steps_text = [step["text"] for step in script["steps"]]
    assert script["expected_dialogue"]["known_name"] not in steps_text


def _persona_node(business_model: str):
    return SimpleNamespace(
        node_type="persona", data={"business_model": business_model},
    )


def test_generate_script_uses_the_v3_publication_version_when_one_is_active(monkeypatch):
    """Regression test for the false graph-lineage gap found live 2026-08-09.

    A persona actually running graph_agent_runtime_v3 (Aurora) reports the
    v3 compiler's own publication version/checksum on every real turn
    (graph_agent_runtime_v3.build_context() reads it from
    graph_publications, never from the legacy v2.1 store) -- a separate
    counter from the v2.1 store version _build_graph_context() returns.
    Before this fix, generate_script() baked the v2.1 version into
    expected_knowledge and the script label, so analyze_gaps() always
    compared two counters that could never match by design, reporting a
    false "high" severity gap and dragging overall_score down on a
    perfectly successful conversation. The v3 publication's own
    version/checksum, when one is active, is what a real turn actually
    reports, so it must be the "expected" baseline instead.
    """
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda slug: {"id": "persona-1", "name": "Aurora"})
    monkeypatch.setattr(
        wv, "_build_graph_context",
        lambda slug: ("kb context", 14, "sha256:legacy-v14", SimpleNamespace(nodes=[_persona_node("appointment")])),
    )
    monkeypatch.setattr(
        wv.supabase_client, "get_active_graph_publication",
        lambda persona_id: {"version": 40, "checksum": "sha256:real-v40"},
    )
    monkeypatch.setattr(wv.supabase_client, "get_persona_routing", lambda slug: {})
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda persona_id: [])
    monkeypatch.setattr(wv.supabase_client, "upsert_wa_validator_session", lambda *a, **k: None)
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *a, **k: None)

    result = wv.generate_script("aurora", "sdr_qualificacao_carro", "5511999999999")

    assert result["script"]["meta"]["graph_version"] == 40
    assert result["script"]["meta"]["graph_checksum"] == "sha256:real-v40"
    assert result["script"]["expected_knowledge"] == ["graph:40:sha256:real-v40"]


def test_generate_script_falls_back_to_the_v2_store_version_without_a_v3_publication(monkeypatch):
    """No active v3 publication (e.g. a persona still fully on the legacy
    engine) -- behavior must stay exactly as before this fix."""
    monkeypatch.setattr(wv.supabase_client, "get_persona", lambda slug: {"id": "persona-1", "name": "Baita"})
    monkeypatch.setattr(
        wv, "_build_graph_context",
        lambda slug: ("kb context", 14, "sha256:legacy-v14", SimpleNamespace(nodes=[_persona_node("sales")])),
    )
    monkeypatch.setattr(wv.supabase_client, "get_active_graph_publication", lambda persona_id: None)
    monkeypatch.setattr(wv.supabase_client, "get_persona_routing", lambda slug: {})
    monkeypatch.setattr(wv.supabase_client, "get_workflow_bindings", lambda persona_id: [])
    monkeypatch.setattr(wv.supabase_client, "upsert_wa_validator_session", lambda *a, **k: None)
    monkeypatch.setattr(wv.supabase_client, "insert_event", lambda *a, **k: None)

    result = wv.generate_script("baita-conveniencia", "duvida_frete", "5511999999999")

    assert result["script"]["meta"]["graph_version"] == 14
    assert result["script"]["meta"]["graph_checksum"] == "sha256:legacy-v14"
    assert result["script"]["expected_knowledge"] == ["graph:14:sha256:legacy-v14"]
