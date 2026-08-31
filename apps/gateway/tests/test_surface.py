from __future__ import annotations

import os

import main
from brain_shared import verify_principal


def test_gateway_exposes_its_own_health_metadata(monkeypatch) -> None:
    monkeypatch.setenv("BRAIN_CONTRACTS_VERSION", "3.0.0")
    payload = main._build_payload(ready=True)
    assert main.app.title == "Brain Gateway"
    assert payload["service"] == "brain-gateway"
    assert payload["contracts_version"] == "3.0.0"


def test_gateway_routes_runtime_and_signs_short_lived_principal(monkeypatch) -> None:
    secret = "a" * 32
    monkeypatch.setenv("BRAIN_INTERNAL_AUTH_SECRET", secret)
    monkeypatch.setenv("BRAIN_RUNTIME_URL", "https://runtime.internal")
    assert main._upstream("/process") == "https://runtime.internal"

    token, signature = main._principal({
        "user": {"id": "user-1", "role": "operator", "email": "operator@example.test"},
        "personas": [{"id": "persona-1"}],
    })
    claims = verify_principal(token, signature, secret=secret)
    assert claims["iss"] == "brain-gateway"
    assert claims["persona_ids"] == ["persona-1"]
