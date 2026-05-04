# Auditoria de arquitetura do banco - AI Brain Dashboard

Data: 2026-05-04

Escopo: varredura estatica do repositorio para identificar uso das tabelas `public` no frontend Next.js, API FastAPI, services, workers, testes, docs e migrations. Nenhum SQL foi executado e nenhuma tabela foi alterada.

## Sumario executivo

O app atual nao acessa Supabase de forma totalmente espalhada. A maior parte do backend passa por `api/services/supabase_client.py`; o frontend passa por `dashboard/lib/api.ts` e rotas HTTP do backend. Existem excecoes diretas no frontend:

- `dashboard/app/assets/page.tsx` le diretamente `assets`.
- `dashboard/components/LiveFeed.tsx` le e assina realtime de `agent_logs`.
- `dashboard/app/messages/page.tsx` assina realtime de `messages`.

As tabelas mais centrais hoje sao:

- CRM: `leads`, `messages`
- Identidade/roteamento: `personas`, `agents`, `persona_role_assignments`, `workflow_bindings`
- Knowledge atual: `knowledge_items`, `kb_entries`, `knowledge_nodes`, `knowledge_edges`, `knowledge_sources`
- RAG novo: `knowledge_intake_messages`, `knowledge_rag_entries`, `knowledge_rag_chunks`
- Operacao: `system_health`, `system_events`, `flow_insights`, `integration_status`, `n8n_executions`, `agent_logs`, `sync_runs`, `sync_logs`

As tabelas mais suspeitas/legadas:

- `lead_buffer`: nao encontrada no codigo.
- `lead_context`: aparece apenas em workflow JSON do n8n.
- `chat_history`: aparece como legado/externo em workflow e analise arquitetural.
- `agent_prompt_profiles`: sem uso runtime no codigo; aparece em migration/testes/prompt.
- `knowledge_artifacts`, `knowledge_artifact_versions`, `knowledge_curation_runs`, `knowledge_curation_proposals`, `knowledge_validation_rules`: arquitetura planejada/migrations/testes/prompt; sem uso runtime direto.
- `kb_intake`: apenas insert best-effort em upload de arquivo do `/kb-intake`; se esta vazia, provavelmente nao e essencial.
- `knowledge_rag_links`: usada por backfill, mas vazia e recentemente removida do fluxo Sofia/Criar.
- `brand_profiles`, `campaigns`, `assets`: tabelas fisicas pouco usadas/vazias; o app usa mais `knowledge_nodes` para brand/campaign/asset semanticos.

Observacao importante: existe uso de `pipeline_status` em `api/services/supabase_client.py`, embora essa tabela nao esteja na lista enviada.

## A) Mapa de uso por tabela

Legenda:

- Frontend: consumo direto via Supabase ou via `dashboard/lib/api.ts`.
- API/services: rotas, services, workers e agentes.
- Migration only: aparece apenas em migrations/testes/docs/prompts, sem uso runtime claro.
- Risco de remover considera o app atual, nao apenas dados vazios.

