"""QA-only real-model replay on existing internal Validator leads, without commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from services import agentic_turn, conversation_runtime, supabase_client, wa_validator_service


def run(case: dict) -> dict:
    session = wa_validator_service._session_get(case["session_id"])
    lead_ref = int(session["lead_ref"])
    lead = supabase_client.get_lead_by_ref(lead_ref)
    assert (lead.get("metadata") or {}).get("validation"), "only internal Validator leads"
    turn_id = str(uuid4())
    context = conversation_runtime.build_context(
        persona_slug=session["persona_slug"], lead_ref=lead_ref,
        message=case["message"], message_id=turn_id,
    )
    removed = set(case.get("pending_fields") or [])
    cart = {**context.cart,
            "facts": {k: v for k, v in (context.cart.get("facts") or {}).items() if k not in removed},
            "facts_by_key": {k: v for k, v in (context.cart.get("facts_by_key") or {}).items() if k not in removed},
            "sdr_state": "collecting", "pending_confirmation_ref": None}
    cart.pop("terminal_handoff", None)
    context = context.model_copy(update={
        "cart": cart, "operational_mode": "collection", "journey_state": "collecting",
        "messages": [*case["history"], {"role": "user", "content": case["message"], "message_id": turn_id}],
        "shared_memory": context.shared_memory.model_copy(update={
            "profile_facts": [f for f in context.shared_memory.profile_facts if f.key not in removed],
        }),
    })
    with patch.object(conversation_runtime, "build_context", return_value=context), \
         patch.object(conversation_runtime, "commit", side_effect=AssertionError("candidate must not commit")):
        result = agentic_turn.execute(
            persona_slug=session["persona_slug"], lead_ref=lead_ref,
            message=case["message"], message_id=turn_id, correlation_id=turn_id,
            inbound_buffer_id=turn_id, phone_number_id=None,
            channel_binding_id="candidate-no-commit", provider="internal_validator",
            commit_result=False,
        )
    response = result["response"]
    proof = response.proof
    assert result["model_calls"] == 2 and proof["valid"] is True
    assert response.reply_text and proof.get("delivery_authorized") is not False
    assert not any(f.get("field_key") in case.get("forbidden_extracted_fields", [])
                   for f in proof.get("accepted_facts") or []), "contextual answer misclassified"
    return {"case": case["name"], "lead_ref": lead_ref, "publication_id": context.publication_id,
            "graph_checksum": context.graph_checksum, "commit": False, "model_calls": 2,
            "reply": response.reply_text, "question_kind": proof.get("question_kind"),
            "asked_field_key": proof.get("asked_field_key"), "technical_pass": True,
            "quality_warnings": proof.get("quality_warnings") or []}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=["human-conversation-2026-09-25"])
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "evaluation" / (args.fixture + ".json")
    for case in json.loads(fixture.read_text(encoding="utf-8")):
        print("CANDIDATE_CONVERSATION_PROBE=" + json.dumps(run(case), ensure_ascii=True), flush=True)
