# Sofia Agent Harness

## Objetivo e limites

O harness torna a sessão da Sofia durável e auditável, coordena especialistas
internos e expõe somente ferramentas tipadas. A fonte canônica é Postgres; os
arquivos de `.runtime/kb-intake-sessions` permanecem apenas como compatibilidade
temporária.

Esta entrega não contém cliente MCP, plugin STDIO, envio de WhatsApp, scheduler
ou SSE. Um adaptador MCP remoto futuro deve fazer discovery dinâmico de
capabilities/tools/resources/prompts e usar Streamable HTTP. Essa separação segue
a arquitetura publicada pelo MCP, sem antecipar credenciais ou execução remota
nesta branch.

## Componentes

- `sofia-coordinator`: classifica a intenção, seleciona capabilities mínimas,
  delega e mantém o escopo original de usuário e persona.
- `graph_card_specialist`: lê cards, cria drafts, valida e publica patches e
  administra relações sem apagar nodes protegidos.
- `campaign_operator`: normaliza contatos, gera previews, cria imports e drafts
  e controla pausa/cancelamento com os serviços de campanha existentes.
- `qa_validator`: valida contrato, Graph, permissões e resultado; não escreve.

A delegação tem profundidade máxima 2, no máximo 12 steps por run e bloqueio de
ciclos. Escritas e operações destrutivas incluem uma validação QA antes do
commit. Delegações nunca ampliam grants.

## Persistência

A migration `088_sofia_agent_harness.sql` cria exatamente três tabelas:

- `agent_sessions`: escopo, snapshot de Graph, seleção, memória, revisão e TTL;
- `agent_runs`: intenção, especialista, plano, artefatos, lease, revisão e
  idempotência;
- `agent_run_steps`: ferramenta/versionamento, efeito, risco, schemas, duração,
  idempotência e erro sanitizado.

As tabelas usam RLS service-only. `PUBLIC`, `anon` e `authenticated` não têm
acesso direto; somente o backend com `service_role` opera os dados. Eventos em
`system_events` recebem payload redigido. Dados privados do run podem conter PII,
mas telefones não são publicados no Graph ou em eventos públicos.

`sofia_plan_sessions` é fonte conservadora de backfill. `agent_prompt_profiles`
armazena os quatro perfis; a tabela `agents` continua reservada aos bots
comerciais. Grants tipados ficam em `user_persona_access.agent_tool_grants`.

## Manifesto e autorização

Cada `ToolManifest` declara nome e versão, proprietário, modelos Pydantic de
entrada e saída, efeito, risco, permissão, escopo, timeout, idempotência, campos
sensíveis e handler. O startup rejeita nomes duplicados, handlers ou schemas
inválidos e ferramentas depreciadas expostas ao modelo.

Leituras, validações, drafts e previews executam diretamente. Uma escrita exige
grant vigente que corresponda a usuário, persona, nome, versão e checksum do
schema. Sem grant, o run fica `awaiting_approval`. Destruição ou cancelamento
definitivo sempre requer confirmação pontual, mesmo quando existe grant.

Toda mutação de API exige `expected_revision`, `idempotency_key` e `reason`. Os
grants não ignoram login, persona, consentimento, opt-out, nodes protegidos,
idempotência ou versão/hash do Graph.

## API

- `POST /agent-harness/sessions`
- `GET /agent-harness/sessions/{id}`
- `POST /agent-harness/sessions/{id}/messages`
- `GET /agent-harness/runs/{id}`
- `POST /agent-harness/runs/{id}/approve`
- `POST /agent-harness/runs/{id}/cancel`
- `GET /agent-harness/capabilities`
- `GET /agent-harness/grants`
- `PUT /agent-harness/grants`

`/kb-intake/*` adota a mesma sessão durável como adapter. A rota histórica
`/sofia/graph-command` continua compatível durante a migração; novas integrações
devem chamar `/agent-harness/*`.

## Cards, Graph e campanhas

`CardDraft` é compatível com Graph JSON 2.1 e preserva tipo, slug, conteúdo,
lifecycle, status, proveniência, fonte, validação, tags, spec e relações
propostas. Publicações usam `Patch`/`PatchOperation`, versão/hash esperados e
idempotência. Conflito de Graph retorna 409 e exige novo preview.

Audience semântica gera node e `belongs_to_persona`. Coortes, contagens e
telefones permanecem no domínio operacional. Persona, Embedded e Gallery são
protegidos; remoções comuns arquivam/revogam.

Campanhas reutilizam parsing, imports, audience, consentimento, preview, draft,
pause e cancel existentes. A Sofia nunca envia mensagens nesta entrega. O modo
`AI_BRAIN_META_MOCK=true` só funciona fora de produção e altera elegibilidade do
preview sem executar tráfego externo nem criar outbox.

## Operação e auditoria

Subir a stack com:

```powershell
docker compose --env-file .env.compose up -d --build
```

O dashboard usa polling e mostra especialista, plano, steps, diffs, ferramentas,
confirmações e resultados. `/marketing/criacao`, `/knowledge/capture` e a sidebar
do Graph compartilham a sessão do harness.

Para um teste Meta controlado em QA, definir temporariamente
`AI_BRAIN_META_MOCK=true`, criar somente preview/draft e verificar que não há
linhas de outbox. Nunca usar esse modo para envio ou em produção.
