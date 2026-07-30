import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import lead_qualification


def _apply(previous, *, model, intent, state, stage="novo"):
    return lead_qualification.calculate(
        previous=previous,
        business_model=model,
        intent=intent,
        state=state,
        current_stage=stage,
        evidence_node_ids=["node:test"],
    )


def test_complete_appointment_caps_at_100_and_pauses_as_opportunity():
    state = {
        "business_model": "appointment",
        "appointment_request": {
            "customer_name": "Ana",
            "service_slug": "lavagem",
            "vehicle_model": "Corolla",
            "vehicle_size": "sedan",
            "condition": "com manchas",
            "desired_date": "31/07",
            "time_window": "tarde",
        },
        "conversation_state": "handoff",
    }
    qualification, stage = _apply(
        None,
        model="appointment",
        intent="complete_booking_request",
        state=state,
    )
    assert qualification["score"] == 100
    assert stage == "oportunidade"


def test_complete_sales_order_scores_95():
    state = {
        "items": [{"product_slug": "agua", "quantity": 2, "unit_price": 5}],
        "customer_name": "Ana",
        "address": {"street": "Rua QA", "number": "100"},
        "confirmation_status": "confirmed_pending_human",
        "conversation_state": "handoff",
    }
    qualification, stage = _apply(
        None, model="sales", intent="confirm_order", state=state,
    )
    assert qualification["score"] == 95
    assert stage == "oportunidade"


def test_signals_are_idempotent_and_terminal_stage_is_preserved():
    state = {"items": [{"product_slug": "agua", "quantity": 1, "unit_price": 5}]}
    first, _ = _apply(None, model="sales", intent="add_item", state=state)
    second, stage = _apply(
        first, model="sales", intent="add_item", state=state, stage="fechado",
    )
    assert second["score"] == first["score"]
    assert len(second["signals"]) == len(first["signals"])
    assert stage == "fechado"


def test_complaint_does_not_receive_commercial_signals():
    qualification, stage = _apply(
        None, model="appointment", intent="exceptional_support",
        state={"business_model": "appointment", "conversation_state": "handoff"},
    )
    assert qualification["score"] == 5
    assert [item["key"] for item in qualification["signals"]] == ["first_contact"]
    assert stage == "contatado"
