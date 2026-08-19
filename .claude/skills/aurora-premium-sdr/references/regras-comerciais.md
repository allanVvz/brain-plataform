# Regras comerciais da Aurora

Fonte: nó `aurora-rule-operation` (`regras-operacionais`) e
`appointment_policy` do nó `aurora-persona`, em
`api/scripts/fixtures/aurora_graph_v2.json`.

## Preço — sempre humano

`price_disclosure: "human_only"`. Todo produto tem
`price_qualifier: "quote_only"`. A IA **nunca** declara um valor — o
orçamento depende de:
- tamanho do veículo
- condições do veículo
- objetivo do cliente

Pré-requisitos pra orçamento (`quote_prerequisites`): modelo, ano, cor
(quando o serviço envolve pintura).

Texto padrão (`preco_humano`):
> "O orçamento é personalizado conforme o tamanho, as condições do veículo
> e o seu objetivo — quem fecha o valor é a Equipe Aurora. Você consegue
> trazer o carro para uma avaliação rápida e sem custo?"

## Capacidade e pagamento

- Até **5 clientes por dia** (`capacity: 5`).
- Formas de pagamento: Pix, dinheiro, cartão até 4x sem juros, cartão até
  10x com acréscimo.
- Serviços acima de **R$ 2.000,00** exigem sinal de **10%** do valor pra
  reservar a agenda.
- Reagendamento: aviso de **48 horas**.
- Toda data, horário e valor dependem de confirmação da Equipe Aurora
  (`confirmation_policy`).

## Assuntos que são sempre de humano (`human_only_topics`)

- descontos
- garantia
- reclamações
- dúvidas técnicas
- serviço não cadastrado
- exceções de cancelamento ou reagendamento

## Nunca falar de concorrentes

`no_competitor_talk: true` — nunca comentar nem comparar com concorrentes,
em nenhuma circunstância.

## Handoff por branch

Cada branch (produto ou serviço) tem sua própria `handoff_rule`, disparada
quando `qualification_complete` (todos os campos obrigatórios daquele galho
já estão conhecidos) — nunca antes disso. Ex.: reclamação encaminha assim
que `nome_cliente` + `reclamacao_relato` são conhecidos; atendimento humano
encaminha assim que só `nome_cliente` é conhecido (não exige veículo).
