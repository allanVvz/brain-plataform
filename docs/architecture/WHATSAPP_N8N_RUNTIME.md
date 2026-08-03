# WhatsApp / n8n runtime

Referência única e atual do pipeline de mensagens WhatsApp. Substitui a
descrição legada em `PROJECT_REQUIREMENTS.md` §11, que documenta um modelo
(`personas.process_mode` + `outbound_webhook_url`) que a migration
`069_block_legacy_n8n_direct_transport.sql` já bloqueia para novas escritas.
Atualizado em 2026-08-01 após uma sessão de correção ao vivo (migrations
073-077) e um E2E real em produção entre as personas Baita e Aurora.

## 1. Duas pipelines, não confundir

### 1.1 Pipeline real de produção (a que importa)

```text
Evolution/Meta webhook -> lead_buffer (inbound, buffered)
  -> WhatsAppDispatchWorker.claim_whatsapp_buffer (poll 2s, FOR UPDATE SKIP LOCKED)
  -> decision_owner = deterministic | n8n_agents
       deterministic: conversation_runtime.execute_pipeline() direto no worker
       n8n_agents:    POST /internal/conversations/{context,decide,commit} via n8n
  -> conversation_runtime.commit() (função compartilhada pelos dois motores)
       decide route/handoff, grava lead.metadata/stage, chama
       whatsapp_outbox.enqueue_outbound() se houver reply_text
  -> lead_buffer (outbound, pending_send)
  -> WhatsAppDispatchWorker._dispatch_outbound
  -> provider.send_text/send_media (Evolution ou Meta)
  -> complete_whatsapp_outbound_result (grava wamid, marca sent/waiting_human)
```

Roteamento é **exclusivamente**
`workflow_bindings.metadata.decision_owner` (`deterministic` | `n8n_agents`),
não `personas.process_mode` — esse campo só afeta a rota legada `/process`
descrita abaixo. `activate_persona_whatsapp_binding()` é o único caminho
correto para ativar um binding; preserva `decision_owner` exatamente como
configurado, nunca força para `deterministic` (bug real corrigido pela
migration 074, confirmado ao vivo em 2026-07-31).

### 1.2 Rota legada `/process`

`api/routes/process.py`, governada por `personas.process_mode`
(`internal`/`n8n`), usa `agents.sdr.SDRAgent`/`CloserAgent` — um motor de
decisão **diferente** do `conversation_runtime`, sem fila, sem
idempotência por `lead_buffer`. `PROJECT_REQUIREMENTS.md` §11 documenta só
essa rota. Não é o caminho que Baita ou Aurora usam em produção hoje. Não
estender essa rota; toda automação nova entra pela pipeline 1.1.

## 2. Máquina de estados do `lead_buffer`

Estados: `received`, `buffered`, `processing`, `pending_send`, `retry`,
`sent`, `delivered`, `read`, `dead_letter`, `waiting_human`.

- `claim_whatsapp_buffer` reivindica `buffered`/`retry`/`pending_send` (por
  `available_at`) e `processing` com lease expirado sem flag de tentativa
  ambígua — sempre chama `quarantine_expired_whatsapp_attempts` primeiro.
- `mark_whatsapp_attempt` grava `{kind}_attempt_started_at` no `payload`
  antes de uma chamada externa (decisão ou envio ao provider). Uma
  reexecução na mesma linha (`mark_whatsapp_attempt` retorna `false`)
  registra `whatsapp.safety_violation` e move a linha para
  `waiting_human` — nunca reprocessa silenciosamente.
- `record_whatsapp_safety_violation` pausa a IA do lead
  (`leads.ai_paused=true`), move o inbound em voo para `waiting_human`, e
  após 3 violações distintas em 5 minutos marca o binding inteiro como
  `safety_paused` (bloqueia todo envio até intervenção humana).
- `handoff_whatsapp_lead(_state)` pausa a IA e varre `lead_buffer` do lead
  para `waiting_human` — **escopado a `direction = 'inbound'` desde a
  migration 077**. Antes disso, a varredura também descartava respostas já
  decididas e ainda em `pending_send`, sem tentativa de envio e sem erro
  (achado ao vivo em 2026-08-01: 3 mensagens corretas na plataforma, zero
  entregues).
