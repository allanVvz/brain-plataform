# Handoff da release — Sofia Agent Harness

Data: 2026-08-03
Branch: `feat/sofia-agent-harness`
Base preservada: `59399d8` (`feat: bulk campaigns rollout 1`)
Status: implementação e validação local concluídas; pronta para promoção em staging

## 1. Resumo executivo

Esta release transforma a Sofia em uma coordenadora durável de especialistas
internos, com ferramentas tipadas, autorização por grant, confirmação pontual,
idempotência, auditoria redigida e persistência compartilhada entre workers.

Especialistas entregues:

- `graph_card_specialist`: cards, patches, edges e validação de Graph;
- `campaign_operator`: contatos, imports, audience semântica, consentimento,
  preview, draft, pause e cancel;
- `qa_validator`: valida contratos, escopo, Graph e operações sem escrever;
- `sofia`: coordenadora que classifica intenção e limita capabilities e escopo.

O envio de WhatsApp não faz parte desta release. Os cenários E2E terminam em
preview/draft e não chamam provider externo.

## 2. Escopo entregue

### Persistência e segurança

A migration `088_sofia_agent_harness.sql` cria somente as três tabelas aprovadas:

- `agent_sessions`;
- `agent_runs`;
- `agent_run_steps`.

As tabelas têm RLS service-only, revogação para `PUBLIC`, `anon` e
`authenticated`, acesso de `service_role`, índices de sessão/status/lease e
campos de revisão, idempotência e expiração. `sofia_plan_sessions` é backfill
conservador, não a nova fonte canônica.

`user_persona_access.agent_tool_grants` armazena grants tipados por ferramenta,
versão e checksum, com ator, validade e motivo. `agent_prompt_profiles` recebeu
os quatro perfis internos; a tabela `agents` permanece exclusiva aos bots
comerciais.

### Harness e ferramentas

O `ToolManifest` unifica schema e handler. Cada manifest declara:

- nome, versão e especialista proprietário;
- modelos Pydantic de entrada e saída;
- efeito, risco, permissão e escopo de persona;
- timeout, idempotência, campos sensíveis e estado de depreciação.

O registry valida paridade e não publica ferramentas depreciadas ao modelo.
Leituras/drafts/previews são diretos. Escritas exigem grant compatível ou
confirmação. Operações destrutivas sempre exigem confirmação pontual.

Limites aplicados: profundidade de delegação 2, máximo de 12 steps por run,
prevenção de ciclo, timeout por step e QA antes de write/destructive/external.

### Graph e cards

Foram adicionados `CardDraft`, `CardPatch` e `PatchOperation`, compatíveis com
Graph JSON 2.1. Publicações carregam versão/hash esperados e idempotency key;
conflito retorna 409. Persona, Embedded e Gallery continuam protegidos.

Audience semântica cria node e edge `belongs_to_persona`. Coortes, contagens e
PII continuam operacionais e não entram no Graph.

### Campanhas

O especialista usa os serviços de campanha existentes, sem SQL de policy
duplicado. Ferramentas entregues:

- `contacts.parse_list`;
- `imports.preview` e `imports.create`;
- `audiences.resolve_semantic_group` e `audiences.create_semantic_group`;
- `consents.resolve`;
- `campaigns.preview`, `campaigns.create_draft`, `campaigns.pause` e
  `campaigns.cancel`.

A migration `089_fix_semantic_group_replay.sql` corrige um defeito encontrado no
E2E: o trigger de membership era disparado antes do `ON CONFLICT`, impedindo o
replay quando o lead já pertencia ao mesmo grupo. O RPC agora consulta a
membership antes de inserir. Batches não concluídos também deixaram de ser
aceitos como replay bem-sucedido.

### Protocolo dos modelos

O `ModelRouter` preserva `tool_call_id` e usa os papéis/blocos nativos de OpenAI
e Anthropic. Resultados de tools não são mais convertidos em mensagens falsas
de usuário.

### APIs e compatibilidade

Novas rotas autenticadas:

