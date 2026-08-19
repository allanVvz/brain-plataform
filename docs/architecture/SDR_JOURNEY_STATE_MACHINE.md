# Jornada comercial — estados, eventos e desfecho

Contrato canônico da jornada de um pedido: da qualificação do SDR até entrega ou
cancelamento. O SDR termina na qualificação; conversão, venda, entrega e
cancelamento são **decisões humanas registradas explicitamente**, nunca inferidas
pelo modelo.

Migrations relevantes: `118` (tabelas), `121` (máquina de estados),
`122` (suporte pós-handoff), `123` (desfecho comercial), `124` (conversão
reversível), `125` (cancelar estorna a compra), `126` (seletor de estado),
`128` (confirmação por galho dentro da mesma jornada).

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

### O ciclo do pedido

O pedido anda em dois passos, e o par de eventos de cada passo depende do
`business_model` da persona (`personas.config.portal.business_model`):

| Passo | Produto (`sales`) | Serviço (`appointment`) |
|---|---|---|
| 1 — o pedido nasce | comprado (`sale_recorded`) | agendado (`appointment_booked`) |
| 2 — o pedido fecha | entregue (`delivered`) | concluído (`service_completed`) |
| 2 — ou morre | cancelado (`cancelled`) | cancelado (`cancelled`) |

Os dois passos podem estar desligados: é o estado natural de um pedido que ainda
não andou. Fechar — por conclusão ou cancelamento — **reinicia o ciclo
agêntico**: a jornada sai de `is_current`, e o próximo inbound cria a seguinte
com `opening_reason='new_demand_after_closed_request'`, ledger novo e sem fatos.

### O closer humano é quem manda: seletor de estado

`record_conversation_journey_event_v1` é append-only e idempotente — certo para
integração e para o agente, errado para um humano corrigindo o registro. A outra
metade do contrato é `set_conversation_journey_state_v1` (migration 126), que
recebe o **estado-alvo** e calcula o delta, inclusive os caminhos de volta:

| De → para | O que acontece |
|---|---|
| vendido → convertido | estorna a conversão e remove `metadata.sold` |
| convertido → qualificado | limpa `converted_at` desta jornada |
| fechado → qualquer aberto | reabre (`is_current=true`) |

**Reabrir falha se já existir jornada com `sequence` maior.** O índice parcial
`idx_conversation_journeys_one_current` garante uma corrente por lead; a função
levanta `a newer order already exists for this lead` em vez de deixar o banco
recusar com violação de índice.

Rotas: `POST /portal/leads/{id}/journey-state` e a gêmea em `/agents`. O
endpoint de eventos continua existindo para integração.

### Fechar o pedido religa a IA

Alvo `entregue` ou `cancelado` chama `agents_service.resume_lead`: zera
`handoff_level`, marca `pending_reconfirmation` e — o que importa — devolve à
fila os inbounds parqueados em `waiting_human`. Sem isso o lead segue mudo
indefinidamente: o handoff grava `handoff_level='full'` automaticamente
(`conversation_runtime.py`) e **nenhum worker reclama `waiting_human`**.

O religamento emite `lead.ai_resumed` com `by: "journey_closed"`, para a origem
ser auditável em vez de parecer um resume manual.

### Conversão da lead é permanente

`leads.metadata.first_converted_at` é carimbado uma única vez na primeira venda
ou agendamento — pela via de eventos (trigger em `sales_conversions`) e pelo
seletor. Ninguém o apaga: nem o cancelamento, nem o seletor, nem o ciclo
seguinte. Ele vira o **piso** do seletor: uma lead já convertida não recebe
`qualificado` como opção.

Não use `converted_at` para isso — o seletor pode limpá-lo ao voltar um estado.

### O segundo ciclo do SDR

Fechar o pedido reinicia o ciclo agêntico com **ledger novo e sem fatos**. Sem
mais nada, o SDR reperguntaria o nome a cada pedido.

O contrato compilado marca cada field com `carry_over`, e o default vem da
**origem do field** — nunca de uma lista de nomes no código:

