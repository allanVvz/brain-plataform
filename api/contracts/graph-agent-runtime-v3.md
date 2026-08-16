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
- Cada field declara `validation.mode`: `enum`, `schema` ou `semantic`.
- `enum` exige valores canônicos e aliases publicados; `schema` exige JSON
  Schema; `semantic` exige descrição e tipo, exemplos ou regras suficientes.
- `scope=declaration` faz o field pertencer ao node que o declarou. Os scopes
  compatíveis `persona` e `branch` permanecem disponíveis.
- Fields obrigatórios precisam de pergunta publicada, statuses aceitos e
  overwrite policy. Dependências de fields não podem formar ciclos.
- Handoff e claims comerciais exigem regra, política e evidência publicada.
- Uma publicação só ativa depois de coordenadas, memberships, contratos,
  entries, chunks e embeddings completos nas quantidades do manifesto.
- O provider de embeddings vem do runtime; o modelo efetivo integra o checksum.
- Claims, rules, validators, perguntas e fatos estruturados possuem chunks
  próprios. Perguntas ancoradas em outro galho não entram no contrato.
- `Embedded` e `Gallery` protegidos são reutilizados pela projeção; versões
  anteriores são desativadas sem exclusão destrutiva.

## Turno conversacional

```text
inbound canônico
→ resolução literal/semântica de todos os serviços
→ consumo dos spans de serviço
→ retrieval híbrido dentro da membership
→ proposta JSON estrita do modelo
→ validação declarativa dos demais fields
→ proof checker e um repair direcionado opcional
→ pergunta/fallback publicado
→ ledger + proof exatamente uma vez
→ outbox idempotente
```

`service_operations[]` é o contrato autoritativo do conjunto de serviços. Cada
operação contém `add`, `keep` ou `drop`, anchor publicado, checksum do caminho e
evidência literal. Um novo serviço é adicionado por padrão; somente linguagem
explícita de troca ou remoção gera `drop`. Repetição só muda o foco. Seleção
ambígua não altera ledger nem branches.

Um span consumido como serviço nunca pode validar outro field. O
`active_branch_node_id` representa o foco e `active_branch_node_ids` representa
o conjunto autoritativo. Os campos singulares continuam apenas como adaptador
de compatibilidade.

Na primeira resposta incompatível, nenhum fato é persistido e a pergunta
publicada é repetida. Na segunda, o field recebe `status=unknown`, `value=null`
e motivo `ignored_twice`. “Não sei” explícito pode gerar `unknown`
imediatamente. `collection_complete` encerra a coleta; `qualification_complete`
só é verdadeiro quando todos os campos obrigatórios são conhecidos.

Falha técnica não produz copy nem handoff. Handoff só é válido por regra do
contrato compilado. Claims usam apenas evidência autorizada. Mudanças de
publicação invalidam fatos incompatíveis antes do próximo commit.

## Projeção e auditoria

A nota comercial estruturada separa fatos comuns de fatos por serviço e é
persistida em metadata. `commercial_note` e `interesse_produto` singulares
continuam refletindo o serviço em foco por compatibilidade.

`canonical_inbound_id` é único em `conversation_turn_proofs`. Fatos preservam
mensagem, evidence span, confiança, revisão e supersessão. O proof expõe a
resolução de serviços, operações, spans consumidos, conjunto anterior/posterior
e resultado de validação de cada field.

Uma resposta HTTP perdida depois do commit não autoriza replay. A reconciliação
operacional só encerra o inbound quando encontra uma prova válida, no máximo um
outbound e sua mensagem persistida; ela não chama retrieval, modelo ou
transporte.
