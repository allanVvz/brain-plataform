# Handoff de implementação — Portal do Cliente com Evolution API

Data do handoff: 2026-07-28
Status: implementação inicial concluída em 2026-07-29; validação integrada com Docker pendente porque o daemon local não estava disponível
Repositório: `C:\Repositores\brain-plataform`
Escopo: autenticação, autorização por persona, portal restrito, CRM, mensageria, abstração de canal WhatsApp, Evolution API, Docker Compose, testes e piloto

## 0. Atualização de implementação — 2026-07-29

Entregue no workspace:

- migrações `061_client_portal_accounts.sql` e `062_whatsapp_channel_bindings.sql`;
- `account_type`, `must_change_password`, perfis e capacidades efetivas;
- bloqueio deny-by-default para contas `client`;
- troca obrigatória de senha;
- gestão de membros por agência;
- APIs `/portal/*`;
- providers Meta/Evolution e webhook Evolution autenticado;
- roteamento do worker por `channel_binding_id`;
- suporte de saída a texto e mídia;
- navegação client, Login, Minha conta, WhatsApp e Acessos;
- Evolution/Redis/Base Evolution no Compose sob profile `evolution`;
- testes isolados de backend e testes/build do dashboard.

Evidências executadas:

```text
Backend: 6 testes passaram.
Frontend: 54 testes passaram.
Next.js: build de produção passou com 37 rotas.
Compose: config base e profile evolution passaram.
Python: py_compile passou.
```

Limitação da sessão de implementação:

- o Docker Desktop não estava ativo; por isso migrations reais, healthchecks,
  pareamento QR e E2E com a imagem Evolution não foram executados;
- o profile Evolution permanece desabilitado por padrão e exige segredos reais;
- digest da imagem continua sendo gate obrigatório antes de produção.

## 1. Objetivo e definição de pronto

O Brain AI deve oferecer, dentro do dashboard existente, uma experiência restrita para clientes finais que não usam a API oficial da Meta. Não será criada outra aplicação, outro domínio ou outra fonte de verdade.

Uma conta `client` autenticada verá somente:

- Mensagens;
- Leads;
- Pipeline comercial;
- conexão e estado do WhatsApp;
- Minha conta.

Uma conta `client` não poderá acessar Grafos, Knowledge Base, Marketing, Assets, Logs, ferramentas administrativas, integrações internas ou configurações do Brain. Esconder menus não é controle de segurança: o backend deve responder `403` para chamadas diretas a APIs internas.

O fluxo-alvo é:

```text
WhatsApp
  -> instância Evolution exclusiva da persona
  -> webhook Evolution autenticado do Brain
  -> lead_buffer
  -> lead + messages
  -> runtime da persona ou atendimento humano
  -> lead_buffer de saída
  -> WhatsAppProvider
  -> Evolution API
  -> WhatsApp
```

A Evolution é somente transporte. Decisão, contexto, RAG, grafo, regras, memória, carrinho, auditoria, handoff, retry e idempotência continuam no Brain AI e sempre sob o escopo de uma persona.

A entrega somente estará pronta quando todos os critérios da seção 19 passarem, incluindo isolamento entre personas, ausência de loops `fromMe`, coexistência com Meta/n8n e preservação das instâncias após reinício.

## 2. Restrições que não podem ser violadas

1. A operação local continua sendo `.env.compose` + Docker Compose:

   ```powershell
   docker compose --env-file .env.compose up -d --build
   ```

2. O dashboard continua chamando o backend por `/api-brain`, via `dashboard/lib/api.ts`. Não adicionar URL hardcoded do backend ou acesso direto do navegador ao Supabase.
3. Não criar nova tabela funcional no banco Brain. Estender `app_users`, `workflow_bindings`, `leads`, `messages`, `lead_buffer`, `personas.config` e estruturas já existentes.
4. O banco `evolution` é uma base lógica isolada, pertencente ao serviço Evolution. Ele não é uma nova tabela do domínio Brain.
5. Não alterar o raciocínio, Graph/RAG ou contrato público `/api/menu/{persona_slug}`.
6. Não expor no navegador, eventos, logs ou payload público:

   - `AUTHENTICATION_API_KEY`;
   - token da instância;
   - callback token completo;
   - segredo n8n;
   - token Meta;
   - `whatsapp_phone_number_id` de outra persona;
   - QR Code depois da expiração/conexão.

7. Não apagar mensagens, leads, KB ou Assets no logout de uma instância.
8. Não implementar exclusão definitiva de instância para agência ou cliente. Essa ação ficará restrita ao Brain Admin.
9. Redis da Evolution não é fonte de verdade.
10. A primeira versão aceita uma única integração WhatsApp ativa por persona.

## 3. Estado real encontrado no repositório

O próximo implementador deve partir deste estado, sem recriar capacidades já existentes.

### 3.1 Autenticação e permissões atuais

- `supabase/migrations/018_auth_users_permissions.sql` já cria:
  - `app_users`;
  - `user_persona_access`;
  - `can_view`, `can_edit` e `can_manage`;
  - RLS service-only.
- `api/services/auth_service.py` já possui:
  - hash `pbkdf2_sha256`;
  - cookie HTTP-only assinado;
  - leitura de `user_persona_access`;
  - filtro de personas;
  - `assert_persona_access`.
- `api/middleware/auth.py` já consulta o usuário e as associações em cada requisição.
- `api/routes/auth.py` já expõe login, `/auth/me` e logout.
- O middleware ainda possui fallback para os dados do cookie assinado quando a consulta de usuário falha. Esse fallback deve ser removido para contas reais: autorização deve falhar fechada quando o banco não puder revalidar usuário e associações.
- `app_users.role` aceita atualmente `admin`, `user`, `viewer` e `operator`.
- Ainda não existem `account_type` nem `must_change_password`.
- Ainda não existe uma verificação central de capacidade `view|edit|manage`.

### 3.2 WhatsApp e mensageria atuais

- `workflow_bindings` existe desde `supabase/migrations/002_knowledge_platform.sql`.
- `supabase/migrations/012_lead_whatsapp_phone_number_id.sql` adiciona `whatsapp_phone_number_id` a `leads`, `messages` e `workflow_bindings`.
- `supabase/migrations/050_whatsapp_runtime_buffer.sql` cria `lead_buffer`, a outbox/inbox durável e um índice único global em `messages.external_message_id`.
- `supabase/migrations/051_whatsapp_buffer_leases.sql` implementa leasing com `FOR UPDATE SKIP LOCKED`.
- `supabase/migrations/052_whatsapp_delivery_reconciliation.sql` alinha callbacks de entrega.
- `supabase/migrations/055_atomic_conversation_handoff.sql` pausa IA e quarentena a fila na mesma transação.
- `supabase/migrations/060_leads_metadata_for_deterministic_cart.sql` usa `leads.metadata` para estado conversacional/carrinho.
- `api/routes/whatsapp.py` recebe Meta e insere `lead_buffer`/`messages`.
- `api/workers/whatsapp_dispatch_worker.py` decide entrada e entrega saída por n8n.
- `api/services/conversation_runtime.py` contém o runtime da persona e deve continuar independente do transporte.
- `api/routes/messages.py`, `api/routes/leads.py` e `api/routes/pipeline.py` são rotas internas. O portal deve ganhar contratos próprios em `/portal/*`.

