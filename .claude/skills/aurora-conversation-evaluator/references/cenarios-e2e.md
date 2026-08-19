# Cenários reais capturados nesta sessão (2026-08-10 a 2026-08-14)

Três incidentes reais de produção, todos diagnosticados com evidência
direta do banco (`conversation_turn_proofs`, `system_events`,
`lead_buffer`). Úteis como cenários de regressão manual e como calibração
de "o que uma falha realmente parece nos dados".

## Cenário 1 — Cascata de silêncio por guard de duplicidade (lead 87)

**Sintoma reportado**: Aurora parou de responder por horas.

**Causa real**: um guard de conteúdo duplicado (texto idêntico a um
outbound recente) devolvia HTTP 409 e chamava
`record_whatsapp_safety_violation`, que pausava a lead inteira
(`handoff_level='full'`) e varria **todo** o resto do backlog de mensagens
não respondidas pra `waiting_human` — de uma vez, sem tentar mais nada.

**Status**: corrigido (`9ee8d45`) — duplicidade de conteúdo agora só
suprime o reenvio silenciosamente, sem pausar a lead nem varrer irmãs.
Retry limitado + escalonamento gradual (`level="partial"`) também
adicionados pra evitar que uma falha isolada pause a conversa inteira.

**Como reconhecer no dado**: `system_events` com
`whatsapp.safety_violation` seguido imediatamente por múltiplos
`whatsapp.inbound_waiting_human` pro mesmo `lead_ref` num intervalo de
segundos.

## Cenário 2 — Entrada na branch de reclamação sem motivo (leads 135, 136)

**Sintoma reportado**: Aurora entrou no fluxo de reclamação (pediu desculpa
por um problema que o cliente nunca mencionou) e insistiu mesmo depois do
cliente dizer "não aconteceu nada".

**Causa real**: `branch_selection_allowed` (o gate que autoriza a primeira
seleção de galho) era calculado sobre os top-8 candidatos **sem nenhum piso
de pontuação** — qualquer branch, mesmo com score 0, entrava. O modelo
podia "selecionar" a branch de reclamação com zero evidência real.

**Status**: corrigido (`14e6d9c`) — `_evidenced_branch_candidates()` agora
exige `score >= BRANCH_EVIDENCE_MIN_SCORE (0.18)`, o mesmo piso já usado
pra troca de branch (`possible_switches`).

**Como reconhecer no dado**: `conversation_ledgers.active_branch_node_id`
apontando pra uma branch de serviço (reclamação/atendimento-humano) sem
nenhuma mensagem do cliente mencionando problema, insatisfação, ou pedido
de humano.

## Cenário 3 — "keep" sem branch ativa, com evidência real (lead 87, teste do Allan)

**Sintoma reportado**: Aurora repetiu a pergunta de serviço mesmo depois do
cliente responder com sinal forte e real ("polimento no vidro e polimento
na lataria" — 8 branches candidatas, todas bem acima do piso 0.18).

**Causa real**: o modelo propôs `branch_action: "keep"` em vez de
`"select"` no turno que deveria estabelecer a primeira branch — resto da
proposta perfeito (branch certa, fato extraído certo, resposta natural).
`graph_proof_checker_v3.check()` rejeita `"keep"` sem branch ativa sem
nenhuma recuperação quando havia evidência real, e a proposta boa inteira
foi descartada, caindo num fallback que repete o texto literal do grafo.

**Status**: mitigado via `SYSTEM_PROMPT` (parágrafo novo explicando a
semântica dos 4 verbos de `branch_action` — ver `exemplos-de-conversas.md`
no skill `aurora-premium-sdr`). Trava de segurança no backend documentada
mas **não implementada** — ver `pendencias-tecnicas.md`.

**Como reconhecer no dado**:
`proof_result.model_proposal_errors == ["keep_without_active_branch"]` com
`proof_result.mode == "published_fallback"`, em turnos onde
`retrieval_trace.branch_candidates` não está vazio (ou seja, havia
evidência real — não é o caso legítimo de "conversa fiada sem sinal
nenhum").

## Como usar estes cenários pra testar uma mudança de prompt

Depois de qualquer ajuste no `SYSTEM_PROMPT`, reproduza (com lead de teste,
nunca lead real) a mensagem "polimento no vidro e polimento na lataria"
logo após o nome, e confirme em `conversation_turn_proofs.proof_result`
que `mode` não é mais `"published_fallback"` e
`active_branch_node_id` no ledger fica preenchido.