| Origem | `carry_over` | Por quê |
|---|---|---|
| field `scope="persona"` | `true` | é o que o cliente **é** (nome, veículo) |
| intenção deste atendimento (`objective`, `can_visit_in_person`) | `false` | descreve **esta** visita, não o cliente |
| seletor de galho (`servico`) | `false` | cada ciclo escolhe o seu |

O grafo sobrescreve campo a campo declarando `carry_over` no próprio field.

O default é derivado do **escopo**, não de uma lista de nomes: qualquer campo
persona-scoped futuro carrega automaticamente. Antes de 2026-08-18 só o literal
`appointment_policy.identity_field` atravessava, e um cliente que voltava tinha
de repetir o veículo inteiro (`api/scripts/publish_aurora_graph.py`, campo
`carry_over`).

Quando a jornada seguinte nasce, `_seed_carried_facts` semeia no ledger vazio os
fatos `known` cujo field carrega, marcados com `carried_from_journey`. Daí
`_known_facts_payload` os rotula como `origem: "anterior"` **e**
`carregado_do_pedido_anterior: true`, e o prompt manda **usar direto, sem
perguntar nem confirmar** — é identidade do cliente, não dado deste pedido. Só
os demais fatos `"anterior"` (sem esse carimbo — veículo, data, janela do
pedido anterior) continuam exigindo confirmação antes de uso.

`servico` não é semeado: cada ciclo escolhe o seu.

⚠️ `carry_over` entra em `branch_contracts`, que é compilado **no publish**
(`graph_compiler_v3.py`). Uma publicação anterior à migration não tem o atributo,
e nada atravessa até o grafo ser republicado.

### Confirmação por galho, não por jornada

`post_qualification_support` é o modo que a jornada assume depois da primeira
confirmação explícita — e por design ele não deveria travar um segundo
serviço/produto que o cliente confirma na mesma conversa ainda aberta.
Migration 105 já suporta múltiplos galhos ativos simultâneos
(`conversation_ledger_branches`, um fato por `(field_key, owner_node_id)`),
mas nada gravava o estado `completed` até a migration 128: o galho só
alternava entre `active` e `dropped`, então não havia como distinguir "este
galho ativo já foi confirmado" de "este é novo e ainda precisa da própria
confirmação".

- `graph_agent_runtime_v3.py::build_context` busca
  `conversation_ledger_branches.state` do ledger e monta
  `ConversationContext.completed_branch_node_ids`. Uma jornada já em
  `post_qualification_support` sem nenhum registro `completed` ainda (i.e.
  publicada antes da migration 128) faz um *grandfather* único: tudo que já
  estava ativo no início do turno vira `completed` — só um galho novo, a
  partir daí, pede confirmação própria.
- `_decide` calcula `pending_branch_confirmation = active_branch_ids -
  completed_branch_node_ids`. Enquanto não vazio, o lock de
  `post_qualification_support` não se aplica: a coleta e a confirmação
  seguem normalmente para aquele galho, mesmo com a jornada já tendo
  confirmado outro antes.
- Ao aceitar um "sim" explícito, `_deterministic_confirmation_decision`
  grava `confirmed_branch_node_ids` (todo `active_branch_node_id` +
  `active_branch_node_ids` do context) no `proof`; o turno chega em
  `commit_graph_turn_and_outbox_v3` (migration 128) que faz
  `UPDATE conversation_ledger_branches SET state='completed'` para esses
  galhos, na mesma transação do resto do commit.
- Nenhum nome de campo é hardcoded: o seletor de galho vem de
  `branch_selection_field_key(document)`, que lê o field marcado
  `branch_selection_field` no contrato compilado (fallback `"servico"` só
  para publicações anteriores a esse flag) — o mesmo mecanismo vale para uma
  persona de produto ou catálogo de vários produtos.

### Precedência: desfecho comercial vence proof

`project_conversation_journey_from_proof_v1` **nunca regride** uma jornada em
`converted` ou `closed`. O proof continua escrevendo `metadata`
(`last_proof_id`, `confirmation_state`, `handoff_reason`), mas não o `state`.

