# Roadmap de Agentes de IA — Brain AI

> **Este documento é a autoridade máxima do projeto.**
> Quando qualquer outro arquivo contradiz este, este vence. Um agente que
> encontrar contradição deve **reportar o conflito**, nunca escolher em silêncio.
>
> Criado em 2026-08-19. Ordem de precedência declarada em `CLAUDE.md`.

## Ordem de precedência

```
1. docs/roadmaps/AGENT_ROADMAP.md   <- este arquivo (autoridade máxima)
2. AGENTS.md                        <- regras operacionais de produção
3. PROJECT_REQUIREMENTS.md          <- contrato de produto
4. memory.md                        <- estado corrente (não é contrato)
5. docs/**                          <- referência
   docs/archive/**                  <- NUNCA ler; histórico morto
```

---

## Princípio arquitetural

O erro estrutural atual foi deixar conteúdo, compilação, runtime, transporte e
publicação evoluírem como um processo único. A separação obrigatória é:

```
Conteúdo    : Sofia + GraphBundle
Runtime     : backend genérico (graph_agent_runtime_v3)
Transporte  : n8n / WhatsApp
```

**Uma mudança de conteúdo deve tocar somente a primeira camada.**

Três invariantes sustentam tudo:

1. **Card = node do grafo = arquivo Markdown.** O que o operador edita na tela de
   grafos, o que a Sofia escreve e o que o agente lê é o mesmo objeto. Nenhum
   conhecimento existe fora do grafo, e todo node tem parent estrutural
   (`contains`, `primary_tree=true`).
2. **FAQ validada é o embedding.** Cobertura de posicionamento comercial se
   resolve com mais FAQs validadas, nunca com prompt maior.
3. **O checksum aprovado é o checksum ativado.** A normalização acontece antes da
   aprovação; publicar não pode produzir outro checksum.

O que **nunca** é removível, por mais que simplifique: proof e exactly-once;
bloqueio de preço/agenda/promessa sem fonte; teste sintético sem WhatsApp real.

---

## Estratégia de migração — persona por persona

Aurora permanece no processo atual até o fim. O pipeline novo nasce com a
Tock Fatal e só absorve a Aurora quando estiver provado.

```
Aurora     --[ fixture + publish_aurora_graph.py + compile_persona_publication ]--> ATIVA
              congelada: só correção de bug, nenhuma feature nova

Tock Fatal --[ GraphBundle + publisher genérico + PublicationPlan ]--------------> ATIVA
              nasce no pipeline novo, prova o modelo genérico

Aurora migra por último: bundle reconstruído do grafo ativo, compilado em
shadow, comparado por checksum, promovido.
```

Os dois caminhos escrevem em `graph_publications` e ativam por
`activate_graph_publication_v3`. O runtime não distingue — lê a publicação ativa.
**A divergência é só de quem escreve, nunca de quem lê.** É isso que torna o
paralelo seguro.

---

## Estado do roadmap

| # | Item | Estado | Agente |
|---|---|---|---|
| P0 | Destravar a Aurora SDR (ciclo com memória travado) | **em aberto — bloqueia tudo** | `aurora-unblock` |
| 0 | Higiene do repositório e precedência de documentos | **concluído 2026-08-19** | `deprecation-sweeper` |
| 1 | Publisher genérico, PublicationPlan, embeddings incrementais | a fazer | `bundle-migrator`, `graph-publisher`, `release-gate` |
| 2 | Cards editáveis alteram o agente de verdade | a fazer | `card-editor` |
| 3 | Sofia produz dados declarativos, não código | a fazer | `faq-coverage`, `sdr-evaluator` |
| 4 | Tock Fatal nasce no pipeline novo | a fazer | `graph-publisher` |
| 5 | n8n estável e desacoplado do conteúdo | a fazer | — |
| 6 | Aurora migra para o bundle | a fazer | `bundle-migrator` |
| 7 | Orquestradores por estágio e campanha por ciclo | a fazer | `graph-publisher`, `card-editor` |

