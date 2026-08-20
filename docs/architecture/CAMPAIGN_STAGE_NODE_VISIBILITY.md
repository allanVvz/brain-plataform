# Escopo de node por campanha/estágio

Autoridade: `docs/roadmaps/AGENT_ROADMAP.md`, item 7 ("Orquestradores por
estágio e campanha por ciclo → arquitetura multi-agente"). Este arquivo é um
apontador, não uma segunda fonte de verdade — em caso de conflito, o roadmap
vence.

## O que este arquivo cobre

- A pontuação de jornada (item 7a) — completude do "caminho feliz" como sinal
  de estágio (SDR/conversão/venda/pós-venda), hoje só exposta, sem
  roteamento automático.
- O Agent Registry mínimo (item 7b) — SDR e Closer como papéis configurados
  sobre o mesmo grafo, não personas/modelos separados.
- O gap real por trás de "node visível só na campanha de qualificação":
  `campaigns_service.py` já produz `audience_snapshot` por revisão de
  campanha, mas `conversation_runtime`/`graph_agent_runtime_v3` nunca leem
  isso — confirmado, zero hits. Um Closer futuro reusaria os mesmos
  nodes/offers do grafo já compilado, só acrescentando condição por
  `campaign_stage` — nunca duplicando grafo ou persona.

## Decisão explicitamente não tomada aqui

Vínculo lead→campanha escrito pelo próprio ciclo vs. tabela nova — as duas
opções seguem em aberto no roadmap (item 7). Criar tabela nova exige
autorização explícita do humano (regra de governança 7 do roadmap,
`AGENTS.md` §2). Não decidir isso em silêncio.

## Armadilha já identificada

`visible_to_agent` (relation_type usado num design anterior, arquivado em
`docs/archive/DEPRECATED_2026-08-19/BRAIN_AI_MASTER_ROADMAP.md`) **não serve**
pra condicionar visibilidade por agente/estágio — vira `publishes_to`
genérico no upgrade v2.0→v2.1 (`api/services/graph_json_v21_adapter.py:14`) e
perde toda semântica. O mecanismo real é `qualification.condition`/
`conditional_fields`, já usado pra condicionar oferta e pergunta por
audiência.
