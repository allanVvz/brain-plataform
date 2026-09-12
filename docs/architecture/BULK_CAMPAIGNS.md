# Campanhas em massa

Arquitetura expand-first para imports, consentimento e campanhas. O rollout 1 nao envia mensagens: ele cria coortes operacionais, calcula elegibilidade e congela drafts auditaveis. O envio individual e a conversa atual permanecem inalterados.

## Modelo

Estruturas reutilizadas:

- `leads`: identidade do contato; nao guarda o estado canonico de uma campanha.
- `audiences` e `lead_audience_memberships`: grupo semantico. Existe no maximo um grupo semantico por lead/persona.
- `campaigns`: identidade e estado agregado.
- `lead_buffer`: outbox tecnica compartilhada, com lease em `attempt_count`.
- `messages`: mensagens observadas.
- `workflow_bindings`: provider, credencial e saude do canal.
- `system_events`: trilha append-only; nao e uma projecao consultiva.

Estruturas adicionadas pela migration `087_campaign_delivery_one.sql`:

- `lead_import_batches` e `lead_import_rows`: coorte operacional, proveniencia, composicao e reconciliacao. Import nao vira node do Graph.
- `contact_consents`: eventos append-only por lead, persona, canal, finalidade e categoria. `granted`, `refused`, `revoked`, `pending` e `review_required` nao sao estados globais do lead.
- `campaign_revisions`: snapshot append-only de audience, Graph, Copy/template/assets, objetivo, finalidade e politica numerica, com checksums.
- `campaign_revision_imports`: imports usados pela revisao.
- `campaign_recipients`: projecao explicita por lead e revisao, com sequencia, supressao, validade do contato, tentativas comerciais, resposta atribuida e conversao.

As dimensoes nao compartilham um enum:

- consentimento: `contact_consents.status`, projetado em `campaign_recipients.consent_status`;
- sequencia: `campaign_recipients.sequence_status`;
- supressao/cooldown: `campaign_recipients.suppression_status` e datas da sequencia;
- validade do contato/provider: `campaign_recipients.contact_status` e `workflow_bindings`;
- entrega: `lead_buffer.status`/`messages.status`;
- processamento tecnico: `lead_buffer.attempt_count`;
- chamadas externas: `lead_buffer.provider_attempt_count`;
- tentativa comercial: `campaign_recipients.commercial_attempt_count`.

## Autorizacao e congelamento

O backend separa `resolve_contact_policy`, `resolve_applicable_consent` e `evaluate_recipient_eligibility`. A persistencia final usa uma transacao pequena (`create_campaign_draft_v1`), sem mover o gate inteiro para uma RPC monolitica.

Precedencia de politica: default seguro, persona, audience, campanha. Campos desconhecidos sao rejeitados. O preview devolve `policy_checksum` e `preview_checksum`; o draft so e criado se a elegibilidade recalculada ainda corresponder ao preview confirmado.

A revisao congela Graph, audience, imports, conteudo, assets, finalidade, objetivo e limites numericos. Antes de cada envio do rollout 2, permanecem vivos e obrigatorios: revogacao/opt-out, consentimento aplicavel, supressao, provider/credencial, numero invalido, deduplicacao, entrega anterior e capacidade consumida por outra campanha.

As novas tabelas tem RLS habilitada e acesso revogado de `PUBLIC`, `anon` e `authenticated`. O navegador usa apenas FastAPI com sessao e escopo de persona. Integridade de persona tambem e validada por triggers no banco.

## Resposta e transicao para atendimento

Uma mensagem inbound so podera ser atribuida quando for humana, `fromMe=false`, posterior ao outbound da campanha, da mesma persona/binding/canal, dentro da janela e correlacionavel ao recipient/step. Receber, atribuir, interromper retries, conceder consentimento e pedir revisao sao fatos separados (`response_received_at`, `response_attributed_at`, `retries_stopped_at`, classificacao e consent outcome).

