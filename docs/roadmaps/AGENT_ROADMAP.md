# Roadmap de Agentes de IA — Brain AI

Publicações de conteúdo isoladas pausam somente a persona alvo. Personas não
envolvidas continuam operando.

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

### Checkpoint Aurora — 2026-08-31 (auditoria somente-leitura)

Concluído: a baseline produtiva foi identificada e permanece isolada. A Aurora
está na `graph_publications` **v75 ativa** (`d5c7afd7-24ea-44d6-90e9-8532fd3fc303`),
checksum `sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec`,
compilador `graph-compiler-v3.6.3`, com 140 nodes, 274 edges, 14 contratos de
branch e 551 chunks publicados. O binding Meta Cloud está ativo e conectado.

Concluído: foi verificada a origem da publicação. Ela não possui
`source_table` nem `graph_bundle_draft_checksum`, e `origin/main` não contém
`data/graph_bundles/aurora/`. Portanto, a v75 é uma publicação v3 imutável
produzida pelo caminho autoral legado, não um GraphBundle declarativo. Nenhum
staging, ativação, pausa ou envio foi executado nesta auditoria.

O importador shadow-only foi preparado para aceitar exclusivamente um export
cujo checksum e contagens reproduzam a v75 ativa; ele rejeita v66, fixtures e
documentos incompletos. O próximo gate do item 6 é obter esse export
autenticado, gerar o bundle declarativo, compilar em dry-run/shadow, revisar o
diff e os dois checksums e só então solicitar autorização específica para
staging, WA Validator interno e ativação isolada da persona.

### Checkpoint mídia no SDR — 2026-08-31 (auditoria somente-leitura)

Conflito de documento resolvido (governança regra 3): o item 4 dizia "baseline
produtiva v11 … com mídia"; o item 8a dizia "falta assets/fotos/vídeos/links".
O item 8a está correto. **Nenhuma execução de mídia está em produção nem em
`main`.**

O que existe de mídia:

- **Conteúdo autorado** — os bundles `sdr-qualification-v11-product-media.json`
  (só na worktree `recovery-question-hotfix`) e `-v12-model-owned.json`
  (untracked) declaram 4 `asset` nodes, `gallery:tock-default`, a política
  `content_delivery` e `rule/copy/faq:tock-product-media-delivery`. Os 4 jpeg +
  `manifest.json` (sha256 por produto) estão em `docs/sdr/tock-fatal/product-media/`
  da worktree; não confirmado que subiram para o bucket `assets-raw`.
- **Rascunho de execução, nunca commitado** — a worktree `recovery-question-hotfix`
  (HEAD `f2a896a`, base anterior a 131/132) tem `_media_delivery_request()` no
  runtime, `131_graph_media_batch_outbox.sql` (colide com o 131 de `main` —
  renumerar para 134+), mudanças em compiler/proof/`conversation_runtime`/
  `whatsapp_dispatch_worker`/n8n template, e uma trava `raise RuntimeError("graph
  media batch requires an Evolution binding")` — o rascunho só funcionava em
  Evolution.
- **Feito 2026-08-31 em `main`** — `MetaWhatsAppProvider.send_media()` (Graph API
  upload-by-id, `api/services/whatsapp_providers/meta.py`) + `MEDIA` question
  kind e `MediaItem`/`media_batch` em `api/schemas/conversation.py`.

Decisões: Tock permanece no binding **Meta Cloud** (não reativar Evolution);
reimplementar a execução limpa a partir do main atual, usando a worktree só como
referência de leitura. Plano completo:
`~/.claude/plans/lea-os-logs-de-atomic-candle.md`.

---

## Estado do roadmap