| Tabela | Uso encontrado | Operacoes | Criticidade | Risco de remover | Classificacao |
|---|---|---:|---|---|---|
| `leads` | `api/routes/leads.py`, `api/routes/messages.py`, `api/services/supabase_client.py`, `api/services/agents_service.py`, dashboards `/`, `/leads`, `/messages`, `/pipeline` via API | read, insert, update | Alta | Alto | Core essencial |
| `messages` | `api/routes/messages.py`, `api/services/supabase_client.py`, `dashboard/app/messages/page.tsx` realtime, pipeline e dashboard via API | read, insert, realtime | Alta | Alto | Core essencial |
| `lead_context` | Somente `api/n8n-workflows/Tock Vitoria Crm Low.json` | externo/legacy | Baixa | Baixo no app; investigar n8n | Candidata a arquivar |
| `lead_buffer` | Nao encontrada | nenhum | Baixa | Baixo, se confirmada vazia | Candidata a remover futuramente |
| `chat_history` | `api/n8n-workflows/Tock Vitoria Crm Low.json`, `api/agents/flow_validator/architecture_analyzer.py` como problema legado | externo/legacy | Baixa | Baixo no app; medio se n8n usa | Candidata a arquivar |
| `personas` | `api/routes/personas.py`, `api/routes/graph.py`, `api/routes/messages.py`, `api/services/supabase_client.py`, filtros globais do dashboard | read, upsert, update | Alta | Alto | Core essencial |
| `agents` | `api/services/agents_service.py`, `api/routes/process.py`, `api/routes/messages.py`, logs/roteamento | read, insert, update | Alta | Alto | Core essencial |
| `persona_role_assignments` | `api/services/agents_service.py` para resolver SDR/Closer/Followup | read, upsert | Alta | Alto para roteamento | Core essencial |
| `agent_prompt_profiles` | Migrations/testes/prompts; sem helper runtime encontrado | migration/prompt only | Baixa | Baixo no app; investigar roadmap | Candidata a arquivar |
| `agent_logs` | `api/routes/logs.py`, `api/services/supabase_client.py`, `api/services/sre_logger.py`, `dashboard/components/LiveFeed.tsx` | read, insert, realtime | Media | Medio | Logs/observabilidade |
| `system_health` | `api/routes/health.py`, `api/routes/logs.py`, `api/services/supabase_client.py` | read, insert | Media | Medio | Logs/observabilidade |
| `system_events` | `api/routes/pipeline.py`, `api/services/event_emitter.py` via `supabase_client.insert_event/get_events` | read, insert | Media | Medio | Logs/observabilidade |
| `flow_insights` | `api/routes/insights.py`, flow validator, dashboard principal/pipeline | read, insert, update | Media | Medio | Logs/observabilidade |
| `integration_status` | `api/routes/integrations.py`, `api/services/supabase_client.py`, health workers, Tools/Integracoes | read, insert, update, upsert | Media | Medio | Logs/observabilidade |
| `workflow_bindings` | `api/routes/knowledge.py`, `api/routes/messages.py`, `api/services/supabase_client.py`, persona routing | read, upsert | Alta | Alto para WhatsApp/n8n | Core/integracoes |
| `n8n_executions` | `api/routes/logs.py`, `api/services/supabase_client.py`, n8n sync/health | read, upsert | Media | Medio | Logs/observabilidade |
| `sync_runs` | `/knowledge/sync/runs`, `vault_sync`, `supabase_client` | read, insert, update | Media | Medio | Sync/auditoria |
| `sync_logs` | `/knowledge/sync/runs/{id}/logs`, `vault_sync`, `supabase_client` | read, insert | Baixa/Media | Baixo/Medio | Sync/auditoria |
| `kb_entries` | `/kb`, `/knowledge/kb/*`, `/knowledge/context`, graph rebuild, chat context fallback, pipeline metrics | read, upsert, update | Alta hoje | Alto imediato | Knowledge legado ativo |
| `kb_intake` | `api/routes/kb_intake.py` upload best-effort, `supabase_client.insert_kb_intake` | insert | Baixa | Baixo se vazia | Candidata a consolidar |
| `knowledge_sources` | uploads manuais e vault sync em `supabase_client`/`vault_sync` | read, insert, update | Media | Medio | Knowledge/source tracking |
| `knowledge_items` | fila de validacao, uploads, vault sync, graph bootstrap, dashboards knowledge/pipeline | read, insert, update | Alta | Alto | Knowledge staging |
| `knowledge_nodes` | `/knowledge/graph-data`, chat context, graph bootstrap, RAG mirror | read, insert, update | Alta | Alto | Knowledge graph |
| `knowledge_edges` | `/knowledge/graph-data`, chat context, graph bootstrap/backfill | read, insert | Alta | Alto para grafos | Knowledge graph |
| `knowledge_node_type_registry` | `/knowledge/graph-data`, layout/hierarquia de grafo | read | Media | Medio | Registry/view candidate |
| `knowledge_relation_type_registry` | `/knowledge/graph-data`, registry de relacoes; UI esta sendo simplificada | read | Baixa/Media | Baixo se UI nao usa; medio se graph API usa | Candidata a simplificar |
| `knowledge_artifacts` | Migrations/testes/prompts/docs; sem runtime direto | migration only | Baixa | Baixo no app; investigar dados | Candidata a arquivar |
| `knowledge_artifact_versions` | Migrations/testes/prompts/docs; sem runtime direto | migration only | Baixa | Baixo no app; investigar dados | Candidata a arquivar |
| `knowledge_curation_runs` | Migrations/testes/prompts; vazia | migration only | Baixa | Baixo | Candidata a remover futuramente |
| `knowledge_curation_proposals` | Migrations/testes/prompts/docs; vazia | migration only | Baixa | Baixo | Candidata a remover futuramente |
| `knowledge_validation_rules` | Migrations/testes/prompts/docs; sem runtime direto | migration only | Baixa | Baixo/Medio se regras forem roadmap | Candidata a view/config |
| `knowledge_intake_messages` | `knowledge_rag_intake.process_intake`, `supabase_client` | insert, update | Media | Medio | RAG intake |
| `knowledge_rag_entries` | `/knowledge/intake`, `/knowledge/rag/backfill`, `knowledge_rag_intake`, `knowledge_rag_backfill` | upsert, read | Alta para RAG novo | Alto se RAG novo ativo | Knowledge/RAG canonico |
| `knowledge_rag_chunks` | `replace_knowledge_rag_chunks` | delete, insert | Alta para RAG novo | Alto se RAG novo ativo | Knowledge/RAG canonico |
| `knowledge_rag_links` | `knowledge_rag_backfill`, helper `upsert_knowledge_rag_link`; vazio | upsert via backfill | Baixa agora | Baixo/Medio | Candidata a opcional/arquivar |
| `brand_profiles` | `/knowledge/brand/{persona_id}`, persona page, helper `get/upsert_brand_profile`; vazia | read, upsert | Baixa/Media | Baixo se vazia; UI espera endpoint | Candidata a consolidar |
| `campaigns` | `get_campaigns`, migrations; app usa principalmente campaign nodes em `knowledge_nodes` | read | Baixa | Baixo se vazia | Candidata a virar view |
| `assets` | `dashboard/app/assets/page.tsx` direto; semantic assets tambem via `knowledge_nodes`; tabela vazia | read direto | Baixa/Media | Medio por rota `/assets` | Candidata a virar view |

