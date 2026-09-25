# Correções preparadas após o E2E de conversa

Fonte das ocorrências: [auditoria da release](conversation-human-contract-2026-09-25.md).

O candidate de `conversation-runtime` passa a exigir uma fixture de conversa
com o modelo real antes do cutover. A fixture de Utzig rejeita a retomada
imediata de `nome_cliente` e a repetição da fala anterior. O prompt orienta a
esclarecer a dúvida e adiar o mesmo campo; no estado de confirmação, orienta
a apresentar o resumo e reservar a afirmação de encaminhamento para handoff.

Quando o RPC de contexto omite os metadados da última pergunta, o runtime
consulta a projeção canônica de mensagens. O transport terminaliza como `sent`
todo inbound cujo runtime concluiu o commit, inclusive handoff. Há regressões
para os motores determinístico e agentic e para o sink interno.

A política publicada `explicit_correction` continua protegendo os fatos
anteriores. As mudanças de preferência vistas na Tock precisam de revisão
específica antes de permitir uma substituição automática de valores.

Estas correções estão somente no código fonte. Não houve novo build, candidate,
cutover ou WA Validator; as duas jornadas e o buffer histórico continuam
pendentes de validação produtiva. `conversation-runtime` e `transport` exigem
releases distintas, cada uma com seu digest e candidate. O buffer que já tem
commit não deve ser reprocessado para demonstrar a correção do worker.
