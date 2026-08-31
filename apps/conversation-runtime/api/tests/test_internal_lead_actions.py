from routes import leads


def test_repeated_resume_delegates_to_idempotent_runtime_service(monkeypatch):
    calls = []
    monkeypatch.setattr(leads.internal_auth, "authorize_webhook_token", lambda token: calls.append(("auth", token)))
    monkeypatch.setattr(leads.agents_service, "resume_lead", lambda lead_ref: calls.append(("resume", lead_ref)) or True)
    monkeypatch.setattr(leads.agents_service, "reactivation_notice", lambda *_args, **_kwargs: {"sent": False})
    monkeypatch.setattr(leads.event_emitter, "emit", lambda *args, **kwargs: calls.append(("event", args, kwargs)))

    first = leads.resume_ai_internal(42, "token", "user-7")
    second = leads.resume_ai_internal(42, "token", "user-7")

    assert first["ai_paused"] is False
    assert second["ai_paused"] is False
    assert calls.count(("resume", 42)) == 2
    assert [call for call in calls if call[0] == "auth"] == [
        ("auth", "token"),
        ("auth", "token"),
    ]
