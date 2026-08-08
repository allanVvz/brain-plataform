---
name: whatsapp-binding-reassignment
description: Move an active WhatsApp binding (meta_cloud or evolution_baileys) from one persona to another safely — reparent routing, detach affected leads, update the deploy hotfix pairing, verify without sending a live message. Use whenever a phone number's owning persona changes, a persona is retired, or a number is freed up for a different persona.
---

# WhatsApp Binding Reassignment

Moving a WhatsApp phone number's owning persona is routine but has broken
production twice already:

- **2026-08-04** — Baita's number moved to VZ Lupas. Only `persona_id` was
  reparented; the binding kept executing **Baita's** n8n workflow under VZ
  Lupas's identity. Silent — no error, just wrong-persona replies, until
  someone noticed.
- **2026-08-05→06** — Aurora reconnected on a new number. VZ Lupas's lead
  record for "Aurora" kept the **old** number in `external_contact_id`.
  Three real sends reported `status=sent` (the provider accepted them) and
  never arrived — nothing in the code detects this. There is no
  code/dashboard fix for a stale `external_contact_id`; only a real inbound
  message from the correct device repairs it.

Read this whole skill before touching `workflow_bindings` in production.
Treat every step's "why" as load-bearing — skipping one reproduces one of
the two incidents above.

## Establish the plan before touching anything

1. Identify the exact `binding_id`, `provider`, and current `persona_id` for
   both the source and target of every move (a persona reassignment is
   usually two moves — see "Ordering" below).
2. Read the binding's full `metadata` JSON, not just `decision_owner`. If it
   says `n8n_agents`, decide explicitly what the target's routing should be:
   clone another binding's metadata verbatim (safest, when the target
   persona already has a working `n8n_agents`/`graph_agent_runtime_v3`
   config elsewhere), point at a specific existing n8n workflow
   (`set_binding_n8n_webhook.py`), or fall back to `deterministic`
   (`set_binding_deterministic.py`, the safe default for a persona with no
   existing agentic setup).
3. List every lead currently pointing at the binding being moved
   (`leads.channel_binding_id = <binding_id>`). Decide what happens to them
   — see "Leads" below. Never plan to `DELETE` a lead or message row; that
   is a permanent-data-deletion action outside what an agent should do
   unilaterally.
4. Check `.env.compose` on the VPS for `WHATSAPP_META_PERSONA_SLUG` and
   `WHATSAPP_EVOLUTION_PERSONA_SLUG` — see "Deploy hotfix pairing" below.
   If either changes ownership, both must be updated in the same window.

## Ordering

The DB enforces **exactly one active WhatsApp binding per persona**
(`idx_workflow_bindings_one_active_whatsapp_per_persona`, migration 067).
If you are swapping two personas' numbers (A's number → B, B's number → A),
**free the destination persona first**:

```
move A's binding away from A  (A now has zero active bindings)
move B's binding into A       (no collision — A had zero)
```

Doing it in the other order makes the second `UPDATE` collide with the
still-active binding and fail on the unique index.

## Run the move

```bash
docker compose --env-file .env.compose exec -T api \
  python scripts/move_whatsapp_binding.py \
  --from-persona-slug <source> --to-persona-slug <target> \
  [--provider meta_cloud|evolution_baileys]  # only if source has >1 active binding
```

Dry-run by default — review the printed plan (it lists every lead that will
be detached and warns if the target already has a binding of that
provider) before adding `--apply`. This single script now handles both
providers and detaches affected leads automatically
(`channel_binding_id = NULL` + a `metadata.channel_reassignment` note —
never a delete).

**This script does not fix routing.** Immediately after `--apply`, resolve
the reminder it prints:

- Target has no existing agentic setup → `set_binding_deterministic.py --persona-slug <target> --apply`.
- Target should point at a specific, already-existing n8n workflow →
  `set_binding_n8n_webhook.py --persona-slug <target> --webhook-url ... --n8n-workflow-id ... --apply`.
