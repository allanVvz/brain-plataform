# brain-contracts

The only shared source for private Brain HTTP/event schemas.  It accepts v2
conversation envelopes only for a rolling migration and normalizes them to v3.
Apps may import this package and `packages/brain-shared`; they must never
import another application's source tree.