## B) Classificacao arquitetural

### Core essencial

- `leads`
- `messages`
- `personas`
- `agents`
- `persona_role_assignments`
- `workflow_bindings`

Essas tabelas sustentam CRM, mensagens, roteamento de agentes/personas e envio via WhatsApp/n8n.

### Logs/observabilidade

- `system_health`
- `system_events`
- `flow_insights`
- `integration_status`
- `n8n_executions`
- `agent_logs`
- `sync_runs`
- `sync_logs`

Podem ter retencao/arquivamento, mas nao devem ser removidas sem substituir dashboards e workers.

### Knowledge/RAG em uso

- `knowledge_sources`
- `knowledge_items`
- `kb_entries`
- `knowledge_nodes`
- `knowledge_edges`
- `knowledge_node_type_registry`
- `knowledge_relation_type_registry`
- `knowledge_intake_messages`
- `knowledge_rag_entries`
- `knowledge_rag_chunks`

### Candidatas a consolidar

- `kb_entries` -> compatibilidade/KB ativa; pode virar view em cima de `knowledge_rag_entries` ou `knowledge_items` validados.
- `knowledge_items` -> staging/draft; pode ficar como fila operacional e nao como fonte final.
- `knowledge_nodes`/`knowledge_edges` -> podem ser derivadas/materializadas de RAG entries + metadados no futuro, mas hoje alimentam o grafo.
- `brand_profiles`, `campaigns`, `assets` -> podem virar views filtrando `knowledge_nodes` ou `knowledge_rag_entries`.
- `kb_intake` -> pode ser substituida por `knowledge_intake_messages`.

### Candidatas a virar view

- `campaigns` -> `select * from knowledge_nodes where node_type='campaign'`
- `assets` -> `select * from knowledge_nodes where node_type='asset'`
- `brand_profiles` -> `select * from knowledge_nodes where node_type='brand'`
- `kb_entries` -> view de compatibilidade em cima de `knowledge_rag_entries` validadas, quando endpoints forem migrados.

### Candidatas a arquivar

- `lead_context`
- `chat_history`
- `knowledge_artifacts`
- `knowledge_artifact_versions`
- `agent_prompt_profiles`
- `knowledge_validation_rules`

Arquivar significa manter fisicamente, remover de telas/fluxos novos e documentar que sao legado/roadmap.

### Candidatas a remover futuramente

Somente depois de 2 a 4 semanas de observabilidade sem leitura/escrita:

- `lead_buffer`
- `knowledge_curation_runs`
- `knowledge_curation_proposals`
- possivelmente `kb_intake`
- possivelmente `knowledge_rag_links`, se relacoes forem descontinuadas tambem no backfill

## C) Proposta de arquitetura menor

Modelo minimo recomendado, preservando compatibilidade:

### CRM

- `leads`
- `messages`

Remover dependencias futuras de `chat_history`, `lead_context` e `lead_buffer`.