- Target should inherit routing identical to another binding of the same
  persona (e.g. reclaiming a persona's own channel with a different number)
  → clone that binding's `metadata` wholesale via a direct, reviewed SQL
  `UPDATE workflow_bindings SET metadata = ... WHERE id = ...` rather than
  reconstructing fields by hand. `set_binding_n8n_webhook.py` only writes
  the basic `conversation_v1` contract — it does **not** carry over
  `runtime_version`, `pipeline_contract: conversation_v3`, `model`,
  `model_endpoint`, or `reply_source`, so a `graph_agent_runtime_v3` persona
  needs the clone, not the script.

## Leads

`move_whatsapp_binding.py` detaches (`channel_binding_id = NULL`) every lead
still pointing at the moved binding — this alone prevents two concrete
failures: sends to that lead 403 (`whatsapp_outbox.resolve_lead_binding`
checks `persona_id` matches), and any edit to that lead hard-fails with
Postgres `23514` (trigger `enforce_lead_channel_binding`, migration 067,
fires on write, not retroactively).

Beyond that automatic detach, decide per lead:

- **Real, ongoing contacts** (the persona keeps receiving inbound from
  them): leave them alone after the detach. The same trigger auto-fills
  `channel_binding_id` back onto them from whatever binding the persona
  next activates — that's the correct self-healing behavior.
- **Test/throwaway artifacts** (E2E fixtures, "Teste" in the name, a
  contact that only ever existed to validate a prior swap): explicitly
  archive them (`stage`, `ai_paused`, a `metadata.archived_reason` tag) so
  they don't quietly reattach and confuse the next person. Still never
  `DELETE` the row.
- **A lead whose contact number now belongs to the SAME persona from the
  other side** (e.g. persona A's lead representing persona B, after B's
  number becomes A's own number): always archive — the lead would otherwise
  represent the persona talking to itself.

Note: `enforce_lead_channel_binding` (migration 067) force-fills
`channel_binding_id` from the owning persona's active binding on **every**
write whenever that persona has one — read its definition
(`pg_get_functiondef('enforce_lead_channel_binding'::regproc)`) before
assuming otherwise. You cannot keep a lead's `channel_binding_id` null once
its persona reacquires an active binding, not even by setting it explicitly
in the same statement that archives the lead. Archiving means `stage` +
`ai_paused=true` + a `metadata` tag — it does not mean the FK stays empty.

## Deploy hotfix pairing

`api/scripts/configure_whatsapp_hotfix_bindings.py` runs on **every** VPS
deploy (`ops/vps/deploy.sh`), reading `WHATSAPP_META_PERSONA_SLUG` and
`WHATSAPP_EVOLUTION_PERSONA_SLUG` from `.env.compose`. It requires
**exactly one** active binding of the expected provider for the persona
named in each slug — if a move leaves either slug pointing at a persona
with zero matching bindings, the very next deploy raises `RuntimeError`,
`deploy.sh` treats that as a failed deploy and **automatically rolls back
the containers** — while the binding move in the DB is untouched, so the
rollback deploy hits the identical failure again.

The same script also force-resets any `n8n_agents` binding that isn't
*fully* configured (`decision_owner` + `n8n_workflow_id` +
`conversation_webhook_url` all present) back to `deterministic` — this has
silently undone an intentional agentic activation twice already
(2026-08-01, 2026-08-02). Leave every touched binding fully configured
before the next deploy, or explicitly `deterministic`; never half-configured.

**Update both slugs in `.env.compose` on the VPS in the same maintenance
window as any move that changes ownership of the meta_cloud or evolution
"hotfix" persona.**

## Verify — without sending a live message

1. `workflow_bindings`: each involved persona has exactly the active
   binding(s) you intend, with the provider, `decision_owner`, and (for
   `n8n_agents`) `n8n_workflow_id` + `conversation_webhook_url` you expect.
2. Manually check the binding against every rule
   `whatsapp_outbox.validate_direct_binding` enforces (decision_owner valid,
   transport_mode=`provider_direct`, no outbound-webhook keys present,
   provider-specific required fields present, `connection_status` in
   `{connected, open}`) — this is exactly what would 409 at send time, so
   confirm it by reading the row, not by sending.
3. For an Evolution binding that changed owner: `connectionState` live via
   the Evolution API should be unchanged — persona ownership moved, not the
   underlying WhatsApp session. Logging out/restarting the instance is a
   separate, deliberate action; a plain persona move must never touch it.
4. `.env.compose` slugs match the new ownership.
5. `ops/vps/audit.sh` clean.
6. **Do not send a test WhatsApp message as part of this verification.**
   Delivery proof requires a live conversational test, which is a distinct,
   deliberate step (see `.agents/skills/brain-agent-e2e/SKILL.md`) — never
   improvised as a side effect of a binding move.

## Stop conditions

- Target persona already has an **active** binding of the same provider —
  the unique index will reject the write; move that one away first.
- The binding you're moving is mid-conversation (recent inbound with no
  reply yet) — wait for it to settle, or you risk splitting a live thread
  across the ownership change.
- You cannot determine the correct post-move routing (no existing reference
  binding to clone, no known n8n workflow, and the target has no clear need
  for agentic behavior) — default to `deterministic` rather than guessing.
- Any step returns unexpected state (binding still shows the old persona
  after `--apply`, `connectionState` looks different than before) — stop,
  do not retry blindly, diagnose against the plan you wrote in step 1.

## What this skill cannot fix

- A **stale `external_contact_id`** on a lead belonging to a *third* persona
  that still references a number's old owner (2026-08-05→06 incident). This
  is not corrected by any binding move — it self-heals only from a genuine
  inbound message sent from the correct device to that third persona's
  number. If other personas besides the two directly involved in a move
  have ever talked to the number that's moving, expect this exact failure
  mode for them until a physical inbound message occurs.
- **Hard-deleting an Evolution instance.** `DELETE /instance/delete/{name}`
  has no production entry point in this codebase (only test/demo fixtures
  call it) — there is no admin way to fully retire an old Evolution
  instance, only to log it out (which forces a fresh QR scan) or leave it
  connected and reparent its binding, as this skill does.