Sem essa guarda, um inbound qualquer depois de uma venda jogava a jornada de
volta para `collecting` ou `handed_off` e o desfecho sumia da tela. A migration
122 já protegia o ramo `post_qualification_support`; a 123 estendeu a guarda aos
quatro ramos da projeção.

## Eventos

`POST /agents/leads/{lead_ref}/journey-events` — sete tipos:

| Evento | Efeito | Aceita valor? |
|---|---|---|
| `converted` | `state='converted'`, `converted_at`, guarda `state_before_conversion`. Jornada segue corrente. | não |
| `conversion_reverted` | Desfaz a conversão e volta ao `state_before_conversion`. Recusa se houver venda. | não |
| `sale_recorded` | Insere `sales_conversions` (`purchase`), `state='converted'`, `metadata.sold=true`. | sim |
| `appointment_booked` | Idem, `conversion_type='appointment_booked'`. | sim |
| `delivered` | `state='closed'`, `is_current=false`, `metadata.closing_event`. | não |
| `service_completed` | Idem — o equivalente de `delivered` para serviço. | não |
| `cancelled` | Idem, e **estorna a compra**: as conversões `completed` da jornada viram `cancelled` e `metadata.sold` é removido. | não |

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

`conversion_reverted` é a exceção deliberada: em vez de anexar a própria entrada,
ele **remove** a entrada do `converted` que desfez. Sem isso o operador só
conseguiria converter uma vez por jornada e o toggle não poderia voltar. A
idempotência do revert vem do estado: reverter uma jornada que não está
convertida é no-op.

### Cancelar estorna a compra, não a conversão

Cancelar transiciona para `cancelled` toda conversão ainda `completed` da
jornada corrente e remove `metadata.sold` — o controle de venda volta a aparecer
desligado e a receita deixa de ser contada. Antes da migration 125 a jornada
fechava mas a linha em `sales_conversions` seguia `completed`: a tela dizia
cancelado e o ledger discordava.

`converted_at` **fica**. Depois do primeiro agendamento ou compra o lead está
convertido, e cancelar o pedido não desfaz isso: conversão é fato do lead, venda
é fato do pedido. Pela mesma razão `lead_first_conversion` ignora linhas
canceladas — uma venda estornada não pode fazer a próxima parecer recorrência.

A chave de idempotência de uma venda cancelada fica queimada: relançar com a
mesma chave levanta `idempotency key belongs to a cancelled conversion`, em vez
de ressuscitar a linha em silêncio.

### Conversão é reversível; venda não

Conversão é leitura do operador — e leitura se corrige. Enquanto não existe
registro em `sales_conversions`, o toggle vai e volta entre `qualificado` e
`convertido` quantas vezes for preciso. Assim que a venda entra, `metadata.sold`
trava o controle: desfazer passaria por estorno em `sales_conversions`, que é
outro contrato.

`converted` guarda `state_before_conversion` para que o retorno seja ao estado
real de origem. Sem isso, uma jornada convertida a partir de
`qualified_confirmed` voltaria para `handed_off` e pareceria ter sido entregue
ao humano sem nunca ter sido.

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

No rail direito, a fase reversível vive num **toggle** (`qualificado ⇄
convertido`) e não em botões: um botão sugere ação irreversível. Abaixo dele
ficam os dois passos do pedido. O botão 2 é o terminal, e o próprio botão diz
como o pedido fechou — `Entregue`/`Concluído` em navy, `Cancelado` riscado em
cinza. A escolha entre os dois acontece num diálogo ao clicar; concluir fica
indisponível enquanto o passo 1 não foi registrado, porque não há o que
entregar.

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
  das migrations 123 (guarda de regressão, `converted`, marcador `sold`) e 124
  (retorno ao estado de origem, venda torna a conversão final, liberação da
  chave de idempotência).
- `tests/test_agents_conversion_api.py` — contrato do endpoint e a proibição de
  valor comercial em `converted`.
- `tests/test_conversation_journeys_migration.py` — invariantes das 118/121/122.
- `dashboard/__tests__/messages-journey-outcome.test.tsx` — cor na lista, notas
  no rail, o toggle nos dois sentidos, o travamento após a venda, regras dos
  botões, confirmação e idempotência do clique duplo.
