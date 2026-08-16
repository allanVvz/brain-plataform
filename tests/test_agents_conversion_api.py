from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from routes import agents
from routes.agents import JourneyEventBody, PurchaseCompletedBody


def test_purchase_requires_currency_when_amount_is_present():
    with pytest.raises(ValidationError):
        PurchaseCompletedBody(
            idempotency_key="one", source="erp", occurred_at=datetime.now(timezone.utc),
            amount_minor=100,
        )


def test_purchase_normalizes_iso_currency_and_accepts_optional_value():
    valued = PurchaseCompletedBody(
        idempotency_key="one", source="erp", occurred_at=datetime.now(timezone.utc),
        amount_minor=100, currency="brl", items=[{"sku": "x"}],
    )
    assert valued.currency == "BRL"
    assert valued.amount_minor == 100
    unvalued = PurchaseCompletedBody(
        idempotency_key="two", source="manual", occurred_at=datetime.now(timezone.utc)
    )
    assert unvalued.amount_minor is None


@pytest.mark.parametrize(
    "event_type",
    ["sale_recorded", "appointment_booked", "delivered", "service_completed", "cancelled"],
)
def test_journey_event_contract_accepts_the_published_variants(event_type):
    body = JourneyEventBody(
        event_type=event_type,
        idempotency_key=f"event:{event_type}",
        source="operator",
        occurred_at=datetime.now(timezone.utc),
    )
    assert body.event_type == event_type


def test_closing_journey_event_rejects_commercial_payload():
    with pytest.raises(ValidationError):
        JourneyEventBody(
            event_type="delivered", idempotency_key="delivery:one", source="erp",
            occurred_at=datetime.now(timezone.utc), amount_minor=100,
            currency="BRL",
        )


def test_purchase_endpoint_adapter_records_sale_without_requesting_a_new_journey(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agents.supabase_client, "get_lead_by_ref",
        lambda _lead_ref: {"id": 42, "persona_id": "persona:one"},
    )

    def record_event(**payload):
        captured.update(payload)
        return {"deduplicated": False, "new_journey_created": False}

    monkeypatch.setattr(
        agents.supabase_client, "record_conversation_journey_event", record_event,
    )
    body = PurchaseCompletedBody(
        idempotency_key="sale:one", source="erp",
        occurred_at=datetime.now(timezone.utc), amount_minor=100, currency="BRL",
    )
    result = agents._record_purchase(42, body, None)
    assert captured["p_event_type"] == "sale_recorded"
    assert captured["p_idempotency_key"] == "sale:one"
    assert result["new_journey_created"] is False
