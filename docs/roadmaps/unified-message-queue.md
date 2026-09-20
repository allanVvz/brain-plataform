# Fila unificada de mensagens e reativação contextual

Status: em execução — a tela de lotes foi substituída por uma fila global operacional de `lead_buffer`. Ela mostra somente mensagens ativas: pendentes em vermelho, previews prontos e mensagens enviadas em verde até a próxima resposta da lead. Histórico e filtro por lead não fazem parte desta tela.

`lead_buffer` é o buffer canônico; `messages` fornece a linha do tempo e `conversation_turn_proofs` prova somente a resposta normal ao inbound canônico. Mensagens proativas terão identidade e proof próprios e nunca reutilizarão o inbound.

O reprocessamento de uma falha técnica não reenvia um outbound antigo: ele reclama o inbound canônico sem proof, gera uma nova resposta `preview_ready` com proof e só a ação explícita `Enviar preview` a libera. Pausar, retomar e gerar/enviar preview não pedem motivo; cada ação continua auditada em `system_events`.

Próximas etapas: publicar por persona a regra e copies de horário no GraphBundle, tornar o runtime consumidor apenas desses nodes publicados e validar aviso único/reativação no WA Validator interno antes de ativar envio proativo.

## Entregue em 2026-09-20 — idempotência, erros e cobertura de browser

Sem migration nova. `POST /messaging/queue/*` e `/queue/reprocess-next` aceitam
`idempotency_key` opcional; `release_queue_service.with_idempotency` regrava a
mesma resposta para uma repetição da mesma chave usando `system_events`
(`entity_type='messaging_queue_idempotency'`) e recusa com 409 a reutilização da
chave para outra ação/alvo. A trava real contra envio duplicado continua sendo a
transição atômica de `lead_buffer.status` dentro dos RPCs — esta camada só
garante resposta idêntica a um retry de rede.

A recuperação de claim stale da migration 158 deixou de ser silenciosa: o
serviço detecta o evento `messaging.queue.stale_commit_released` da própria
chamada e devolve `recuperando_tentativa_antiga` em vez do rótulo genérico de
prévia gerada. Uma prévia bloqueada por proof/publicação inválida passa a ser
rotulada "Proof inválida" em vez de "Pronta". O painel diferencia 401/403, 409,
422, 502-504 e timeout com instrução operacional e `request_id` visível, e o
histórico expandível não repete mais as duas mensagens já exibidas no cabeçalho.

Cobertura: `dashboard/e2e/messaging-queue/operational-queue.spec.ts`
(`npm run test:e2e:messaging-queue`, 10 casos em browser real com todas as
chamadas HTTP interceptadas, sem backend e sem WhatsApp) e
`apps/control-plane/api/tests/test_release_queue_idempotency.py`.

## A fazer — ação explícita de template aprovado

Hoje a fila não tem nenhum caminho para disparar um template aprovado: não
existe rota, função SQL nem botão. A entrega precisa de migration própria e
autorização própria, e deve cobrir, na ordem:

1. selecionar um template já aprovado para o binding da persona;
2. validar idioma, parâmetros, publicação ativa, janela de atendimento e
   binding antes de qualquer escrita;
3. gerar proof próprio — o template é mensagem proativa e nunca reutiliza o
   inbound canônico (mesma regra das linhas de reativação);
4. exigir confirmação explícita do operador antes do envio;
5. permanecer exactly-once por identidade própria do template, com evento
   auditável em `system_events`.

O ciclo de vida do template na Meta (rascunho → `submit` → `edit` → `sync`) já
existe e está descrito em `docs/architecture/BULK_CAMPAIGNS.md`; o que falta é
apenas o consumo dele como ação da fila.

## A fazer — lacunas menores encontradas na auditoria de 2026-09-20

- `item.actions` já devolve `pause`, `resume` e `reactivate`, mas o painel só
  renderiza as três ações por mensagem (Gerar prévia / Retry / Enviar). Essas
  ações de demanda não têm ponto de entrada na UI.
- `list_actionable_message_queue_v156` não projeta "bloqueada por inbound mais
  recente" por mensagem: uma linha pode chegar com `can_send=true` e só falhar
  com `superado` no clique. Corrigir exige nova revisão da função.
- Desempenho não foi medido nesta rodada: falta `EXPLAIN (ANALYZE, BUFFERS)`
  contra produção e o p95 para 50 linhas.