### Personas/agentes

- `personas`
- `agents`
- `persona_role_assignments`
- `workflow_bindings`

### Knowledge canonico

- `knowledge_sources`: origem/auditoria de arquivos, upload, URL, vault.
- `knowledge_items`: fila/staging operacional.
- `knowledge_intake_messages`: entrada bruta de intake conversacional/manual.
- `knowledge_rag_entries`: unidade canonica recuperavel.
- `knowledge_rag_chunks`: chunks para embedding/RAG.
- `knowledge_nodes`: indice/materializacao para grafo visual.
- `knowledge_edges`: manter enquanto grafo visual precisa de conexoes. UI pode mostrar apenas Entra/Sai.

Fase posterior:

- `kb_entries` vira view de compatibilidade.
- `brand_profiles`, `campaigns`, `assets` viram views de compatibilidade.
- `knowledge_artifacts*` e `curation*` ficam arquivadas ate existir curadoria real.

### Observabilidade

- `system_events`
- `system_health`
- `integration_status`
- `n8n_executions`
- `agent_logs`
- `sync_runs`
- `sync_logs`

`flow_insights` pode continuar como tabela operacional de alertas, mas no futuro pode ser derivada parcialmente de `system_events`.

## D) Analise especial de tabelas

### `kb_entries`

Uso atual forte. Alimenta `/kb`, `/knowledge/context/{persona_slug}`, pipeline metrics, chat context fallback e validacao. Nao remover agora.

Recomendacao: manter como tabela legada ativa por enquanto. Criar camada `knowledgeRepository` e depois migrar endpoints para `knowledge_rag_entries`. Quando o contrato estabilizar, criar view `kb_entries_compat` ou substituir a tabela por view em uma fase separada.

### `kb_intake`

Uso fraco. Apenas upload do `/kb-intake/upload` tenta inserir arquivo em `kb_intake` best-effort. Se esta vazia, nao esta no caminho principal.

Recomendacao: substituir por `knowledge_intake_messages` e storage metadata. Manter tabela temporariamente.

### `knowledge_items`

Uso forte. E fila de validacao/upload/vault sync e base para dashboard de conhecimento.

Recomendacao: manter como staging operacional, nao como fonte final RAG.

### `knowledge_rag_entries` / `knowledge_rag_chunks`

Arquitetura mais limpa para conhecimento canonico e RAG. Ja existe intake deterministico e backfill.

Recomendacao: promover gradualmente para fonte canonica de leitura.

### `knowledge_artifacts` / `knowledge_artifact_versions`

Existem dados, mas nao encontrei uso runtime direto. Parecem tentativa de identidade canonica/versionamento ainda nao integrada.

Recomendacao: investigar manualmente antes de apagar. Se nao houver UI/processo ativo, arquivar e nao criar novas dependencias.

### `knowledge_nodes` / `knowledge_edges`

Uso forte no grafo, chat context e dashboard. Mesmo se relacoes perderem significado na UI, a estrutura ainda alimenta navegacao, foco e contexto.

Recomendacao: manter. Futuramente podem virar materialized views geradas de `knowledge_rag_entries`.

### `knowledge_curation_runs` / `knowledge_curation_proposals`

Vazias e sem runtime direto.

Recomendacao: candidatas a remocao futura depois de confirmar que nenhum job externo usa.

### `knowledge_rag_links`

Vazia. O fluxo Sofia/Criar nao deve mais criar links obrigatorios. O backfill ainda pode criar links a partir de `knowledge_edges`.

Recomendacao: tornar opcional. Se a decisao de produto for "sem relacoes semanticas", remover do backfill em fase futura e arquivar.

### `lead_context`

Aparece apenas no workflow n8n exportado. Nao encontrei uso no app.

Recomendacao: investigar no n8n real antes de remover.

### `assets`

Tabela fisica vazia, mas `/assets` le direto dela. Ao mesmo tempo, assets semanticos sao extraidos de `knowledge_nodes`.

Recomendacao: substituir `/assets` por API/backend ou view sobre `knowledge_nodes`/`knowledge_rag_entries`. Nao remover antes de ajustar `dashboard/app/assets/page.tsx`.

### `brand_profiles`

Endpoint e persona page ainda chamam. Tabela vazia.

Recomendacao: migrar brand profile para `knowledge_rag_entries` ou `knowledge_nodes(node_type='brand')`; manter endpoint retornando fallback.

### `campaigns`

