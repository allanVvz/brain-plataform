# Infraestrutura self-hosted de produção

A definição versionada é [`docker-compose.yml`](../docker-compose.yml), mas ela
é operada somente no host final aprovado. Não execute Docker/Compose localmente.

O pipeline instala artefatos checksummed e imagens imutáveis no host, seguindo
o plano de impacto. Os comandos oficiais e idempotentes são:

- `release-prepare.sh`
- `release-migrate.sh`
- `release-rollout-api.sh`
- `release-rollout-worker.sh`
- `release-verify.sh`
- `release-resume.sh`

`deploy.sh` permanece apenas como compatibilidade de bootstrap/rollback; não é
o caminho normal de release. Veja
[`docs/runbooks/RELEASE_ORCHESTRATION.md`](../docs/runbooks/RELEASE_ORCHESTRATION.md)
e [`docs/VPS_PRODUCTION_RUNBOOK.md`](../docs/VPS_PRODUCTION_RUNBOOK.md).
