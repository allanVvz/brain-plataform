# Handoff — runtime semantic-first, escopo por ramo e por agente

Sessão de 2026-08-21/22. Branch **`agent/sofia-vitoria-audit`**, worktree
`C:\Repositores\brain-plataform-sofia-vitoria-audit`, base `29f6ba0`.

**Nada foi deployado, publicado, ativado, migrado ou enviado.** O workflow n8n de
produção não foi tocado — só o template versionado em disco. Transporte e IA
seguem como estavam. A publicação **v8** continua ativa e intacta.

---

## 1. O que originou tudo

Teste ao vivo da Vitória contra o pipeline real de produção (n8n real → DeepSeek
real → proof-checker real → commit real), com dois leads sintéticos de telefone
falso (`leads.id` 69 e 70, `TESTE_BURRICE_QA*`). Nenhum contato real recebeu
nada. Detalhe em `VITORIA_V8_LIVE_TESTING_FINDINGS_2026-08-21.md`.

Três defeitos reais, todos reproduzidos:

1. **Reconciliação semântica rejeitada por matcher literal.** O DeepSeek propôs
   corretamente `select` do anchor de varejo para `"uso próprio mesmo"`; o
   resolvedor literal não achou alias, o backend descartou a proposta certa e
   repetiu a mesma pergunta. Loop infinito para qualquer fraseado natural.
2. **Confirmação final bloqueada.** `"sim, tá correto"` não pertencia ao conjunto
   fixo `_EXPLICIT_CONFIRMATIONS` (~11 frases, comparação exata). O modelo já
   tinha proposto `qualification_complete` + `handoff_requested`; o lead nunca
   chegava à equipe. Provado enviando o literal `"sim"` no mesmo lead: funcionou
   na hora.
3. **Pergunta comercial absorvida como campo.** `"quero uns 50 vestidos em
   mousse pra começar, vocês tem?"` virou o valor bruto de `volume_interest` e a
   pergunta nunca foi respondida.

O `P0001` que apareceu no meio é **falso positivo do harness** (omiti
`external_message_id`), inalcançável pelo WhatsApp real — o Meta sempre manda
`wamid`. Fica só a sugestão preventiva de validar cedo em `build_context`.

---

## 2. Arquitetura decidida

### Interpretar é do modelo; provar é do backend

```
inbound
→ interpretação estruturada pelo modelo   (SemanticInterpretation)
→ validação determinística de segurança   (semantic_interpretation_validator)
→ reconciliação com estado e grafo
→ recuperação de conhecimento/FAQ
→ seleção da próxima ação
→ composição natural
→ proof
→ commit idempotente
→ no máximo um outbound
```

O backend **não volta a interpretar linguagem com listas de frases**. Só verifica
se o que o modelo afirmou está sustentado pela mensagem literal e permitido pelo
grafo publicado. Não há confiança numérica em lugar nenhum do contrato novo:
todo elemento carrega o trecho literal da mensagem do cliente, porque um score
não é explicação.

