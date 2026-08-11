---
name: whatsapp-binding-reassignment
description: Move an active WhatsApp binding between personas safely, including routing selection, lead detachment, deploy pairing and read-only verification. Use when a Meta Cloud or Evolution number changes owner or a persona is retired.
---

# WhatsApp Binding Reassignment

Treat a move as an ownership, routing and lead-integrity change. Read
[references/historical-incidents.md](references/historical-incidents.md) only
when investigating a recurrence or preparing an incident report.

## Establish the plan

1. Record the binding ID, provider, source persona, target persona and complete
   non-secret routing metadata.
2. List leads whose `channel_binding_id` points at the binding. Never delete
   leads or messages.
3. Decide routing before applying: generic deterministic routing or a complete
   clone from another WhatsApp binding already owned by the target persona.
4. Confirm the target has no conflicting active WhatsApp binding. When swapping
   two channels, free the destination first.
5. Confirm no recent inbound is still awaiting a reply.

## Run the reviewed script

Dry-run first:

```bash
docker compose --env-file .env.compose exec -T api \
  python scripts/move_whatsapp_binding.py \
  --from-persona-slug <source> --to-persona-slug <target> \
  --routing deterministic
```

For agentic routing, use:

```bash
docker compose --env-file .env.compose exec -T api \
  python scripts/move_whatsapp_binding.py \
  --from-persona-slug <source> --to-persona-slug <target> \
  --routing clone --routing-binding-id <target-reference-binding-id>
```

Add `--provider meta_cloud|evolution_baileys` only to disambiguate multiple
source bindings. Review the complete plan, then repeat with `--apply` under the
approved maintenance window. Never use manual SQL to clone routing.

The script reparents the existing row, applies the selected routing and detaches
affected leads with audit metadata. It does not delete history or reconnect a
provider session.

## Verify without sending

1. Read binding ownership, provider, connection status, `decision_owner`,
   workflow ID and webhook configuration.
2. Confirm `transport_mode=provider_direct` and all provider-required fields.
3. Confirm affected leads were detached or deliberately archived, not deleted.
4. Confirm production environment pairing variables reflect the intended
   owners; code deploy must not rewrite bindings.
5. Run the read-only production audit and preserve IDs/timestamps with secrets
   masked.

Use `brain-agent-e2e` only for a separately authorized delivery test. A provider
`sent` state is never destination proof.

## Stop conditions

- conflicting active target binding;
- pending inbound or ambiguous conversation ownership;
- missing target routing reference for `--routing clone`;
- changed provider session state;
- any state differing from the reviewed dry-run.

Stop without retrying or sending a test message.
