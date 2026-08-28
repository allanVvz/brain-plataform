# Relatório consolidado — Vitória (runtime) e Sofia (autoria)

Branch `agent/sofia-vitoria-audit`, worktree
`C:\Repositores\brain-plataform-sofia-vitoria-audit`, base `29f6ba0`.

**Nada foi deployado, publicado, ativado, migrado ou enviado.** O workflow n8n
de produção não foi tocado — só o template versionado em disco. Transporte e IA
seguem como estavam.

---

## A. Vitória / runtime

### A1. Reconciliação semântica rejeitada por matcher literal — **corrigido**

Causa provada em produção: `_apply_authoritative_branch_resolution` montava a
decisão só a partir de `service_resolution`, produzido pelo matcher literal de
título/slug/alias. Sem correspondência literal, o `branch_anchor_node_id`
correto lido pelo modelo era descartado e a interpretação virava `action=none`.

Correção: `_with_semantic_branch_fallback` injeta a leitura do modelo como
resolução do turno **quando o matcher literal não resolve**. Só preenche
lacuna — resolução ou ambiguidade literal continuam vencendo.

### A2. Confirmação final bloqueada — **corrigido**

Causa: `_deterministic_confirmation_decision` decidia por pertencimento exato a
`_EXPLICIT_CONFIRMATIONS` (~11 frases). `"sim, tá correto"` (3 tokens) não batia
com nenhuma entrada de 1–2 tokens, o modelo já tinha proposto
`qualification_complete` + `handoff_requested`, e o lead ficava sem handoff.

Correção: a função recebe uma `SemanticInterpretation` validada e pergunta
`semantic_conversation_policy.confirms_pending`/`rejects_pending`. Todas as
consequências continuam determinísticas — rota, estágio, `handoff_reason`, e o
carimbo `confirmed_branch_node_ids` que `commit_graph_turn_and_outbox_v3`
(migration 128) consome para fechar ramos do ledger.

### A3. Seleção de público bloqueada — **corrigido** (mesma raiz de A1)

Além disso, `_deterministic_pending_service_clarification` — a escada de
desambiguação — desistia com base em regex de markers; agora lê a interpretação.
E `_deterministic_pending_fact_confirmation` deriva a ação (`add`/`switch`/
`drop`) de `branch_selection` em vez dos markers.

### A4. Pergunta comercial absorvida como campo — **contrato pronto, composição não**

`CustomerQuestion` é um campo separado no contrato, com `kind` (availability,
price, stock, policy, schedule, deadline…), e
`semantic_conversation_policy.unanswerable_commercial_questions` isola as que
não têm nó publicado por trás, para o turno deferir à equipe em vez de inventar
ou ignorar. `claims` sem nó de evidência publicado são descartadas pelo
validador.

**Ressalva honesta:** a *composição* da resposta final (reconhecimento + resposta
às dúvidas + no máximo uma próxima pergunta) ainda não foi reescrita. O contrato
e a validação garantem que a pergunta não vire valor de campo e que nada seja
inventado; garantir que a resposta sempre trate explicitamente as duas partes da
mensagem é a etapa seguinte.

### A5. Falso positivo do harness — **classificado, não é bug**

`P0001 "fact is missing field_key, owner_node_id or source_message_id"` veio de
o meu harness de teste omitir `external_message_id`. Inalcançável pelo WhatsApp
real (o Meta sempre envia `wamid`). Registrada apenas a sugestão preventiva:
validar cedo em `build_context` quando um fato é resolvido sem mensagem de
origem, para não estourar exceção crua de Postgres no meio do commit.

### O que sobrou de literal

`_EXPLICIT_CONFIRMATIONS`, `_EXPLICIT_REJECTIONS` e os markers de serviço
sobrevivem **apenas** como normalizadores auxiliares
(`_is_social_or_non_service_value`) e um campo de proof só-auditoria. Nenhum
controla confirmação, público, serviço ou handoff.

### Diretriz não cumprida por inteiro — dito explicitamente

