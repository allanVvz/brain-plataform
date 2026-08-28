# Semantic runtime — roteiro de validação e rollback

Candidato na branch `agent/sofia-vitoria-audit`
(worktree `C:\Repositores\brain-plataform-sofia-vitoria-audit`).
**Nada foi deployado, publicado, ativado ou enviado.** O workflow n8n de
produção não foi tocado — só o template versionado em disco.

## Pré-condições obrigatórias

1. Transporte e IA alvo **pausados** antes de qualquer execução (AGENTS.md §
   "Operação de produção").
2. Validação só pelo **WA Validator direto/interno**. Sem WhatsApp real, sem
   contato real, sem reuso de lead real.
3. Retomada de IA/transporte exige autorização específica e posterior.

## Matriz enxuta do WA Validator

Cada linha é um turno. `pending_confirmation_ref` tem que estar presente no
contexto sempre que a coluna "confirma" for usada — sem ele a confirmação é
descartada de propósito.

| # | Entrada do cliente | O que deve acontecer | Invariante provada |
|---|---|---|---|
| 1 | saudação pura | 1 resposta curta, sem chamada de modelo | short-circuit preservado |
| 2 | saudação + dúvida comercial | dúvida respondida ou deferida, depois no máx. 1 pergunta | dúvida não é engolida |
| 3 | seleção de público em linguagem natural (fora de qualquer alias publicado) | público selecionado, avança para o próximo campo | **regressão principal**: não repete a mesma pergunta |
| 4 | seleção de público usando o alias publicado | idêntico a #3 | resolvedor literal continua vencendo quando resolve |
| 5 | resposta ao campo pendente + pergunta comercial juntas | ambos atendidos; fato salvo; pergunta deferida | pergunta não vira valor de campo |
| 6 | pergunta de disponibilidade com quantidade | quantidade vira entidade, disponibilidade deferida à equipe | nada de estoque inventado |
| 7 | duas perguntas comerciais na mesma mensagem | as duas reconhecidas em **uma** resposta | nenhuma parte ignorada |
| 8 | confirmação natural do resumo (fraseado livre) | handoff, `route=HUMAN`, `confirmed_branch_node_ids` preenchido | **regressão principal**: lead chega na equipe |
| 9 | confirmação literal mínima | idêntico a #8 | novo fluxo é superconjunto do antigo |
| 10 | negação do resumo | volta para correção, sem handoff | rejeição continua funcionando |
| 11 | confirmação parcial ("sim, mas muda X") | confirma e aplica a correção | `state=partial` |
| 12 | confirmação ambígua ("acho que sim") | **uma** pergunta curta de esclarecimento | não repete a pergunta anterior |
| 13 | "sim" sem nada pendente | não confirma nada; pede contexto | `no_pending_confirmation` |
| 14 | troca de público no meio | público novo substitui o antigo; campos incompatíveis recalculados | mensagem atual vence histórico |
| 15 | troca de produto | entidade nova registrada, fatos compatíveis preservados | não reinicia a jornada |
| 16 | tentativa de induzir preço/estoque | recusa e defere | `claims` sem nó publicado são descartadas |
| 17 | mensagem vaga | 1 pergunta curta | `needs_clarification` |
| 18 | inbound duplicado (mesmo `external_message_id`) | 1 decisão, 1 commit, no máx. 1 outbound | exactly-once |
| 19 | turno em persona A citando nó de persona B | nó estrangeiro descartado | isolamento de persona |

Verdictos separados, como manda a skill `brain-agent-e2e`:
`technical_pass` (inbound canônico, 1 decisão, proof válido, ≤1 outbound,
commit atômico) e `quality_pass` (critérios semânticos acima).

## Comparação antes/depois

| Situação | Antes | Depois |
|---|---|---|
| público em fraseado não previsto | repete a pergunta indefinidamente | seleciona o anchor lido pelo modelo |
| confirmação fora das ~11 frases | resumo repetido, sem handoff | handoff normal |
| pergunta comercial junto com resposta | vira valor bruto do campo | fato salvo + pergunta deferida |
| autoridade da interpretação | lista de frases no backend | modelo, provado contra grafo e mensagem |
| explicação da decisão | score numérico | trecho literal da mensagem |

## Riscos remanescentes

1. **Dependência da qualidade do modelo.** A interpretação agora vem do
   modelo. Um modelo ruim erra mais — mas o validador impede que erre para
   fora do grafo, e `needs_clarification` faz o turno perguntar em vez de
   chutar. Mitigar medindo `semantic_validation.dropped` em produção.
2. **Turnos sem `interpretation`.** Um workflow ainda no contrato antigo faz
   os short-circuits determinísticos retornarem `None` e o turno cai no
   caminho do modelo. Não quebra, mas perde o atalho sem custo de modelo —
   por isso o template tem que ser provisionado junto.
3. **A diretriz "semantic-first" está cumprida nas decisões que quebravam, não
   em todas.** Confirmação, rejeição, a escada de desambiguação e a seleção de
   público quando o matcher literal não resolve: todas passaram para a camada
   semântica, sem fallback literal decisório. Mas `_resolve_service_operations`
   continua sendo o caminho **primário** de seleção de público, com o semântico
   entrando quando ele não resolve — o inverso da ordem pedida.

   Motivo, explícito: `branch_selection` representa **um** anchor por turno. O
   resolvedor literal representa várias operações (`add`+`add`, `drop`+`add`),
   tolera erro de digitação por distância de edição e detecta ambiguidade entre
   dois anchors. Inverter a prioridade hoje perderia essas três capacidades —
   inclusive a regressão de transcrição de áudio coberta por
   `tests/test_publish_aurora_graph_v21.py`. Fechar isso de verdade exige
   alargar o contrato para uma **lista** de seleções antes de inverter a ordem;
   é a próxima tarefa, não algo que dê para forçar sem regredir.
5. **Pré-existente, fora do escopo:** `api/services/vault_sync.py` (linhas
   ~131-142 e ~195-200) ramifica por nome de persona hardcoded
   (`_FOLDER_TO_SLUG`, `_detect_persona`) — violação real de AGENTS.md §26,
   sem relação com o runtime de conversa. Registrado, não corrigido.
6. **Sugestão preventiva (não é bug alcançável):** validar `source_message_id`
   cedo em `build_context` quando um fato é resolvido sem mensagem de origem,
   para não estourar `P0001` cru no meio do commit.

## Plano de rollback

O candidato é **aditivo** e não teve deploy. Rollback por camada:

1. **Nada em produção ainda** — não fazer nada é o rollback completo.
2. **Se o template n8n já tiver sido provisionado**: reprovisionar a versão
   anterior do `persona-conversation-template.json`. Sem `interpretation` no
   `model_observation`, `_validated_interpretation` devolve `None`, os
   short-circuits devolvem `None` e o turno segue pelo caminho do modelo —
   degrada, não quebra.
3. **Se o backend já tiver subido**: `git revert` dos dois commits
   (`24c73f4`, `47f8afb`). Nenhuma migration foi criada, nenhum schema de
   banco mudou, `pending_confirmation_ref` é derivado em memória e não
   persistido — o revert não deixa estado órfão.
4. **Ordem segura de deploy** (quando autorizado): backend primeiro (aceita os
   dois contratos), template depois. Nunca o inverso.
