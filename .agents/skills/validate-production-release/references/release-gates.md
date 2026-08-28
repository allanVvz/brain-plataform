# Production release gates

| Gate | Required evidence |
|---|---|
| Identity | Full source SHA, installed artifact checksum, configured image and running image ID/digest |
| Database | Migrations 112–127 present; no unsafe public grants; RLS enabled |
| Stability | Zero CAS conflicts for 15 minutes; no orphan processing/proof work |
| Conversation | No branch/fact checksum divergence; no unproved outbound |
| Resources | PostgreSQL below 70% CPU and PostgREST below 20% at rest; disk below 35% after separately approved cleanup |
| Recovery | Data-only backup within 26 hours for migrations; warning for durable non-migration releases; isolated restore proof within 30 days remains required |
| Optional observation | WA Validator and conversational soak may add diagnostic evidence but are never deploy or resume gates |

Fail closed when a metric is unavailable. Do not run cleanup, restart or retry
from this audit.

## Pause scope

The table above is a shared code/infra release gate, so all agents and
transport are paused for that cutover. A persona-scoped content publication is
different: only the target binding/AI is paused when it exists. A new persona
without binding, workflow or transport is already inert, and unrelated
personas remain operational.
