# E2E evidence and report contract

## Evidence per turn

Record:

- persona and lead reference on both sides;
- masked channel identity or binding ID;
- exact test message;
- source outbound ID, timestamp, direction and status;
- destination inbound ID, timestamp, direction and status;
- target decision/log ID and correlation ID;
- target outbound ID and timestamp;
- source inbound ID and timestamp;
- latency for each transport leg and agent processing;
- AI state before and after the turn;
- graph version/checksum and qualification state when relevant.

Delivery is proven only by the destination message. Provider `sent`/`delivered` remains supporting evidence.

## Report structure

1. Outcome: pass, fail or safety stop.
2. Scope and environment without credentials.
3. Final state of both agents.
4. Pairing evidence and any asymmetric display names.
5. Timeline with non-secret IDs and HTTP statuses.
6. Qualification fields/stage and terminal handoff evidence.
7. Console, page and API failures.
8. Runtime log diagnosis.
9. Duplicates, context drift or forbidden confirmations.
10. Screenshots and artifact locations.
11. Recommended fixes and exact retest acceptance criteria.

## Redaction

Never include:

- session cookies;
- webhook/provider tokens;
- API keys or auth headers;
- full public/private phone identifiers when masking suffices;
- HAR files with unredacted bodies or headers.

Technical message, lead, workflow, binding, event and graph IDs are acceptable when they are not credentials.
