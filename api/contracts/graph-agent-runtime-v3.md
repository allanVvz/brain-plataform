# Graph Agent Runtime v3 — contrato executável

Contract-ID: `graph-agent-runtime-v3`

Compiler: `graph-compiler-v3.2.1`

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

`canonical_inbound_id` é único em `conversation_turn_proofs`. Fatos preservam
mensagem, evidence span, confiança, revisão e supersessão. O binding define
runtime, modelo, endpoint e credencial; o template não define conteúdo de
cliente, fields, produto, preço ou modelo comercial.

Uma resposta HTTP perdida depois do commit não autoriza replay. A reconciliação
operacional só encerra o inbound quando encontra exatamente uma prova válida,
um outbound único e sua mensagem persistida; ela não chama retrieval, modelo
ou transporte.
