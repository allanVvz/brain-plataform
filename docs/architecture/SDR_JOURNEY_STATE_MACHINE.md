# Jornada comercial — estados, eventos e desfecho

Contrato canônico da jornada de um pedido: da qualificação do SDR até entrega ou
cancelamento. O SDR termina na qualificação; conversão, venda, entrega e
cancelamento são **decisões humanas registradas explicitamente**, nunca inferidas
pelo modelo.

Migrations relevantes: `118` (tabelas), `121` (máquina de estados),
`122` (suporte pós-handoff), `123` (desfecho comercial).

## Estados

`conversation_journeys.state` — CHECK definido na migration 118, seis valores:

| Estado | Quem escreve | Significado |
|---|---|---|
| `collecting` | proof do SDR | Identificando serviço e coletando fields pendentes. |
| `awaiting_confirmation` | proof do SDR | Resumo e `confirmation_question` emitidos, sem handoff. |
| `qualified_confirmed` | proof do SDR | Confirmação explícita do cliente, sem rota humana. |
| `handed_off` | proof do SDR | Entregue ao closer humano; a IA pausa. |
| `converted` | evento humano | O cliente aceitou. O pedido **continua aberto**. |
| `closed` | evento humano | Entregue, concluído ou cancelado. `is_current=false`. |

Exatamente uma jornada é corrente por `(persona, lead)` — índice parcial
`idx_conversation_journeys_one_current`.

### Precedência: desfecho comercial vence proof

`project_conversation_journey_from_proof_v1` **nunca regride** uma jornada em
`converted` ou `closed`. O proof continua escrevendo `metadata`
(`last_proof_id`, `confirmation_state`, `handoff_reason`), mas não o `state`.

Sem essa guarda, um inbound qualquer depois de uma venda jogava a jornada de
volta para `collecting` ou `handed_off` e o desfecho sumia da tela. A migration
122 já protegia o ramo `post_qualification_support`; a 123 estendeu a guarda aos
quatro ramos da projeção.

## Eventos

`POST /agents/leads/{lead_ref}/journey-events` — seis tipos:

| Evento | Efeito | Aceita valor? |
|---|---|---|
| `converted` | `state='converted'`, `converted_at`. Jornada segue corrente. | não |
| `sale_recorded` | Insere `sales_conversions` (`purchase`), `state='converted'`, `metadata.sold=true`. | sim |
| `appointment_booked` | Idem, `conversion_type='appointment_booked'`. | sim |
| `delivered` | `state='closed'`, `is_current=false`, `metadata.closing_event`. | não |
| `service_completed` | Idem — o equivalente de `delivered` para serviço. | não |
| `cancelled` | Idem. Fatos preservados. | não |

Valor comercial só é aceito em `sale_recorded`/`appointment_booked`. A regra é
validada duas vezes, no Pydantic (`JourneyEventBody`) e no plpgsql, para que a
variante interna por webhook não escape da checagem.

**Venda não abre jornada nova.** `maybe_open_next_conversation_journey_v1` é
no-op desde a migration 121. A jornada seguinte nasce apenas no próximo inbound
depois do fechamento, com `opening_reason='new_demand_after_closed_request'` —
única via de sucessão, em `assign_conversation_ledger_journey_v1`.

### Autenticação

| Rota | Auth |
|---|---|
| `POST /agents/leads/{ref}/journey-events` | sessão + `assert_persona_capability(request, "edit", persona_id)` |
| `POST /internal/agents/leads/{ref}/journey-events` | header `X-Webhook-Token` |

`POST /agents/leads/{ref}/purchase-completed` permanece como adaptador
compatível: monta `event_type="sale_recorded"` e usa o mesmo RPC.

### Idempotência

Dois canais, ambos por `(source, idempotency_key)`:

- eventos de conversão — constraint `sales_conversions UNIQUE(persona_id, source, idempotency_key)`;
- demais eventos — varredura de `conversation_journeys.metadata.event_idempotency`.

Reusar a mesma chave para outro lead ou outro tipo levanta
`idempotency key belongs to a different journey event`. Repetir o mesmo evento
devolve `deduplicated: true` sem gravar de novo.

O dashboard usa chave determinística `dashboard:{lead_ref}:{event_type}` — clique
duplo colide na chave em vez de gerar dois registros.

