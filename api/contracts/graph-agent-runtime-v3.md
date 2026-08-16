# Graph Agent Runtime v3 — contrato executável

Contract-ID: `graph-agent-runtime-v3`

Compiler: `graph-compiler-v3.3.0`

Este Markdown faz parte da proveniência de cada publicação. O compilador grava
seu caminho e checksum no Graph JSON; qualquer alteração deliberada neste
contrato produz um novo checksum de publicação.

## Autoridade

`knowledge_nodes` e `knowledge_edges` são a única fonte editável. O Graph JSON
v3 é um snapshot compilado, imutável e auditável. Um node só é branch anchor
quando declara `capabilities.branch_anchor=true`.

## Invariantes de compilação

- Um caminho primário não pode ter ciclo nem dois pais.
- Fields podem pertencer a qualquer node alcançável e precisam declarar owner,
  pergunta publicada, statuses aceitos, JSON Schema e overwrite policy.
- Dependências de fields não podem formar ciclos.
- Handoff e claims comerciais exigem regra/política e evidência publicada.
- Uma publicação só ativa depois de coordenadas, memberships, contratos,
  entries, chunks e embeddings completos, nas quantidades exatas do manifesto
  de projeção compilado.
- O provider de embeddings vem do runtime (`openai`, `local` ou `auto`) e o
  modelo efetivo integra o checksum. Sem chave OpenAI, `auto` usa o modelo
  multilíngue local empacotado na imagem; nunca gera vetor sintético.
- Claims, rules, validators, perguntas e fatos estruturados possuem chunks
  próprios; rules e perguntas exigidos pelo contrato não são descartados pelo
  reranking probabilístico.
- Perguntas ancoradas em outro galho não podem ser importadas para o contrato.
- `Embedded` e `Gallery` protegidos são reutilizados pela projeção; versões
  anteriores são desativadas sem exclusão destrutiva.

## Turno conversacional

Antes do turno, `embed` e `embedded` compilam para o mesmo tipo protegido e a
subarvore de um node `global_context` integra todas as memberships de branch.
Publicacoes com `faq_projection_contract=v1` so ativam quando cada FAQ factual
elegivel possui membership, entry e chunk canonico `faq` com pergunta e resposta.

```text
inbound canônico
→ resolução semântica de branch
→ retrieval híbrido Postgres dentro da membership
→ proposta JSON estrita do modelo
→ proof checker declarativo
→ um repair direcionado opcional
→ pergunta/fallback publicado
→ ledger + proof exatamente uma vez
→ outbox idempotente
```

Falha técnica não produz copy nem handoff. Handoff somente é válido por uma
regra do contrato compilado. A pergunta publicada é composta no momento da
emissão; o modelo não precisa repeti-la literalmente em `reply`.

Claims só podem usar evidência explicitamente autorizada pela política do
contrato. Uma resposta curta com field pendente não dispara resolução global
de branch. Mudanças de publicação invalidam fatos incompatíveis antes do
próximo commit.

## Identidade e auditoria

Em mensagens compostas, a clausula interrogativa e ranqueada separadamente.
Pergunta ou alias normalizado exato vence; selecao semantica exige score minimo
de `0.18` e margem de `0.03`. A resposta canonica do FAQ precede exatamente a
primeira pergunta pendente e seu chunk reservado nao participa do MMR.

`canonical_inbound_id` é único em `conversation_turn_proofs`. Fatos preservam
mensagem, evidence span, confiança, revisão e supersessão. O binding define
runtime, modelo, endpoint e credencial; o template não define conteúdo de
cliente, fields, produto, preço ou modelo comercial.

Uma resposta HTTP perdida depois do commit não autoriza replay. A reconciliação
operacional só encerra o inbound quando encontra exatamente uma prova válida,
um outbound único e sua mensagem persistida; ela não chama retrieval, modelo
ou transporte.

## Máquina de estados SDR

- `collecting` resolve um serviço publicado e coleta somente o primeiro field
  realmente pendente.
- Campos completos produzem o resumo e a `confirmation_question` publicada,
  transitando para `awaiting_confirmation` sem handoff.
- Somente uma confirmação explícita em turno posterior produz
  `qualified_confirmed`, `route=HUMAN` e handoff no mesmo commit.
- Negação ou correção volta à coleta sem apagar fatos; uma dúvida é respondida
  com FAQ aprovada antes de retomar a confirmação.
- Handoff incompleto registra os fields não confirmados e preserva todos os
  fatos para o humano.
- Depois de reativação, `post_qualification_support` responde saudação e FAQ
  sem reiniciar o roteiro. Uma nova confirmação só é exigida após alteração
  explícita do pedido.

Saudação é intenção transversal do turno atual e nunca preenche field. O field
`servico` é referencial: seu valor, owner, anchor e path checksum precisam
resolver para uma branch da publicação por título, slug, alias ou evidência
semântica segura. Saudações, confirmações, respostas sociais e números isolados
nunca são serviço.

A proteção antirrepetição não lança exceção em produção: fatos aceitos são
commitados e o outbound duplicado é suprimido. CI e Validator continuam
reprovando o critério semântico pelo proof. Todo proof expõe `intent_audit`,
`service_resolution`, `journey_transition`, `confirmation_state` e
`repetition_action`.

## Desfecho comercial

O SDR termina na qualificação. Conversão, venda, entrega e cancelamento são
eventos humanos registrados em `POST /agents/leads/{lead_ref}/journey-events`,
nunca inferidos pelo modelo, e levam a jornada a `converted` ou `closed`.

A projeção a partir do proof **não regride** uma jornada em `converted` ou
`closed`: `journey_transition` continua sendo emitido e a metadata continua
evoluindo, mas o `state` fica com o desfecho registrado pelo humano. Um inbound
depois da venda é suporte ao pedido, não uma nova coleta.

O contrato completo — eventos, idempotência, derivação de `journey_outcome` e a
paleta `resultado/*` — está em `docs/architecture/SDR_JOURNEY_STATE_MACHINE.md`.
