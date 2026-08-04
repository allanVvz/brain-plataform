"""One-off: switch an existing WhatsApp binding's conversation routing to
the deterministic pipeline (persona_slug-driven, reads the persona's own
Graph JSON) instead of an n8n workflow webhook.

Use this after move_whatsapp_binding.py when the moved binding still
carries a decision_owner=n8n_agents / conversation_webhook_url pointing at
another persona's n8n workflow. Only touches metadata + the n8n_workflow_id
column; credential, phone_number_id and connection_status are untouched.

Dry-run by default; pass --apply to actually write.

Usage (on the VPS, inside the api container):
  docker compose --env-file .env.compose exec -T api \
    python scripts/set_binding_deterministic.py --persona-slug vz-lupas --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = API_DIR.parent
for path in (API_DIR, ROOT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services import supabase_client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona-slug", required=True)
    parser.add_argument("--apply", action="store_true", help="Without this flag, only prints the plan.")
    args = parser.parse_args()

    persona = supabase_client.get_persona(args.persona_slug)
    if not persona:
        raise SystemExit(f"persona not found: {args.persona_slug}")

    binding = next(
        (
            b for b in supabase_client.get_workflow_bindings(persona["id"])
            if b.get("provider") == "meta_cloud" and b.get("active")
        ),
        None,
    )
    if not binding:
        raise SystemExit(f"no active meta_cloud binding found for {args.persona_slug}")

    old_metadata = dict(binding.get("metadata") or {})
    new_metadata = {
        **old_metadata,
        "decision_owner": "deterministic",
        "conversation_mode": "deterministic",
        "transport_mode": "provider_direct",
        "pipeline_contract": "conversation_v1",
    }
    new_metadata.pop("conversation_webhook_url", None)
    new_metadata.pop("n8n_outbound_webhook_url", None)

    plan = {
        "persona_slug": args.persona_slug,
        "binding_id": binding["id"],
        "old_decision_owner": old_metadata.get("decision_owner"),
        "old_conversation_webhook_url": old_metadata.get("conversation_webhook_url"),
        "old_n8n_workflow_id": binding.get("n8n_workflow_id"),
        "new_decision_owner": "deterministic",
    }
    if not args.apply:
        print(json.dumps({**plan, "dry_run": True}, ensure_ascii=False, indent=2))
        return

    client = supabase_client.get_client()
    result = (
        client.table("workflow_bindings")
        .update({"metadata": new_metadata, "n8n_workflow_id": None})
        .eq("id", binding["id"])
        .execute()
    )
    supabase_client.update_persona_routing(args.persona_slug, {"process_mode": "internal"})
    supabase_client.insert_event(
        {
            "event_type": "whatsapp.binding_conversation_mode_changed",
            "entity_type": "workflow_binding",
            "entity_id": binding["id"],
            "persona_id": persona["id"],
            "payload": {
                "from": old_metadata.get("decision_owner"),
                "to": "deterministic",
            },
        },
        source="scripts.set_binding_deterministic",
    )
    print(json.dumps({
        **plan,
        "ok": True,
        "applied": True,
        "updated_binding": result.data[0] if result.data else None,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