### Progresso local do pipeline novo — 2026-08-20

O item 1 continua **a fazer** como entrega publicável. Foi concluído apenas o
primeiro slice local e reversível: contrato `GraphBundle` em memória,
`PublicationPlan` puro, CLI dry-run, fixture comercial sintética e skill Sofia
composta. O slice não persiste staging, não gera embeddings, não ativa
publicação e não altera produção.

Em 2026-08-20 foi acrescentado o publisher genérico com duas fases e gates CAS:
materialização/staging e ativação explícita. Embeddings incrementais por chunk e
o publisher completo de edição/remoção continuam pendentes; por isso o item 1
ainda não está concluído como arquitetura final.

Roadmap incremental e gates: `docs/architecture/GRAPH_BUNDLE_PUBLICATION_PLAN.md`.

O P0 permanece aberto até a evidência formal da seção seguinte existir. Commits
de correção e relatos de conversa funcionando não substituem a prova de saída
via WA Validator interno.

### Débito técnico — motor selecionado não significa motor operacional

Confirmado em produção para `tock-fatal` em 2026-08-20: o dashboard mostrava
`deterministic` selecionado embora o binding ainda estivesse em
`conversation_v1`, sem `runtime_version`, sem workflow n8n e sem qualquer
publicação GraphRAG v3. A seleção persistida é somente intenção de routing;
ela não constitui prova de prontidão.

O contrato da UI/API passa a separar `conversation_mode` de `readiness` e deve
exibir estado `blocked` ou `paused` enquanto faltar binding, publicação v3,
credencial/workflow ou executor compatível. Nenhum card pode usar “ativado”
apenas porque está selecionado. Fechar este débito exige a mesma verificação
como gate transacional antes da troca e como diagnóstico no GET de routing.

---

## P0 — Destravar a Aurora SDR

Sintoma: os ciclos de SDR agora têm memória (migrations 129/130, commits
`3153c8c`, `fd9e20b`) **mas o fluxo está travado**.

Os relatórios de 2026-08-10 (`AURORA_INVESTIGATION_REPORT.md`,
`investigation_aurora_allan.md`, `AURORA_HANDOFF_FIX.md`) descrevem uma trava de
HANDOFF **anterior e já resolvida**. Foram arquivados em
`docs/archive/DEPRECATED_2026-08-19/` justamente porque agentes os liam como
diagnóstico corrente. Não usar.

**Nenhuma etapa da refatoração começa antes deste item fechar.**

### Evidência obrigatória (read-only, produção)

Destino: `docs/evidence/AURORA_STUCK_2026-08-19/`

| Arquivo | Conteúdo |
|---|---|
| `conversation_turn_proofs.json` | últimos 30 turnos do lead — `proof.valid`, `reply_text`, `journey_id`, `publication_version` |
| `journeys.json` | `conversation_journeys` — `sequence`, `state`, `metadata.source`, `outcome` |
| `carry_over.json` | retorno de `conversation_carry_over_facts_by_lead_v1` (migration 129) |
| `ledger.json` | `facts_by_key`, `asked_question_node_ids`, `revision` |
| `publication.json` | `graph_publications` ativa — `version`, `checksum`, `status`, `compiler_version` |
| `migrations.txt` | prova de que 129 **e** 130 estão aplicadas em produção |
| `n8n.json` | workflow `k5JWkvpQyb8EB3Vw` — checksum vs `persona-conversation-template.json` |
| `logs.txt` | `system_events` + `/logs` da persona Aurora, janela de 24h |

### Hipóteses ordenadas

1. **Migration 130 não aplicada.** `shared_lead_memory.py` foi commitado em
   `3153c8c`; sem a migration, o runtime chama função inexistente e a decisão
   falha em silêncio. *Teste:* `migrations.txt`.