Isso não contradiz `.agents/skills/brain-agent-e2e/SKILL.md` ("model output never
owns routing, required fields, the next question, handoff or confirmation
policy"): mudou a **fonte da interpretação**, não a fonte da política. Rota,
campos obrigatórios, próxima pergunta (`field_questions[missing_fields[0]]`),
handoff e confirmação continuam determinísticos.

### Escopo bidimensional: ramos ativos × agente que responde

- **Ramo** decide *de quem é o conhecimento* — varejo vs. atacado.
- **Agente** decide *o que pode ser afirmado* — o SDR qualifica; um Closer
  futuro fecha preço.

Preço não é regra global da persona. Quem fala preço é o agente que responde.
Isso se declara em **vários cards `Embedded`, um por agente**
(`data.agent_slug`); um card sem `agent_slug` continua significando "todos os
agentes", então Aurora, Baita e a Tock atual seguem funcionando sem migração.

O Embedded já é o ponto certo: a aresta `faq → embedded` é hoje o que decide
quais FAQs viram **claim autorizada** (`graph_compiler_v3.py:746-752` monta
`embedded_faq_ids`; `:955-972` só autoriza claim de FAQ desse conjunto). Ele já
governa "o que pode ser afirmado" — falta governar "por quem".

---

## 3. Fatos de arquitetura levantados (não repetir a investigação)

**O fechamento de ramo é de passo único e não transitivo.**
`graph_compiler_v3.py:788-799`: `frontier` é fixado **antes** do loop; a aresta
semântica adiciona só o nó-alvo, nunca a subárvore `contains`. Foi por isso que
a v8 precisou de 165 arestas individuais.

**A diferenciação de ramo não existe hoje.** Consulta ao grafo publicado v8: os
dois ramos enxergam **176 dos 182 nós cada um**; só o nó de audiência e suas 3
FAQs de qualificação são exclusivos. Consequência direta das 165 arestas
`persona → nó` — como `persona` é ancestral de todo ramo, tudo entra em todo
ramo. O catálogo ficou visível ao custo da diferenciação.

**Multi-ramo já é real no runtime, menos na recuperação.**
`active_branch_node_ids`, `check_service_operations` (`graph_proof_checker_v3.py:392`)
e os `aggregate_missing_fields/askable/required_field_count` (`:213-300`) já
trabalham com lista, com testes provando 2–3 ramos ativos. Mas
`_retrieval_branch_for_turn` (`graph_agent_runtime_v3.py:2967-2990`) resolve
**um** ramo e só os chunks dele viram `context_cards`.

**A trava de preço em texto livre já existe — no pipeline errado.**
`graph_conversation_contract.py:587-606` (`_MONETARY_FIGURE`) e `:746-763`
(`check_proposal`) varrem a prosa da resposta atrás de valor monetário e
rejeitam se nenhum nó citado sustenta o número, com testes em
`tests/test_graph_conversation_contract.py:404-457`. O v3 **não chama nada
disso**. É código para portar, não inventar.

**Flags inertes, confirmado por grep exaustivo.** `commercial_claims_allowed`,
`forbid_unpublished_price_stock_deadline_policy` e
`unsupported_commercial_claim` não são lidos por nenhum caminho de execução. Só
`doubt_handling.deferred_response` é realmente usado
(`graph_agent_runtime_v3.py:2178,2207`).

**Estrutura real do catálogo da Tock Fatal** (rascunho de 402 nós vs. v8 de 182):
```
persona:tock-fatal
├── campaign:tock-whatsapp-qualification
│   ├── audience:tock-retail      (branch_anchor)
│   └── audience:tock-reseller    (branch_anchor)
└── campaign:tock-catalogo-produtos
    ├── product_group × 7 → product × 73 → offer × 146 + copy × 146
    └── audience:tock-ctx-* × 4   (contexto, não são anchors)
```
Cada produto tem **duas** ofertas (`-varejo` preço cheio mín. 1; `-atacado` 30%
off mín. 3) e duas copies. As marcas estão **vazias**
(`brand:tock-fatal-varejo` 0 filhos; `brand:tock-fatal-atacado` só a regra de
desconto). As 5 arestas `visible_to_agent` do rascunho estão com
`metadata: null` — hoje não fazem nada.

**Armadilha de arquivo.** Os bundles da Tock Fatal são **untracked** e existem só
em `C:\Repositores\brain-plataform\data\graph_bundles\tock-fatal\` (diretório
compartilhado com outra sessão). **Não vieram para esta worktree**, que só tem
`sdr-qualification-v1.json`. Primeiro passo de quem continuar: copiar para a
worktree e commitar. Nada é escrito no diretório compartilhado.

---

## 4. Arquivos alterados nesta branch

Commits: `24c73f4`, `47f8afb`, `6f9ffc4`, `d0200c7`, `a1bcd52`, `f48110b`, mais
o trabalho em curso descrito abaixo.

**Produção — novos**
| Arquivo | Papel |
|---|---|
| `api/services/semantic_interpretation_validator.py` | Validação determinística: evidência na mensagem, pertencimento ao grafo, enum declarado pelo grafo, coerência com o pendente, contradição, claim sem nó, handoff permitido, isolamento de persona. Sem lista de frases, sem alias, sem regex sobre texto do cliente. |
| `api/services/semantic_conversation_policy.py` | Ponte da interpretação para as decisões: `confirms_pending`/`rejects_pending`, `semantic_service_resolution`, `unanswerable_commercial_questions` e `interpretation_to_proposal`. |

**Produção — modificados**
| Arquivo | Mudança |
|---|---|
| `api/schemas/conversation.py` | `SemanticInterpretation` e modelos de apoio; `ConversationContext.pending_confirmation_ref`. |
| `api/services/graph_agent_runtime_v3.py` | `_validated_interpretation`, `_pending_confirmation_ref`, `_with_semantic_branch_fallback`; confirmação, confirmação de fato pendente e escada de desambiguação passam a ler a interpretação; `available_services` publica os aliases do grafo. |
| `api/n8n-workflows/persona-conversation-template.json` | Pede e parseia `SemanticInterpretation` nos 4 nós (request/validate, e os dois de repair). Persona-neutro, JSON válido. |

**Testes**
| Arquivo | Mudança |
|---|---|
| `api/tests/test_semantic_interpretation_validator.py` | **novo**, 143 testes parametrizados. |
| `tests/test_graph_agent_runtime_v3.py` | 9 testes migrados para o contrato novo + `test_semantic_interpretation_payload_reaches_a_real_decision`. |
| `tests/test_conversation_architecture_contract.py`, `tests/test_conversation_modes.py`, `tests/test_sdr_name_unblock.py`, `tests/test_shared_lead_memory_v4.py`, `api/tests/test_deepseek_n8n_service.py` | Migrados do contrato antigo para o novo. |

**Documentação**
`docs/architecture/SEMANTIC_FIRST_CONVERSATION_RUNTIME.md`,
`docs/handoffs/SEMANTIC_RUNTIME_WA_VALIDATOR_MATRIX.md` (matriz de 19 casos,
antes/depois, riscos, rollback),
`docs/handoffs/RELATORIO_CONSOLIDADO_VITORIA_SOFIA_2026-08-21.md`,
`docs/handoffs/VITORIA_V8_LIVE_TESTING_FINDINGS_2026-08-21.md`,
`docs/roadmaps/AGENT_ROADMAP.md` (item 8 novo + seção "Runtime semantic-first").

---

## 5. Estado do trabalho em curso (seção A do plano)

**Bug bloqueante encontrado e corrigido nesta sessão.** O template novo passou a
enviar `model_observation = {interpretation, repair_attempt, ...}` sem a chave
`proposal`. `_decide()` validava o dict inteiro como `ConversationProposal`
(`StrictModel`, `extra="forbid"`) → `extra_forbidden` nas quatro chaves → **todo
turno sem atalho determinístico caía em `_invalid_proposal_fallback`**. O caminho
principal de decisão estava morto para a forma que a produção envia. Nada
deployado, então sem dano em produção.

Correção aplicada (não commitada ainda):
- `semantic_conversation_policy.interpretation_to_proposal` traduz a
  interpretação para a forma que `_decide` fala, mantendo **um** caminho de
  decisão em vez de dois.
- `_decide` carrega a publicação **antes** de validar, senão fato e âncora são
  descartados por falta de documento e contrato (a validação é genuinamente de
  dois estágios: o que depende só da mensagem roda cedo e barato; o que depende
  do grafo roda onde há grafo).
- `tests/test_graph_agent_runtime_v3.py::test_semantic_interpretation_payload_reaches_a_real_decision`
  — **verifiquei que o teste pega o bug**: falha com `proposal_schema_invalid`
  sem a correção, passa com ela.

**Pendente de verificação:** a suíte completa não rodou depois desta última
correção. Rodar `python -m pytest tests/ api/tests/ -q --ignore=api/tests/test_auth.py`
e comparar com a linha de base **1289 passando / 2 falhando** — as duas falhas
(`test_client_portal`, `test_graph_markdown_catalog`) foram confirmadas falhando
no commit base `29f6ba0` em worktree limpa, então são pré-existentes.

---

## 6. O que ainda precisa ser feito

Ordem importa; o plano aprovado está em
`C:\Users\allan\.claude\plans\ent-o-adapte-toda-a-foamy-magpie.md`.

| # | Item | Estado |
|---|---|---|
| A | Ponte interpretação→proposal | **concluída** (`65a3bc6`) — com teste de regressão verificado (falha sem a correção) |
| B | `branch_selections` como **lista** (um, dois ou ambos os ramos por turno) | **concluída** (`83a47ec`) — validação item a item, contradição `add`+`drop` é erro do turno, N operações no mesmo formato do resolvedor literal, template n8n como array |
| C | Recuperação **unida** entre ramos ativos | a fazer — é o que falta para "receber mais de uma branch" de verdade; respeitar o orçamento de 24000 tokens com poda por ramo |
| D | `include_subtree_in_branch` no compilador | **concluída** (`fa43939`) — 3 testes fixam subárvore / nó único / aresta sem escopo |
| E | Bundle: `offer`/`copy` de canal penduradas na **marca** certa, 4 arestas de escopo, remover as 165 arestas `persona → nó` | **próximo** — decisão do usuário confirmada; depende de copiar os bundles untracked para a worktree |
| F | **v9** — estrutura e escopo, **sem preço** | a fazer, depois de E |
| G | Cards `Embedded` por agente + portar a trava de preço para rodar contra a política do agente | a fazer |
| H | **v10** — catálogo comercial completo (146 `offer`, 146 `copy`, regra de desconto) | a fazer, só depois de F e G |

**Suíte na última verificação: 1298 passando / 2 falhando** — as duas
pré-existentes já confirmadas no commit base.

**Decisões do usuário já tomadas, não reabrir:**
- v9 (escopo) e v10 (preço) são publicações **separadas**, nessa ordem; v10 só
  com a trava no lugar.
- `offer`/`copy` de canal vão para baixo da marca do seu canal, cada oferta
  mantendo `about_product → product`.
- Quem pode falar preço é o **agente**, via cards Embedded — não uma regra
  global.

**Riscos remanescentes:** dependência da qualidade do modelo (mitigar medindo
`semantic_validation.dropped` em produção); turno sem `interpretation` degrada
para o caminho do modelo mas não quebra; ordem segura de deploy quando
autorizado é **backend primeiro, template depois**.

---

## 7. Fora de escopo, registrado

- **Sofia**: a bateria de auditoria de autoria **não pôde rodar** — não há
  credencial de LLM no ambiente (zero linhas habilitadas para
  `openai`/`anthropic` em `user_integration_connections`, envs vazias no
  container `api`). Isso significa que a Sofia não opera hoje para nenhum
  operador nesse ambiente. O harness de auditoria está pronto e é seguro (chama
  `kb_intake_service.chat/save` em processo, nunca `approve-publication`).
- `api/services/vault_sync.py` (~131-142, ~195-200) ramifica por nome de persona
  hardcoded (`_FOLDER_TO_SLUG`, `_detect_persona`) — violação real de
  AGENTS.md §26, sem relação com este trabalho.
- Leads sintéticos `69` e `70` seguem em produção para inspeção; removíveis com
  `delete from leads where id in (69,70);`.
