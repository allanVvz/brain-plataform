from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import wa_validator_service as wv


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