Helper existe, tabela vazia; campanhas aparecem de verdade como `knowledge_nodes`.

Recomendacao: virar view de compatibilidade.

## E) Estrategia segura de migracao

### Fase 0 - Observabilidade sem mudanca destrutiva

1. Criar uma query diaria para medir leitura/escrita por tabela via logs da API, se possivel.
2. Separar dados "externos n8n" de dados "app AI Brain".
3. Marcar tabelas suspeitas como `deprecated` em documentacao, nao no schema.

### Fase 1 - Repositories/adapters

Criar camada de acesso:

- `api/repositories/leads_repository.py`
- `api/repositories/messages_repository.py`
- `api/repositories/personas_repository.py`
- `api/repositories/knowledge_repository.py`
- `api/repositories/system_repository.py`
- `api/repositories/integrations_repository.py`

No frontend, evitar Supabase direto:

- Trocar `dashboard/app/assets/page.tsx` para API route/backend.
- Trocar `dashboard/components/LiveFeed.tsx` para endpoint + SSE ou manter realtime isolado em `dashboard/lib/repositories/liveRepository.ts`.
- Manter realtime de `messages` isolado em `messagesRepository`.

### Fase 2 - Views de compatibilidade

Criar views novas, sem apagar tabelas:

- `dashboard_lead_funnel`
- `dashboard_brain_stats`
- `dashboard_system_health_latest`
- `dashboard_recent_events`
- `dashboard_integration_status_latest`
- `dashboard_agent_metrics`
- `assets_compat`
- `campaigns_compat`
- `brand_profiles_compat`

### Fase 3 - Migrar leituras

1. Dashboard e pipeline passam a ler views/RPCs.
2. Knowledge context passa a priorizar `knowledge_rag_entries`.
3. `kb_entries` fica apenas fallback.

### Fase 4 - Migrar escritas

1. Sofia/Criar grava em `knowledge_intake_messages` + `knowledge_rag_entries` + `knowledge_rag_chunks`.
2. Upload/vault sync continua em `knowledge_items`, mas promove para RAG de forma explicita.
3. `kb_intake` deixa de receber inserts.

### Fase 5 - Congelar legado

1. Bloquear novas escritas em tabelas legadas no codigo.
2. Manter views/tabelas antigas por 30 dias.
3. Registrar contadores de acesso.

### Fase 6 - Remocao planejada

Somente remover depois de:

- backup/export;
- 0 referencias no codigo;
- 0 chamadas externas confirmadas;
- plano de rollback;
- deploy canario validado.

## F) Refatoracao no codigo

Arquivos que precisam mudar para reduzir acoplamento:

- `api/services/supabase_client.py`: hoje e um "god client"; dividir por dominio.
- `api/routes/knowledge.py`: mistura queue, upload, KB, RAG, graph rebuild e context.
- `api/services/knowledge_graph.py`: ainda depende de `knowledge_items`, `kb_entries`, `knowledge_nodes`, `knowledge_edges`.
- `api/services/knowledge_rag_backfill.py`: ainda cria `knowledge_rag_links`.
- `dashboard/app/assets/page.tsx`: Supabase direto em componente.
- `dashboard/components/LiveFeed.tsx`: Supabase direto/realtime em componente.
- `dashboard/app/messages/page.tsx`: realtime direto de `messages`.
- `dashboard/app/pipeline/page.tsx`: consome varias APIs e faz agregacoes no cliente.
- `dashboard/app/page.tsx`: consome varias APIs e faz agregacoes no cliente.

Repositories sugeridos no backend:

- `api/repositories/leads_repository.py`
- `api/repositories/messages_repository.py`
- `api/repositories/agents_repository.py`
- `api/repositories/knowledge_repository.py`
- `api/repositories/graph_repository.py`
- `api/repositories/system_repository.py`
- `api/repositories/integrations_repository.py`

Repositories sugeridos no frontend, se mantiver Supabase realtime:

- `dashboard/lib/repositories/messagesRealtimeRepository.ts`
- `dashboard/lib/repositories/liveLogsRepository.ts`
- `dashboard/lib/repositories/assetsRepository.ts`

## G) Dashboard: views/RPCs sugeridas

### `dashboard_lead_funnel`

```sql
create or replace view public.dashboard_lead_funnel as
select
  persona_id,
  coalesce(stage, 'novo') as stage,
  count(*)::int as total,
  min(created_at) as first_seen_at,
  max(updated_at) as last_seen_at
from public.leads
group by persona_id, coalesce(stage, 'novo');
```

