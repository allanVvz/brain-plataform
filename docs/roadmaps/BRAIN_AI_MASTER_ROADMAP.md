# Brain AI master roadmap

P0 is the durable multi-persona WhatsApp runtime: unique phone binding, allowlisted Baita pilot, canonical inbound/status APIs, durable buffer, Brain-owned decisions, human handoff and shared context. P1 follows with multi-persona onboarding and published graph reconciliation. P2 covers public sites and Creative Studio; P3 MCP/plugin governance; P4 social channels; P5 removes legacy n8n/WhatsApp paths only after observability gates.

## Jornada comercial e closer agentico

Entregue: a jornada do pedido tem desfecho registrado por humano — conversao,
compra, entrega/conclusao e cancelamento — exposto como `journey_outcome` e
pintado na tela de Mensagens. O SDR continua terminando na qualificacao e o
closer continua humano. Contrato em `docs/architecture/SDR_JOURNEY_STATE_MACHINE.md`.

Proximo: `campaign.metadata.offering_kind ∈ {product, service}`. A distincao
produto/servico pertence a campanha, nao a persona — uma persona pode operar as
duas ao mesmo tempo. O `offering_kind` passa a escolher os fields obrigatorios
de qualificacao (hoje derivados de `business_model`, o que impede a coexistencia)
e o par de eventos correto de conversao e fechamento.

Depois: closer agentico. As edges `visible_to_agent` distinguem SDR de Closer, o
Closer enxerga apenas o subgrafo da campanha do pedido corrente, e so entra em
jornada `qualificado` ou `convertido` — nunca `entregue` ou `cancelado`.
Detalhamento em `docs/knowledge-flow.md`, secao "Produto e servico".
