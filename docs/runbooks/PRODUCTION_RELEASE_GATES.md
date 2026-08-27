# Gates de release de produção

O contrato detalhado está em
[`RELEASE_ORCHESTRATION.md`](RELEASE_ORCHESTRATION.md). Esta página resume os
gates e substitui listas históricas de migrations e procedimentos manuais.

| Classe | Gates obrigatórios |
|---|---|
| `frontend` | CI e resultado do deploy Vercel |
| `api` | CI, SHA/digest imutável, readiness e rollback automático |
| `runtime` | CI, plano, `release_pause`, drain, digests, verify e aprovação para resume |

Migration adiciona o gate dinâmico `MIGRATION_MANIFEST.json`. Backup novo só é
gate quando o plano informa `backup_mode=fresh_required`; migration aditiva usa
a evidência agendada. Grants/RLS, disco, backup diário e restore periódico são
coletados em `.deploy/evidence/environment.json`, fora do deploy.

O relatório canônico é `.deploy/releases/<sha>.json`. `deploy_validated` e
`workers_resumed` continuam estados distintos. Required reviewers devem ficar
no environment `production-resume`, não em cada etapa técnica anterior.

`binding_safety_pause` e `persona_pause` não pertencem ao lifecycle da release:
são preservadas durante a retomada. O resume remove somente `release_pause`.

WA Validator e soak são diagnósticos opcionais. Quando solicitados, usam o
caminho direto/interno sem WhatsApp real; não substituem SHA, proof,
exactly-once ou isolamento. Release de código nunca publica GraphBundle,
documentos de persona, workflows ou backfills.

Rollback continua obrigatório diante de CAS recorrente, outbound sem proof,
divergência de checksum, trabalho crítico órfão ou pressão de recursos. Uma
autorização de rollback/deploy não autoriza limpeza, migration destrutiva ou
retomada.