### `dashboard_brain_stats`

```sql
create or replace view public.dashboard_brain_stats as
select
  persona_id,
  count(*) filter (where status in ('approved','embedded','validated'))::int as validated_knowledge_items,
  count(*)::int as total_knowledge_items,
  count(*) filter (where content_type = 'asset')::int as asset_items,
  count(*) filter (where status in ('pending','needs_persona','needs_category','pending_validation'))::int as pending_items
from public.knowledge_items
group by persona_id;
```

### `dashboard_system_health_latest`

```sql
create or replace view public.dashboard_system_health_latest as
select distinct on (persona_id)
  *
from public.system_health
order by persona_id, snapshot_at desc;
```

### `dashboard_recent_events`

```sql
create or replace view public.dashboard_recent_events as
select *
from public.system_events
where created_at >= now() - interval '7 days'
order by created_at desc;
```

### `dashboard_integration_status_latest`

```sql
create or replace view public.dashboard_integration_status_latest as
select distinct on (persona_id, service)
  *
from public.integration_status
order by persona_id, service, last_check desc nulls last;
```

### `dashboard_agent_metrics`

```sql
create or replace view public.dashboard_agent_metrics as
select
  persona_id,
  agent_type,
  count(*)::int as total_logs,
  count(*) filter (where action like '[ERROR]%')::int as errors,
  avg(latency_ms)::numeric(12,2) as avg_latency_ms,
  max(created_at) as last_seen_at
from public.agent_logs
group by persona_id, agent_type;
```

### `dashboard_message_metrics`

```sql
create or replace view public.dashboard_message_metrics as
select
  l.persona_id,
  count(distinct m.lead_ref)::int as conversations,
  count(*)::int as total_messages,
  count(*) filter (where lower(coalesce(m.sender_type,'')) in ('lead','user','client'))::int as user_messages,
  count(*) filter (where lower(coalesce(m.sender_type,'')) in ('agent','ai','assistant'))::int as assistant_messages
from public.messages m
left join public.leads l on l.id = m.lead_ref
group by l.persona_id;
```

## H) Listas finais

### Tabelas seguras para manter

- `leads`
- `messages`
- `personas`
- `agents`
- `persona_role_assignments`
- `workflow_bindings`
- `agent_logs`
- `system_health`
- `system_events`
- `flow_insights`
- `integration_status`
- `n8n_executions`
- `sync_runs`
- `sync_logs`
- `knowledge_sources`
- `knowledge_items`
- `knowledge_nodes`
- `knowledge_edges`
- `knowledge_node_type_registry`
- `knowledge_rag_entries`
- `knowledge_rag_chunks`
- `knowledge_intake_messages`
- `kb_entries` por compatibilidade atual

### Tabelas suspeitas

- `lead_context`
- `lead_buffer`
- `chat_history`
- `agent_prompt_profiles`
- `kb_intake`
- `knowledge_artifacts`
- `knowledge_artifact_versions`
- `knowledge_curation_runs`
- `knowledge_curation_proposals`
- `knowledge_validation_rules`
- `knowledge_rag_links`
- `brand_profiles`
- `campaigns`
- `assets`

### Exigem investigacao manual

- `lead_context`: confirmar n8n real.
- `chat_history`: confirmar se algum agente/n8n externo ainda escreve.
- `knowledge_artifacts` e `knowledge_artifact_versions`: existem linhas; entender se representam dados que precisam ser preservados.
- `agent_prompt_profiles`: confirmar se vai virar configuracao real de prompts.
- `assets`: ajustar rota `/assets` antes de remover/trocar.
- `brand_profiles`: persona page ainda consulta endpoint.
- `campaigns`: confirmar se n8n externo espera tabela fisica.
- `pipeline_status`: tabela extra nao enviada, mas usada por `/pipeline/status`.

## Proximos patches seguros

1. Criar repositories backend sem alterar comportamento, apenas movendo funcoes de `supabase_client.py`.
2. Trocar `dashboard/app/assets/page.tsx` para usar `dashboard/lib/api.ts` + endpoint backend, removendo Supabase direto.
3. Criar views de dashboard e novos endpoints paralelos, mantendo endpoints atuais.
4. Adicionar endpoint de diagnostico admin que retorna contagem e ultima escrita por tabela suspeita.
5. Remover do backfill a criacao de `knowledge_rag_links` se a decisao de produto for eliminar relacoes semanticas tambem em nivel de dados.