`_resolve_service_operations` continua sendo o caminho **primário** de seleção
de público, com o semântico como fallback — o inverso da ordem pedida.
Motivo: `branch_selection` carrega **um** anchor por turno; o resolvedor literal
carrega várias operações, tolera erro de digitação por distância de edição e
detecta ambiguidade entre dois anchors. Inverter hoje perderia as três — inclusive
a regressão de transcrição de áudio coberta por
`tests/test_publish_aurora_graph_v21.py`. Fechar exige alargar o contrato para
uma **lista** de seleções antes de inverter. É a próxima tarefa.

---

## B. Sofia / autoria

**A bateria pedida não pôde ser executada.** Motivo concreto e verificado: não
há credencial de LLM em produção. `user_integration_connections` não tem
nenhuma linha habilitada para `openai`/`anthropic`, e as env
`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` chegam vazias no container `api` (existem
no `.env.compose`, mas sem valor). O `start_bootstrap_session` de teste voltou
`"LLM indisponivel: Nenhum provedor de IA disponivel"`.

Isso é, por si só, um achado: **a Sofia não consegue operar hoje para nenhum
operador nesse ambiente** — o chat de autoria inteiro depende dessa credencial.

Nenhum dos itens de auditoria (fidelidade à fonte, estruturação em nodes/edges,
tratamento de lacunas, `appointment_policy.required_fields`/`field_questions`,
separação de campos comuns e específicos, falha antes da publicação, não copiar
de outra persona, não tratar o grafo como fonte factual de si mesmo, entregar só
diff/GraphBundle/PublicationPlan) foi validado empiricamente. Não foram
executados testes mutáveis, então **nenhuma persona foi contaminada e nada foi
publicado** — o critério de parada de emergência não chegou a ser acionado.

O harness de auditoria ficou pronto e é seguro (chama
`kb_intake_service.chat/save` em processo, nunca `approve-publication`, e o
`save()` de persona v3 para em `awaiting_publication_approval` sem publicar).
Basta uma credencial para rodar a bateria.

---

## Verificação executada

| Item | Resultado |
|---|---|
| Suíte completa (`tests/` + `api/tests/`) | **1289 passaram, 2 falharam** |
| As 2 falhas | confirmadas falhando no commit base `29f6ba0`, em worktree limpa |
| Novos testes do validador | 143, todos passando |
| `py_compile` de routes/services/core/workers | OK |
| `git diff --check` | limpo |
| Template n8n | JSON válido; zero literal de persona/produto |
| Teste anti-hardcoded do próprio repo | passa |

### Correções que fiz em afirmações de subagentes (não aceitei de saída)

1. Um subagente marcou 5 falhas como "pré-existentes". Rodei em worktree limpa
   no commit base: **as 5 passam lá** — eram regressões nossas. Migradas.
2. Outro afirmou que `compile_branch_contract` não emite `validation`, o que
   invalidaria a checagem de enum. **Emite** — `_field_specs` faz `spec =
   dict(item)` e preserva a chave do grafo.
3. Um subagente encontrou bug real meu: `decide()` validava a interpretação sem
   o documento do grafo, então **toda** `branch_selection` era descartada como
   anchor desconhecido. Corrigido, com a validação em dois estágios documentada.
4. Uma asserção migrada tinha ficado mais fraca do que a original (`"facts"` é
   substring de `facts_by_key`). Reforçada.

---

## Riscos remanescentes

1. Qualidade da interpretação passa a depender do modelo. O validador impede
   erro para fora do grafo e `needs_clarification` faz perguntar em vez de
   chutar. Medir `semantic_validation.dropped` em produção.
2. Turno sem `interpretation` (workflow no contrato antigo) faz os atalhos
   determinísticos devolverem `None` e cair no caminho do modelo — degrada, não
   quebra. Backend primeiro, template depois; nunca o inverso.
3. `branch_selection` com um anchor por turno (ver acima).
4. Composição da resposta para múltiplas intenções ainda não reescrita (A4).
5. Pré-existente, fora de escopo: `api/services/vault_sync.py` (~131-142,
   ~195-200) ramifica por nome de persona hardcoded — violação real de
   AGENTS.md §26, sem relação com o runtime de conversa.

Roteiro de validação, matriz do WA Validator, comparação antes/depois e plano de
rollback: `docs/handoffs/SEMANTIC_RUNTIME_WA_VALIDATOR_MATRIX.md`.
Arquitetura e contrato: `docs/architecture/SEMANTIC_FIRST_CONVERSATION_RUNTIME.md`.
