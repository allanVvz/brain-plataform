# Exemplos reais de conversa

Capturados direto de `conversation_turn_proofs` em produção durante a
investigação de 2026-08-14 (lead 87, Aurora, teste real com o WhatsApp do
Allan). Não são exemplos inventados.

## Exemplo 1 — abertura (sem galho ainda) e a dúvida engolida

Cliente: "Oi! Tudo bem? Queria saber quais serviços vocês fazem aí na
Aurora."

Resposta da Aurora **naquele momento**:
> "Olá! Que bom falar com você. Antes de tudo, como você se chama?"

Metade certo, metade errado.

Certo: nenhuma pergunta genérica sobre serviço foi assumida como seleção de
galho — a Aurora ainda está no nível persona, colhendo o nome antes de
qualquer coisa. `branch_action` nem entra em jogo aqui porque não há sinal
de produto específico ainda.

**Errado: a pergunta sobre os serviços nunca foi respondida.** "serviços"
não bate em nenhum branch anchor, então `deterministic_candidates` vinha
vazio e o turno caía no curto-circuito determinístico da saudação — zero RAG,
zero chamada de modelo, e o pedido do cliente descartado junto.

Corrigido: só uma saudação que **não pede nada** pode pular o modelo
(`_is_bare_greeting`, `graph_agent_runtime_v3`). "Oi", "oii", "oi, tudo bem?"
seguem model-free; qualquer coisa depois da saudação vai para o caminho
normal, com a saudação virando prefixo (`retrieval_trace.greeting_response`).
A resposta esperada hoje é saudação + os serviços do grafo + a pergunta do
nome, numa mensagem só.

## Exemplo 2 — o bug real: "keep" no lugar de "select"

Cliente: **"polimento no vidro e polimento na lataria"**

`model_proposal` real (turno `31ac8fa5-f9f8-40bb-93f8-982fa03b91d8`):

```json
{
  "reply": "Entendi, você quer o polimento de vidros e também na lataria. Vou anotar os dois. E o que mais te incomoda no carro hoje?",
  "branch_action": "keep",
  "branch_anchor_node_id": "aurora-product-glass-polish",
  "branch_evidence_span": "polimento no vidro e polimento na lataria",
  "extracted_facts": [{
    "field_key": "servico", "value": "polimento de vidros",
    "confidence": 0.9, "evidence_span": "polimento no vidro"
  }]
}
```

Isso é **quase perfeito**: branch certa identificada (havia 8 candidatas
evidenciadas, essa foi a de maior pontuação), fato extraído certo, resposta
natural. O único erro: `branch_action: "keep"` — não havia nenhum galho
ativo ainda, então isso deveria ter sido `"select"`.

Consequência: `graph_proof_checker_v3.check()` rejeita `"keep"` sem galho
ativo incondicionalmente (`keep_without_active_branch`), sem nenhuma
recuperação quando havia evidência real. A proposta inteira — boa reply,
fato certo — foi descartada, e a conversa caiu num fallback que repetiu a
pergunta de serviço, palavra por palavra, nos turnos seguintes, mesmo
depois do cliente responder de novo.

## O que a mesma proposta deveria ter sido

A correção é só o verbo — todo o resto já estava certo:

```json
{
  "reply": "Entendi, você quer o polimento de vidros e também na lataria. Vou anotar os dois. E o que mais te incomoda no carro hoje?",
  "branch_action": "select",
  "branch_anchor_node_id": "aurora-product-glass-polish",
  "branch_evidence_span": "polimento no vidro e polimento na lataria",
  "extracted_facts": [{
    "field_key": "servico", "value": "polimento de vidros",
    "confidence": 0.9, "evidence_span": "polimento no vidro"
  }]
}
```

Com `"select"`, a branch teria sido estabelecida de verdade, o fato de
`servico` teria sido persistido, e a conversa seguiria naturalmente pro
próximo campo (`objective`) sem nunca cair em fallback.

Este é exatamente o caso que motivou o parágrafo novo no `SYSTEM_PROMPT`
(`graph_agent_runtime_v3.py`) explicando a semântica dos 4 verbos de
`branch_action`. Ver `pendencias-tecnicas.md` para a trava de segurança no
backend que ainda não foi implementada, caso o ajuste de prompt sozinho não
seja suficiente.
