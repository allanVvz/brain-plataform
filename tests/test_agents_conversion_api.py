from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from routes.agents import PurchaseCompletedBody


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