| # | Item | Estado | Agente |
|---|---|---|---|
| P0 | Reduzir memoria e complexidade da recuperacao conversacional | **em aberto - incidente produtivo confirmado em 2026-08-24: `/internal/conversations/context` e `/internal/conversations/decide` carregam nodes, edges e projecoes legacy em volume excessivo por turno; a API atingiu o limite de 1,5 GiB e workers Gunicorn foram encerrados por OOM, deixando inbounds em `dead_letter` sem resposta. O hotfix tornou o coercion compativel com `semantic_type`/JSON Schema nullable em lista; ainda falta limitar a recuperacao a publicacao ativa, top-k RAG e consultas em lotes/server-side, sem reconstruir o grafo completo no runtime. Preservar proof sem reescrita e exactly-once.** | `runtime-rag` |
| P0 | Destravar a Aurora SDR (ciclo com memória travado) | **em aberto — evidência coletada 2026-08-19 (branch `chore/aurora-unblock-p0-evidence-2026-08-19`, commit `62d8c62`, não mesclada): nenhuma das 5 hipóteses reproduziu contra tráfego real; falta sessão de prova formal via WA Validator e teste da hipótese 3 (orçamento de prompt) antes de marcar concluído** | `aurora-unblock` |
| 0 | Higiene do repositório e precedência de documentos | **concluído 2026-08-19** | `deprecation-sweeper` |
| 1 | Publisher genérico, PublicationPlan, embeddings incrementais | **em progresso — GraphBundle + PublicationPlan + staging/ativação em duas fases já existem e publicaram a Tock Fatal real; falta embeddings incrementais por chunk e o publisher completo de edição/remoção** | `bundle-migrator`, `graph-publisher`, `release-gate` |
| 2 | Cards editáveis alteram o agente de verdade | **em progresso — 2a e 2b entregues no editor GraphBundle v3; 2c–2e permanecem bloqueadas pelos gates de revisão/publicação; 2f tem catálogo local recuperável, mas UI e projeções ainda estão pendentes** | `card-editor` |
| 2c.1 | Ordem visual e editável das perguntas de qualificação, integrada à Sofia | **a fazer — prioridade de autoria; sem tornar a conversa um roteiro rígido** | `card-editor`, `graph-publisher` |
| 2f | Skills como blocos renderizáveis | **fase 1 entregue localmente — Humanizer instalada e manifestada; catálogo/projeções/UI permanecem a fazer, sem publicação produtiva** | `card-editor`, `graph-publisher` |
| 3 | Sofia produz dados declarativos, não código | **a fazer — inclui: Sofia lê o grafo, atualiza FAQ e cria os blocos dos sites. Os `requires` do template ativo viram a checklist concreta que hoje é a instrução vaga "SAIDA PUBLICA DE SITE" em `agents/sofia_criar.md`.** | `faq-coverage`, `sdr-evaluator` |
| 3a | Sofia Skill Connector | **a fazer — contrato definido; nenhuma skill entra no prompt ou runtime nesta fase** | `card-editor`, `graph-publisher` |
| 4 | Tock Fatal nasce no pipeline novo | **em progresso — baseline produtiva v11 (`sha256:e139c137…a9a5dc65`) com catálogo, 605 FAQs e isolamento varejo/atacado; candidato declarativo v12 preparado somente em código, com política conversacional model-owned e sem FAQ nova. Dry-run local passou, mas publicação e ativação continuam sem autorização. Os nós de mídia (asset/gallery/`content_delivery`) do v11/v12 são **conteúdo autorado**, não feature ativa — ver item 8a e o checkpoint de mídia (2026-08-31). LP pública de varejo gerada do bundle em 2026-09-04 pelo item 10, sem publicar nem alterar checksum.** | `graph-publisher` |
| 5 | n8n estável e desacoplado do conteúdo | **em progresso — template único v3 preparado para ambas as personas, envelope único e validador determinístico advisory; provisionamento, teste produtivo e deploy permanecem pendentes de gates próprios.** | — |
| 6 | Aurora migra para o bundle | **em preparação — baseline v75, checksum, projeções e binding produtivos auditados em 2026-08-31; importador shadow-only estrito preparado, mas o export autenticado da publicação ativa ainda não está disponível no workspace. Restam gerar o bundle a partir desse export, dry-run/shadow, revisão dos dois checksums, WA Validator interno e autorização separada de staging/ativação.** | `bundle-migrator` |
| 7 | Orquestradores por estágio e campanha por ciclo → arquitetura multi-agente | **redesenhado 2026-08-20; decisão nova 2026-08-22: escopo de conhecimento por agente via cards Embedded — ver seção própria abaixo** | `graph-publisher`, `card-editor` |
| 8 | Runtime semantic-first (interpretação pelo modelo, prova pelo backend) | **em progresso 2026-08-31 — resposta e próxima pergunta pertencem ao modelo no modo n8n; `missing_fields` mede completude e o proof preserva a fala, descartando apenas componentes inválidos. Runtime, migration funcional e rollout ainda aguardam revisão e autorizações separadas.** | `graph-publisher` |
| 8a | Navegação consultiva de catálogo e mídia no SDR | **FAQ por ProductGroup entregue no candidato 2026-08-24. Envio de mídia: `MetaWhatsAppProvider.send_media` implementado 2026-08-31; falta retrieval multimodal (compiler não projeta asset), resolução de lote no runtime, prova de asset no proof, migration de lote, vídeos/links e avaliação offline. Rascunho de referência em `.worktrees/recovery-question-hotfix/` (não commitado). Plano: `~/.claude/plans/lea-os-logs-de-atomic-candle.md`.** | `faq-coverage`, `sdr-evaluator` |
| 9 | Deploy incremental, leve e retomável | **em progresso 2026-08-24 — lifecycle durável, classificação, pausa/drain/resume, proof do primeiro claim, blue-green da API, imagens separadas, retenção autorizada e gates semânticos implementados no candidato; medição real e prova em QA/produção ainda pendentes** | `release-gate` |
| 10 | Saída pública por template de blocos | **em progresso 2026-09-04 — `api/services/site_blocks.py` resolve blocos declarativos com `scope` de galho; LP de varejo da Tock Fatal gerada e renderizada em `/lp/:personaSlug`. Falta expor os blocos por `/api/menu`, mover `structure` para o banco e ligar a Sofia.** | `graph-publisher`, `card-editor` |
| 11 | Plataforma Brain: cliente, CRM e páginas públicas integrados | **a fazer — no login o cliente acessa suas páginas públicas (LP e cardápio/catálogo), configurações e o CRM já existente. Fundação obrigatória: evento e clique usam `node_id` do grafo como chave nos dois lados.** | — |

### 9 — Deploy incremental, leve e retomável

O deploy é classificado automaticamente em `documentation`, `dashboard`,
`graph`, `api`, `worker`, `conversational` ou `migration`. Documentação e grafo
não fazem deploy de código; dashboard fica no fluxo Vercel; API isolada não
toca workers; worker isolado pausa novos claims, drena e troca apenas o worker.

O lifecycle persistido em `.deploy/lifecycle.json` é atômico e retomável:

`prepared -> images_pulled -> claims_paused -> queue_drained -> migration_complete -> candidate_healthy -> awaiting_resume_authorization -> workers_resumed -> verified`

`validator_complete` e `soak_complete` permanecem apenas como estados legados
compatíveis para evidência opcional; não são gates de deploy ou retomada.
Etapas não aplicáveis podem ser puladas, mas uma regressão só é permitida para
`claims_paused` como safety stop. A retomada é uma operação separada, exige
autorização durável e prova um inbound canônico com uma decisão, um proof, um
commit e no máximo um outbound. Webhooks continuam gravando durante a pausa.

API e worker têm imagens e SHAs de componente independentes. Um deploy isolado
portanto pode produzir SHAs diferentes sem reiniciar o outro processo; o
manifesto aprovado é a autoridade e a divergência fica alertada. Exigir SHA
literal igual e simultaneamente proibir o restart do componente não alterado é
um contrato impossível, por isso o gate correto compara cada container ao seu
SHA/digest aprovado no release.

Retenção preserva atual, rollback e imagens em uso. Apply de limpeza continua
separado do deploy e exige autorização própria. O limite de disco é `<40%`.
O soak conversacional de no mínimo 30 minutos é durável e não entra no tempo
ativo do deploy: a instalação chega a `candidate_healthy`, o validador interno
é registrado, e outra operação completa o soak e pede autorização de resume.

O blue-green mantém o admin do Caddy restrito a `127.0.0.1:2019` dentro do
container; a porta não é publicada pelo Compose. Instalações legadas com
`admin off` fazem uma única recriação controlada do Caddy ainda apontando para
a API ativa e, depois disso, cada cutover usa reload gracioso. Um candidato
substituto só pode reiniciar o lifecycle até `queue_drained`, com o mesmo
`previous_sha`; após `candidate_healthy`, a troca automática continua proibida.
Uma substituição post-cutover revisada exige `supersede_unfinished_release`,
motivo não vazio e marker de claims pausados. Antes do novo `prepared`, o estado
completo anterior é preservado em `.deploy/releases/<candidate_sha>.json` e o
evento `superseded` é anexado ao ledger durável.