## Desfecho (`journey_outcome`)

`delivered`, `service_completed` e `cancelled` colapsam no mesmo `state='closed'`
e só se distinguem por `metadata.closing_event`. A UI precisa de um valor único,
então a derivação vive num lugar só: `api/services/journey_outcome.py::derive`.

```
closed + closing_event=cancelled                      -> cancelado
closed + closing_event in (delivered,service_completed)-> entregue
converted + metadata.sold                              -> vendido
converted                                              -> convertido
qualified_confirmed | handed_off                       -> qualificado
senão                                                  -> null
```

O terminal vence: vendido e depois cancelado lê `cancelado`.

`metadata.sold` é gravado pelo próprio evento de venda para que a derivação leia
uma tabela só — a lista de conversas pinta todos os itens de uma vez, e um
`select` em `sales_conversions` por lead seria um N+1.

### `journey_outcome` não é `stage`

Eixos independentes, os dois verdadeiros ao mesmo tempo:

- `stage` (`novo → contatado → engajado → qualificado → oportunidade`, mais
  `fechado`/`perdido`/`nao_qualificado`) é o **funil manual**, editado no
  pipeline, definido em `api/routes/portal.py::PIPELINE_STAGES`.
- `journey_outcome` é o **desfecho do pedido corrente**, derivado da jornada.

Um lead pode estar `qualificado` no funil e `convertido` na jornada. Nenhum dos
dois reescreve o outro.

### Leitura em lote

`journey_outcome` entra decorado nas listagens já existentes — `/portal/leads`,
`/portal/conversations`, `/leads` e os detalhes — via
`journey_outcome.decorate_leads`, que agrupa por persona e faz uma consulta
paginada por lote (`get_current_journeys_by_lead_refs`, chunk de 100).

## Cor

Família `resultado/*`, quarto eixo semântico do design system. Os três acentos
reservados continuam intactos: `--obs-violet` evidência do grafo, `--obs-live`
canal/IA ativa, `--obs-amber` ação humana, `--obs-teal` evidência na tela de
Mensagens.

| Desfecho | Token | Claro | Escuro |
|---|---|---|---|
| qualificado | `--obs-faint` | `#64748B` | — |
| convertido | `--obs-outcome-converted` | `#2563C9` | `#6C9BEE` |
| vendido | `--obs-outcome-sold` | `#A32E7A` | `#D470B0` |
| entregue | `--obs-outcome-delivered` | `#14375E` | `#8FA8CC` |
| cancelado | `--obs-outcome-cancelled` | `#64748B` | `#64748B` |

`qualificado` não ganha token de propósito: o estágio continua categórico,
codificado por peso, e só compromisso, venda e entrega gastam cor.

Na lista de conversas, o marcador de desfecho ocupa o lugar do `StageBadge` —
300px não comportam os dois eixos, e o estágio completo continua no perfil do
rail direito. **Atenção e desfecho coexistem**: `attentionRowStyle` continua dono
do `borderLeft` e do fundo; o desfecho entra como ponto cheio mais rótulo.

Protótipo: página `04 · Jornada` do arquivo Figma "Brain — Portal do Cliente".

## Funções depreciadas

A migration 121 deixou duas funções da 118 órfãs. Continuam definidas e com
`GRANT` para `service_role`, mas **não devem ser chamadas**:

- `record_purchase_completed_v1` — ainda contém a abertura automática de jornada
  que a 121 aboliu. Chamá-la direto contradiz o contrato desta página. Use
  `record_conversation_journey_event_v1`.
- `mark_conversation_journey_qualification_v1` — a qualificação passou a ser
  projetada pelo trigger do proof.

## Testes

- `tests/test_journey_outcome.py` — derivação, leitura em lote e o contrato SQL
  da migration 123 (guarda de regressão, `converted`, marcador `sold`).
- `tests/test_agents_conversion_api.py` — contrato do endpoint e a proibição de
  valor comercial em `converted`.
- `tests/test_conversation_journeys_migration.py` — invariantes das 118/121/122.
- `dashboard/__tests__/messages-journey-outcome.test.tsx` — cor na lista, notas
  no rail, regras dos botões, confirmação e idempotência do clique duplo.