2. **`reply_text` vazio não coberto pelo n8n.** Pendência registrada
   explicitamente em `memory.md`: a rede de segurança
   `conversation_runtime._ensure_reply_text_or_log` cobre só o lado Python; o node
   `Align reply with qualification state` do n8n continua sem checar `reply_text`
   vazio. *Teste:* proofs com `proof.valid=true`, `reply_text` nulo e zero outbound.
3. **Orçamento de prompt estourado.** `fba579a` e `f983988` atacam duplicação de
   camadas do prompt; o Validator já foi bloqueado por um componente de 4.882
   tokens. *Teste:* logs do n8n com truncamento.
4. **`publication_changed` invalidando fatos a cada turno.** Se a v62 não bate com
   o checksum guardado no ledger, `invalidated_fact_keys` limpa a memória todo
   turno e o ciclo nunca fecha. *Teste:* `trace.publication_changed`.
5. **`unknown` absorvendo campo obrigatório.** `e6fc4e3` ("treat pending-field
   deferral as unknown"). Se `vehicle_color` (único campo com
   `accepted_statuses: ["known","unknown"]`) virar `unknown` cedo demais, a
   qualificação não completa e o campo não pode ser reperguntado.
   *Teste:* `facts_by_key`.

### Prova de saída

Validação **somente** pelo WA Validator interno (`POST /wa-validator/run-direct`),
nunca WhatsApp real — regra rígida de `AGENTS.md`.

- 1 inbound → 1 decisão → 1 proof válido → 1 commit → 1 outbound inerte
- `qualification_complete=true`
- memória sobrevive a **dois** fechamentos de jornada seguidos (modelo, cor e ano
  do veículo preservados; só o serviço reconfirmado)
- zero turnos com `reply_text` vazio

---

## 7 — Orquestradores por estágio e campanha por ciclo

Estrutura alvo do atendimento, registrada aqui porque **nada dela entra no P0**.
Hoje a Aurora tem um binding só, e esse binding acumula SDR e CS.

### Um dono por estágio

```
SDR     -> até `qualificado`
Closer  -> `convertido` e `agendado`
CS      -> `concluído`
```

Os galhos `service` do grafo (`atendimento-humano`, `reclamacao`) já são
roteiros de atendimento distintos da qualificação comercial: são os primeiros
candidatos a ganhar dono próprio. Enquanto isso, o SDR responde por eles.

O histórico atravessa todos os estágios sem cópia: `conversation_journeys`
guarda sequência e desfecho, `carry_over` guarda o que o cliente **é**, e
`conversation_carry_over_facts_by_lead_v1` (migration 129) busca em qualquer
jornada do lead. Um orquestrador novo lê a mesma memória — nenhum deles ganha
armazenamento próprio.

### Campanha muda com o ciclo

Concluir a primeira qualificação move a lead de campanha. Cada campanha tem seu
público exato ligado à audiência, e pode declarar outros serviços e outros
appointments:

```
ativação  ->  CS  ->  reativação  ->  remarketing
```

O que falta existir: vínculo lead→campanha escrito pelo próprio ciclo (hoje
`campaign_recipients` só serve a disparo de saída), e o contrato que diz qual
audiência/serviço/appointment cada campanha publica. Enquanto isso não existe,
a diferença de comportamento entre o primeiro ciclo e os seguintes é apenas de
prompt, lendo `journey.sequence` e `shared_memory.journey_outcomes` — que é o
que o P0 entregou.

### O que o P0 deliberadamente não fez

- Não criou tabela, migration nem vínculo lead→campanha.
- Não separou bindings por estágio.
- Não moveu os galhos `service` para outro dono.

---

## Arquitetura alvo — GraphBundle

Uma única fonte autoral declarativa por persona. Todo o resto é derivado.