No rollout 2, uma resposta atribuida abre ou reutiliza a conversa canonica do lead e resolve o binding ativo da mesma persona. O agente e escolhido pelo `workflow_bindings.metadata.decision_owner`; recebe `campaign_id`, revisao, recipient, objetivo, finalidade, audience snapshot, Graph congelado e citacoes. A mensagem inbound entra no fluxo conversacional normal, preservando atribuicao. Handoff nao altera outbounds de campanha; sweeps e retries sempre filtram `message_origin`.

## Entregas

### Entrega 1 — implementada

- coorte de import separada do Graph;
- grupo semantico unico e acao `Gerenciar grupo`;
- consentimento escopado e append-only;
- preview deduplicado e bloqueios explicitos;
- revisao/destinatarios congelados em draft;
- polling simples no admin;
- pause/cancel auditados, sem envio;
- flag `BULK_CAMPAIGNS_ROLLOUT1_ENABLED` (por default so ambientes local/QA; `personas.config.bulk_campaigns.enabled=false` desabilita uma persona).

### Entrega 2 — Meta controlada

- validar template aprovado e binding Meta;
- admissao transacional na outbox com `message_origin=campaign`;
- envio manual ou agenda simples, limites e retries comerciais;
- revalidacao viva antes do provider;
- callbacks, resposta correlacionada e transicao para atendimento;
- metricas minimas de enviados, bloqueados, respostas e falhas.

### Entrega 3 — automacao e escala

- scheduler avancado e concorrencia multi-worker;
- metricas completas, alertas e overrides;
- SSE;
- Evolution experimental, com canario, limites pequenos e sem paridade prometida com Meta;
- otimizacoes e projecoes analiticas.

## Templates Meta — ciclo de vida

`message_templates` (migration `090_campaign_delivery_two_send.sql`, colunas de
aprovacao adicionadas em `140_message_template_meta_lifecycle.sql`) so guardava
uma referencia a um nome ja aprovado manualmente no WhatsApp Manager. Nao existia
chamada para a API de templates da Meta nem coluna de status de aprovacao —
so o `status` proprio (draft/active/archived), sem relacao com PENDING/APPROVED/
REJECTED do lado da Meta.

Hoje existe o ciclo completo, mas **sem sincronizacao automatica por webhook**
(decisao deliberada: so sob demanda por enquanto — ver "Fora de escopo" abaixo):

1. **Criar rascunho local** — `POST /messaging/templates`
   (`campaigns_service.create_message_template`). Aceita `components`
   estruturados (`HEADER`/`BODY`/`FOOTER`/`BUTTONS`, formato de fio da Meta) ou,
   por conveniencia, um `body` piano que vira um unico componente `BODY`. Nao
   fala com a Meta — so cria a linha, `meta_approval_status="draft"`.
2. **Submeter para revisao** — `POST /messaging/templates/{id}/submit`
   (`campaigns_service.submit_message_template` →
   `transport_client.create_meta_template` →
   `apps/transport/.../whatsapp.py::meta_template_create_internal` →
   `MetaWhatsAppProvider.create_template`, `POST /{waba_id}/message_templates`).
   Grava `meta_template_id` e `meta_approval_status="pending"`. So permitido uma
   vez por template (`meta_template_id is None`) — resubmeter e papel da edicao.
3. **Editar** — `PATCH /messaging/templates/{id}`
   (`campaigns_service.edit_message_template`). Nunca aceita mudar
   `meta_template_name`/`meta_template_language`/`provider`/`template_key` —
   isso e identidade do template na Meta; renomear e criar um template novo, nao
   editar este. Se ja foi submetido (`meta_template_id` existe), a edicao chama
   `update_template` (`POST /{meta_template_id}`, endereçado pelo id do
   template, nao pelo `waba_id`) e a Meta volta o status para revisao — o codigo
   espelha isso localmente na hora (`meta_approval_status="pending"`) em vez de
   esperar o proximo sync, para o dashboard nunca mostrar "aprovado" desatualizado
   enquanto a Meta esta revisando o novo conteudo.