- `requeue_waiting_human_whatsapp_buffer` (migration 075, chamada por
  `resume_lead`) é o único caminho que tira uma linha **inbound** de
  `waiting_human` de volta para `retry`. Outbound em `waiting_human` nunca
  é reenfileirado automaticamente — reenviar conteúdo já decidido e
  potencialmente desatualizado seria incorreto; exige decisão humana.
- `complete_whatsapp_outbound_result` grava o `external_message_id` real
  (wamid) só na linha de `lead_buffer` cujo `id` bate exatamente, mas o
  `UPDATE` em `messages` era escopado só por
  `(channel_binding_id, correlation_id)` — se a resposta reaproveitasse o
  `correlation_id` da mensagem inbound que a gerou (bug real, corrigido em
  `conversation_runtime.py` + migration 076), a atualização batia nas duas
  linhas e violava `idx_messages_channel_external_unique`, abortando a
  confirmação mesmo com entrega já aceita pelo provider.

### 2.1 Estado sticky "handoff" (motor determinístico)

`DeterministicAppointment.handle()` tem um estado terminal
`conversation_state == "handoff"`: uma vez setado, toda mensagem seguinte
retorna imediatamente sem gerar resposta. Esse curto-circuito usava o
default `handoff=False` do dataclass, diferente de todo outro ponto da
função que entra em handoff (que corretamente passa `handoff=True`) —
corrigido em 2026-08-01. Sem a correção, mensagens para um lead já
escalado eram descartadas silenciosamente e a linha nunca era
re-confirmada como precisando de atenção humana.

Importante: mesmo corrigido, esse estado **não gera resposta nova** — é
comportamento intencional ("uma vez escalado, aguarde humano"). Para
retomar respostas automáticas de verdade é preciso limpar
`leads.metadata.conversation_state` explicitamente (não existe hoje um
botão de UI para isso; feito via `update_lead` direto).

## 3. Evolution × Meta — simetria de provider

`api/services/whatsapp_providers/{evolution,meta,mock}.py` implementam o
mesmo `Protocol` (`base.py`). Desde 2026-08-01:

- Guarda de tamanho de payload (`*_WEBHOOK_MAX_BYTES`, default 2MB) em
  ambos os webhooks.
- Debounce (`available_at`, 3s) e o gate de allowlist/modo de teste
  (`mode` em `active`/`test_allowlist`/`disabled`, default `active` para
  bindings sem `mode` explícito) em ambos.
- `MetaWhatsAppProvider` tem stubs explícitos (`NotImplementedError`) para
  os métodos do `Protocol` que não implementa (`get_connection_status`,
  `get_qr_code`, `restart_instance`, `logout_instance`, `send_media`), em
  vez de deixar uma chamada dinâmica falhar com `AttributeError`.
- `MockWhatsAppProvider` (`registry.get_provider("mock")`) nunca sai para a
  rede; grava envios em memória (`MockWhatsAppProvider.sent`), útil para
  testes que exercitam `whatsapp_dispatch_worker._dispatch_outbound` de
  ponta a ponta sem tocar Evolution/Meta de verdade.

## 4. Risco crítico conhecido: Evolution/Baileys e WhatsApp LID

**Achado ao vivo em 2026-08-01, não corrigível neste repositório.**

Aurora usa Evolution API (Baileys — cliente WhatsApp multi-device não
oficial). Confirmado durante o E2E de produção: respostas do bot para
múltiplos contatos reais (não só o número de teste) geram
`WARN Original message not found for update. Skipping` no log do
Evolution, correlacionado a `remoteJid` no formato `@lid` (identidade
oculta que a WhatsApp vem expandindo por privacidade). O sistema recebe
callbacks de status reais da WhatsApp (server-ack, delivery-ack) para
essas mensagens, mas o cache interno do Evolution não consegue
correlacionar o `@lid` com a mensagem que ele mesmo enviou — e, mais
grave, houve confirmação direta de que a mensagem **não chegou no
aparelho real** apesar do nosso sistema registrar `status=sent` com um
wamid real retornado pela API do Evolution.

Isso é um bug conhecido e ativamente discutido no ecossistema Baileys/
Evolution (não específico do Brain AI):