### 3.3 Dashboard atual

- `dashboard/app/AppShell.tsx` possui navegação única e seletor global de persona.
- O seletor persiste `ai-brain-persona-slug` e `ai-brain-persona-id` em `localStorage`.
- `dashboard/app/login/page.tsx` seleciona a primeira persona após login, mas não redireciona por `account_type`.
- `dashboard/lib/api.ts` centraliza as chamadas e já usa a base `/api-brain`.
- As telas existentes `/messages`, `/leads` e `/pipeline` podem ser reaproveitadas visualmente.
- O dashboard não deve buscar dados de `messages`, `leads` ou eventos diretamente no Supabase.

### 3.4 Infraestrutura atual

- `docker-compose.yml` já contém Postgres, Storage, PostgREST, Kong, migration runner, API, workers, n8n, WA Validator e Caddy.
- O Postgres atual inicia com a base lógica `brain`.
- Não existem `evolution-api`, `evolution-redis`, base/usuário `evolution` ou volumes da Evolution.
- `.env.compose.example` é o contrato versionado de configuração e deve ser atualizado; `.env.compose` populado não deve ser commitado.

## 4. Decisões de arquitetura

### 4.1 Tipos de conta e perfis derivados

Adicionar a `app_users`:

```text
account_type: internal | agency | client
must_change_password: boolean
```

Não aumentar o enum de `role` nesta entrega. O perfil exibido ao frontend será calculado a partir de `account_type`, `role` e da capacidade na persona.

Regras:

| Condição | `access_profile` |
|---|---|
| `internal + admin` | `brain_admin` |
| `internal + operator` | `brain_operator` |
| `internal + viewer` | `brain_viewer` |
| `agency + can_manage` | `agency_manager` |
| `agency + can_edit` | `agency_operator` |
| `agency + can_view` | `agency_viewer` |
| `client + can_manage` | `client_manager` |
| `client + can_edit` | `client_operator` |
| `client + can_view` | `client_viewer` |

O `role` define o teto:

- `viewer`: nunca recebe capacidade efetiva acima de `view`;
- `operator`: nunca recebe capacidade efetiva acima de `edit`;
- `user`: pode receber `view`, `edit` ou `manage`;
- `admin`: só é administração global quando `account_type=internal`.

Uma associação incoerente, por exemplo `role=viewer` com `can_manage=true`, não eleva o usuário. O backend reduz a capacidade ao teto do papel e registra evento de diagnóstico sem dados sensíveis.

`manage_members` não será coluna. É uma capacidade derivada:

```text
brain_admin
OR (account_type=agency AND capacidade efetiva manage na persona)
```

Clientes nunca gerenciam membros, mesmo que sejam `client_manager`.

### 4.2 Autorização por requisição

Criar em `api/services/auth_service.py`:

```python
assert_persona_capability(
    request,
    capability: Literal["view", "edit", "manage"],
    *,
    persona_id: str | None = None,
    persona_slug: str | None = None,
) -> dict
```

Essa função deve:

1. exigir sessão válida;
2. consultar o usuário atual e `user_persona_access` na requisição;
3. resolver exatamente uma persona;
4. não aceitar falta de persona para mutações;
5. aplicar o teto de `role`;
6. retornar a associação/capacidade resolvida;
7. responder `403` genérico sem revelar se outra persona existe.

`assert_persona_access` pode permanecer temporariamente como alias de `view` durante a migração, mas novas rotas não devem usá-lo.

Para contas reais, erro ao consultar `app_users` ou `user_persona_access` resulta em `503` ou `401/403` fail-closed. Não usar dados do cookie como autorização substituta.

### 4.3 Bloqueio deny-by-default de conta cliente

No middleware:

- `client` autenticado pode acessar somente:
  - `/auth/me`;
  - `/auth/logout`;
  - `/auth/change-password`;
  - `/portal/*`.
- Enquanto `must_change_password=true`, pode acessar somente:
  - `/auth/me`;
  - `/auth/logout`;
  - `/auth/change-password`.
- `/access/*` é permitido apenas a Brain Admin e agência; as rotas ainda validam `manage_members`.
- Qualquer API interna chamada por uma conta `client` retorna `403`.
- Rotas públicas existentes continuam públicas somente quando explicitamente listadas pelo middleware.

Não usar prefixos genéricos que liberem rotas futuras. A lista para cliente deve ser uma allowlist curta.

### 4.4 Estado global da automação

Não criar coluna ou tabela nova. Usar:

```json
personas.config.portal = {
  "automation_mode": "ai_with_handoff" | "human_only"
}
```

Precedência:

```text
lead.ai_paused=true                    -> humano
senão automation_mode=human_only      -> humano
senão                                 -> IA com handoff
```

Não confundir `automation_mode` com `personas.process_mode`. O primeiro controla se a IA responde; o segundo escolhe o runtime interno/n8n já existente.

### 4.5 Fonte de verdade das conversas

- `leads`: identidade e estado atual da conversa;
- `messages`: histórico canônico;
- `lead_buffer`: inbox/outbox, retry, lease e dead letter;
- `workflow_bindings`: canal/provedor e estado de conexão;
- `system_events`: auditoria e origem do feed SSE filtrado;
- `assets` + Storage Brain: mídia validada.

Não criar tabela `conversations`, `channels`, `instances` ou `portal_events`.

## 5. Migrações de banco — expand-first

Usar migrações numeradas após a última existente. No estado deste handoff, a última é `060`. Separar expansão, backfill/validação e contração para permitir deploy sem downtime.

### 5.1 Migração 061 — conta e capacidades

Alterações:

```sql
ALTER TABLE public.app_users
  ADD COLUMN IF NOT EXISTS account_type text NOT NULL DEFAULT 'internal',
  ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;
```

Adicionar check para `internal|agency|client` de maneira idempotente e índice por `account_type`.

Backfill:

- todos os usuários existentes permanecem `internal`;
- nenhum usuário existente recebe troca obrigatória de senha;
- o admin QA por token continua sendo tratado como `internal/admin` apenas em ambiente QA/preview.

Não alterar hashes existentes. Novas senhas temporárias usam o mesmo hash forte do serviço atual; nunca persistir senha em texto puro.

### 5.2 Migração 062 — modelo genérico de canal

Adicionar a `workflow_bindings`:

