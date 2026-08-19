# Pendências técnicas conhecidas

## Trava de segurança para "keep sem branch ativa com evidência real"

**Status**: documentada, não implementada. Decisão de escopo (2026-08-14):
priorizar o ajuste de `SYSTEM_PROMPT` primeiro (ensinar a semântica de
`branch_action`) e observar se isso já resolve na prática antes de mexer em
código de produção. Esta nota existe pra retomar rápido sem re-investigar,
caso o padrão volte a aparecer depois do fix de prompt.

### O bug

`branch_action: "keep"` proposto pelo modelo sem nenhum galho ativo, mas com
evidência real (branch citada, fato extraído, evidence_span literal) —
`graph_proof_checker_v3.check()` rejeita incondicionalmente
(`keep_without_active_branch`), sem nenhum caminho de recuperação quando
havia sinal real. A proposta inteira (boa) é descartada e a conversa cai
num fallback que repete a pergunta publicada, palavra por palavra, pra
sempre — o modelo, uma vez que "acha" que já selecionou, nunca propõe
`"select"` de novo sozinho.

Caso real de produção que expôs isso: ver `exemplos-de-conversas.md`
(`conversation_turn_proofs.id = 31ac8fa5-f9f8-40bb-93f8-982fa03b91d8`).

### Por que não é sempre pego

Já existe um mecanismo — `_apply_authoritative_branch_resolution()`
(`api/services/graph_agent_runtime_v3.py`, ~linha 693) — que ignora o
`branch_action` do modelo e decide autoritativamente sempre que o backend
consegue resolver a mensagem do cliente **deterministicamente** para
exatamente um produto (`deterministic_candidates` com length==1). Nesse
caminho, a lógica já está certa: `action = "switch" if active else "select"`
— nunca "keep" incorreto.

O bug só aparece no caminho **ambíguo**: quando a mensagem do cliente casa
com mais de um produto do catálogo (ex.: "polimento" bate em 7 produtos
diferentes — ver `servicos.md`), a resolução determinística não dispara, e
a função cai direto no branch final:

```python
else:
    return proposal   # devolve a proposta do modelo sem correção nenhuma
```

É exatamente aqui que o `"keep"` errado do modelo passa sem ajuste.

### Onde a correção deve entrar (quando for implementar)

No mesmo `else: return proposal` (~linha 725-726 de
`graph_agent_runtime_v3.py`). Antes de devolver a proposta sem alteração,
checar: `branch_action == "keep"` sem branch ativa, mas
`branch_anchor_node_id` presente em
`context.retrieval_trace.branch_candidates` (já filtrado por
`BRANCH_EVIDENCE_MIN_SCORE = 0.18`) e `branch_evidence_span` não vazio → se
sim, tratar como o caminho determinístico já trata: `anchor =
proposal.branch_anchor_node_id`, `action = "select"`, `evidence_span =
proposal.branch_evidence_span`, caindo no mesmo bloco de montagem final que
o caminho `resolved_anchor` já usa (linha 728+) — reaproveita código
existente, não duplica lógica.

Isso não relaxa a régua de evidência (continua exigindo
`BRANCH_EVIDENCE_MIN_SCORE`) — só corrige o rótulo do verbo quando o modelo
já escolheu certo mas nomeou errado.

### Critério pra retomar

Se, depois do fix de prompt, o mesmo padrão (`keep_without_active_branch`
com evidência real presente) ainda aparecer em produção — consultar
`conversation_turn_proofs.proof_result->'model_proposal_errors'` pra
confirmar antes de reabrir.
