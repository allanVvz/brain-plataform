# Divida tecnica

## UMQ-001 - WA Validator marca falsamente a pergunta de nome

Em 2026-09-18, a sessao interna `014b2cf4-fb69-4cda-93fa-189df60c68af`
teve `technical_pass=true`, mas falhou em `customer_name_question_once`.
Sua evidencia mostra uma unica emissao da pergunta, com
`previous_question_emissions=0` e auditoria de repeticao aprovada. A regra de
qualidade precisa distinguir a pergunta valida da resposta do cliente no turno
seguinte. Nenhuma mensagem real foi enviada por essa validacao.

Status: aberto.

Dono: runtime/WA Validator.

Criterio de encerramento: uma sessao `cold` passa com a pergunta de nome
emitida uma vez e com proof e ledger preservados em todos os turnos.
