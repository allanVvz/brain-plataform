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

## Rollback do rollout 1

Desabilitar a flag global ou `personas.config.bulk_campaigns.enabled`. Como nao ha envio, nenhum outbound precisa ser cancelado. Drafts, consents, imports e eventos permanecem para auditoria; o fluxo individual e `ai_paused` nao sao alterados. Reativacao recalcula preview e exige nova confirmacao se o checksum mudou.
