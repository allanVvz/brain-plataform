# E2E interno de conversa em producao — 2026-09-24

## Escopo e release

- Teste direto pelo WA Validator com provider `internal_validator` e sink interno. Nenhuma mensagem foi enviada ao WhatsApp real. Nao houve browser, request HTTP de cliente nem screenshot neste teste.
- Workflow de release: `36057946348`; candidate isolado, cutover blue/green e canario interno passaram.
- Runtime ativo: slot `blue`, SHA `0703d78fb2d26f31dfd2f5db2027e1584511ef08`, digest `sha256:5b0bb7af00bc0c855440d8faf7df867039f450a090f9f5deb463eef65aece3ca`.
- Gateway, control-plane e transport permaneceram nos digests anteriores. Claims nao foram pausados.
- Auditoria posterior: zero conflitos CAS em 15 minutos, zero buffers criticos, zero outbound de agente sem proof em 15 minutos e zero divergencia de checksum. Backup recente foi apenas aviso, sem migration nesta release.

## Utzig Garage

- Sessao `d59a2c87-bfb4-4ee5-94f1-6a62123facf7`, 20:57:27–20:58:36 UTC.
- Publicacao `2a2fa0a6-1dc0-4b2e-b903-343323720e63`, versao 11, checksum `sha256:658229a5356e6876c297aa68641755b3bf3f88d29a58bf12e290462dae3a89de`.
- Seis inbounds internos, seis decisoes, seis proofs validos, seis commits completos e seis outbounds persistidos no sink interno. Cada turno teve dois model calls, nenhum repair, um unico outbound depois do proof. Latencia entre mensagem sintetica e resposta: aproximadamente 10–12 s por turno.
- `technical_pass=true`; `quality_pass=false`. A primeira resposta registrou `fact_dependency_unsatisfied:servico:nome_cliente` e descartou metadado opcional de claim, preservando a resposta e os fatos validos.
- Ao receber a duvida "Como pedir uma avaliacao?" enquanto aguardava nome, a IA respondeu a duvida, mas perguntou o nome novamente. O audit registrou `customer_name_question_once=false` e `question_attempt_budget_exceeded`.
- Ao receber o nome, todos os campos obrigatorios ficaram completos. A resposta resumiu servico, veiculo e condicao e disse que encaminharia o pedido, mas terminou perguntando se o cliente queria contar mais algo. O "Sim" seguinte nao levou ao handoff: a jornada terminou em `awaiting_confirmation`, sem confirmacao explicita nem handoff.

## Tock Fatal

- Sessao `c14e81de-f316-4d34-b604-497c4529b211`, 20:59:11–21:01:45 UTC.
- Publicacao `2b46d7a2-fba9-4b92-aa2a-27fb53f55af4`, versao 38, checksum `sha256:3aa4cd2d4a7c50389534ab9cb7c372474030b3852eaaa4c851fc8b7f14d6a28a`.
- Sete inbounds internos, sete decisoes, sete proofs validos, sete commits completos e sete outbounds persistidos no sink interno. Cada turno teve dois model calls, nenhum repair, um unico outbound depois do proof. Latencia entre mensagem sintetica e resposta: aproximadamente 18–27 s por turno.
- `technical_pass=true`; `quality_pass=false`. O primeiro turno teve observacao editorial `required_reply_content`, sem bloqueio tecnico.
- Depois de perguntar o nome, o driver sintetico enviou "Sim" porque os campos obrigatorios ja estavam completos. O proof do inbound `e968e091-48ff-408c-b144-92003fcf35c8` aceitou `nome_cliente="Sim"`, owner `persona:tock-fatal`, sem erro de validacao. A IA respondeu que "Sim" talvez nao fosse o nome e perguntou de novo. O ledger e a resposta ficaram contraditorios.
- A jornada terminou em `awaiting_confirmation`, com campos obrigatorios completos e sem handoff. O turno final respondeu uma duvida sobre pecas casuais, mas nao concluiu o pedido.

## Correcoes locais apos o E2E

- O driver do Validator agora responde uma pergunta opcional ainda pendente antes de enviar a confirmacao sintetica.
- A validacao generica de nome rejeita respostas afirmativas isoladas como `Sim`, `Nao`, `Yes` e `OK`; um nome curto plausivel continua valido.
- Regressao local: 16 testes focados e 39 testes de runtime/Validator passaram; `py_compile` dos arquivos alterados passou.
- Essas correcoes nao estao no digest ativo. Nenhum segundo deploy corretivo foi iniciado nesta operacao.

## Reteste necessario

Com a correcao acima em uma release futura, executar novamente Utzig e Tock pelo WA Validator interno e exigir nome correto no ledger, pergunta final inequivoca, confirmacao e um handoff. Depois cobrir nome espontaneo, duvida entre perguntas, veiculo no resumo final, nova jornada, troca de servico, interesse antigo e inbound duplicado. Interromper novos envios se houver fato atual contraditorio, duplicidade, persona errada ou confirmacao indevida de preco, data ou horario.
