"""One-off: move an active Meta Cloud WhatsApp binding from one persona to
another, in place.

This re-parents the existing workflow_bindings row (same id, same
provider_secret_ciphertext, same whatsapp_phone_number_id) rather than
creating a new one, so the encrypted Meta credential is never re-entered,
re-encrypted, or exposed as plaintext anywhere. Because it's a single row
throughout, the partial unique index on (whatsapp_phone_number_id) WHERE
active is never at risk of a two-active-rows conflict.

Dry-run by default; pass --apply to actually write.

Usage (on the VPS, inside the api container):
  docker compose --env-file .env.compose exec -T api \
    python scripts/move_whatsapp_binding.py \
    --from-persona-slug baita-conveniencia --to-persona-slug vz-lupas --apply
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
    parser.add_argument("--from-persona-slug", required=True)
    parser.add_argument("--to-persona-slug", required=True)
    parser.add_argument("--workflow-name", default=None, help="Optional rename; keeps the original if omitted.")
    parser.add_argument("--apply", action="store_true", help="Without this flag, only prints the plan.")
    args = parser.parse_args()

    source_persona = supabase_client.get_persona(args.from_persona_slug)
    target_persona = supabase_client.get_persona(args.to_persona_slug)
    if not source_persona:
        raise SystemExit(f"persona not found: {args.from_persona_slug}")
    if not target_persona:
        raise SystemExit(f"persona not found: {args.to_persona_slug}")

    source_binding = next(
        (
            b for b in supabase_client.get_workflow_bindings(source_persona["id"])
            if b.get("provider") == "meta_cloud" and b.get("active")
        ),
        None,
    )
    if not source_binding:
        raise SystemExit(f"no active meta_cloud binding found for {args.from_persona_slug}")

    existing_target_binding = next(
        (
            b for b in supabase_client.get_workflow_bindings(target_persona["id"])
            if b.get("provider") == "meta_cloud"
        ),
        None,
    )

    plan = {
        "binding_id": source_binding["id"],
        "whatsapp_phone_number_id": source_binding.get("whatsapp_phone_number_id"),
        "from_persona_slug": args.from_persona_slug,
        "to_persona_slug": args.to_persona_slug,
        "target_already_has_meta_binding": bool(existing_target_binding),
    }
    if existing_target_binding:
        plan["warning"] = (
            "Target persona already has a meta_cloud binding row; moving the "
            "source row on top of it may leave a stale duplicate. Review before --apply."
        )

    if not args.apply:
        print(json.dumps({**plan, "dry_run": True}, ensure_ascii=False, indent=2))
        return

    client = supabase_client.get_client()
    update_fields: dict = {
        "persona_id": target_persona["id"],
    }
    if args.workflow_name:
        update_fields["workflow_name"] = args.workflow_name

    result = (
        client.table("workflow_bindings")
        .update(update_fields)
        .eq("id", source_binding["id"])
        .execute()
    )

    supabase_client.insert_event(
        {
            "event_type": "whatsapp.binding_moved",
            "entity_type": "workflow_binding",
            "entity_id": source_binding["id"],
            "persona_id": target_persona["id"],
            "payload": {
                "from_persona_slug": args.from_persona_slug,
                "to_persona_slug": args.to_persona_slug,
                "whatsapp_phone_number_id": source_binding.get("whatsapp_phone_number_id"),
            },
        },
        source="scripts.move_whatsapp_binding",
    )
    supabase_client.update_persona_routing(args.to_persona_slug, {"process_mode": "internal"})

    print(json.dumps({
        **plan,
        "ok": True,
        "applied": True,
        "updated_binding": result.data[0] if result.data else None,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
