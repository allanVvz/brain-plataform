# Temporary migration adapters

`api/` is retained only as a compatibility adapter for the currently approved
release.  It is not a source for new service images and its former
conversation-template path has been removed.  All new work belongs to an app
under `apps/`.

Removal requires the separately authorized production cutover evidence: four
images from one source SHA, matching contract checksum, green readiness and a
direct WA Validator proof.  This document is intentionally not authorization
to deploy, migrate, clean data or resume any worker.
