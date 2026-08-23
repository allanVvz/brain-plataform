# n8n template and anti-hardcoded contract

## Canonical source

Treat `api/n8n-workflows/persona-conversation-template.json` as the only provisionable conversation workflow template.

Persona-specific exports such as `baita-vitoria.json` are audit fixtures only. Do not import, provision, clone or evolve them as runtime sources.

The provisioner may substitute only technical bindings such as:

- `__PERSONA_NAME__`
- `__PERSONA_SLUG__`
- `__AGENT_SLUG__`
- `__WEBHOOK_ID__`
- credential and workflow IDs

Business prompts, services, prices, policies, qualification fields and copy must come from the published graph, persona configuration, approved context cards or runtime binding.

## Portable workflow requirements

Require the template to:

1. Validate `persona_slug`, `lead_ref`, `buffer_id`, `correlation_id` and `channel_binding_id`.
2. Load the published graph context from the backend.
3. Resolve the published graph context: authorized knowledge, commercial facts/limits, qualification completion state and persona/agent scope.
4. Build model input only from the canonical event, published context, approved context and technical model configuration.
5. Validate structured model output and the citations it supplies.
6. Preserve a valid grounded model reply: the model owns explanation, recommendation, language, conversational flow and its next natural question.
7. Proof-check cited published evidence plus persona/agent isolation; do not deterministically select FAQ, force `missing_fields[0]`, or rewrite a valid reply into a scripted question.
8. Commit once using the canonical inbound correlation/buffer identity (CAS/atomic claim).
9. Route every node failure to a generic fail-safe handoff with non-secret diagnostics.
10. Start inactive and contain no production URL, phone, token or customer-specific credential.

Provision the same unmodified JSON structure for at least two fixture personas. Differences may exist only in substituted binding values and graph-driven runtime data.

## Backend anti-hardcoded rule

Production code under `api/routes`, `api/services`, `api/core` and `api/workers` must not branch on a real customer, persona, brand, product, campaign, service, domain, FAQ or lead name.

Use:

- `persona_id` / `persona_slug` resolved from authenticated scope;
- `node_type`, `slug`, `relation_type` and graph paths;
- persona `config` and channel binding metadata;
- published graph version/checksum and approved evidence;
- repository/adapters for provider behavior.

Allow real names only in tests, fixtures, one-time migrations, explicitly QA-only routes and legacy audit exports. Ensure those paths cannot become production decision sources.

During review, search the changed production files for newly introduced commercial literals and inspect every match. Do not use a fixed denylist as the only guard; compare literals with persona fixtures, prompts and graph data in the change.

## State and idempotency

- Key processing by the canonical inbound identity, not a retry-generated correlation ID.
- Atomically claim a waiting item before running a decision.
- Enforce one logical decision and one outbound per inbound.
- Make resume idempotent.
- Resume only inbound rows without `payload.conversation_commit`; a completed or processing commit is not safe to replay.
- On graph version change, atomically migrate or reset incompatible conversation state before asking the next question.
- When an explicit new service is detected, replace incompatible historical service state and recalculate missing fields.
- Treat `missing_fields` as completeness/eligibility, not as a mandatory prompt sequence. Product, Offer and Copy belong to the published compiled bundle and must not be rebuilt per inbound.
- Preserve exactly one canonical inbound -> one decision -> one commit -> at most one outbound. Exactly-once prevents duplicate processing; it does not decide conversational content.

## Publication boundary

- Before publication, validate active top-down FAQ accumulation from Persona through the hierarchy to every FAQ used as commercial evidence, including source/status and persona/agent scope.
- Tock Fatal runs on GraphBundle. Aurora remains on its isolated legacy contract until an explicit, audited GraphBundle migration retires that debt; the template/runtime must not blend the two publication contracts.

## Required regression matrix

Test at least:

1. two personas using the same template;
2. one inbound delivered twice by the provider;
3. concurrent workers claiming one buffer;
4. pause, inbound, resume and repeated resume;
5. graph vN conversation against graph vN+1;
6. explicit service change over old history;
7. a direct answer to each required field;
8. fail-safe handoff without automatic price/date/time confirmation.