Pendências para concluir o item:

- provar em QA a alternância blue-green e o rollback automático do upstream;
- provar API e worker abaixo de 1,5 GB no registry/host;
- medir p95 de deploy comum abaixo de 3 minutos e candidato conversacional
  abaixo de 8 minutos, excluindo soak e espera humana;
- validar os novos workflows em QA e depois em janela produtiva autorizada.

### 2a — Ordem visual das perguntas e autoria pela Sofia

O editor do grafo deve permitir ordenar visualmente as perguntas de
qualificação dentro de cada Persona, Audience, produto ou serviço. A ordem
vertical apresentada na tree deve corresponder à preferência declarada em
`qualification.fields[]`, preservando `question_node_id`, `depends_on`,
`priority`, fonte e status. Arrastar uma pergunta para cima ou para baixo deve
gerar um patch declarativo no grafo existente; não criar tabela, campo
persistente paralelo nem regra por persona.

Regras de produto e autoria:

- a UI mostra uma prévia numerada da sequência por branch e permite reordenar
  por drag-and-drop;
- a posição visual livre só altera a semântica quando o operador salva/aprova
  a nova ordem; o layout não pode mudar o atendimento silenciosamente;
- dependências continuam soberanas: a UI bloqueia ou explica uma ordem em que
  uma pergunta apareça antes do campo declarado em `depends_on`;
- fatos já conhecidos, campos recusados e perguntas respondidas são pulados;
- a ordem é uma preferência entre perguntas atualmente elegíveis, não uma
  volta ao `missing_fields[0]`: o modelo ainda pode escolher outra pergunta
  pendente e permitida, responder uma dúvida primeiro e variar a linguagem;
- o proof valida que a pergunta escolhida pertence ao conjunto pendente e tem
  dependências satisfeitas, sem substituir a resposta do modelo.