```
GraphBundle (banco, versionado)
├── identidade + versão de contrato
├── nodes e edges
├── prompt do modelo          <- hoje SYSTEM_PROMPT hardcoded em Python
├── políticas de conversa     <- hoje conversation_policy no publisher da Aurora
├── fields, confirmação, carry_over, scope
├── aliases
├── claims e evidências (claim_type por FAQ)
├── políticas de memória
└── proveniência

  -> normalização determinística    graph_markdown.canonicalize_graph
  -> validação estrutural/comercial graph_json_v2_validator + regras do bundle
  -> compilação PURA                graph_compiler_v3.compile_graph      [JÁ EXISTE]
  -> PublicationPlan (diff + custo)                                      [NOVO]
  -> chunks e embeddings incrementais por chunk_checksum                 [NOVO]
  -> staging + ativação atômica     activate_graph_publication_v3
  -> export de cards Markdown para a tela de grafos                      [NOVO]
```

O operador enxerga três passos, não quinze:

```
Alterar (card)  ->  Aprovar (plano)  ->  Publicar
```

```json
{
  "draft_checksum": "...",
  "runtime_checksum": "...",
  "next_version": 65,
  "nodes_added": 1,
  "nodes_changed": 2,
  "branches_affected": ["polimento-tecnico"],
  "chunks_reused": 143,
  "chunks_to_embed": 3,
  "estimated_embedding_cost": "...",
  "breaking_contract_changes": [],
  "validation_errors": []
}
```

Adicionar o alias "polimento" deve virar: 1 node alterado, 0 embeddings novos,
1 teste de resolução, publicação em segundos. Hoje atravessa fixture, código
Python, publicação fonte, projeção, recompilação GraphRAG, embeddings, n8n e
Validator.

### O que se perde (e está tudo bem)

- Não é mais possível colocar exceção arbitrária em Python para uma persona.
- Não existem múltiplos caminhos independentes de publicação.
- Hotfix direto no banco é bloqueado ou detectado como drift.

---

## Catálogo de agentes

Cada agente vive em `.claude/agents/<nome>.md`, declara seu próprio modelo e
ferramentas no frontmatter, lê o contexto de que precisa e executa a tarefa sob
demanda. Nenhum deles re-deriva o projeto do zero.

| Agente | Modelo | Responsabilidade | Item |
|---|---|---|---|
| `aurora-unblock` | opus | Coleta evidência read-only, testa as 5 hipóteses do P0 em ordem, salva em `docs/evidence/` | P0 |
| `graph-publisher` | opus | Gera `PublicationPlan`, compara checksums, publica e ativa; recusa se `validation_errors` não vazio | 1, 4 |
| `bundle-migrator` | opus | Move regra de negócio de Python para o bundle, um bloco por vez, com teste de equivalência de checksum | 1, 6 |
| `card-editor` | sonnet | Aplica operações declarativas em cards e devolve o diff semântico | 2 |
| `faq-coverage` | opus | Audita cobertura de FAQ por branch; aponta `claim_type` faltante e posicionamento descoberto | 3 |
| `sdr-evaluator` | opus | Avalia transcript contra critérios de qualidade (reusa a skill `aurora-conversation-evaluator`) | 3 |
| `deprecation-sweeper` | sonnet | Detecta arquivo que contradiz este roadmap e propõe arquivamento | 0 |
| `release-gate` | opus | Roda só os testes que o `PublicationPlan` exige; suíte completa apenas em breaking change | 1 |

### Regras de governança (valem para todo agente)

1. Nunca publicar sem plano aprovado por humano.
2. Nunca ler `docs/archive/**`.
3. Conflito entre documentos resolve pela ordem de precedência, e o agente
   **reporta** o conflito — não escolhe em silêncio.
4. Nunca rodar Docker local (`AGENTS.md`).
5. Nunca testar conversa por WhatsApp real; só WA Validator interno.
6. Reusar as skills existentes em vez de duplicar:
   - `.claude/skills/aurora-premium-sdr/`
   - `.claude/skills/aurora-conversation-evaluator/`
   - `.agents/skills/brain-agent-e2e/`
   - `.agents/skills/validate-production-release/`
7. Nunca criar tabela nova sem perguntar (`AGENTS.md` §2).
8. Nunca ramificar código de produção por cliente, persona, produto ou serviço
   (`AGENTS.md` §26).
