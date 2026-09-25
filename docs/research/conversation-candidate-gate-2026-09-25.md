# Candidate conversacional barrado em 2026-09-25

Impacto pretendido: `service`, somente `conversation-runtime`. A auditoria
read-only na VPS passou: runtime azul no digest
`sha256:392e138720deeda5db5159e3ca35ad01eb7505023eb700fbcb6608b774a23523`,
claims ativos, zero conflito CAS, zero outbound sem proof e zero divergência de
checksum. Havia um buffer crítico sintético já conhecido do E2E anterior.

O build imutável de `9f21691a25cd918cbec18fcfe219f043af2073ee` produziu
`sha256:02fe8052888301031edae5485b5742ec2132373a6ae7cdcf11d336418bb545ad`.
O manifesto incremental `d38d08190ee70c4ccdca6395b9466a9c8b70ec87` preservou
as entradas de gateway, control-plane e transport. O
[dry-run](https://github.com/allanVvz/brain-plataform/actions/runs/36185642472)
passou. A
[release](https://github.com/allanVvz/brain-plataform/actions/runs/36185750075)
iniciou o candidate no slot verde, mas falhou às 20:28:18 UTC antes do cutover:
`AssertionError: candidate repeated the interrupted qualification field`.
O caso era a dúvida da Utzig enquanto `nome_cliente` estava pendente. O probe
usa duas chamadas ao modelo, provider `internal_validator` e `commit_result=False`.
Como a validação ocorreu antes da impressão do resultado, o log registrou a
causa e o campo repetido, mas não o texto da resposta.

Após a falha, `rollout-microservices.sh status` mostrou runtime azul e todos os
serviços alinhados, sem pausa; `docker ps` remoto não mostrou runtime verde
rodando. Nenhum outbound real ou do Validator foi enviado nesta tentativa.
Transport não foi promovido. O buffer antigo não foi reprocessado.

Foi preparado um ajuste posterior somente em código: a resposta recebe
`reply_guidance.defer_field_until_later` quando a última pergunta enviada era
de qualificação, o campo continua pendente e a mensagem atual traz uma dúvida.
Esse campo sai das guias elegíveis daquele turno, sem escolher outro campo pelo
modelo. O probe passa a imprimir observação sanitizada antes de validar, para
que uma falha futura preserve a resposta. Testes focados passaram; o ajuste
não foi construído nem testado em candidate. As jornadas completas Utzig e
Tock continuam pendentes.