- `POST /agent-harness/sessions`;
- `GET /agent-harness/sessions/{id}`;
- `POST /agent-harness/sessions/{id}/messages`;
- `GET /agent-harness/runs/{id}`;
- `POST /agent-harness/runs/{id}/approve`;
- `POST /agent-harness/runs/{id}/cancel`;
- `GET /agent-harness/capabilities`;
- `GET/PUT /agent-harness/grants`.

Toda mutação recebe revisão esperada, idempotency key e motivo. As rotas
`/kb-intake/*` e `/sofia/graph-command` funcionam como adapters do estado
durável durante a migração.

### Dashboard

`AgentHarnessStatus` usa polling a cada 2 segundos e mostra especialista, status,
mensagem, ferramentas, QA, duração e botões de confirmação/cancelamento. Foi
integrado em `/marketing/criacao`, `/knowledge/capture` e na sidebar da Sofia no
Graph.

## 3. Configuração e operação

Subida canônica:

```powershell
docker compose --env-file .env.compose up -d --build
```

Defaults obrigatórios:

```text
ENVIRONMENT=qa
API_INTERNAL_BASE_URL=http://localhost:8080
NEXT_PUBLIC_API_BASE_URL=/api-brain
AI_BRAIN_META_MOCK=false
```

`AI_BRAIN_META_MOCK=true` é permitido somente em QA/test/preview/development/
local. Ele torna o preview Meta elegível, mas não envia mensagem nem cria
outbox. Em produção o flag é ignorado.

Auditoria rápida:

```powershell
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs -f db api workers
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

## 4. Evidências de aceitação

### E2E normal — provider indisponível

- sessão durável retomada após rebuild/restart e atendida por dois workers;
- 2 contatos normalizados e deduplicados;
- import criado, 2 consentimentos `pending`;
- preview de campanha com 2 selecionados, 0 elegíveis e 2 bloqueados por
  provider indisponível;
- draft criado, pausado e cancelado com QA e confirmação;
- zero envio e zero outbox.

IDs locais para auditoria:

- session: `dbf2cb9c-6d49-58b9-8414-c9c5bd3e00bf`;
- import batch: `1a37c67e-fc4a-4c08-b0ba-8fd58a592d45`;
- campaign: `971acadb-18b2-49c4-9e39-ba686097ee7d`.

### E2E Meta mock — sem tráfego externo

- health: provider `meta_cloud`, `ready=true`, `mock=true`;
- 2 selecionados, 2 elegíveis, 0 bloqueados;
- draft criado após confirmação e QA;
- zero step external e zero outbox;
- ambiente restaurado para `AI_BRAIN_META_MOCK=false` ao final.

IDs locais:

- run: `a92a659c-903f-46bd-a245-750b3159d703`;
- campaign: `c9ac3512-6d53-45aa-9bd0-21df94d445f3`.

### E2E em navegador real

Em `/marketing/criacao`, com operador restrito a `baita-conveniencia`:

- login e seleção da persona validados;
- sessão `/kb-intake` refletida em `agent_sessions`;
- lista enviada pelo browser e delegada ao `campaign_operator`;
- preview mostrou 2 contatos únicos antes da escrita;
- UI exibiu confirmação e os steps `contacts.parse_list` e `imports.preview`;
- após confirmar, UI exibiu `qa.validate_operation` e `imports.create` como
  `completed`;
- batch final contém 2 linhas e atualizou os 2 leads já existentes.

IDs locais:

- session: `cf0be467-3a2b-401c-b0a8-ff88329dad88`;
- run concluído: `0781bdfc-bcde-48ad-ad36-41081081a7ba`;
- batch: `7c482f56-237c-41f2-8295-988c916a28b3`.

Consultas de auditoria retornaram:

- telefones no Graph: `0`;
- telefones em `system_events`: `0`;
- outbox do campaign mock: `0`;
- consentimentos pendentes do primeiro import: `2`.

### Testes automatizados

Resultado final reproduzido em 2026-08-03:

- backend completo: `391 passed, 2 skipped, 3 warnings` em `560.86s`;
- harness e campanhas: `21 passed`;
- FAQ, adapter Graph, memória de sessão e loop v2: `30 passed`;
- cenários focados de Graph/crawler/contratos: `27 passed, 1 skipped`;
- `python -m compileall -q api`: verde;
- `npm run build`: verde, incluindo TypeScript e geração de 38 páginas;
- `git diff --check`: verde.

Os três warnings do backend são preexistentes e não bloqueantes: depreciação do
`TestClient` e dois campos Pydantic chamados `validate`.

### Smoke local pós-rebuild

- `docker compose --env-file .env.compose up -d --build`: concluído;
- API, DB, Kong, Storage e n8n: `healthy`; workers ativos;
- `GET /health`: `status=ok`, `workers_embedded=false`;
- `GET /api/menu/baita-conveniencia`: `ok=true` e site público reconstruído;
- migrations: 088 já aplicada e 089 aplicada com `MIGRATIONS APPLIED OK`;
- RLS ativo nas três tabelas e `SELECT=false` para `anon` e `authenticated`;
- `AI_BRAIN_META_MOCK=false` confirmado dentro do container da API.

A conta local `codex-harness-qa@local.test`, criada somente para o E2E, foi
desativada e marcada para troca de senha. Ela não foi apagada porque o banco
corretamente bloqueou o `ON DELETE SET NULL` sobre consentimentos append-only;
isso preserva a trilha de auditoria.

## 5. Observabilidade, PII e segurança

- payload privado de run/step pode conter PII operacional;
- respostas públicas, logs e `system_events` usam redaction;
- UUIDs não são confundidos com telefones pelo redactor;
- grants não ampliam persona nem ignoram consentimento, opt-out, versão do Graph
  ou nodes protegidos;
- browser/anon não acessam diretamente as três tabelas;
- nenhum segredo Meta, n8n ou de modelo aparece nos payloads públicos.

## 6. Rollback

Rollback de aplicação:

1. desativar consumidores de `/agent-harness/*` e manter os adapters legados;
2. publicar o commit anterior da API/dashboard;
3. manter as tabelas e eventos para auditoria — não apagar runs/sessions;
4. garantir `AI_BRAIN_META_MOCK=false`;
5. se necessário, revogar todos os grants em
   `user_persona_access.agent_tool_grants` sem remover o acesso à persona.

Não é recomendado fazer downgrade destrutivo das migrations 088/089. Elas são
aditivas e o rollback seguro é de código/feature flag.

## 7. Itens fora desta release

- MCP externo, STDIO e marketplace de plugins;
- cliente MCP remoto e credenciais de conectores;
- execução arbitrária de código;
- SSE;
- scheduler avançado, retries de provider e envio WhatsApp real;
- dashboard analítico completo;
- redesenho geral da plataforma.

O futuro adaptador MCP deve usar discovery dinâmico e Streamable HTTP, com
allowlist, OAuth, health check, isolamento e cache de capabilities.

## 8. Checklist de promoção

Concluído localmente:

- [x] suíte backend integralmente verde;
- [x] build do dashboard verde;
- [x] migrations 088 e 089 aplicadas pelo Compose;
- [x] RLS/revokes conferidos;
- [x] `AI_BRAIN_META_MOCK=false` confirmado na API;
- [x] smoke de login, persona, sessão, preview e confirmação;
- [x] confirmação de zero outbox durante os E2Es;
- [x] nenhum grant persistente concedido por padrão.

Obrigatório na promoção:

- [ ] aplicar migrations 088 e 089 em staging;
- [ ] conferir RLS/revokes em staging;
- [ ] confirmar `AI_BRAIN_META_MOCK=false` no ambiente promovido;
- [ ] repetir smoke de login, persona, sessão, preview e confirmação;
- [ ] confirmar zero outbox durante o smoke;
- [ ] revisar os grants iniciais;
- [ ] monitorar `agent_runs.status=failed` e leases expirados;
- [ ] registrar o commit promovido e a janela da release.

## 9. Arquivos de referência

- `docs/architecture/SOFIA_AGENT_HARNESS.md`;
- `supabase/migrations/088_sofia_agent_harness.sql`;
- `supabase/migrations/089_fix_semantic_group_replay.sql`;
- `api/routes/agent_harness.py`;
- `api/services/agent_harness.py`;
- `api/services/agent_harness_tools.py`;
- `api/services/agent_tool_registry.py`;
- `dashboard/components/agents/AgentHarnessStatus.tsx`;
- `tests/test_agent_harness.py`.
