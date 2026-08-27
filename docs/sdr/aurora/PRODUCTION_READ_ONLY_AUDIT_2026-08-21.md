# Auditoria read-only de produção — Aurora — 2026-08-21

Resultado: `FAIL_CLOSED` para publicação, ativação ou E2E.

Nenhuma mutação, deploy, restart, pausa, retomada ou mensagem de WhatsApp foi
executada.

## Identidade e saúde

- HEAD local observado: `29f6ba0616fdb1c53465b06820d87a69d9bb23db`.
- Release API instalado: `09b6c9c7618c…`.
- Imagem workers: `c5936b648327…`.
- Existe skew de SHA entre API e workers.
- `/health/live`: `status=ok`, `workers_embedded=false`.
- `/health/ready`: `status=ready`, Supabase disponível.

## Gates oficiais

- Migrations 112–130: 19/19 presentes.
- Grants inseguros em tabelas/funções: 0/0.
- Tabelas públicas sem RLS: 0.
- CAS conflicts em 15 minutos: 0.
- Buffers críticos: 0.
- Divergência ledger/publicação: 0.
- Publicações ativas sem checksum: 0.
- Outbounds observados em 15 minutos: 1.
- Disco: 34%.
- Backup data-only dentro de 26h: presente.
- Restore isolado dentro de 30 dias: presente, última prova em 2026-08-11.

## Baseline Aurora

- Persona ID: `96e0d69f-9abd-406a-bbb9-3e7977f24ec8`.
- Binding: `6386bc58-ade9-44c4-9211-0f59f23ffca5`, Meta Cloud,
  `decision_owner=n8n_agents`, `runtime_version=graph_agent_runtime_v3`,
  `pipeline_contract=conversation_v3`.
- Workflow: `k5JWkvpQyb8EB3Vw`, ativo, template `graph_agentic_v3`.
- Checksum renderizado do workflow:
  `sha256:2d0e4a748ccad91b2dd010af0fdc67a9d40b3d8d07d0ef229e24f055ceea7aeb`.
- Publicação ativa: versão 67, ID
  `ba580282-c4cd-4466-b4a4-7131ae932677`.
- Checksum ativo:
  `sha256:bb40f955211c4a3173531faac17177e4a2dd794827ba4d6f8b9146021ea46b40`.
- Compiler: `graph-compiler-v3.6.2`; 90 entries, 2.343 chunks e 2.343
  embeddings.

## Stop conditions

O binding da persona alvo Aurora está `active=true`,
`connection_status=connected` e não declara `safety_paused`. Como esta auditoria
era da própria Aurora, isso viola o gate de manter o recurso afetado pausado
durante auditoria e validação. Essa conclusão não se estende a bindings de
outras personas: publicação isolada de outra persona não exige pausar Aurora.
A auditoria também não possui um SHA de release candidato aprovado e observou
um outbound na janela de estabilidade.

Por fail-closed, não foi executado WA Validator, compilação candidata contra o
documento ativo, publicação ou ativação. Pausar binding/transporte requer
autorização produtiva explícita e separada.