```text
channel                    text, default whatsapp
provider                   text, meta_cloud | evolution_baileys
provider_instance_key      text, nullable
provider_secret_ciphertext text, nullable
connection_status          text
last_connection_at         timestamptz
updated_at                 timestamptz
```

`metadata` já existe e continuará contendo somente dados não sensíveis:

```json
{
  "provider_version": "2.3.7",
  "diagnostic_code": "optional-safe-code",
  "last_event": "CONNECTION_UPDATE",
  "reply_address_kind": "pn|lid|unknown"
}
```

Não colocar QR, API key, token de instância, telefone completo, texto de mensagem ou callback token em `metadata`.

Adicionar:

```text
leads.channel_binding_id          uuid -> workflow_bindings.id
leads.external_contact_id         text
messages.channel_binding_id       uuid -> workflow_bindings.id
lead_buffer.channel_binding_id    uuid -> workflow_bindings.id
```

Neste primeiro passo, todas as colunas novas são nullable. `whatsapp_phone_number_id` continua como está para compatibilidade.

Índices novos:

- busca de binding por `(provider, provider_instance_key)`;
- busca de leads por `(persona_id, channel_binding_id, external_contact_id)`;
- busca de mensagens por `(channel_binding_id, external_message_id)`;
- busca da fila por `channel_binding_id`.

Não criar ainda os índices únicos substitutos antes do backfill e relatório de duplicidades.

### 5.3 Migração/script 063 — backfill e relatório

O backfill Meta deve:

1. localizar o binding ativo pelo `whatsapp_phone_number_id`;
2. preencher `provider='meta_cloud'` e `channel='whatsapp'`;
3. preencher `channel_binding_id` em `leads`, `messages` e `lead_buffer`;
4. preencher `external_contact_id` somente quando a identidade externa for conhecida;
5. produzir relatório de:
   - linhas sem binding;
   - mais de um binding candidato;
   - `external_message_id` duplicado dentro do mesmo binding;
   - contatos duplicados dentro da mesma persona/binding;
   - `lead_id` global que aparece em mais de uma persona.

O backfill não deve escolher silenciosamente entre múltiplos bindings. Registros ambíguos ficam sem `channel_binding_id`, entram no relatório e bloqueiam a fase de contração.

### 5.4 Migração 064 — constraints finais

Somente após relatório limpo e aplicação já escrevendo `channel_binding_id`:

1. criar unicidade parcial de uma integração WhatsApp ativa por persona:

   ```text
   UNIQUE (persona_id, channel) WHERE active=true AND channel='whatsapp'
   ```

2. criar unicidade:

   ```text
   (provider, provider_instance_key)
   WHERE provider_instance_key IS NOT NULL
   ```

3. substituir a unicidade global de `messages.external_message_id` por:

   ```text
   UNIQUE (channel_binding_id, external_message_id)
   WHERE channel_binding_id IS NOT NULL
     AND external_message_id IS NOT NULL
     AND external_message_id <> ''
   ```

4. substituir a unicidade legada de `lead_buffer` baseada em telefone por:

   ```text
   UNIQUE (channel_binding_id, external_message_id)
   WHERE channel_binding_id IS NOT NULL
     AND external_message_id IS NOT NULL
     AND external_message_id <> ''
   ```

5. manter `lead_buffer.idempotency_key` globalmente único;
6. criar unicidade:

   ```text
   UNIQUE (persona_id, channel_binding_id, external_contact_id)
   WHERE channel_binding_id IS NOT NULL
     AND external_contact_id IS NOT NULL
     AND external_contact_id <> ''
   ```

7. remover `NOT NULL` de `lead_buffer.whatsapp_phone_number_id`, pois Evolution não fornece Meta `phone_number_id`;
8. remover, após auditoria, a unicidade global legada de `leads.lead_id`.

O item 8 é obrigatório. O bootstrap local atual cria `leads.lead_id text unique`; enquanto essa unicidade global existir, o mesmo telefone não poderá ser representado em duas personas. Antes de remover, consultar `pg_constraint` e `pg_indexes`, pois o nome exato pode variar entre ambientes.

`lead_id` permanece como compatibilidade, mas novas resoluções de identidade usam:

```text
persona_id + channel_binding_id + external_contact_id
```

### 5.5 Compatibilidade de leitura/escrita

Durante a janela expand-first:

- leitura tenta primeiro `channel_binding_id`;
- para linha Meta legada sem binding, usa `whatsapp_phone_number_id`;
- novas linhas Meta escrevem ambos;
- novas linhas Evolution escrevem `channel_binding_id` e deixam `whatsapp_phone_number_id` nulo;
- o worker nunca escolhe transporte só pelo telefone depois da fase 064.

## 6. Contrato de identidade WhatsApp

### 6.1 Binding

Uma instância Evolution corresponde a exatamente um `workflow_binding`, e esse binding corresponde a exatamente uma persona.

Exemplo seguro:

```json
{
  "id": "uuid",
  "persona_id": "uuid",
  "channel": "whatsapp",
  "provider": "evolution_baileys",
  "provider_instance_key": "brain-<slug-curto>-<sufixo>",
  "connection_status": "connecting",
  "last_connection_at": null,
  "active": true,
  "metadata": {
    "provider_version": "2.3.7"
  }
}
```

O nome da instância não deve conter e-mail, telefone ou nome completo do cliente.

### 6.2 Contato externo

`external_contact_id` é o identificador canônico fornecido pelo transporte, não um telefone inferido.

Para Evolution:

1. se `remoteJid` for um PN confiável, usá-lo;
2. se `remoteJid` for LID e `remoteJidAlt` trouxer PN confiável, usar `remoteJidAlt` como endereço de resposta e preservar ambos em `leads.metadata.identities`;
3. se houver apenas LID, criar/manter o lead com o LID como identidade externa, sem inventar telefone;
4. marcar `leads.metadata.portal.reply_state='awaiting_identification'`;
5. não enfileirar saída enquanto não existir endereço válido.

Exemplo:

```json
{
  "identities": {
    "remote_jid": "masked-or-normalized-id",
    "remote_jid_alt": "masked-or-normalized-id",
    "lid": "provider-id"
  },
  "portal": {
    "reply_state": "ready|awaiting_identification"
  }
}
```

Dados completos de identidade só podem ser retornados a rotas autorizadas da própria persona. Logs usam versão mascarada.

### 6.3 Mensagem externa

Idempotência de webhook:

```text
channel_binding_id + external_message_id
```

Idempotência do trabalho:

```text
lead_buffer.idempotency_key
```

Eventos sem `external_message_id` estável recebem uma chave determinística baseada em binding, tipo de evento e identificadores estáveis do payload; nunca usar timestamp local isoladamente.

## 7. API de autenticação e acessos

### 7.1 `GET /auth/me`

Resposta mínima:

```json
{
  "user": {
    "id": "uuid",
    "email": "cliente@empresa.com",
    "name": "Nome",
    "role": "user",
    "account_type": "client",
    "must_change_password": false
  },
  "access_profile": "client_manager",
  "personas": [
    {
      "id": "uuid",
      "slug": "cliente-a",
      "name": "Cliente A",
      "capabilities": {
        "view": true,
        "edit": true,
        "manage": true,
        "manage_members": false
      }
    }
  ]
}
```

Não retornar `provider_secret_ciphertext`, tokens, config interna completa da persona ou personas não autorizadas.

### 7.2 `POST /auth/change-password`

Body:

```json
{
  "current_password": "required",
  "new_password": "required"
}
```

Regras:

- validar senha atual;
- exigir política mínima e rejeitar senha igual à atual;
- atualizar somente o hash;
- definir `must_change_password=false`;
- não registrar senha em logs/eventos;
- manter ou renovar a sessão de forma explícita;
- aplicar rate limit.

### 7.3 Gestão de acessos pela agência

Rotas:

```text
GET    /access/personas/{slug}/members
POST   /access/personas/{slug}/members
PATCH  /access/personas/{slug}/members/{user_id}
DELETE /access/personas/{slug}/members/{user_id}
```

Todas exigem `manage_members`.

`POST`:

- aceita e-mail, nome e capacidades;
- agência só cria `account_type=client`;
- novo e-mail:
  - gerar senha com CSPRNG;
  - persistir somente hash;
  - `must_change_password=true`;
  - retornar `temporary_password` uma única vez na resposta `201`;
- e-mail existente:
  - não alterar senha;
  - não alterar `account_type`;
  - rejeitar se for conta `internal` ou `agency`;
  - criar/reativar somente a associação permitida;
- não emitir senha em evento de auditoria.

`PATCH`:

- altera `can_view`, `can_edit`, `can_manage`;
- normaliza invariantes: `manage => edit => view`;
- não permite elevar acima do teto do `role`;
- não altera usuário global.

`DELETE`:

- não apaga associação nem usuário;
- define `can_view=false`, `can_edit=false`, `can_manage=false`;
- registra revogação;
- passa a valer na requisição seguinte.

Somente Brain Admin desativa `app_users.is_active` globalmente.

## 8. APIs do portal

Todas as rotas:

- resolvem a persona da requisição;
- exigem capacidade apropriada;
- filtram a consulta no banco pela persona;
- nunca aceitam `persona_id` do body como autoridade;
- não retornam status técnico de worker, stack trace ou payload bruto do provedor.

Para cliente, uma persona ativa é obrigatória. Preferir `persona_slug` em query/path e resolvê-la contra `/auth/me`.

### 8.1 Conversas e mensagens

```text
GET  /portal/conversations?persona_slug=...
GET  /portal/conversations/{lead_id}/messages?persona_slug=...
POST /portal/messages
```

Capacidades:

- listar/histórico: `view`;
- enviar: `edit`.

`POST /portal/messages` aceita texto ou multipart para:

- `text`;
- `image`;
- `audio`;
- `document`.

Regras:

- a mensagem deve referir lead da mesma persona;
- resolver `channel_binding_id` do lead;
- recusar envio se canal desconectado ou endereço de resposta ausente, mantendo histórico legível;
- inserir `messages` e `lead_buffer` antes de chamar transporte;
- responder `202` com estado `pending_send`;
- mídia entra primeiro no Storage Brain;
- o navegador nunca recebe URL interna da Evolution.

Projeção de mensagem:

```json
{
  "id": 123,
  "lead_id": 45,
  "direction": "outbound",
  "sender_type": "human",
  "type": "text",
  "text": "Olá",
  "media": null,
  "status": "pending|sent|delivered|read|failed",
  "created_at": "ISO-8601"
}
```

### 8.2 Leads

```text
GET   /portal/leads?persona_slug=...
GET   /portal/leads/{lead_id}?persona_slug=...
PATCH /portal/leads/{lead_id}
POST  /portal/leads/{lead_id}/ai/pause
POST  /portal/leads/{lead_id}/ai/resume
POST  /portal/leads/{lead_id}/handoff
```

Capacidades:

- GET: `view`;
- PATCH, pause, resume, handoff: `edit`.

Campos mutáveis no primeiro release:

- `stage`;
- `nome`;
- `email`;
- `cidade`;
- `cep`;
- `metadata.portal.notes`;
- `metadata.portal.tags`.

Bloquear alteração de:

- `persona_id`;
- `channel_binding_id`;
- `external_contact_id`;
- `whatsapp_phone_number_id`;
- identidades do provedor;
- estado interno da fila;
- campos Graph/RAG.

### 8.3 Pipeline comercial

```text
GET /portal/pipeline?persona_slug=...
```

Não reutilizar a projeção técnica de `/pipeline/status` ou `/pipeline/events`.

Etapas canônicas:

| Ordem | Slug | Rótulo |
|---:|---|---|
| 1 | `novo` | Novo |
| 2 | `nao_qualificado` | Não qualificado |
| 3 | `contatado` | Contatado |
| 4 | `engajado` | Engajado |
| 5 | `qualificado` | Qualificado |
| 6 | `oportunidade` | Oportunidade |
| 7 | `fechado` | Fechado |
| 8 | `perdido` | Perdido |

A resposta contém colunas e cards de leads, sem erros de worker, IDs internos de outra persona ou payloads de sistema.

### 8.4 Automação

```text
PATCH /portal/personas/{slug}/automation
```

Exige `manage`. Body:

```json
{
  "mode": "ai_with_handoff"
}
```

Atualiza somente `personas.config.portal.automation_mode`, preservando o restante de `config`.

### 8.5 SSE

```text
GET /portal/events/stream?persona_slug=...
```

Regras:

- autenticação pelo cookie HTTP-only same-origin;
- capacidade `view`;
- eventos filtrados pela persona antes da serialização;
- heartbeat no máximo a cada 15 segundos;
- suporte a `Last-Event-ID`;
- payload projetado, nunca `system_events.payload` bruto;
- reconexão no frontend;
- fallback de polling com backoff.

Eventos permitidos:

```text
message.created
message.status_changed
lead.updated
lead.ai_paused
lead.ai_resumed
lead.handoff
whatsapp.connection_changed
```

Em implantação com múltiplos processos, não depender somente de memória local. Usar `system_events` existente como cursor/poll de origem até existir infraestrutura de broadcast aprovada.

## 9. Abstração de transporte

Criar pacote:

```text
api/services/whatsapp_providers/
  __init__.py
  base.py
  registry.py
  meta.py
  evolution.py
  schemas.py
```

Interface:

```python
class WhatsAppProvider(Protocol):
    def provision_instance(...) -> ProvisionResult: ...
    def get_connection_status(...) -> ConnectionResult: ...
    def get_qr_code(...) -> QRResult: ...
    def send_text(...) -> SendResult: ...
    def send_media(...) -> SendResult: ...
    def restart_instance(...) -> ConnectionResult: ...
    def logout_instance(...) -> ConnectionResult: ...
    def normalize_webhook(...) -> list[NormalizedWhatsAppEvent]: ...
```

