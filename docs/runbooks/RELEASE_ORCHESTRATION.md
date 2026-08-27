# Orquestração de releases de produção

Este é o contrato canônico. Registros de incidente e runbooks arquivados são
históricos; não definem o estado atual nem adicionam gates à release.

## Plano por impacto

`scripts/classify_deploy_impact.py` lê o diff e produz um plano JSON versionado.
Ele separa o componente alterado (`dashboard`, `api`, `worker`, `migration`,
`content`) da classe operacional:

| Classe | Execução | Pausa | Backup na release | Retomada |
|---|---|---|---|---|
| `frontend` | CI + Vercel | nenhuma | nenhum | não se aplica |
| `api` | imagem imutável, blue/green, readiness e rollback | nenhuma | consulta evidência | automática |
| `runtime` | plano, drain, rollout e verify | `release_pause` | somente se houver risco de dados | aprovação humana |

Mudança desconhecida falha de forma conservadora como `runtime`. Conteúdo de
GraphBundle tem pipeline próprio e isolado por persona; não vira deploy de
runtime por associação.

## Evidência contínua

Backup agendado, restore testado, disco e grants/RLS pertencem ao ambiente.
`.github/workflows/audit-production-environment.yml` executa a coleta read-only
a cada seis horas e grava `.deploy/evidence/environment.json`. A release
consulta esse documento; ela não refaz backup ou restore como rotina.
Na primeira adoção, se o arquivo ainda não existir, o prepare executa uma única
coleta read-only para inicializá-lo; depois disso, evidência ausente ou vencida
é corrigida pelo workflow agendado/manual, não pelo deploy.

Migration compatível usa `backup_mode=evidence_only`. Um novo backup é exigido
somente para SQL destrutivo, header `brain-release-risk: data-risk` ou migration
cuja fonte não pôde ser lida. O header
`-- brain-release-risk: compatible` documenta uma alteração aditiva revisada.

O runner gera `MIGRATION_MANIFEST.json` com nome e SHA-256 de todas as
migrations. O gate compara o manifesto instalado ao ledger
`_compose_migrations`; não existe lista fixa ou contador manual.

## Pausas independentes

- `release_pause`: marcador host-side temporário para rollout compartilhado;
  tem causa, owner, SHA e lifecycle próprios.
- `binding_safety_pause`: proteção durável de um binding. A retomada da release
  preserva e apenas reporta essas pausas.
- `persona_pause`: pausa operacional de uma persona/conteúdo; não é alterada
  por release compartilhada.

Uma flag antiga de binding não pode impedir que o runtime saudável volte para
as demais personas, e a retomada global nunca limpa essa flag.

## Fluxo oficial

O workflow `.github/workflows/deploy-production.yml` oferece:

1. `plan`: classifica e publica o plano JSON, sem produção.
2. `deploy`: executa apenas os gates da classe e termina runtime em
   `awaiting_resume_authorization`.
3. `resume`: usa o environment `production-resume`; este é o único ponto que
   deve ter required reviewers.
4. `rollback`: restaura a release imutável anterior pelo caminho controlado.

Configure `production` para segredos e auditoria sem required reviewers, e
`production-resume` com os mesmos segredos e aprovação humana. A autorização de
deploy não autoriza migration destrutiva, limpeza ou retomada.

No host, o orquestrador chama comandos estreitos e idempotentes: `prepare`,
`migrate`, `rollout-api`, `rollout-worker`, `verify` e `resume`. O estado é
atualizado atomicamente em `.deploy/lifecycle.json` e espelhado como relatório
compacto em `.deploy/releases/<sha>.json`, contendo SHA anterior, classe,
backup mode, gates, pausa e autorização de retomada.

Nenhum desses comandos deve ser executado localmente. Operações produtivas
começam por auditoria read-only/dry-run e usam exclusivamente o host aprovado.
