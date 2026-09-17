from services import integration_service


def test_deepseek_credential_is_encrypted_for_runtime_without_n8n(monkeypatch):
    saved = []
    monkeypatch.setattr(
        integration_service.supabase_client,
        "get_persona_integration_connection",
        lambda *_args: {},
    )
    monkeypatch.setattr(
        integration_service.supabase_client,
        "save_persona_integration_connection",
        lambda payload: saved.append(payload),
    )
    monkeypatch.setattr(
        integration_service, "validate_deepseek", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        integration_service.secret_store,
        "encrypt_secret",
        lambda value: f"encrypted:{len(value)}",
    )
    monkeypatch.setattr(
        integration_service,
        "get_persona_integration_state",
        lambda persona_id, service: {"persona_id": persona_id, "service": service},
    )

    integration_service.save_persona_integration(
        persona_id="persona-1",
        actor_user_id="user-1",
        service="deepseek",
        enabled=True,
        credentials={
            "api_key": "sk-fixture-secret",
            "model": "fixture-model",
            "endpoint": "https://model.invalid/chat/completions",
            "structured_output_mode": "json_object",
        },
    )

    payload = saved[0]
    assert payload["secret_ciphertext"] == "encrypted:17"
    assert payload["config_json"]["pipeline_contract"] == "conversation_agentic_v1"
    assert "n8n_credential_id" not in payload["config_json"]
    assert "api_key" not in payload["config_json"]