O evento normalizado deve carregar:

```text
event_type
channel_binding_id
external_message_id
external_contact_id
reply_address
direction
from_me
message_type
text
media_descriptor
occurred_at
provider_status
raw_event_id
```

O worker consome somente o contrato normalizado e seleciona o provider por `workflow_bindings.provider`.

### 9.1 Meta

`MetaWhatsAppProvider` encapsula o comportamento existente sem reescrever o runtime:

- mantém webhooks Meta e validação atual;
- mantém n8n como transporte onde já configurado;
- usa `channel_binding_id` como rota primária;
- mantém `whatsapp_phone_number_id` como identidade específica Meta;
- não muda a persona Baita ou bindings ativos durante o rollout Evolution.

### 9.2 Evolution

`EvolutionWhatsAppProvider` usa `httpx` com:

- base URL somente de `EVOLUTION_API_URL`;
- header global `apikey` vindo do servidor;
- token de instância descriptografado apenas no momento da chamada;
- timeouts distintos de conexão/leitura;
- limite de resposta;
- redirects desabilitados;
- retry somente em operações idempotentes ou com idempotency key do Brain;
- logs redigidos.

Endpoints oficiais a validar na versão fixada:

- `POST /instance/create`;
- `GET /instance/connect/{instanceName}`;
- envio de texto por `/message/sendText/{instanceName}`;
- configuração de webhook por instância;
- endpoints de restart/logout/status correspondentes à versão fixada.

Não codificar contrato com base em exemplos de outra versão sem fixture real da imagem usada.

## 10. Provisionamento e API de canal

Rotas:

```text
GET  /portal/personas/{slug}/channels/whatsapp
POST /portal/personas/{slug}/channels/whatsapp/evolution/provision
POST /portal/personas/{slug}/channels/whatsapp/evolution/connect
POST /portal/personas/{slug}/channels/whatsapp/evolution/restart
POST /portal/personas/{slug}/channels/whatsapp/evolution/logout
```

Permissões:

- GET: `view`;
- provision/connect/restart/logout: `manage`.

### 10.1 Provision

Transação lógica:

1. verificar `EVOLUTION_ENABLED`;
2. exigir `manage`;
3. adquirir lock por persona;
4. consultar binding WhatsApp ativo;
5. se Meta ativo, responder `409`;
6. se Evolution já existe, retornar estado idempotente, sem criar segunda instância;
7. gerar nome não sensível e token forte por instância;
8. chamar Evolution `instance/create` com `integration=WHATSAPP-BAILEYS`, QR habilitado, `syncFullHistory=false` e webhook específico;
9. criptografar token com `secret_store.encrypt_secret`;
10. salvar binding, estado e versão sem QR;
11. retornar estado seguro.

Se a chamada externa tiver sucesso e a persistência falhar, registrar reconciliação necessária e não repetir criação cegamente. O endpoint deve pesquisar a instância pelo nome determinístico antes de retry.

### 10.2 Connect/QR

- QR só é retornado a `manage`;
- nunca persistir QR;
- nunca emitir QR em evento/log;
- usar `Cache-Control: no-store`;
- remover do frontend quando:
  - estado virar conectado;
  - expirar;
  - componente desmontar;
  - usuário trocar persona.

Resposta:

```json
{
  "status": "qr_ready",
  "qr": {
    "base64": "data:image/png;base64,...",
    "expires_at": "ISO-8601"
  }
}
```

### 10.3 Estados normalizados

```text
disabled
provisioning
qr_ready
connecting
connected
disconnected
error
```

O status bruto do provider pode ficar em metadata não sensível; o portal recebe apenas o estado normalizado e diagnóstico seguro.

### 10.4 Logout e exclusão

Logout:

- chama Evolution;
- marca binding desconectado/inativo conforme contrato;
- preserva leads, mensagens, fila, assets e auditoria.

Exclusão definitiva:

- não faz parte das rotas do portal;
- será endpoint/admin action separada;
- exige Brain Admin, confirmação explícita e auditoria.

## 11. Webhook Evolution

Rota pública específica:

```text
POST /webhooks/evolution/{binding_id}/{callback_token}
```

### 11.1 Autenticação

- `callback_token` é derivado com HMAC-SHA256 usando segredo exclusivo do Brain e `binding_id`;
- comparar em tempo constante;
- validar assinatura oficial da Evolution quando a versão fixada a enviar;
- confirmar `provider=evolution_baileys`;
- confirmar que `provider_instance_key` do evento corresponde ao binding;
- rejeitar binding inativo;
- limitar tamanho do body antes do parse;
- aplicar rate limit por binding/IP;
- não incluir token completo em logs de acesso. Configurar redação no proxy/logger.

Não inventar nome de header de assinatura. Capturar fixture da versão `2.3.7`, consultar a documentação da mesma versão e implementar os headers realmente emitidos.

### 11.2 Matriz de eventos

| Evento Evolution | Ação Brain |
|---|---|
| `MESSAGES_UPSERT` inbound | normalizar, resolver lead, persistir message e inbox |
| `MESSAGES_UPSERT` com `fromMe` | confirmação/espelho de saída; nunca nova entrada |
| `MESSAGES_UPDATE` | reconciliar sent/delivered/read/failed |
| `SEND_MESSAGE` | reconciliar saída se possuir correlação confiável |
| `CONNECTION_UPDATE` | atualizar binding e emitir evento seguro |
| `QRCODE_UPDATED` | atualizar estado efêmero; não persistir QR |
| grupos/status/newsletters/calls | marcar ignored sem criar conversa |
| sincronização histórica | ignorar na v1 |
| evento desconhecido | `202 ignored`, métrica e amostra redigida |

Responder rápido após persistência durável. Decisão da IA e download pesado não devem bloquear o ACK do webhook.

### 11.3 Eventos duplicados e fora de ordem

- insert de mensagem usa conflito por `(channel_binding_id, external_message_id)`;
- evento de status nunca regride estado:

  ```text
  pending < sent < delivered < read
  ```

- `failed` registra falha, mas callback atrasado de entrega pode reconciliar segundo regra explícita;
- `fromMe` não enfileira decisão;
- retry do webhook retorna sucesso se o evento já foi persistido.

### 11.4 Mídia recebida

O webhook não autoriza fetch arbitrário.

Fluxo:

1. persistir descritor normalizado;
2. job servidor-servidor usa somente endpoint autenticado da Evolution na base configurada ou conteúdo inline permitido;
3. redirects desabilitados;
4. limites por tipo/tamanho;
5. validar MIME declarado e assinatura real;
6. rejeitar executáveis, HTML e tipos não permitidos;
7. salvar no Storage Brain;
8. associar via `messages.metadata.asset_id/media`;
9. remover material temporário.

