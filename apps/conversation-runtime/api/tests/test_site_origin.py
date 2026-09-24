from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from services import site_origin


CODE = "BI-0123456789ABCDEF"
DIGEST = hashlib.sha256(CODE.encode("ascii")).hexdigest()


def _event(persona_id: str = "persona-utzig", *, minutes: int = 30) -> dict:
    return {
        "id": "intent-event-1", "persona_id": persona_id,
        "payload": {
            "code_hash": DIGEST,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
            "audience_node_id": "audience:prepare-sale",
            "publication_id": "publication-utzig",
            "graph_checksum": "sha256:utzig",
        },
    }


def test_valid_code_attributes_only_origin(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(site_origin.supabase_client, "find_public_site_intent", lambda persona, digest: calls.append((persona, digest)) or _event())
    origin = site_origin.resolve(f"Quero vender meu carro. Codigo de atendimento: {CODE}", "persona-utzig")
    assert calls == [("persona-utzig", DIGEST)]
    assert origin == {
        "event_id": "intent-event-1", "audience_node_id": "audience:prepare-sale",
        "publication_id": "publication-utzig", "graph_checksum": "sha256:utzig",
    }
    assert "intent" not in origin
    assert "code" not in origin
    assert site_origin.without_code(f"Quero vender meu carro. Código de atendimento: {CODE}") == "Quero vender meu carro."


def test_missing_changed_expired_and_cross_persona_codes_do_not_attribute(monkeypatch) -> None:
    monkeypatch.setattr(site_origin.supabase_client, "find_public_site_intent", lambda *_args: _event())
    assert site_origin.resolve("Quero vender meu carro", "persona-utzig") is None
    assert site_origin.resolve("BI-0123456789ABCDE0", "persona-utzig") is None
    assert site_origin.resolve(CODE, "persona-tock") is None
    monkeypatch.setattr(site_origin.supabase_client, "find_public_site_intent", lambda *_args: _event(minutes=-1))
    assert site_origin.resolve(CODE, "persona-utzig") is None
