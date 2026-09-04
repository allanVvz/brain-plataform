"""Dry-run/apply one evidence-backed historical conversation fact repair."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import supabase_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-id", required=True)
    parser.add_argument("--invalid-fact-id", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--field-key", required=True)
    parser.add_argument("--owner-node-id", required=True)
    parser.add_argument("--source-message-id", required=True)
    parser.add_argument("--evidence-span", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--confidence", required=True, type=float)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = supabase_client.get_client().rpc(
        "repair_literal_conversation_fact_v1",
        {
            "p_ledger_id": args.ledger_id,
            "p_invalid_fact_id": args.invalid_fact_id,
            "p_expected_revision": args.expected_revision,
            "p_field_key": args.field_key,
            "p_owner_node_id": args.owner_node_id,
            "p_source_message_id": args.source_message_id,
            "p_evidence_span": args.evidence_span,
            "p_value_text": args.value,
            "p_confidence": args.confidence,
            "p_apply": args.apply,
        },
    ).execute().data
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