Nunca fazer GET para URL arbitrária recebida no payload. O host permitido é o `EVOLUTION_API_URL` configurado, mesmo sendo uma rede privada intencional.

Limites iniciais devem ser configuráveis. Sugestão para piloto:

- imagem: 10 MiB;
- áudio: 20 MiB;
- documento: 25 MiB;
- payload JSON do webhook: 2 MiB.

## 12. Worker e runtime

Refatorar `api/workers/whatsapp_dispatch_worker.py` em duas responsabilidades:

1. entrada:
   - obter binding por `channel_binding_id`;
   - respeitar `ai_paused` e `automation_mode`;
   - executar o runtime existente;
   - criar saída durável;
2. saída:
   - obter provider pelo binding;
   - validar endereço de resposta;
   - chamar `send_text` ou `send_media`;
   - persistir ID externo e estado;
   - aplicar retry/dead letter existente.

Não alterar contratos `ConversationContext`, `ConversationDecision` ou `AgentResponse` para incluir detalhes da Evolution. O runtime recebe texto/mídia normalizada e contexto da persona, não payload bruto do provider.

Leasing continua no banco. Se necessário, evoluir `claim_whatsapp_buffer` sem criar outra fila.

Erros retryable:

- timeout;
- conexão;
- `429`;
- `5xx`;
- desconexão temporária.

Erros não retryable:

- endereço ausente/inválido;
- binding/persona divergente;
- MIME bloqueado;
- autorização rejeitada;
- instância pertencente a outro binding.

Erros não retryable ficam auditáveis como `dead_letter` ou `waiting_human`, sem loop.

## 13. Dashboard

### 13.1 Sessão e guarda de rota

Criar um contexto de sessão compartilhado a partir de `/auth/me`.

Regras:

- `account_type=client` após login:
  - se `must_change_password`, redirecionar para `/account/change-password`;
  - senão redirecionar para `/messages`;
- `internal` e `agency` mantêm o redirecionamento atual;
- guarda client-side melhora UX, mas o backend continua sendo a autoridade;
- ao receber `401`, limpar estado local e ir para `/login`;
- ao receber `403`, não mostrar detalhes de persona proibida.

### 13.2 Navegação

Para cliente:

```text
Mensagens      /messages
Leads          /leads
Pipeline       /pipeline
WhatsApp       /whatsapp
Minha conta    /account
```

Para agência, adicionar `Acessos` somente quando houver ao menos uma persona com `manage_members`.

Não renderizar itens internos para `client`.

### 13.3 Seletor de persona

- origem exclusiva: `session.personas`;
- validar o slug e ID salvos contra a lista atual;
- valor inválido é removido;
- cliente não recebe opção “Todos”;
- Mensagens e WhatsApp exigem uma persona;
- troca de persona cancela requests/SSE anteriores;
- diferentes usuários na mesma persona veem a mesma fonte de dados.

### 13.4 Reaproveitamento das telas

Preservar componentes visuais, mas separar os clientes de API:

```text
api.internal.* -> rotas atuais
api.portal.*   -> /portal/*
```

As telas escolhem o contrato pelo `account_type`; evitar condicionais dispersas em cada fetch.

Viewer:

- sem composer de mensagem;
- sem drag/drop ou alteração de etapa;
- sem pause/resume/handoff;
- sem ações de conexão.

Operator:

- envia e altera etapa;
- pause/resume/handoff;
- não provisiona/reinicia/logout.

Manager:

- todas as operações do operator;
- modo global de automação;
- ciclo de conexão Evolution.

## 14. Docker Compose e configuração

### 14.1 Serviços

Adicionar:

```text
evolution-api
evolution-redis
```

`evolution-redis`:

- imagem fixada por versão/digest;
- volume persistente apenas quando recomendado;
- healthcheck;
- sem porta host;
- `restart: unless-stopped`;
- rede `backend`.

`evolution-api`:

- imagem `evoapicloud/evolution-api:v2.3.7`;
- digest validado e registrado antes do merge;
- healthcheck;
- depende de `db`, bootstrap da base Evolution e Redis;
- volume persistente de instâncias;
- sem porta pública em produção;
- rede `backend`;
- `restart: unless-stopped`.

Não usar `latest`.

### 14.2 Base lógica e usuário próprios

O bootstrap deve criar idempotentemente:

```text
database: evolution
role/login: evolution
password: EVOLUTION_DB_PASSWORD
```

O usuário `evolution` não recebe privilégios na base `brain`. O serviço Brain não usa a base `evolution`.

Como `CREATE DATABASE` não pode rodar dentro de bloco transacional comum, o bootstrap deve:

1. consultar a existência;
2. criar role com senha;
3. criar database fora de `DO`;
4. definir owner/privilégios;
5. não imprimir senha.

### 14.3 Variáveis

Adicionar a `.env.compose.example`:

```text
EVOLUTION_ENABLED=false
EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_VERSION=2.3.7
EVOLUTION_API_IMAGE=evoapicloud/evolution-api:v2.3.7@sha256:<DIGEST_VALIDADO>
EVOLUTION_AUTHENTICATION_API_KEY=
EVOLUTION_DB_PASSWORD=
EVOLUTION_REDIS_PASSWORD=
EVOLUTION_WEBHOOK_HMAC_SECRET=
AI_BRAIN_SECRETS_KEY=
```

Mapear para o backend:

```text
EVOLUTION_ENABLED
EVOLUTION_API_URL
EVOLUTION_AUTHENTICATION_API_KEY
EVOLUTION_WEBHOOK_HMAC_SECRET
AI_BRAIN_SECRETS_KEY
```

O nome exato das variáveis internas da imagem Evolution para Postgres, Redis, histórico e autenticação deve ser confirmado contra a documentação/compose da tag fixada. Não copiar configuração de `develop` ou 2.4.

### 14.4 Versão e licença

Na consulta feita para este handoff, a release oficial marca `v2.3.7` como latest e `2.4.0-rc` como pré-release com mudança de ativação/licença. Portanto:

- usar 2.3.7 no piloto;
- capturar o digest real com `docker buildx imagetools inspect` ou `docker manifest inspect`;
- registrar digest, arquitetura e data no PR;
- não inventar digest no código;
- revisar licença, condições adicionais de marca, telemetria e LGPD antes da produção;
- revalidar release e digest imediatamente antes do merge.

Referências:

