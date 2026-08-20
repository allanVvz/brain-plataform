> **DEPRECIADO em 2026-08-19 — SUPERSEDED BY `docs/roadmaps/AGENT_ROADMAP.md`.**
> Não usar como fonte de verdade. Mantido apenas como histórico.
> Motivo: numeração P0-P5 e mecanismo proposto (`offering_kind`, `visible_to_agent`
> para distinguir SDR/Closer) contradizem a numeração e o estado atual de
> `AGENT_ROADMAP.md` §7 ("Orquestradores por estágio e campanha por ciclo") e não
> foram reconciliados com a arquitetura Graph JSON v2/`graph_agent_runtime_v3`.
> A ideia de `campaign.metadata.offering_kind ∈ {product, service}` (produto/
> serviço pertence à campanha, não à persona) segue viva como referência de
> design em `docs/architecture/CAMPAIGN_STAGE_NODE_VISIBILITY.md`. **Atenção:**
> `visible_to_agent` especificamente é uma armadilha — vira `publishes_to`
> genérico no upgrade v2.0→v2.1 (`api/services/graph_json_v21_adapter.py:14`) e
> perde toda semântica de audiência/estágio; não reusar esse relation_type para
> condicionar visibilidade de node por agente.

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