A Sofia deve conseguir criar, revisar e reordenar essa sequência por linguagem
natural, por exemplo: "pergunte primeiro se é uso próprio ou revenda e deixe
volume por último". Antes de salvar, ela apresenta o diff `ordem anterior →
ordem proposta`, dependências afetadas, nodes/edges envolvidos e perguntas sem
fonte ou sem `question_node_id`. A mudança segue o mesmo PublicationPlan, CAS,
checksum e aprovação humana dos demais cards.

Gate de compilação e aceite:

1. compilar a ordem por topological sort de `depends_on`, usando a sequência
   visual declarada e `priority` apenas como desempate;
2. rejeitar ciclos, dependência ausente, pergunta fora da branch ou mistura de
   persona/canal;
3. mostrar no dry-run a sequência final de cada branch e marcar como breaking
   change quando a ordem publicada for alterada;
4. provar em teste que reordenar visualmente muda o contrato compilado e o
   checksum, mas não muda fatos, copy, Embedded ou outro fluxo;
5. manter Aurora e Tock Fatal no runtime v3 com publicacoes e bindings isolados
   explícita da Aurora.

### Progresso local do pipeline novo — 2026-08-20

`GraphBundle` (contrato declarativo), `PublicationPlan` (diff + checksum +
custo) e o publisher em duas fases (materialização/staging com gate CAS,
depois ativação explícita via `activate_persona_whatsapp_binding`) existem e
já publicaram um bundle real: `data/graph_bundles/tock-fatal/sdr-qualification-v1.json`,
ativo em produção, `runtime_version=graph_agent_runtime_v3`,
`decision_owner=n8n_agents` (binding `680422f3`). A seleção de galho deixou de
usar o literal `servico` — `conversation_policy.branch_selection.field_key`
agora é lido do grafo (`purchase_profile` na Tock Fatal); `appointment_policy`
segue só como adapter legado da Aurora. Saudação também deixou de ser string
hardcoded: `_greeting_policy` (commit `0c587f6`, 2026-08-20) agora lê nodes FAQ
com `role: greeting_response` do grafo publicado, casados por trigger da
mensagem do cliente — mais um caso do princípio "card = node do grafo".

Ainda pendente pro item 1 fechar como arquitetura final: embeddings
incrementais por `chunk_checksum` (compilação hoje reembeda tudo a cada
publish) e o publisher completo de edição/remoção (hoje só cobre
materialização inicial). Roadmap incremental e gates completos:
`docs/architecture/GRAPH_BUNDLE_PUBLICATION_PLAN.md`.

### Runtime semantic-first e escopo bidimensional — 2026-08-22

Decisões desta sessão, implementadas ou aprovadas na branch
`agent/sofia-vitoria-audit`. Handoff completo:
`docs/handoffs/SESSAO_2026-08-22_SEMANTIC_RUNTIME_E_ESCOPO.md`.

**Interpretar é do modelo; provar é do backend.** Uma auditoria ao vivo em
produção (2026-08-21) provou que o modelo lia certo e o backend descartava a
leitura correta por não bater com lista de frases: `"uso próprio mesmo"` não
selecionava público e `"sim, tá correto"` não fechava a qualificação — o
primeiro e o último passo do funil quebravam por fraseado. `_EXPLICIT_CONFIRMATIONS`
e os markers de serviço deixaram de ser autoridade; sobrevivem só como
normalizadores auxiliares. O contrato novo é `SemanticInterpretation`
(`api/schemas/conversation.py`), **sem confiança numérica** — todo elemento
carrega o trecho literal da mensagem, e o backend reconfere contra a mensagem e
o grafo (`api/services/semantic_interpretation_validator.py`).

**Escopo passa a ser bidimensional: ramos ativos × agente que responde.**
- *Ramo* decide de quem é o conhecimento (varejo vs. atacado).
- *Agente* decide o que pode ser afirmado. Preço não é regra global da persona,
  é competência do agente — hoje só existe o SDR, amanhã haverá outros. Isso
  se declara em **vários cards `Embedded`, um por agente** (`data.agent_slug`);
  card sem `agent_slug` continua valendo para todos, então nada existente
  quebra. O Embedded já governa "o que pode ser afirmado" (a aresta
  `faq → embedded` decide quais FAQs viram claim autorizada,
  `graph_compiler_v3.py:746-752,955-972`) — passa a governar também "por quem".
  Isso substitui `commercial_claims_allowed`,
  `forbid_unpublished_price_stock_deadline_policy` e
  `unsupported_commercial_claim`, **confirmados inertes**: não são lidos por
  nenhum caminho de execução.

**Fatos de arquitetura levantados nesta sessão (não repetir a investigação):**
- O fechamento de ramo é de **passo único e não transitivo**
  (`graph_compiler_v3.py:788-799`): a aresta semântica traz só o nó-alvo, nunca
  a subárvore `contains`. Foi por isso que a v8 precisou de 165 arestas
  `persona → nó` — e é por isso que os dois ramos hoje enxergam 176 dos 182
  nós, ou seja, **a diferenciação de ramo não existe na prática**.
- Multi-ramo já é real no runtime **menos na recuperação**:
  `active_branch_node_ids`, `check_service_operations` e os `aggregate_*`
  (`graph_proof_checker_v3.py:213-300,392`) já trabalham com lista, mas
  `_retrieval_branch_for_turn` resolve **um** ramo e só os chunks dele viram
  `context_cards`.
- A trava de preço em texto livre **já existe, no pipeline legado**
  (`graph_conversation_contract.py:587-606,746-763`, testes em
  `tests/test_graph_conversation_contract.py:404-457`). O v3 não a chama. É
  código para portar, não para inventar.

### Fronteira central de runtime

**Risco arquitetural resolvido no candidato de 2026-09-01:** o cutover havia
deixado composicao deterministica e fallback publico dentro do caminho agentic,
alem de duas fontes concorrentes de runtime. `apps/conversation-runtime` agora
e a unica fonte produtiva; execute/decide possuem entradas exclusivas,
`decision_owner` falha fechado no commit e o canario prova que uma reply
sentinela do modelo nao e anexada nem substituida. Deploy e prova produtiva
continuam pendentes de autorizacoes operacionais separadas.

O GraphBundle publicado fornece conhecimento, fatos comerciais e limites. O
modelo possui explicacao, recomendacao, linguagem, fluxo conversacional e a
proxima pergunta natural; nao pode inventar fatos. `missing_fields` indica
completude, nao um roteiro: runtime/proof nao podem forcar `missing_fields[0]`,
selecionar FAQ deterministicamente, substituir resposta valida do modelo ou
reconstruir Product/Offer/Copy por turno.

Proof confere somente evidencia publicada citada e isolamento persona/agente.
CAS e exactly-once continuam obrigatorios para um inbound -> uma decisao -> um
commit -> no maximo um outbound, sem escolher conteudo da conversa. O gate de
publicacao deve validar acumulacao top-down de cada FAQ de evidencia, com caminho
ativo da Persona, fonte/status e escopo intactos. Tock Fatal segue GraphBundle;
Aurora e Tock Fatal operam no runtime v3, com publicacoes e estado isolados.

### Comportamento do SDR — prioridade corrente (2026-08-23)

Tock e Aurora estão publicadas e respondendo, mas **as duas estão ruins em
comportamento**, por motivos diferentes e já diagnosticados com dados reais de
produção. Plano completo, com transcrições e causas exatas:
`docs/handoffs/PROXIMA_SESSAO_SDR_INTELIGENTE.md`.

- **Tock**: loop por deadlock de dependência (ramo resolve, mas o fato do campo
  seletor grava `unknown/ignored_twice`, e todo campo que depende dele é
  rejeitado para sempre) + **`eligible_faq = 0`**, ou seja, 365 nós de catálogo
  publicados e **nenhum** capaz de sustentar uma resposta.
- **Aurora**: tem o conhecimento e não o usa — só libera depois que o cliente
  nomeia o serviço, quando o trabalho do SDR é justamente mapear necessidade →
  solução. Confirmação de serviço também não vira fato.
- **Ordem**: corrigir o backend da Tock primeiro; na Aurora só correções
  pequenas no fluxo atual; migrar Aurora para o pipeline novo (item 6) só
  depois da Tock validada.
- **Adiado**: cards `Embedded` por agente (seção G). Hoje só existe o SDR; a
  única diferença prevista é SDR sem preço / Closer com preço.

### Item 4a — o que falta pra Tock Fatal ser uma persona real, não uma prova

O bundle ativo hoje é deliberadamente nominal: **"não declara produto, preço,
estoque, prazo, política nem pedido mínimo"** (`GRAPH_BUNDLE_PUBLICATION_PLAN.md`).
Conteúdo comercial real já está capturado e validado (não inventado) em
`docs/tock-fatal-modal-marketing-graph.md` (2 produtos confirmados — Kit Modal 1
e 2, preços unidade/kit_5/kit_10 — e 2 audiências, `atacado-revenda`/`varejo`,
com copy próprio para cada) e em `tests/fixtures/vault_modal/TOCK_FATAL/`.
Falta: (1) trazer esse conteúdo pro bundle real como próxima revisão do
`PublicationPlan`, nunca reescrevendo os arquivos-fonte; (2) manter fora
`tricots`/`cropped-de-modal` — marcados `pending_source`, proibidos de virar
node por regra do próprio documento; (3) não reusar
`data/graph_documents/tock-fatal.v001.json`/`.v002.json` como fonte — payload é
da Baita, confirmado quebrado.

### Débito técnico — motor selecionado não significa motor operacional

Confirmado em produção para `tock-fatal` em 2026-08-20: o dashboard mostrava
`deterministic` selecionado embora o binding ainda estivesse em
`conversation_v1`, sem `runtime_version`, sem workflow n8n e sem qualquer
publicação GraphRAG v3. A seleção persistida é somente intenção de routing;
ela não constitui prova de prontidão. **O binding específico da Tock Fatal já
foi corrigido** (confirmado via query direta em produção, 2026-08-20:
`runtime_version=graph_agent_runtime_v3`, `pipeline_contract=conversation_v3`,
`decision_owner=n8n_agents`) — mas isso foi uma correção pontual desse
binding, não o fechamento do débito.

O débito estrutural continua aberto: o contrato da UI/API precisa separar
`conversation_mode` de `readiness` e exibir estado `blocked`/`paused` enquanto
faltar binding, publicação v3, credencial/workflow ou executor compatível.
Nenhum card pode usar "ativado" apenas porque está selecionado. Fechar isso
exige a mesma verificação como gate transacional antes da troca e como
diagnóstico no GET de routing — não implementado ainda.

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

### Evidência coletada (2026-08-19, não mesclada)

Rodada de evidência read-only (`aurora-unblock`) contra lead real ativo em
produção (`aurora`, lead_ref 32, publicação v66), na branch
`chore/aurora-unblock-p0-evidence-2026-08-19` (commit `62d8c62`, **ainda não
mesclada em `main`**). Detalhe completo em
`docs/evidence/AURORA_STUCK_2026-08-19/findings.md`.

**Nenhuma das 5 hipóteses acima reproduziu.** Dois sinais que pareciam
confirmar bug eram falsos positivos do próprio script de diagnóstico, não do
runtime: (1) `conversation_carry_over_facts_by_lead_v1(persona_id, lead_ref,
null)` sempre devolve 0 linhas quando `p_field_keys` é `null` — `field_key =
ANY(null)` nunca é verdadeiro em SQL; o runtime real nunca chama a função com
`null`; (2) `final_decision->>'reply_text'` estava vazio nos últimos turnos,
mas o outbound real (`lead_buffer.payload->>'text'`) tinha o texto correto —
o texto sai por `proof_result->>'text'` (rede de segurança
`_ensure_reply_text_or_log`), não pela chave que o script checava.

Achado positivo: a memória sobreviveu a um fechamento de jornada real
(jornada 2 herdou `nome_cliente`, `modelo_veiculo`, `vehicle_year`,
`condicao`, reconfirmando só `servico`).

**Ainda falta antes de marcar concluído**: sessão de prova formal pelo WA
Validator interno (`POST /wa-validator/run-direct`) — a evidência acima veio
de tráfego orgânico real, não de uma sessão sintética controlada — e teste da
hipótese 3 (orçamento de prompt), que não foi coberta nesta rodada.

### Prova de saída

Quando solicitada, a validação usa o WA Validator interno
(`POST /wa-validator/run-direct`) e nunca WhatsApp real. Ela é diagnóstico
opcional, não gate de deploy, publicação ou retomada.

- 1 inbound → 1 decisão → 1 proof válido → 1 commit → 1 outbound inerte
- `qualification_complete=true`
- memória sobrevive a **dois** fechamentos de jornada seguidos (modelo, cor e ano
  do veículo preservados; só o serviço reconfirmado)
- zero turnos com `reply_text` vazio

---

## 7 — Orquestradores por estágio e campanha por ciclo → arquitetura multi-agente

Estrutura alvo do atendimento, registrada aqui porque **nada dela entra no P0**.
Hoje a Aurora tem um binding só, e esse binding acumula SDR e CS.

**Redesenhado em 2026-08-20** a partir de um documento de arquitetura genérica
("Agentic Revenue System" — `Tenant → Persona → Process → Graph → Capabilities
→ Agents`, `LeadState` multi-dimensional, `Next Best Action`, `Agent
Registry`/`Capability Resolver`, `MCP Registry`, `Prompt Stack`, `Control
Plane`/`Runtime Plane`) trazido pelo usuário. **Regra inegociável fixada por
ele**: toda estrutura de conhecimento que a Sofia cria é a fonte universal e
absoluta de conhecimento pra esse sistema — nenhum agente especialista tem
base de conhecimento própria fora do grafo que a Sofia já escreve. A camada
"Graph" + "Knowledge" desse documento **já é** o pipeline GraphBundle →
`graph_compiler_v3` → RAG que este roadmap descreve acima; o que falta
construir é só a camada de **orquestração** por cima — nunca um sistema de
conteúdo paralelo.

### Mapeamento — o que já existe vs. o que falta

| Conceito | Já existe (reusar, não recriar) | O que falta |
|---|---|---|
| `Persona` | tabela `personas` | — |
| `Graph` + `Knowledge` | GraphBundle → `graph_compiler_v3` → RAG chunks/entries que a Sofia escreve | — |
| `State.collected_fields`/`missing_fields` | `conversation_ledger`/`facts_by_key` | dimensão "completude" — ver item 7a |
| `State` (fit/intenção/urgência/autoridade/capacidade) | nada | dimensões extras, deliberadamente fora de escopo agora |
| `Policy` (`required_fields` por processo/audiência) | `appointment_policy`, `conditional_fields`, `conversation_policy.branch_selection` | nomeação genérica ainda incompleta (`appointment_policy` só devia se chamar assim pra agendamento de verdade) |
| `Next Best Action` | implícito dentro de `_decide()` (`graph_agent_runtime_v3.py`, função com ~1200 linhas — o próprio erro estrutural que este roadmap já nomeia) | extrair como decisão explícita e nomeada — pré-requisito técnico pra tudo abaixo |
| `Agent` (especialista com prompt/MCP/tools próprios) | não existe — hoje é 1 persona = 1 modelo/prompt | primeiro só 2 agentes: SDR e Closer, sem MCP |
| `Capability Resolver`/`Agent Registry` | `agents_service.py` (rótulo sdr/closer/followup por estágio — precursor primitivo) | resolução real por capability |
| `MCP Registry` + permissão por tool | nada no repo | fora de escopo — nenhum caso de uso real ainda |
| `Tenant` (multi-organização) | nada | fora de escopo — não necessário no número atual de clientes |
| Seletor `multi_agentic` (3º `decision_owner`) | hoje só `deterministic`/`n8n_agents` existem (migration 074) | novo — ver item 7c |

### 7a — Pontuação de jornada (a dimensão "completude" do `LeadState`)

Pontuação simplificada = fração das perguntas do "caminho feliz" já
respondidas: `score = count(required_fields do galho ativo com status
"known") / count(required_fields totais do galho)`. "Caminho feliz" já é
`branch_contracts[*].fields`, compilado pelo `graph_compiler_v3` — nada novo a
computar na compilação, só consumir. Faixas de estágio (ajustáveis por
persona no futuro, não hardcoded): SDR concede até 50%, conversão 75%, venda
100%, pós-venda acima de 100%. Fica exposto (jornada, dashboard) — **não**
aciona roteamento automático agora. Fecha a peça que este item já chamava de
"o contrato que diz qual audiência/serviço/appointment cada campanha publica".
Peso por tempo/esforço de jornada fica como refinamento futuro documentado,
não construído nesta rodada.

### 7b — Um dono por estágio (Agent Registry mínimo)

```
SDR     -> até `qualificado`
Closer  -> `convertido` e `agendado`
CS      -> `concluído`
```

Primeiro passo real: formalizar o que já existe informalmente em
`agents_service.py` (rótulo por estágio) como registro de verdade —
`capability -> agent`, onde `capability` vem do estágio calculado pela
pontuação (7a) e `agent` é um sub-conjunto de prompt/policy do MESMO grafo
compilado (SDR = galhos até qualificado; Closer = galhos de fechamento). O
Closer continua sem reasoning próprio por enquanto — é um papel configurado,
não um LLM novo. Os galhos `service` do grafo (`atendimento-humano`,
`reclamacao`) já são roteiros distintos da qualificação comercial: são os
primeiros candidatos a ganhar dono próprio; enquanto isso, o SDR responde por
eles.

O histórico atravessa todos os estágios sem cópia: `conversation_journeys`
guarda sequência e desfecho, `carry_over` guarda o que o cliente **é**, e
`conversation_carry_over_facts_by_lead_v1` (migration 129) busca em qualquer
jornada do lead. Um orquestrador novo lê a mesma memória — nenhum deles ganha
armazenamento próprio.

### 7c — `multi_agentic`: terceiro `decision_owner`, gradual, sem quebrar Aurora

`decision_owner` hoje só aceita `deterministic`/`n8n_agents` (migration 074).
Ordem de construção, do menor risco pro maior:

1. **Testar dentro do n8n primeiro.** Hoje `persona-conversation-template.json`
   chama um modelo só. Variante com 2 modelos — um nó classificador leve
   (audiência/intenção/estágio, barato) antes do nó de resposta (especialista,
   como hoje) — prova o conceito de "múltiplos agentes" sem mover nada pro
   backend.
2. **Só depois de provado estável**, mover a orquestração pesada (Capability
   Resolver, seleção de agente) pro backend Python. n8n fica reduzido a
   transporte/log (webhook receive + histórico de execução) — n8n continua
   útil, não é removido.
3. Migration nova permitindo `decision_owner = 'multi_agentic'` só depois do
   passo 1 provado — checar `activate_persona_whatsapp_binding` e as
   triggers de integridade das migrations 067-072 antes de mexer.
4. **A Aurora continua em `n8n_agents` até isso estar provado na Tock Fatal**
   — nenhuma migração forçada de persona já em produção real.

### Campanha muda com o ciclo

Concluir a primeira qualificação move a lead de campanha. Cada campanha tem seu
público exato ligado à audiência, e pode declarar outros serviços e outros
appointments:

```
ativação  ->  CS  ->  reativação  ->  remarketing
```

O que falta existir: vínculo lead→campanha escrito pelo próprio ciclo (hoje
`campaign_recipients` só serve a disparo de saída), e o contrato que diz qual
audiência/serviço/appointment cada campanha publica. `campaigns_service.py`
já produz `audience_snapshot` na revisão da campanha, mas `conversation_runtime`/
`graph_agent_runtime_v3` nunca leem isso — zero hits confirmados. Enquanto
isso não existe, a diferença de comportamento entre o primeiro ciclo e os
seguintes é apenas de prompt, lendo `journey.sequence` e
`shared_memory.journey_outcomes` — que é o que o P0 entregou. Duas opções em
aberto pra decidir depois, nenhuma escolhida aqui: lead→campanha escrito pelo
próprio ciclo, ou tabela nova (precisa de autorização explícita, regra de
governança 7 abaixo).

### O que o P0 deliberadamente não fez

- Não criou tabela, migration nem vínculo lead→campanha.
- Não separou bindings por estágio.
- Não moveu os galhos `service` para outro dono.

### O que fica fora de escopo por enquanto (não é "nunca", é "não agora")

- `Tenant` formal, `MCP Registry`/permissão por tool, `Agent Builder`
  (criação de especialista sem código), dimensões extras de `LeadState`
  (fit/intenção/urgência/autoridade separadas de completude).
- Closer com reasoning próprio (LLM dedicado) — ele entra como próxima etapa,
  depois do Agent Registry mínimo (7b) provado.

---

## Arquitetura alvo — GraphBundle

Uma única fonte autoral declarativa por persona. Todo o resto é derivado.

Tock Fatal usa GraphBundle e Aurora usa o caminho autoral legado, ambas no
runtime v3 e isoladas por publicação, checksum, binding e memória; o runtime
comum não mistura contratos. A migração autoral da Aurora permanece no item 6.

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

### Item 2 — fases do editor GraphBundle

- **2a — Visualização GraphBundle v3:** renderer separado, estados
  draft/staged/ativo e convivência com Graph JSON v2.
- **2b — Layout editável:** movimento de nodes persistido fora do bundle, sem
  alteração semântica ou de checksum.
- **2c — Edição versionada de nodes:** editar título, resumo/conteúdo, tags,
  fonte, status e `data` específica do tipo de node. A ordem visual e editável
  das perguntas de qualificação é o subitem prioritário 2c.1.
- **2d — Operações estruturais:** criar, renomear, arquivar e relacionar nodes,
  com proteção de Persona, Embedded e Gallery.
- **2e — Paridade e retirada controlada do v2:** somente depois de provar
  autoria, aprovação, publicação, rollback e equivalência visual no v3.
- **2f — Skills como blocos renderizáveis:** catálogo global recuperável,
  projeções persona-scoped e cards Skill sem copiar instruções para o RAG.

### 2f — Skills como blocos renderizáveis

Skills são capabilities versionadas e independentes do modelo. O contrato
`BrainSkillManifestV1` registra nome, versão, resumo, gatilhos, limitações,
origem, commit, licença, caminho e checksum do artefato. A fase recuperável usa
o fluxo existente, sem tabela ou `node_type` novo:

```text
data/skills/*.json
  -> knowledge_items(content_type=prompt, persona_id=null)
  -> knowledge_nodes(node_type=rule, metadata.capability_kind=skill)
```

O node global nasce validado e desconectado. Ele não entra no Embedded/RAG,
não é incorporado automaticamente a prompts e não concede ferramentas, rede
ou execução de código. O sincronizador é idempotente, usa dry-run por padrão,
valida confinamento de caminho e checksum e nunca cria edges. Apply no banco
produtivo exige autorização específica, separada da instalação no repositório.

Na fase renderizável, nodes `rule` com `capability_kind=skill` aparecem como
cards "Skill" com nome, versão, resumo, origem, integridade e um dos estados:
`available`, `projected`, `connected` ou `drift`. A paleta "Skills disponíveis"
lista manifests globais e projeções autorizadas da persona. Adicionar uma skill
a uma persona cria uma `SkillProjection`, que referencia o manifesto global em
vez de copiar suas instruções. Nunca se cria edge entre o catálogo global e a
persona.

A UI deve oferecer preview somente leitura do Markdown e mostrar se a projeção
está conectada a algum agente. A API interna deve exigir sessão, filtrar
projeções pelo acesso à persona e responder 403 sem revelar nomes de outras
personas. Sofia pode transformar "adicione Humanizer ao agente de copy" em um
patch/diff declarativo, mas nesta fase não altera prompts nem executa a skill.

Gate de aceite do item 2f:

1. renderizar os quatro estados e o preview recuperável;
2. detectar manifesto ausente, artefato alterado e checksum em drift;
3. provar que a projeção referencia o manifesto e não copia instruções ao RAG;
4. provar 403 por persona e rejeitar toda referência cross-persona;
5. exibir o diff da Sofia antes de criar projeção ou edge.

## 10 — Saída pública por template de blocos

Uma página pública é uma lista de **blocos**. Cada bloco declara de onde no
grafo vem o conteúdo — tipo de nó mais relações nomeadas — em vez de estar
escrito em Python. Um resolvedor serve todos os formatos: página nova é linha
nova de template, não código novo. Isso substitui `build_menu_payload`, que
monta sempre a forma cardápio da Baita e depois carimba `format_key` por cima.

Duas regras tornam isso seguro:

1. **Escopo é branch anchor.** Todo template carrega `scope`: o id de um nó com
   capability `branch_anchor`. Só entra no payload o que está no fecho daquele
   galho, com as mesmas regras do `graph_compiler_v3` (árvore primária +
   `global_context` + arestas que declaram `include_in_branch` /
   `include_subtree_in_branch` / `applies_to`). Site e agente escopam
   conhecimento do mesmo jeito. A Tock Fatal vende os mesmos 73 produtos sob
   duas marcas com preços diferentes; sem isso uma página de varejo poderia
   emitir preço de atacado.
2. **Só relações registradas.** Um bloco só percorre relação que já existe em
   `knowledge_relation_type_registry`. O vocabulário de blocos fica fechado por
   uma tabela que já existe, em vez de virar linguagem de consulta ad-hoc.

Slots de imagem reaproveitam `api/core/landing_slots.py`. Um bloco degrada sem
mídia: a Tock tem imagem aprovada em 4 de 73 produtos, então foto é melhoria e
nunca dependência.

`catalogo_roupas` **não exige** criar `product_collection` — a migration 039 já
canonizou `product_collection`/`category` sob `product_group`. A inferência de
formato da migration 071 deve ser substituída por escolha explícita nas
configurações, e a persona passa a poder ativar mais de uma página.

**A invariante 2 continua valendo.** A projeção em FAQ segue sendo o embedding,
e nenhuma FAQ é aposentada por causa de bloco. O caminho é tornar essas
projeções mais automáticas com o tempo — espelhar o grafo em estruturas fixas
consultando o versionamento — sem que o agente deixe de confiar na FAQ para
retrieval nem bloqueie a mensagem.

Entregue em 2026-09-04: `api/services/site_blocks.py`,
`api/scripts/build_tock_lp_payload.py`, `tests/test_site_blocks_scope.py`, e a
LP de varejo em `/lp/:personaSlug` no repositório renderizador.

Falta: expor blocos por `/api/menu`, mover `structure` para
`public_site_formats` no banco, auditoria de cobertura dos `requires`, e ligar a
Sofia.

### Dívida aberta — nós órfãos por renomeação de agente

Em 2026-09-04 o operador confirmou a quem pertence cada agente: **Vitória é da
tock-fatal**, **Lia é da Aurora**, e **Baita e VZ Lupas não têm agente
nomeado**. Os documentos de vault diziam outra coisa — a Baita declarava
Vitória como agente **com telefone**, e a VZ Lupas também a reivindicava.
Corrigido em `docs/sdr/`.

A correção mudou slugs, e o vault é projetado no grafo pelo `vault_sync`. **A
publicação ativa da Baita ainda contém os nós antigos** (verificado em
`.codex-run/baita-vps-v9-event.json`):

| slug publicado | estado depois da correção |
|---|---|
| `briefing:vitoria` | sem origem no vault — o arquivo foi removido |
| `briefing:checkout-vitoria` | renomeado para `checkout` |
| `briefing:roteiro-comercial-vitoria` | renomeado para `roteiro-comercial` |
| `tone:tom-vitoria` | renomeado para `tom-atendimento` |
| `briefing:aurora` (agente) | renomeado para `lia` |

Republicar Baita ou Aurora **cria os nós novos e deixa os antigos órfãos**, em
vez de atualizá-los: o `vault_sync` casa por slug, então um slug que deixou de
existir na origem não é reconciliado — ele simplesmente para de ser tocado, e
continua ativo no grafo, visível ao agente e elegível a RAG. Um agente da Baita
poderia citar "Vitória" a partir de um nó que nenhum arquivo sustenta mais.

Portanto a republicação dessas duas personas exige **arquivamento explícito**
dos slugs acima no mesmo plano, e não pode ser tratada como republicação
rotineira. A VZ Lupas não tem publicação afetada — a correção lá foi só remover
`public_agent_slug` do `persona.md` — mas segue **sem agente declarado**: se ela
tiver um, falta o nome.

## 11 — Plataforma Brain: cliente, CRM e páginas públicas integrados

Hoje o cliente final da plataforma tem um portal (`/clientes/<persona>`) com
leads, mensagens, disparos e pipeline, e as páginas públicas vivem fora dele,
sem ligação nenhuma. O alvo é um só produto: **ao fazer login, o cliente
administra suas páginas públicas, suas configurações e seu CRM no mesmo lugar**,
com os três compartilhando a mesma fonte — o grafo da persona.

O que isso implica, em ordem de dependência:

1. **Configurações escolhem as páginas ativas.** `personas.config.public_site`
   deixa de guardar um `format_key` único e passa a listar as páginas que a
   persona publica (LP, cardápio/catálogo), cada uma com seu slug, rota e
   `scope` de galho. Isso encerra a inferência de formato da migration 071.
2. **A tela de assets vira a tela de slots.** O maquinário já existe —
   `api/core/landing_slots.py`, `POST /assets/{id}/rebind-path` e
   `GET /api/menu/{slug}/admin-blocks` já entregam a grade de blocos com o asset
   atual de cada posição. Falta ligá-la ao template ativo em vez da landing fixa
   da Baita.
3. **A tela de FAQ elege FAQ de site.** A projeção em FAQ continua sendo o
   embedding (invariante 2); o que muda é poder marcar uma FAQ autoral como
   conteúdo público. Sem eleição, o bloco resolve vazio e a seção some.
4. **Trackeamento com chave de grafo.** Não existe hoje: nenhuma rota pública
   aceita evento e `whatsapp_href` não anexa parâmetro. A fundação obrigatória é
   que clique no site e mensagem na conversa gravem o **mesmo `node_id`** do
   grafo. A LP já emite `data-node-id`/`data-block-id` e um `ref` no `wa.me`
   por isso. Se cada lado inventar id próprio, costurar "viu no catálogo →
   perguntou no WhatsApp" depois exige tabela de conciliação.
5. **Atribuição no lead.** `leads.metadata` (migração 060) é o único campo livre
   já migrado; `leads.canal`/`origem` hoje só carregam constantes grosseiras
   (`whatsapp`, `bulk_import`). Atenção ao guard-rail: `_execute_lead_write`
   descarta em silêncio qualquer coluna que o PostgREST não conheça, então
   atribuição nova precisa de migração ou vai para `metadata`.
6. **Rota pública de evento.** Não existe. `system_events` é o sink natural
   (append-only, fire-and-forget), mas `insert_event` filtra para 7 colunas e
   toda rota de escrita hoje exige sessão. Uma rota pública de evento é
   superfície nova e precisa de rate limit e de contrato próprio — não herda o
   fato de `/api/menu/{slug}` ser anônimo.

Ordem sugerida: 1 e 2 destravam o produto sem infra nova; 3 é conteúdo; 4 é
disciplina de chave e custa quase nada se feita antes; 5 e 6 são o CRM de fato e
exigem migração e superfície nova.

### 3a — Sofia Skill Connector

A conexão é exclusivamente por agente. Uma projeção na mesma persona recebe
uma edge `visible_to_agent` para o role-node alvo. O catálogo global permanece
sem edges. Sofia resolve `pedido -> skill candidata -> agente alvo -> patch` e
mostra versão, checksum e efeito antes de pedir aprovação.

O conector produz `ResolvedSkillContext` somente quando todos os gates passam:

- a projeção e o agente pertencem ao mesmo `persona_id`;
- existe edge `visible_to_agent` ativa para o agente exato;
- manifesto, artefato e checksum são válidos;
- a solicitação atual corresponde a um gatilho declarado;
- o operador tem autorização para a persona e para a alteração.

A precedência é: segurança e isolamento, fatos do GraphBundle, contrato da
skill e solicitação atual. Humanizer pode ajustar redação, mas não pode inventar
ou alterar fatos, preços, datas, regras ou estados. Falta de conexão, artefato,
autorização ou checksum válido falha fechada, sem injeção. A auditoria registra
persona, agente, skill, versão, checksum, gatilho e motivo da resolução, sem
conteúdo secreto.

Gate de aceite do item 3a:

1. provar que uma skill desconectada nunca aparece no prompt;
2. provar que conexão na Aurora não habilita Tock Fatal nem outro agente da
   Aurora;
3. ativar Humanizer somente para o agente conectado e pedidos compatíveis;
4. falhar fechado em drift, manifesto ausente ou checksum inválido;
5. avaliar textos com fatos comerciais e provar mudança de estilo sem mudança
   de significado.

Contrato obrigatório da edição GraphBundle futura:

```text
Editar node
  -> salvar nova revisão do draft com CAS
  -> validar GraphBundle
  -> compilar PublicationPlan
  -> exibir diff semântico e novos checksums
  -> aprovação humana
  -> staging
  -> ativação explicitamente autorizada
```

Regras do editor:

- Nunca editar diretamente uma `graph_publications` ativa.
- Cada save exige `expected_draft_checksum` e chave idempotente; conflito de
  versão retorna 409 sem sobrescrever outro operador.
- `id` e `projection_node_id` são imutáveis; rename de slug é operação
  estrutural própria.
- Conteúdo sem fonte ou validação permanece `pending_source` ou
  `pending_validation` e bloqueia publicação.
- Exclusão comum arquiva; remoção física não faz parte do editor.
- Somente admin ou acesso `can_edit` altera; viewer permanece somente leitura.
- Layout não participa do checksum semântico.
- Cada alteração cria revisão recuperável; desfazer cria outra revisão, sem
  reescrever histórico.
- Nenhum save publica automaticamente.

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
| `card-editor` | sonnet | Aplica operações declarativas versionadas em cards e devolve o `PublicationPlan` com diff semântico; nunca publica nem ativa | 2 |
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
5. Quando houver teste automatizado de conversa, preferir o WA Validator
   interno; ele não é obrigatório para deploy ou retomada.
6. Reusar as skills existentes em vez de duplicar:
   - `.claude/skills/aurora-premium-sdr/`
   - `.claude/skills/aurora-conversation-evaluator/`
   - `.agents/skills/brain-agent-e2e/`
   - `.agents/skills/validate-production-release/`
7. Nunca criar tabela nova sem perguntar (`AGENTS.md` §2).
8. Nunca ramificar código de produção por cliente, persona, produto ou serviço
   (`AGENTS.md` §26).
