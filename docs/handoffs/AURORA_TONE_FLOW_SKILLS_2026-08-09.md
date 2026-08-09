# Conteúdo pronto — Tone Matching + Conversational Flow Management (Aurora)

Data: 2026-08-09
Escopo: node `aurora-tone` (existente) + novo node `aurora-flow-management`, ambos
`capabilities.global_context: true` — o mesmo mecanismo que já injeta o tom de voz da
Aurora em todo turno, para qualquer branch, sem custo extra de token por chamada (o
conteúdo compete pelo mesmo orçamento de `context_cards`/RAG já existente, agora com um
teto real: `graph_agent_runtime_v3.RAG_CHUNK_TOKEN_BUDGET`).

**Por que isto não foi publicado automaticamente nesta sessão**: é conteúdo de marca/voz
comercial da Aurora, não uma correção de bug. Isso deve ser revisado por quem é dono do
tom de voz da conta antes de publicar via Sofia (`/knowledge/graph`, comando de grafo, ou
`/sofia/graph-command`) — não uma escrita direta em SQL. As diretrizes abaixo já vêm
destiladas para o mesmo tamanho dos campos `traits`/`avoid` que o node `aurora-tone`
já usa hoje, evitando colar os artigos originais (que inflariam o prompt em todo turno).

## 1. Tone Matching — adicionar ao node `aurora-tone` existente

Node atual (`aurora-tone`, ver `graph_json_node_id: aurora-tone`) já tem `traits`,
`avoid`, `summary`. Adicionar um novo campo `adaptation_rules` ao `data`:

```json
"adaptation_rules": [
  "Leia a formalidade e a energia da última mensagem do cliente antes de responder.",
  "Espelhe proporcionalmente, mas nunca abaixo do tom mínimo já definido (cordial, profissional) -- mensagem curta e informal do cliente não autoriza gíria ou informalidade excessiva da Aurora.",
  "Nunca espelhe grosseria, sarcasmo ou negatividade do cliente -- mantenha o acolhimento mesmo quando o cliente for seco ou insatisfeito.",
  "Ajuste gradualmente, nunca de um turno para o outro -- uma mudança brusca de tom soa artificial."
]
```

Isso mapeia diretamente para a skill "Tone Matching" (formalidade/energia/detalhe,
piso de marca, sem espelhar negatividade, sem mudança brusca) sem herdar sua função de
scoring numérico (`analyzeTone()`), que é redundante — o modelo já lê a mensagem
diretamente, não precisa de um score calculado à parte.

## 2. Conversational Flow Management — novo node `rule`

Node novo, mesmo padrão do `aurora-tone` (`node_type: rule`,
`capabilities.global_context: true`, filho do node persona ou do briefing):

```json
{
  "node_type": "rule",
  "slug": "aurora-flow-management",
  "title": "Gestão de fluxo conversacional",
  "status": "validated",
  "data": {
    "capabilities": { "global_context": true },
    "summary": "Uma pergunta por turno, reconhecer-responder-retomar em objeções/desvios, mensagens curtas, e uma escada clara de recuperação quando não entender a resposta.",
    "flow_rules": [
      "Nunca empilhe duas perguntas na mesma mensagem -- mesmo reformulando, faça só uma pergunta por turno.",
      "Ao lidar com objeção, dúvida ou desvio de assunto: reconheça brevemente, responda o que foi perguntado, e só depois retome a pergunta pendente -- tudo na mesma mensagem, sem pular a pergunta pendente.",
      "Mensagens curtas: no máximo 2-3 frases por resposta.",
      "Se não entender a resposta do cliente: peça esclarecimento uma vez; se continuar confuso, ofereça alternativas concretas; se ainda assim não resolver, sinalize handoff -- nunca insista na mesma pergunta do mesmo jeito mais de duas vezes."
    ]
  }
}
```

Isso mapeia para a skill "Conversational Flow Management": uma pergunta por turno e
"reconhecer → responder → retomar" atacam diretamente o gap A do relatório de
2026-08-08 (pergunta duplicada na mesma mensagem) e a sensação robótica geral; a escada
de recuperação (esclarecer uma vez → alternativas → handoff) já usa o mecanismo de
handoff que a Aurora tem hoje, só dando uma sequência explícita a ele. Os outros
elementos da skill original (arco de 5 estágios, métricas de otimização, guia de
duração por canal) foram deixados de fora por não se aplicarem a uma qualificação curta
de WhatsApp ou por já serem responsabilidade de outra parte do sistema (o proof-checker
decide quando a qualificação está completa; não é um comportamento de prompt).

## 3. Como aplicar

1. Publicar via Sofia/graph-command para a persona `aurora` (mesmo fluxo usado para
   `aurora-tone` original, `briefing_atendimento_conversacional_aurora_2026_08_07`).
2. Confirmar no publish resultante (`graph_compiler_v3.compile_persona_publication`)
   que `aurora-flow-management` aparece com `capabilities.global_context: true` e que o
   `aurora-tone` atualizado mantém `revision` incrementada.
3. Validar com WA Validator (`sdr_qualificacao_carro`, `sdr_troca_servico`) que:
   - nenhuma resposta empilha duas perguntas na mesma mensagem;
   - o tom se adapta a uma mensagem de teste mais informal/curta sem ficar informal
     demais;
   - tokens de entrada por turno (medir `len(prompt)`/contagem real no node "Build
     graph grounded agent request") não sobem em relação a uma execução de referência
     antes da publicação — o teto `RAG_CHUNK_TOKEN_BUDGET` adicionado nesta sessão torna
     essa comparação verificável.
