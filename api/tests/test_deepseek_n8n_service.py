from services import deepseek_n8n_service


def test_provision_keeps_key_only_in_n8n_credential(monkeypatch):
    calls = {}

    def create_credential(**payload):
        calls["credential"] = payload
        return {"id": "credential-new"}

    def update_workflow(workflow_id, workflow):
        calls["workflow"] = workflow
        return {"id": workflow_id}

    deleted = []
    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "create_credential", create_credential)
    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "update_workflow", update_workflow)
    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "activate_workflow", lambda workflow_id: {"id": workflow_id})
    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "delete_credential", deleted.append)

    key = "sk-test-deepseek-secret"
    result = deepseek_n8n_service.provision(
        persona={
            "id": "persona-id",
            "slug": "baita-conveniencia",
            "name": "Baita",
            "config": {"agent_slug": "vitoria"},
        },
        api_key=key,
        previous_config={
            "n8n_workflow_id": "workflow-existing",
            "n8n_credential_id": "credential-old",
        },
    )

    assert calls["credential"]["data"]["value"] == f"Bearer {key}"
    assert key not in str(calls["workflow"])
    deepseek_node = next(node for node in calls["workflow"]["nodes"] if node["id"] == "deepseek")
    assert deepseek_node["credentials"]["httpHeaderAuth"]["id"] == "credential-new"
    assert calls["workflow"]["settings"]["saveDataSuccessExecution"] == "none"
    assert result["n8n_workflow_id"] == "workflow-existing"
    assert result["n8n_credential_id"] == "credential-new"
    assert key not in str(result)
    assert deleted == ["credential-old"]


def test_provision_rolls_back_only_new_credential_when_workflow_fails(monkeypatch):
    deleted = []
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "create_credential",
        lambda **_payload: {"id": "credential-new"},
    )
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "update_workflow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("n8n failed")),
    )
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "delete_credential",
        deleted.append,
    )

    try:
        deepseek_n8n_service.provision(
            persona={"slug": "baita-conveniencia", "name": "Baita"},
            api_key="sk-test-deepseek-secret",
            previous_config={
                "n8n_workflow_id": "workflow-existing",
                "n8n_credential_id": "credential-old",
            },
        )
        raise AssertionError("provision should fail")
    except RuntimeError as exc:
        assert str(exc) == "n8n failed"

    assert deleted == ["credential-new"]


def test_resync_workflow_reuses_existing_credential_and_reactivates(monkeypatch):
    """Regression test: this replaces the manual SSH ritual (rebuild
    workflow from the template on disk, update_workflow, activate_workflow)
    that was run by hand for every persona-level engine/config change this
    session — the settings UI must be able to trigger the same steps."""
    calls = {}

    def update_workflow(workflow_id, workflow):
        calls["workflow_id"] = workflow_id
        calls["workflow"] = workflow
        return {"id": workflow_id}

    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "update_workflow", update_workflow)
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "activate_workflow",
        lambda workflow_id: calls.setdefault("activated", workflow_id),
    )

    result = deepseek_n8n_service.resync_workflow_for_persona(
        {"id": "persona-id", "slug": "baita-conveniencia", "name": "Baita", "config": {}},
        {"n8n_credential_id": "credential-existing", "n8n_workflow_id": "workflow-existing"},
    )

    assert result["n8n_workflow_id"] == "workflow-existing"
    assert result["conversation_webhook_path"] == "baita-conveniencia/conversation"
    assert calls["workflow_id"] == "workflow-existing"
    assert calls["activated"] == "workflow-existing"
    deepseek_node = next(node for node in calls["workflow"]["nodes"] if node["id"] == "deepseek")
    assert deepseek_node["credentials"]["httpHeaderAuth"]["id"] == "credential-existing"


def test_resync_workflow_creates_it_when_missing_reusing_the_credential(monkeypatch):
    """Regression test for the exact gap found live: a persona
    (baita-conveniencia) already had a DeepSeek credential provisioned but
    its workflow reference was missing, so switching to n8n_agents errored
    out instead of just working. The raw API key isn't recoverable once
    saved (it only lives inside the n8n credential from then on), so the
    fix must build a new workflow from the credential that's already
    there, never ask for the key again."""
    calls = {}

    def create_workflow(workflow):
        calls["created"] = workflow
        return {"id": "workflow-new"}

    monkeypatch.setattr(deepseek_n8n_service.n8n_client, "create_workflow", create_workflow)
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "update_workflow",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must create, not update, when no workflow id exists")),
    )
    monkeypatch.setattr(
        deepseek_n8n_service.n8n_client,
        "activate_workflow",
        lambda workflow_id: calls.setdefault("activated", workflow_id),
    )

    result = deepseek_n8n_service.resync_workflow_for_persona(
        {"id": "persona-id", "slug": "baita-conveniencia", "name": "Baita", "config": {}},
        {"n8n_credential_id": "credential-existing"},
    )

    assert result["n8n_workflow_id"] == "workflow-new"
    assert result["conversation_webhook_path"] == "baita-conveniencia/conversation"
    assert calls["activated"] == "workflow-new"
    deepseek_node = next(node for node in calls["created"]["nodes"] if node["id"] == "deepseek")
    assert deepseek_node["credentials"]["httpHeaderAuth"]["id"] == "credential-existing"


def test_resync_workflow_requires_prior_provisioning(monkeypatch):
    try:
        deepseek_n8n_service.resync_workflow_for_persona(
            {"slug": "baita-conveniencia", "name": "Baita", "config": {}},
            {},
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "provisionado" in str(exc)
