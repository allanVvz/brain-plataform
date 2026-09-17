import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / "migrate-conversation-model-secret.py"
SPEC = importlib.util.spec_from_file_location("model_secret_migration", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_json_from_output_ignores_cli_status_lines():
    assert MODULE._json_from_output('Starting\n[{"id":"cred-1"}]\nDone') == [
        {"id": "cred-1"}
    ]


def test_api_key_accepts_only_authorization_bearer():
    assert MODULE._api_key({
        "data": {"name": "Authorization", "value": "Bearer sk-secret"}
    }) == "sk-secret"
    with pytest.raises(RuntimeError):
        MODULE._api_key({"data": {"name": "X-Key", "value": "sk-secret"}})


def test_model_id_validation_accepts_the_provider_model_name():
    assert MODULE.re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", "deepseek-flash")
    assert not MODULE.re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", "deepseek flash")