4. **Consultar status** — `POST /messaging/templates/{id}/sync`
   (`campaigns_service.sync_message_template_status` → `get_template_status`,
   `GET /{meta_template_id}?fields=status,category,rejected_reason`). Pull sob
   demanda, sem worker/agendamento.

Variavel de template (`{{1}}`, `{{2}}`, ...) exige bloco `example` — a Meta
rejeita a criacao sem ele. `_meta_wire_components`/`_to_meta_wire_component`
(`campaigns_service.py`) validam isso antes de qualquer chamada de rede:
variavel sem `example_values` correspondente e rejeitada localmente, assim como
variavel nomeada (`{{nome}}`) — a Meta so aceita posicional.

**Fronteira de microsservico:** `campaigns_service.py` roda no `control-plane`;
`MetaWhatsAppProvider` roda no `transport`. Toda chamada atravessa
`transport_client.{create,update,get}_meta_template` → rota interna
`/internal/v1/transport/whatsapp/meta/templates/*` (mesmo padrao de
`evolution_action`/`provision_evolution`, autenticado por `X-Webhook-Token`).

**Fora de escopo por decisao (nao "nunca", ver secao propria acima sobre
niveis de entrega):**

- **Webhook de status** (`message_template_status_update`,
  `message_template_quality_update`) — `meta_callback`
  (`apps/transport/api/routes/whatsapp.py`) processa inbound/status hoje sem
  olhar `change["field"]`; um terceiro branch para eventos de template e a
  extensao natural quando isso entrar em escopo, mas nao existe ainda. Ate la,
  `sync` e a unica forma de saber que um template mudou de status.
- **Categoria e enquadramento comercial** — o codigo aceita qualquer
  `MARKETING`/`UTILITY`/`AUTHENTICATION` que o operador escolher; a Meta pode
  recategorizar ou rejeitar por conta propria, e o codigo nao tenta advinhar
  qual categoria "deveria" ser.

### Exemplo real — boas-vindas da VZ Lupas

Unico template hoje aprovado para qualquer persona era o `hello_world` — o
exemplo que a propria Meta cria ao configurar um numero de teste (corpo
generico em ingles sobre a Cloud API). Nunca deve ser referenciado por uma
campanha real; nao precisa ser apagado, so nunca usado.

Componentes prontos para submissao via `POST /messaging/templates` (campos
`persona_id`/`provider="meta_cloud"`/`template_key` omitidos abaixo, sao os
mesmos de qualquer criacao) seguido de `POST /messaging/templates/{id}/submit`,
categoria `MARKETING` (mensagem de saudacao/engajamento que convida a navegar
o catalogo — nao confirma uma transacao especifica, entao `UTILITY` seria mau
enquadramento e risco de rejeicao/recategorizacao):

```json
{
  "meta_template_name": "vz_lupas_boas_vindas",
  "meta_template_language": "pt_BR",
  "meta_template_category": "MARKETING",
  "components": [
    {"type": "HEADER", "text": "Bem-vindo à VZ Lupas"},
    {"type": "BODY", "text": "Olá! 👋\n\nSeja bem-vindo à VZ Lupas 😎\nRecebemos seu contato e já vamos te atender.\n\nSe quiser, pode me dizer o que você procura:\n• Óculos específico\n• Dúvidas sobre modelos\n• Promoções disponíveis\n\nEstou por aqui pra te ajudar 👊"},
    {"type": "FOOTER", "text": "VZ Lupas • Visão de verdade"}
  ]
}
```

Sem variaveis `{{n}}` como esta desenhado — nao precisa de `example`. Corpo bem
abaixo do limite de 1024 caracteres da Meta; header e footer dentro do limite
de 60. Emoji e o caractere `•` (bullet) sao aceitos em texto de template.

## Rollback do rollout 1

Desabilitar a flag global ou `personas.config.bulk_campaigns.enabled`. Como nao ha envio, nenhum outbound precisa ser cancelado. Drafts, consents, imports e eventos permanecem para auditoria; o fluxo individual e `ai_paused` nao sao alterados. Reativacao recalcula preview e exige nova confirmacao se o checksum mudou.