- [releases oficiais](https://github.com/evolution-foundation/evolution-api/releases);
- [repositório oficial](https://github.com/evolution-foundation/evolution-api);
- [criação de instância](https://docs.evolutionfoundation.com.br/en/evolution-api/create-instance);
- [instalação Docker](https://docs.evolutionfoundation.com.br/en/evolution-api/install/docker);
- [configuração de webhook](https://docs.evolutionfoundation.com.br/en/evolution-api/set-webhook).

## 15. Segurança e privacidade

Checklist obrigatório:

- [ ] cookies continuam HTTP-only, Secure em produção e SameSite apropriado;
- [ ] nenhuma autorização vem apenas do frontend;
- [ ] conta cliente possui allowlist de API;
- [ ] acesso é reconsultado a cada requisição;
- [ ] erros não revelam existência/nome de outra persona;
- [ ] senha temporária aparece uma vez e não vai para evento/log;
- [ ] segredo Evolution global fica somente em env;
- [ ] token de instância fica em coluna cifrada;
- [ ] chave de criptografia é separada e rotacionável;
- [ ] callback token é comparado em tempo constante;
- [ ] QR usa `no-store` e nunca é persistido;
- [ ] telefone/conteúdo são mascarados em logs;
- [ ] body do webhook possui limite;
- [ ] mídia não permite SSRF;
- [ ] eventos SSE são projetados e filtrados;
- [ ] payload público do site não muda;
- [ ] retenção, exportação e exclusão LGPD são definidas antes da produção.

O fallback de segredo de desenvolvimento em `secret_store.py` não pode ser aceito quando `ENVIRONMENT=production`. O serviço deve falhar ao iniciar se `AI_BRAIN_SECRETS_KEY` não estiver definido.

## 16. Observabilidade

Métricas por provider e binding, sem labels de alta cardinalidade contendo telefone:

```text
webhook_received_total
webhook_rejected_total
webhook_duplicate_total
message_inbound_total
message_outbound_total
message_delivery_latency_seconds
buffer_retry_total
buffer_dead_letter_total
evolution_connection_state
evolution_reconnect_total
media_download_failed_total
portal_forbidden_total
```

Eventos de auditoria permitidos:

```text
access.member_created
access.member_updated
access.member_revoked
portal.automation_changed
whatsapp.instance_provisioned
whatsapp.connection_changed
whatsapp.instance_restarted
whatsapp.instance_logged_out
```

Payload de auditoria contém IDs internos e ações, nunca segredo, QR ou conteúdo completo.

Alertas mínimos do piloto:

- instância desconectada por mais de 5 minutos;
- dead letter maior que zero;
- aumento de duplicidade;
- fila mais antiga acima de 2 minutos;
- `403` anormalmente elevado;
- falha de mídia repetida;
- erro de descriptografia.

## 17. Ordem de implementação

### Fase 0 — baseline e fixtures

- [ ] rodar testes/backend e build/frontend antes de editar;
- [ ] exportar schema real de `leads`, `messages`, `workflow_bindings` e `lead_buffer`;
- [ ] inventariar bindings Meta ativos e duplicidades;
- [ ] capturar fixtures Evolution 2.3.7 sem dados pessoais:
  - criação;
  - QR;
  - connection update;
  - texto inbound/outbound;
  - imagem, áudio e documento;
  - status;
  - LID + `remoteJidAlt`;
  - `fromMe`.

### Fase 1 — segurança e acesso

- [ ] migração 061;
- [ ] `account_type`, perfil derivado e capacidades;
- [ ] fail-closed;
- [ ] deny-by-default para client;
- [ ] `/auth/me` novo;
- [ ] change-password;
- [ ] gestão de membros;
- [ ] testes de isolamento e revogação.

Não iniciar exposição do portal antes de essa fase passar.

### Fase 2 — modelo de canal

- [ ] migração 062;
- [ ] escrita dupla Meta;
- [ ] backfill 063;
- [ ] relatório/limpeza;
- [ ] constraints 064;
- [ ] provar mesmo telefone em duas personas;
- [ ] provar Meta sem regressão.

### Fase 3 — provider Evolution

- [ ] interface/registry;
- [ ] provider Meta;
- [ ] cliente Evolution;
- [ ] provision/status/QR/restart/logout;
- [ ] webhook normalizado;
- [ ] mídia segura;
- [ ] worker por binding/provider;
- [ ] testes com fixtures e servidor falso.

### Fase 4 — portal

- [ ] rotas `/portal`;
- [ ] SSE/polling;
- [ ] navegação por conta;
- [ ] seletor seguro;
- [ ] mensagens/leads/pipeline;
- [ ] WhatsApp;
- [ ] Minha conta;
- [ ] Acessos de agência.

### Fase 5 — infraestrutura

- [ ] base/role Evolution;
- [ ] Redis;
- [ ] Evolution 2.3.7 com digest;
- [ ] volumes/healthchecks;
- [ ] backup e restore testados;
- [ ] `EVOLUTION_ENABLED=false` por padrão.

### Fase 6 — piloto

- [ ] escolher persona sem Meta ativo;
- [ ] criar gestor e viewer;
- [ ] conectar número;
- [ ] iniciar `ai_with_handoff` monitorado;
- [ ] executar matriz E2E;
- [ ] acompanhar por sete dias;
- [ ] expandir somente sem vazamento, loop ou perda.

## 18. Arquivos-alvo esperados

Arquivos existentes a modificar:

```text
supabase/migrations/...
api/main.py
api/middleware/auth.py
api/services/auth_service.py
api/services/supabase_client.py
api/services/secret_store.py
api/routes/auth.py
api/routes/whatsapp.py
api/workers/whatsapp_dispatch_worker.py
dashboard/lib/api.ts
dashboard/app/AppShell.tsx
dashboard/app/login/page.tsx
dashboard/app/messages/...
dashboard/app/leads/...
dashboard/app/pipeline/...
docker-compose.yml
.env.compose.example
infra/...
```

Novos módulos previstos:

```text
api/routes/access.py
api/routes/portal.py
api/routes/evolution_webhook.py
api/services/whatsapp_providers/...
api/services/evolution_webhook_service.py
dashboard/app/whatsapp/page.tsx
dashboard/app/account/page.tsx
dashboard/app/account/change-password/page.tsx
dashboard/app/access/page.tsx
```

Os nomes podem ser ajustados para a convenção do código, mas não concentrar toda a implementação em `main.py`, `portal.py` ou `supabase_client.py`.

## 19. Matriz de testes e aceitação

### 19.1 Autenticação/autorização

- [ ] admin interno acessa módulos globais;
- [ ] agência vê somente personas atribuídas;
- [ ] cliente vê somente APIs `/portal`;
- [ ] `/knowledge/graph`, `/settings` e APIs internas retornam `403` para client;
- [ ] usuário sem associação recebe `403`;
- [ ] revogação vale na próxima requisição;
- [ ] viewer não envia nem altera etapa;
- [ ] operator edita, mas não administra canal;
- [ ] manager administra canal;
- [ ] agência não gerencia persona fora do escopo;
- [ ] agência não cria conta internal/agency;
- [ ] senha temporária é exibida uma vez;
- [ ] `must_change_password` bloqueia o restante.

### 19.2 Escopo de dados

- [ ] toda query/mutation do portal inclui persona resolvida;
- [ ] lead de outra persona retorna `403` ou `404` genérico;
- [ ] mesmo telefone em duas personas cria dois leads;
- [ ] usuário multi-persona vê somente as atribuídas;
- [ ] localStorage inválido é descartado;
- [ ] client nunca possui “Todos”.

### 19.3 Webhook

- [ ] callback HMAC inválido é rejeitado;
- [ ] instância divergente é rejeitada;
- [ ] payload grande é rejeitado;
- [ ] duplicado não duplica message/buffer;
- [ ] fora de ordem não regride status;
- [ ] `fromMe` não dispara IA;
- [ ] grupo/status/newsletter/call é ignorado;
- [ ] LID sem alt vira awaiting identification;
- [ ] `remoteJidAlt` confiável habilita resposta sem inferência;
- [ ] conteúdo/telefone não aparecem em logs.

### 19.4 Mensagens e mídia

- [ ] texto inbound/outbound;
- [ ] imagem inbound/outbound;
- [ ] áudio inbound/outbound;
- [ ] documento inbound/outbound;
- [ ] status pending/sent/delivered/read/failed;
- [ ] URL arbitrária não gera fetch;
- [ ] MIME falso é rejeitado;
- [ ] mídia acima do limite é rejeitada;
- [ ] falha retryable respeita backoff;
- [ ] falha permanente vai para estado auditável.

### 19.5 IA/humano

- [ ] `human_only` registra entrada sem resposta automática;
- [ ] pause individual prevalece;
- [ ] handoff é atômico;
- [ ] resume volta a permitir IA;
- [ ] Graph/RAG consultado pertence à persona do binding;
- [ ] nenhuma informação de outra persona entra no contexto.

### 19.6 Infraestrutura

- [ ] `docker compose --env-file .env.compose config` passa;
- [ ] stack sobe com `EVOLUTION_ENABLED=false`;
- [ ] stack sobe com Evolution habilitada;
- [ ] healthchecks passam;
- [ ] Evolution/Redis não têm porta pública;
- [ ] restart preserva instância;
- [ ] backup/restore preserva base e volume;
- [ ] Meta/n8n continua operacional.

### 19.7 Frontend

- [ ] menu por conta;
- [ ] redirect client para `/messages`;
- [ ] redirect obrigatório de senha;
- [ ] persona ativa exigida;
- [ ] ações desabilitadas por capacidade;
- [ ] SSE reconecta;
- [ ] polling assume em falha;
- [ ] QR some na conexão/expiração/troca de persona;
- [ ] nenhum segredo aparece em Network/HTML/localStorage.

## 20. Comandos de verificação

Backend:

```powershell
Set-Location api
python -m py_compile main.py routes\*.py services\*.py core\*.py workers\*.py
pytest
```

Frontend:

```powershell
Set-Location dashboard
npm test
npm run lint
npm run build
```

Compose:

```powershell
docker compose --env-file .env.compose config
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs db api workers evolution-api evolution-redis
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

Banco:

- relatório de linhas sem `channel_binding_id`;
- relatório de duplicidades por binding;
- relatório de mais de um binding WhatsApp ativo por persona;
- confirmação de zero segredos em `metadata` e eventos;
- confirmação de isolamento entre bases `brain` e `evolution`.

## 21. Rollout

1. Fazer backup da base Brain, da base Evolution e dos volumes relevantes.
2. Aplicar expansão de schema.
3. Publicar backend com leitura compatível e escrita dupla Meta.
4. Executar backfill e resolver ambiguidades.
5. Aplicar constraints finais.
6. Publicar portal ainda oculto por `EVOLUTION_ENABLED=false`.
7. Subir Evolution/Redis internamente.
8. Habilitar uma persona sem Meta.
9. Começar em `human_only` ou `ai_with_handoff` monitorado.
10. Rodar E2E e acompanhar sete dias.

Não ativar Evolution em uma persona que já possui Meta ativo. O endpoint deve reforçar isso com `409`, e o índice parcial deve impedir corrida.

## 22. Rollback

Rollback de aplicação:

- definir `EVOLUTION_ENABLED=false`;
- colocar persona em `human_only`;
- impedir novo provisionamento/envio Evolution;
- manter webhook aceitando e persistindo com comportamento seguro enquanto houver eventos em trânsito;
- preservar histórico e bindings.

Rollback de infraestrutura:

- parar `evolution-api` e `evolution-redis` somente após drenar/estabilizar a fila;
- não remover volumes;
- não apagar base `evolution`.

Rollback de schema:

- não remover colunas de expansão durante o incidente;
- voltar aplicação para leitura Meta compatível;
- constraints novas só são revertidas se houver evidência de impacto e backup;
- nunca restaurar a unicidade global de `leads.lead_id`, pois ela reintroduz colisão entre personas.

## 23. Riscos residuais aceitos

1. Baileys/WhatsApp Web tem maior risco de desconexão, limitação e bloqueio do que Meta Cloud.
2. O cliente é responsável pelo pareamento do número e deve aceitar o caráter transitório do canal.
3. A Evolution pode mudar payloads entre versões; por isso imagem, digest e fixtures são parte do contrato.
4. LID sem endereço alternativo pode deixar conversa visível, mas sem resposta possível.
5. SSE sobre polling de eventos é suficiente para o piloto, mas pode exigir broadcast dedicado em escala futura.
6. Mídia aumenta consumo de Storage e exige política de retenção.
7. A licença/ativação da linha 2.4 muda o risco operacional; upgrade não faz parte desta entrega.

## 24. Decisões pendentes antes da produção, não antes do desenvolvimento

Estas decisões não bloqueiam a implementação local/piloto, mas bloqueiam produção ampla:

- aceite jurídico/comercial do risco Baileys;
- revisão da licença e condições adicionais de marca da Evolution;
- telemetria e subprocessadores;
- política LGPD de retenção/exportação/exclusão;
- limites finais de mídia;
- SLA de handoff humano;
- política de rate limit e abuso;
- procedimento de rotação de chave de criptografia e tokens de instância;
- janela e retenção de backups.

## 25. Entrega esperada do próximo agente

O próximo agente deve implementar as fases na ordem deste documento, manter commits/mudanças auditáveis e anexar ao fechamento:

- migrations aplicadas;
- relatório de backfill;
- fixtures Evolution redigidas;
- digest validado;
- resultados de testes;
- evidência do mesmo telefone isolado em duas personas;
- evidência de bloqueio de client em APIs internas;
- evidência de QR sem cache/persistência;
- evidência de Meta/n8n sem regressão;
- runbook do piloto e rollback testado.

Qualquer necessidade de nova tabela funcional no banco Brain deve interromper a implementação e ser submetida à aprovação antes de criar schema.
