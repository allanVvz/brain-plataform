# Chatwoot API Inbox bridge

The transport-owned bridge mirrors the active `meta_cloud` binding selected by
`CHATWOOT_BRIDGE_BINDING_ID`. Meta continues to call
`https://lpapi.vzforeal.com/webhooks/whatsapp`; Chatwoot is a projection of the
canonical `messages` ledger and sends human replies through the existing
transport outbox. Do not configure Meta to call Chatwoot directly.

## Setup and cutover

1. Create a Chatwoot **API** inbox in the existing Community account, add the
   attending agent as an inbox member, and configure its callback URL as
   `https://lpapi.vzforeal.com/webhooks/chatwoot`.
2. Obtain a Chatwoot personal API access token and the API inbox callback
   signing secret through the protected Chatwoot administration path. Put
   those values in the protected server `.env.compose`; never put them in Git,
   tickets, shell arguments, or logs.
3. Set the following transport environment keys in that protected file:
   `CHATWOOT_BRIDGE_ENABLED=true`, `CHATWOOT_BASE_URL`,
   `CHATWOOT_API_ACCESS_TOKEN`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_INBOX_ID`,
   `CHATWOOT_INBOX_IDENTIFIER`, `CHATWOOT_BRIDGE_BINDING_ID`,
   `CHATWOOT_WEBHOOK_SECRET`, and `CHATWOOT_AGENT_ID`. The environment
   bootstrap copies these keys only into `transport.env`.
4. Add `/webhooks/chatwoot*` to the transport route map and gateway dispatch;
   deploy only `gateway,transport` through the selective blue/green workflow.
   The existing `/webhooks/whatsapp*` route remains unchanged. Apply migration
   164 through the schema release workflow after its required
   fresh data-only backup and isolated restore verification. Deploy only the
   `transport` service through the compatible microservice release workflow.
   The dispatch worker runs both WhatsApp dispatch and the Chatwoot bridge;
   the bridge stays inert while its enable flag is false.
5. Reconcile canonical history before considering the cutover complete. The
   read-only audit found 159 Tock Fatal leads and 819 canonical messages in
   scope, from 2026-09-14 through 2026-10-05 UTC. The durable projection queue
   imports eligible inbound messages and successfully sent outbound messages
   chronologically and skips messages already authored in Chatwoot.
6. Use the internal WA Validator for the service canary. For the final live
   WhatsApp check, use only a conversation started by the owner from their own
   test number; confirm inbound, Vitória outbound, one human reply, handoff,
   explicit resume, delivery status, and duplicate-event handling. Never send a
   test message to an unrelated customer.

## Handoff controls

- A public reply authored by the configured Chatwoot agent first hands the lead
  to the runtime, which pauses Vitória and parks outstanding inbound work, then
  enters the existing idempotent transport outbox.
- A private note whose entire content is `/desligar-agente` (also `/desligar`,
  `/desligar-ia`, `/assumir-ia`) pauses Vitória without sending anything to the
  customer.
- A private note whose entire content is `/ligar-agente` (also `/ligar`,
  `/ligar-ia`, `/retomar-ia`) explicitly resumes her.
- Other private notes and messages from other users are ignored by the bridge.
- The bridge marker in `content_attributes` prevents its projected messages
  from cycling back into the outbox. The database operation ledger deduplicates
  webhook retries by Chatwoot message ID.

## Recovery

To disable the bridge, set `CHATWOOT_BRIDGE_ENABLED=false` in the protected
server source environment and run the approved transport-only configuration
rollout. This leaves Meta ingress and all Chatwoot data intact. If a rollout
fails, the blue/green workflow restores the previous transport image and route.
Do not remove migration 164 objects during rollback; they are additive and the
previous transport does not read them. Inspect `chatwoot_bridge_operations`
for `retry` or `dead_letter` rows before re-enabling, using redacted IDs and
status only.

The migration rollback is intentionally a no-op: dropping its tables would
discard webhook receipts and Chatwoot mappings and is not part of the service
rollback. To resume after a schema rollback, restore the data-only backup via
the approved isolated restore procedure and reapply the exact schema release;
then deploy the matching transport release. Never restore into the live
database until the isolated verification succeeds.

## Business hours and the agent

Hours switch the **agent**, never a person. A reply typed in the portal or in the
Chatwoot app is sent immediately, at any hour. Outside the persona's hours the
agent is off (default hours come from the GraphBundle; the Agentes screen can
override them, stored in `personas.config.business_hours`). A dialogue that is
still going (someone answered the lead in the last 10 minutes) keeps its agent
until it pauses; a customer message that arrives after the pause waits, unprocessed,
until the next opening. `set-persona-business-hours.yml` switches the hours for
one persona with a dry-run and an audit event.

