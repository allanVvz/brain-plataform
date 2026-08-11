# Production release gates

| Gate | Required evidence |
|---|---|
| Identity | Full source SHA, installed artifact checksum, configured image and running image ID/digest |
| Database | Migrations 112–115 present; no unsafe public grants; RLS enabled |
| Stability | Zero CAS conflicts for 15 minutes; no orphan processing/proof work |
| Conversation | No branch/fact checksum divergence; no unproved outbound |
| Resources | PostgreSQL below 70% CPU and PostgREST below 20% at rest; disk below 35% after separately approved cleanup |
| Recovery | Data-only backup within 26 hours and isolated restore proof within 30 days |
| Soak | 30–60 minutes after direct validator; no live provider E2E without separate approval |

Fail closed when a metric is unavailable. Do not run cleanup, restart or retry
from this audit.