- [evolution-foundation/evolution-api#2597](https://github.com/evolution-foundation/evolution-api/issues/2597) — mensagens presas em PENDING, nunca entregues, ainda aberto na v2.4.0 (nossa produção roda 2.3.7).
- [EvolutionAPI/evolution-api#1872](https://github.com/EvolutionAPI/evolution-api/issues/1872) — recebe evento LID em vez de JID.
- [WhiskeySockets/Baileys#1684](https://github.com/WhiskeySockets/Baileys/issues/1684) — mensagem marcada como enviada mas não entregue no WhatsApp.
- [WhiskeySockets/Baileys#1718](https://github.com/WhiskeySockets/Baileys/issues/1718) — `@lid` não retorna o número real.

Um mantenedor do Baileys também registrou que versões mais novas da
biblioteca deixaram de emitir certos ACKs de entrega porque a WhatsApp
passou a banir contas por esse padrão — ou seja, o risco não é só
confiabilidade de entrega, é exposição a banimento da conta WhatsApp da
Aurora.

**Implicação prática:** `status='sent'` com um `external_message_id`
válido no nosso banco **não é prova suficiente de entrega real** quando o
provider é `evolution_baileys`. Qualquer trabalho futuro de
confiabilidade de entrega para Aurora deve tratar isso como um problema de
infraestrutura/fornecedor, não de código: opções são acompanhar
atualizações do Evolution API, ou migrar Aurora para a WhatsApp Cloud API
oficial da Meta (que Baita já usa sem esse problema). Isso é uma decisão
estratégica, fora do escopo de correção via código.

## 5. Cobertura de teste

- `tests/conftest.py` + `tests/test_whatsapp_sql_functions.py`: 29 testes
  contra Postgres real (container `pgvector/pg16` descartável, migrations
  aplicadas via `scripts/apply_migrations.py`), incluindo regressão
  explícita para os bugs de `record_whatsapp_safety_violation` (cast
  `text = uuid`), `activate_persona_whatsapp_binding` (`decision_owner`
  preservado), `requeue_waiting_human_whatsapp_buffer` (só inbound),
  `handoff_whatsapp_lead(_state)` (não descarta outbound pendente) e
  `complete_whatsapp_outbound_result` (correlation_id compartilhado com
  inbound não corrompe a linha inbound).
- `api/tests/test_whatsapp_mock_provider.py`: 9 testes do
  `MockWhatsAppProvider` (conformidade de Protocol, isolamento de
  instância, sem chamada de rede).
- `tests/test_aurora_appointment_runtime.py`: cobre o motor determinístico
  do Aurora, incluindo o estado sticky de handoff (regressão do bug de
  2026-08-01).
- `dashboard/e2e/wa-validator/two-tab-conversation.spec.ts`: E2E de fumaça
  contra ambiente real com credenciais verdadeiras.

Nenhum teste automatizado ainda cobre a camada Evolution/Baileys real
(seção 4) — o achado veio de teste manual em produção, não de suíte
automatizada. Um teste automatizado não pegaria isso mesmo existindo,
porque o bug é externo (na biblioteca Baileys), não no nosso código.

## 6. Escopo de campanhas em massa

Campanhas compartilham `lead_buffer`, mas nunca o comportamento implicito de
uma conversa. A migration 087 adiciona `message_origin`, `campaign_id`,
`campaign_revision`, `campaign_recipient_id`, `campaign_step` e
`policy_checksum`. Uma linha com `message_origin=campaign` precisa ser outbound
e carregar todo esse escopo; filas conversacionais continuam com
`message_origin=conversation`.

O rollout 1 apenas modela imports, consentimento, preview, revisao e recipients;
nao cria outbounds. No rollout 2, claim, sweep, retry, handoff e reconciliacao de
campanha devem filtrar `message_origin=campaign`. A logica atual de conversa nao
pode reenviar campanha, descartar outbound de campanha, nem alterar `ai_paused`
por causa de um sweep de campanha. Meta Cloud e o primeiro provider funcional;
Evolution permanece experimental. O contrato completo esta em
[`BULK_CAMPAIGNS.md`](BULK_CAMPAIGNS.md).
