# Memory

## Preferencias do usuario

- Sempre salvar o contexto relevante da conversa neste arquivo (`memory.md`) para retomadas futuras.
- Usar este arquivo como memoria operacional do projeto antes de responder sobre estado atual, integracoes ou decisoes ja tomadas.

## Contexto salvo em 2026-04-30

### Integracao atual com n8n

O AI Brain integra com n8n em tres pontos principais:

1. Entrada n8n -> AI Brain:
   - O n8n pode chamar `POST /process`, definido em `api/routes/process.py`.
   - Esse endpoint classifica a mensagem, escolhe SDR/Closer, grava resposta no Supabase e devolve `reply` para o n8n enviar no WhatsApp.

2. Saida Dashboard/operador -> n8n:
   - O dashboard chama `POST /messages/send`, definido em `api/routes/messages.py`.
   - O endpoint salva a mensagem no Supabase e tenta chamar `agent.n8n_webhook_url` via `services/n8n_client.py`.

3. Observabilidade n8n -> Supabase:
   - `workers/n8n_mirror_worker.py` consulta `/api/v1/executions` do n8n a cada `N8N_MIRROR_INTERVAL` segundos.
   - As execucoes sao gravadas na tabela `n8n_executions`.

### Estado confirmado

- A API do n8n respondeu com sucesso via `n8n_client.ping()`.
- A chave `N8N_API_KEY` atual expira em 2026-05-24 03:00 BRT.
- O agente `Sofia` existe no Supabase e esta ativo:
  - `bot_name`: `Sofia`
  - persona: `tock-fatal`
  - `n8n_webhook_url`: `NULL`
- `tock-fatal` tem assignments:
  - `sdr` -> Sofia
  - `closer` -> Sofia
  - `followup` -> humano (`agent_id NULL`)
- `baita-conveniencia` e `vz-lupas` existem como personas ativas, mas nao foi confirmado agente/assignment para elas.

### Pontos quebrados / suspeitos

- O envio manual pelo dashboard salva a mensagem, mas nao entrega ao n8n enquanto `agents.n8n_webhook_url` da Sofia estiver `NULL`.
- Quando nao ha webhook configurado, `api/routes/messages.py` marca a mensagem como `draft`.
- O espelho de execucoes do n8n grava `workflow_name` vazio porque a API de execucoes retorna `workflowId`, mas nao retorna `workflowData.name`.
- `services/vault_sync.py` nao alimenta o n8n diretamente. Ele sincroniza vault local -> `knowledge_items` -> grafo semantico.
- Os workflows n8n ainda usam `vectorStoreInMemory`, entao a KB do n8n nao e persistente nem automaticamente conectada ao vault novo.

### Arquivos relevantes

- `services/vault_sync.py`: sincroniza vault local para `knowledge_items` e espelha no grafo semantico.
- `supabase/migrations/008_knowledge_graph.sql`: cria `knowledge_nodes` e `knowledge_edges`.
- `api/routes/process.py`: endpoint usado pelo n8n para obter resposta/decisao do AI Brain.
- `api/routes/messages.py`: endpoint usado pelo dashboard para salvar mensagem humana e disparar webhook do n8n.
- `services/n8n_client.py`: cliente n8n para webhook, execucoes e ping.
- `workers/n8n_mirror_worker.py`: espelha execucoes do n8n para Supabase.
- `supabase/migrations/007_agents_routing.sql`: cria `agents`, `persona_role_assignments`, `leads.ai_paused` e `messages.sender_id`.

### Proximas correcoes prioritarias

1. Preencher `agents.n8n_webhook_url` da Sofia com o webhook correto do workflow n8n que recebe mensagens humanas/outbound.
2. Ajustar `N8nMirrorWorker` para resolver `workflowId -> workflow name`, provavelmente consultando/cacheando `get_workflows()`.
3. Decidir como conectar a KB nova do vault/grafo ao n8n, ou reduzir o uso da KB em memoria do n8n.

### Fluxo de validacao WhatsApp -> lead -> conhecimento

- O usuario pediu um fluxo de validacao completo para criacao de conhecimento, envio de mensagem via WhatsApp Web, resposta do bot e validacao no dashboard.
- Regra importante: nada deve depender de strings hardcoded como produto especifico, palavra "catalogo", dominio ou link fixo. Produto, pergunta, FAQ e URL precisam ser parametrizaveis por CLI/env para novas validacoes.
- A validacao deve provar a cadeia mensagem -> lead -> conhecimento:
  - inserir conhecimento/FAQ com URL de catalogo e produto configuraveis;
  - enviar a pergunta pelo WhatsApp Web;
  - encontrar a conversa persistida no banco e obter o `lead_ref`;
  - validar `/messages/by-ref/{lead_ref}` com outbound contendo a URL configurada;
  - validar `/knowledge/chat-context?lead_ref=...&q=...` com nos de `product` e `faq` ligados ao slug configurado;
  - o dashboard `/messages` deve expor na sidebar "Conhecimento" os nos do grafo, incluindo produto e FAQ.
- O teste alvo e `tests/e2e_faq_whatsapp_modal_catalog.py`, que deve manter defaults para Tock Fatal/Modal, mas aceitar `--product-slug`, `--product-title`, `--catalog-url`, `--faq-title`, `--question`, `--bot`, `--contact` e `--persona-slug`.
- Em 2026-04-30, o teste backend/integrado de FAQ + grafo passou, mas o E2E real via WhatsApp Web travou na tela inicial de carregamento do WhatsApp antes de abrir a lista de conversas. O usuario pediu para executar novamente o E2E.
- O usuario perguntou se algo mudou no processo de abrir o navegador e pediu testar se o problema nao e a memoria do QR code no Google Chrome. Hipotese a validar: o E2E usa perfil persistente proprio (`.test-browser-profile/whatsapp-faq-catalogo`) e nao necessariamente o perfil real do Google Chrome onde o WhatsApp pode estar logado.
- Diagnostico confirmado: `.test-browser-profile/whatsapp-faq-catalogo` fica em `qr_required`, enquanto `.test-browser-profile/whatsapp-sofia` chega em `ready_chat_list`. O problema era o perfil novo sem memoria do QR/login. O E2E foi ajustado para aceitar `WA_PROFILE_DIR`.
- Rodando `WA_PROFILE_DIR=.test-browser-profile/whatsapp-sofia python tests/e2e_faq_whatsapp_modal_catalog.py`, o WhatsApp abriu, clicou em Sofia e enviou "Qual o catalogo do produto modal?". A mensagem ficou ligada ao `lead_ref=122`. O backend `/knowledge/chat-context?q=...` retornou produto `Modal` e FAQs com `https://tockfatal.com/pages/catalogo-modal`, mas a resposta do bot no WhatsApp foi generica e nao incluiu o link, entao o E2E falhou na validacao `contains_catalog_url`.

### Decisao de arquitetura futura

- Por enquanto, o objetivo principal e validar a arquitetura e a infraestrutura dos dados: criacao de conhecimento, grafo, entidades, produtos, FAQ, briefing, mensagens, leads e sidebar de conhecimento no dashboard.
- A resposta generica do bot no WhatsApp e esperada enquanto a logica de resposta continuar do lado do n8n.
- Posteriormente, a logica de respostas que hoje esta no n8n deve ser trocada/substituida pela logica de respostas deste sistema, usando o conhecimento resolvido por `/knowledge/chat-context` e demais estruturas locais.
- Portanto, nesta fase, falhas de qualidade/conteudo da resposta do n8n nao devem bloquear a validacao da arquitetura de dados, desde que a cadeia mensagem -> lead -> conhecimento esteja correta e auditavel.

### Nova diretriz de refatoracao da base de conhecimento

- O usuario quer reprocessar toda a base de conhecimento e ter um agente que aja sobre ela hierarquizando/organizando os conhecimentos como neuronios em grafo.
- Tipos conceituais principais: Entidade, brand, campanha, tom, produto, copy, assets, FAQ, briefing e regras.
- Nivel/importancia/peso deve ser configuravel, nao hardcoded.
- A visualizacao principal deve ser grafo, nao arvore.
- Ao clicar em um conhecimento na sidebar, o fluxo atual redireciona para paginas inexistentes em alguns casos; isso deve ser corrigido para uma pagina/rota universal de detalhe ou drawer existente.
- O usuario quer validar arquivos/conhecimentos nao validados e visualizar facilmente os conteudos selecionados como grafo.
- Deve-se montar plano completo de refatoracao com olhar de arquiteto de dados, identificando erros conceituais que dificultam implantacoes futuras.
- O usuario reforcou que o problema central e a relacao entre fila de conhecimento, grafo e Git/vault. Pediu investigar o banco com queries, propor uma nova relacao/migration, e considerar que o agente curador deve ser o mesmo KB Classifier, usando as mesmas ferramentas/skills/prompts e agindo quando conhecimento repetido for adicionado.
- Foi criada a rotina `tests/integration_knowledge_curation_architecture.py` para validar a migration 009. Ela faz checks estaticos do SQL, audita o banco atual, valida se as tabelas/views da 009 existem, e tem modo `--apply` quando houver `DATABASE_URL`/`SUPABASE_DB_URL` + `psql`/`psycopg`.
- A migration 009 foi corrigida removendo um `WITH kb_norm AS` duplicado que causaria erro de sintaxe.
- A rotina foi executada em modo auditoria com sucesso: confirmou duplicatas, itens sem grafo e que a migration 009 ainda nao esta aplicada.
- Tentativa de `--apply --require-applied` falhou de forma controlada porque o ambiente atual nao tem conexao Postgres direta (`DATABASE_URL` ou `SUPABASE_DB_URL`); `.env` tem Supabase URL/service key, mas isso nao permite DDL via PostgREST.
- Ao tentar rodar manualmente a migration 009 no Supabase, o usuario recebeu `ERROR: 42P10: there is no unique or exclusion constraint matching the ON CONFLICT specification`.
- Causa identificada: os inserts de `knowledge_artifacts` usavam `ON CONFLICT ((COALESCE(persona_id::text, '')), canonical_hash)`, e o Postgres/Supabase nao inferiu corretamente o indice unico por expressao.
- Correcao aplicada: substituir esses conflitos por `ON CONFLICT DO NOTHING` e fazer o preenchimento de campos existentes em passos explicitos de backfill (`WITH ki_current AS ... UPDATE knowledge_artifacts` e `WITH kb_current AS ... UPDATE knowledge_artifacts`).
- Foi identificado um segundo risco equivalente: `ON CONFLICT (source_table, source_id)` em `knowledge_artifact_versions` usava um indice unico parcial (`WHERE source_id IS NOT NULL`) e tambem poderia gerar `42P10`.
- Correcao aplicada: os inserts de `knowledge_artifact_versions` agora usam `ON CONFLICT DO NOTHING`; as versoes vindas de `kb_entries` calculam `version_no` a partir de `max(version_no)` ja existente por artefato para nao colidir com versoes vindas de `knowledge_items`.
- A rotina `tests/integration_knowledge_curation_architecture.py` agora valida que a migration nao reintroduz alvo de conflito por expressao nem alvo de conflito contra indice parcial, verifica os backfills explicitos e imprime quais objetos faltam quando `--require-applied` falha.
- Foi criado o prompt de handoff `prompts/claude_knowledge_graph_validation.md` para o Claude continuar a estruturacao de conhecimento e validacao em grafo ponta a ponta.
- Esse prompt instrui o Claude a ler `memory.md` antes de qualquer acao, atualizar `memory.md` durante/final da sessao, partir do estado atual da migration 009, validar/aplicar a arquitetura canonica, criar teste parametrizavel de conhecimento completo e corrigir o fluxo de sidebar/detalhe que abre rotas inexistentes.

### Correção frontend: keys duplicadas na sidebar de conhecimento

- O dashboard em `dashboard/app/messages/page.tsx` gerava warning React `Encountered two children with the same key` na secao de FAQs da sidebar de conhecimento.
- Exemplo de key duplicada reportada: `7b076a64-9ad0-4fff-b695-7e8cd8a1925f`.
- Causa imediata: `faqs.map((e, i) => <KbCard key={e.id || i} ... />)` assumia que `kb_entries` vinha sem duplicatas, mas o backend/contexto pode retornar a mesma entrada mais de uma vez enquanto a migration 009/curadoria ainda nao consolidou duplicatas.
- Correcao aplicada em `dashboard/app/messages/page.tsx`:
  - adicionados helpers `uniqueBy`, `nodeIdentity`, `kbEntryIdentity`, `assetIdentity` e `scopedKey`;
  - sidebar agora deduplica nodes, kb_entries e assets antes do render;
  - keys agora sao escopadas por secao (`faq`, `copy`, `graph`, `pending-kb`, etc.) e baseadas em identidade estavel;
  - o warning foi tratado sem hardcode de produto/cliente.
- Verificacao: `npx.cmd tsc --noEmit` em `dashboard/` passou. `npm.cmd run build` compilou, mas falhou depois na etapa TypeScript do Next com `spawn EPERM` do ambiente Windows; nao indicou erro de codigo.

### Prompt Claude: E2E Produto Moosi / Campanha Inverno 2026

- Foi criado `prompts/claude_moosi_winter26_graph_e2e.md` como novo plano de execucao para o Claude.
- Cenario: inserir produto `Conjunto Moosi com calca Pantalona` (aliases incluindo os typos digitados pelo usuario), preco `R$ 169,90`, 5 cores, tamanho unico, campanha `Campanha Inverno 26` normalizada como `Campanha Inverno 2026`, relacionados `Modais 2026` e `Catalogo de Modais 2026`.
- Regra nova: todo produto validado deve ter preco estruturado/configuravel, preferencialmente via `knowledge_node_type_registry.config` ou migration `010_knowledge_product_validation_rules.sql`.
- O prompt exige fixture parametrizavel `tests/fixtures/knowledge_moosi_winter26.json`, rotina `tests/integration_moosi_winter26_graph.py`, possivel E2E `tests/e2e_whatsapp_moosi_winter26_graph.py`, e validacao de grafo por `node_type`, `slug`, `relation_type`, `graph_distance` e `path`, nao por substring.
- Resultado esperado na sidebar: Produto com preco/link, Campanha Inverno 2026, Modais 2026, Catalogo de Modais 2026 e lista de similaridade/relacionados ordenada pela distancia entre edges.
- Se o bot via WhatsApp/n8n ainda nao usar a resposta local do AI Brain, o prompt instrui separar PASS de infraestrutura/grafo/sidebar de FAIL/BLOCKED da resposta final e propor/refatorar integracao com `api/routes/process.py`.

## Sessao 2026-04-30 (continuacao) — execucao do prompt de validacao em grafo

### Comandos executados e resultados

- `python tests/integration_knowledge_curation_architecture.py`
  - Static checks: 11/11 OK (todos os checks de seguranca da 009 passam: sem ON CONFLICT em expressao, sem alvo contra indice parcial, backfills explicitos para `knowledge_items` e `kb_entries`, offset de version_no para versoes vindas de KB).
  - Audit do banco atual:
    - `knowledge_items=167`, `kb_entries=27`, `knowledge_nodes=19`.
    - `expected_item_artifact_groups=155` (12 itens entram em grupos duplicados).
    - **153 de 167 knowledge_items (92%) sem nó no grafo** — sintoma do `bootstrap_from_item` ter sido aplicado parcialmente.
    - **26 de 27 kb_entries sem nó** — KB nao foi espelhado pra grafo.
    - 4 grupos duplicados:
      - `tock-fatal/faq/catalogo-de-modais-de-inverno` × 10 (resíduo dos e2e do FAQ que rodaram repetido).
      - `baita-conveniencia/prompt × 2`, `vz-lupas/prompt × 2`, `tock-fatal/prompt × 2` — duplicatas de prompt por persona.
    - `knowledge_nodes_by_type` = {knowledge_item: 13, faq: 4, persona: 1, product: 1} — falta total de campaign/brand/briefing/copy/asset/tone/audience.
  - Schema check: todas as 7 tabelas/views da 009 ausentes — **migration 009 nao aplicada**.

- `python tests/integration_knowledge_curation_architecture.py --require-applied`
  - FAIL (esperado): "migration 009 is not applied yet".

- Probe do ambiente (sem leak de secrets):
  - `DATABASE_URL`, `SUPABASE_DB_URL`: nao definidas.
  - `psql` nao esta no PATH.
  - `psycopg`/`psycopg2`: nao instalados.
  - `.env` tem `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`, mas service key + PostgREST nao permite DDL.

### Bloqueio para aplicar 009 (acao do operador)

A migration nao pode ser aplicada por agente nesta sessao. Caminhos para o operador desbloquear:

1. **Supabase SQL Editor (mais simples)**:
   - Abrir o projeto `slyxppvghniknqofhqzt` em supabase.com → SQL Editor → New query.
   - Colar o conteudo de `supabase/migrations/009_knowledge_curation_architecture.sql`.
   - Run. Se a migration ja inseriu registries antes, os `ON CONFLICT (...) DO UPDATE` re-aplicam sem erro.
   - Re-rodar: `python tests/integration_knowledge_curation_architecture.py --require-applied`.

2. **DATABASE_URL local + apply via teste**:
   - Pegar a connection string em Supabase → Project Settings → Database → Connection string → URI (substitui `[YOUR-PASSWORD]` pela senha do projeto).
   - `pip install "psycopg[binary]"` (ou instalar PostgreSQL CLI pra ter `psql`).
   - `$env:DATABASE_URL="postgresql://postgres:<senha>@db.slyxppvghniknqofhqzt.supabase.co:5432/postgres"`
   - `python tests/integration_knowledge_curation_architecture.py --apply --require-applied`.

### Audit do dashboard — links da sidebar de conhecimento

Padroes produzidos por `services/knowledge_graph.py::_link_target` (linhas ~116-128) e onde caem hoje:

| `link_target`                                       | Rota dashboard existe?            | Le query param?                   | Veredito                |
|-----------------------------------------------------|-----------------------------------|-----------------------------------|-------------------------|
| `/api-brain/knowledge/file?path=...`                | proxiado via `next.config.js` rewrite → backend `/knowledge/file` | n/a | OK                      |
| `/knowledge/quality?item_id=<uuid>`                 | sim (`dashboard/app/knowledge/quality/page.tsx`) | nao le `item_id`                  | parcial — abre lista, nao foca o item |
| `/knowledge/kb/{source_id}`                         | **nao existe** — sem `dashboard/app/knowledge/kb/[id]/page.tsx` | n/a                                | **404 hard**            |
| `/knowledge/graph?focus=<ntype>:<slug>`             | sim (`dashboard/app/knowledge/graph/page.tsx`) | nao le `focus`                    | parcial — abre grafo cheio, nao centra no node |

**Conclusao**: a queixa do usuario sobre "redireciona para pagina inexistente" e literalmente o `/knowledge/kb/<id>` (qualquer kb_entry promovida cai em 404). Os outros dois sao "rota viva mas ignora o parametro" (UX ruim, mas nao 404).

### Recomendacao arquitetural — rota universal de detalhe

Trocar todos os `link_target` para uma rota unica baseada em `knowledge_nodes.id`, ja que esse e o ID estavel e cobre TODOS os tipos (product, faq, asset, briefing, copy, kb_entry, knowledge_item, etc.):

- Frontend: criar `dashboard/app/knowledge/node/[id]/page.tsx` que busca o node pelo id, mostra metadata, vizinhanca em mini-grafo (focus do node), tabela de versoes (apos 009), botao "Validar" / "Marcar como duplicata" / "Abrir source".
- Backend: criar `GET /knowledge/nodes/{id}` retornando node + neighbors + versoes (quando 009 estiver aplicada) + source row (knowledge_item ou kb_entry).
- Refatorar `_link_target` para sempre devolver `/knowledge/node/{id}` quando houver `id`, caindo nos URLs atuais como fallback.
- Mudar `dashboard/app/messages/page.tsx::NodePill`/`KbCard`/`AssetCard` pra ja consumir `link_target` retornado pelo backend (nao tem mudanca de logica, so do destino).

Isso resolve os 3 problemas (404, focus de grafo, focus de fila) num unico lugar, e e compativel com a 009: quando aplicada, a rota mostra `knowledge_artifacts.versions` + `knowledge_curation_proposals` ligados ao node.

**NAO IMPLEMENTADO nesta sessao** — escopo grande, depende de 009 aplicada pra adicionar a aba de versoes/proposals. Aguardando direcao do operador.

### Plano do teste de conhecimento completo (parametrizavel)

Bloqueado pela 009 (precisa das tabelas `knowledge_artifacts`, `knowledge_artifact_versions`, `knowledge_curation_proposals`). Design fica registrado pra implementacao pos-aplicacao:

- Arquivo: `tests/integration_knowledge_full_artifact.py`.
- Fixture default: `tests/fixtures/knowledge_full_scenario.json` — JSON com lista de items por content_type. Default cobre os 10 tipos do registry (entity, brand, campaign, product, briefing, tone, copy, faq, asset, rule). CLI: `--scenario <path>`, `--persona-slug <slug>`.
- Validacao baseada em **slug + node_type + relation_type** (nada de substring de cliente):
  - Para cada item do scenario, apos `POST /knowledge/upload/text` + `/queue/{id}/approve?promote_to_kb=true`:
    - existe `knowledge_artifacts` com `canonical_key` derivado do (persona, content_type, title_slug);
    - existe `knowledge_artifact_versions` com `source_table='knowledge_items'` e `source_id` casando;
    - existe `knowledge_nodes` com `node_type` igual ao mapeado pelo registry e `slug` casando;
    - relacoes esperadas (do scenario, tipo `[{relation: 'about_product', target_slug: '<slug>'}]`) existem em `knowledge_edges`.
  - Re-rodar o mesmo scenario → confirma nenhum novo artifact (`count == groups`); confirma novo `knowledge_artifact_versions` (apenas se conteudo mudou) OU nova `knowledge_curation_proposals` com `kind='merge'`.
- Ao final, imprime URLs do dashboard pra inspecao visual: `/knowledge/graph?persona_slug=<slug>` e `/messages` (sidebar de conhecimento).
- Skip-on-error: se a 009 nao estiver aplicada, exit 0 com mensagem clara (mesma postura do `integration_chat_context.py`).

### Plano da rotina de reprocessamento dry-run

Bloqueado pela 009. Design:

- Arquivo: `tools/reprocess_knowledge_dryrun.py` (CLI standalone, nao testa) ou endpoint `POST /knowledge/curate/dry-run` em `api/routes/knowledge.py`.
- Modo `--dry-run` (default): le `knowledge_items` + `kb_entries` + opcional vault, agrupa por `(persona_id, content_type, title_slug)`, gera `knowledge_curation_proposals` com `kind in ('merge','create_node','add_edge')` mas NAO aplica.
- Modo `--apply` explicito: efetiva proposals que estao em `status='proposed'` e nao `kind='merge'` (merge sempre humano).
- Relatorio agrupado por persona/tipo/status/backlog reason (a view `v_knowledge_curation_backlog` ja entrega isso; basta SELECT).

### Arquivos consultados nesta sessao

- `tests/integration_knowledge_curation_architecture.py` (rotina de teste estatico/audit/applied).
- `supabase/migrations/009_knowledge_curation_architecture.sql` (schema canonico).
- `services/knowledge_graph.py` (`_link_target`, `bootstrap_from_item`).
- `dashboard/app/messages/page.tsx` (sidebar de conhecimento — ja existe completa, secoes Produtos/Campanhas/FAQs/Briefings/Copies/Regras-Tom/Relacionados/Assets/Pendentes).
- `dashboard/app/knowledge/{quality,graph,kb,...}/page.tsx` (presenca/leitura de query params).
- `dashboard/next.config.js` (rewrite `/api-brain/*` → backend).
- `test-artifacts/knowledge_curation_architecture_test.json` (snapshot completo do audit).

### Estado dos criterios de aceite

1. ✓ memory.md lido no inicio + atualizado agora.
2. ✓ Migration 009 passa nos 11 checks estaticos.
3. ✗ Migration 009 nao esta aplicada — bloqueio documentado, 2 caminhos de unblock pro operador.
4. ✗ `--require-applied` ainda falha (consequencia direta do criterio 3).
5. ✓ Plano tecnico do teste de conhecimento completo registrado com arquivo + fixture + validacao por slug/node_type.
6. (depende da 009) Tratamento de duplicatas via `knowledge_artifacts` + `knowledge_artifact_versions` + `knowledge_curation_proposals` ja esta na 009.
7. ✓ Grafo ja mostra nodes/edges por tipo configuravel (registry) — pos-009 vira programatico.
8. ✗ Sidebar tem 1 link 404 (`/knowledge/kb/<id>`) e 2 links sem foco (`item_id`/`focus`). Plano de rota universal `/knowledge/node/[id]` registrado, nao implementado.
9. ✓ Nenhuma logica nova hardcoda cliente/produto. `_TOPIC_NODE_TYPES` e `_link_target` continuam genericos.
10. ✓ Resultado/pendencias listados acima.

### Pendencias reais (acao necessaria)

1. **Operador**: aplicar `supabase/migrations/009_knowledge_curation_architecture.sql` no Supabase (SQL Editor ou DATABASE_URL).
2. **Pos-009**: implementar `tests/integration_knowledge_full_artifact.py` + fixture.
3. **Independente da 009**: implementar rota `dashboard/app/knowledge/node/[id]/page.tsx` + endpoint `GET /knowledge/nodes/{id}` + ajustar `_link_target`. Resolve os 3 problemas de UX da sidebar.
4. **Pos-009**: implementar dry-run de reprocessamento (CLI ou endpoint).

### Tarefas (sessao)

- #1 ✓ static + audit da 009.
- #2 ✓ verificacao de aplicado + bloqueio documentado.
- #3 ✓ audit dashboard sidebar 404.
- #4 ✓ design teste conhecimento completo (impl bloqueada).
- #5 (em andamento) memory.md atualizado.

## Sessao 2026-04-30 (continuacao Codex) - Moosi Winter 26 graph

### Pedido retomado

O usuario pediu para ler `memory.md` e continuar de onde o Claude parou. O ponto de partida era `prompts/claude_moosi_winter26_graph_e2e.md`: produto `Conjunto Moosi com calca Pantalona`, preco `R$ 169,90`, 5 cores, tamanho unico, campanha `Campanha Inverno 2026`, relacionados por grafo (`Modais 2026`, `Catalogo de Modais 2026`) e regra configuravel de produto com preco obrigatorio.

### Alteracoes aplicadas

- `services/supabase_client.py`: `list_knowledge_nodes_by_type()` agora seleciona `metadata`, permitindo que `_detect_terms()` reconheca `aliases`/`synonyms` da fixture em vez de depender de substring no titulo.
- `services/knowledge_graph.py`: `_link_target()` nao gera mais `/knowledge/kb/<id>` para `kb_entries`, porque essa rota nao existe no dashboard; `kb_entries` no `chat_context` reutilizam o `link_target` do node.
- `dashboard/app/messages/page.tsx`: `ChatContext` tipa `similar`; `NodePill` renderiza preco, cores, tamanho e URL de catalogo vindos de `metadata`; foi criada a secao "Busca por similaridade" com distancia e path; `KbCard` nao cai mais em `/knowledge/kb/<id>`.
- `tests/integration_moosi_winter26_graph.py`: criada rotina parametrizavel com `--scenario`, `--persona-slug`, `--catalog-url`, `--dry-run` e `--apply`. O dry-run valida fixture sem banco. O apply exige catalog URL, cria/atualiza knowledge_items, roda bootstrap do grafo, faz upsert de nodes/edges, cria artifacts/versions quando a 009 existir, e valida `chat_context` por slug, tipo, relation_type, graph_distance e path.
- `tests/integration_knowledge_curation_architecture.py`: adicionados checks estaticos da migration 010 e deteccao de view `v_knowledge_curation_backlog` aplicada sem `artifact_id`.

### Comandos executados e resultados

- `python -m py_compile tests/integration_moosi_winter26_graph.py tests/integration_knowledge_curation_architecture.py services/knowledge_graph.py services/supabase_client.py` - PASS.
- `python tests/integration_moosi_winter26_graph.py --scenario tests/fixtures/knowledge_moosi_winter26.json --dry-run` - PASS. Aviso esperado: `MOOSI_CATALOG_URL`/`--catalog-url` nao configurado. Gerou `test-artifacts/moosi_winter26_graph_test.json`.
- `python tests/integration_knowledge_curation_architecture.py` - PASS em modo normal. A 009 esta aplicada o suficiente para encontrar tabelas/artifacts/versions, mas a view `v_knowledge_curation_backlog` no banco esta desatualizada e nao expoe `artifact_id`.
- `python tests/integration_knowledge_curation_architecture.py --require-applied` - FAIL esperado no estado atual: `v_knowledge_curation_backlog is stale; re-run migration 009 to expose artifact_id`.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.

## Sessao 2026-04-30 - filtro de leads/conversas por persona

### Problema observado

O usuario reportou leads de clientes diferentes aparecendo com filtro errado. A investigacao mostrou:

- `api/routes/leads.py` nao aceitava filtro de persona.
- `services/supabase_client.get_leads(persona_slug=...)` aceitava parametro, mas ignorava o filtro.
- `get_conversations()` agrupava conversas por `nome` antes de `lead_ref`, misturando contatos homonimos entre clientes.
- O seletor global de persona no topo do dashboard nao era consumido pelas paginas de Leads e Mensagens.
- O lead `Allan` (`lead_ref=122`) esta com `persona_id=None`; por seguranca, o sidebar agora bloqueia contexto de conhecimento para lead sem persona para evitar mistura entre clientes.

### Alteracoes aplicadas

- `services/supabase_client.py`
  - `get_leads()` agora filtra por `persona_id` direto ou resolve slug via `get_persona()`.
  - `get_conversations()` agora usa `lead_ref` como chave canonica, inclui `persona_id`/`lead_id`/`interesse_produto`, filtra por persona e evita duplicar mensagens orfas pelo mesmo nome.
  - `get_lead()` aceita tanto `leads.id` numerico quanto `lead_id` externo.
- `api/routes/leads.py`
  - `GET /leads` aceita `persona_id` e `persona_slug`.
- `api/routes/messages.py`
  - `GET /messages/conversations` aceita `persona_id`.
- `dashboard/lib/api.ts`
  - `api.leads()` e `api.conversations()` aceitam `personaId`.
- `dashboard/app/layout.tsx`
  - seletor global salva `ai-brain-persona-slug` e `ai-brain-persona-id` no localStorage e emite evento `ai-brain-persona-change`.
- `dashboard/app/leads/page.tsx` e `dashboard/app/messages/page.tsx`
  - passam a recarregar dados quando o cliente global muda e pedem dados filtrados por `persona_id`.
- `services/knowledge_graph.py`
  - `get_chat_context()` retorna contexto vazio se houver `lead_ref` mas nao houver `persona_id`, bloqueando busca global de KB/grafo.

### Validacao

- `python -m py_compile services\supabase_client.py services\knowledge_graph.py api\routes\leads.py api\routes\messages.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- Sonda no Supabase:
  - Prime Higienizacao: 1 lead, 1 conversa, 0 registros fora da persona.
  - Tock/Baita/VZ: 0 leads filtrados no estado atual do banco.
  - nomes repetidos em conversas: 0 depois do agrupamento por `lead_ref`.
  - Allan (`lead_ref=122`) permanece sem `persona_id`; `get_chat_context()` retorna bloqueio em vez de misturar conhecimento global.

### Correcao de dado operacional

- O usuario confirmou que, com Tock Fatal selecionado no filtro superior, Allan deveria aparecer.
- O lead Allan (`leads.id=122`, `lead_id=555182608510`) estava com `persona_id=None`.
- Foi atualizado no Supabase para `persona_id=75140d57-c57d-419c-9088-6aae73de26a1` (`tock-fatal`).
- Validacao apos update:
  - `get_leads(persona_slug='tock-fatal')` retorna Allan.
  - `get_conversations(..., persona_id=tock_id)` retorna Allan como `lead:122`.
  - `knowledge_graph.get_chat_context(lead_ref=122)` agora resolve 26 nodes e 15 KB entries para o termo `Modal`, sem bloqueio por persona ausente.

### Ajuste do seletor global para Prime/Tock

- O usuario reforcou que selecionar Prime no filtro superior deve levar as conversas para o galho/neuronio Prime.
- Sonda confirmou que Prime esta correto no backend:
  - persona `prime-higienizacao` existe.
  - lead `Teste Prime Bulk` (`lead_ref=125`) pertence a Prime.
  - conversas filtradas por Prime retornam `lead:125`.
  - KB Prime tem 94 entradas ativas, grafo tem 98 nodes e 536 edges.
  - `get_chat_context(lead_ref=125)` resolve termos Prime, 179 nodes no contexto e 154 entradas relacionadas.
- Corrigido `dashboard/app/layout.tsx`: o seletor global nao inicia mais gravando `tock-fatal` antes de carregar personas. Agora carrega personas, preserva slug salvo se existir e so entao grava/propaga `ai-brain-persona-id`.
- Validacao: `cd dashboard; npx.cmd tsc --noEmit` - PASS.

### Reforco dos dois fluxos Tock/Prime

- Pedido: corrigir ambos os fluxos com o proposito de cada filtro/persona buscar seu proprio galho/neuronio de conhecimento.
- `services/supabase_client.py`
  - Adicionada `_resolve_persona_id()`.
  - Adicionada `ensure_lead_for_persona()`: quando `/process` recebe `persona_slug`, garante que o lead exista e fique vinculado ao `persona_id` correto; se o lead ja tem outra persona e nao veio `lead_ref` explicito, nao move o lead para evitar colisao entre clientes.
- `core/context_builder.py`
  - Agora chama `ensure_lead_for_persona()` antes de montar contexto.
  - Historico passa a usar `lead.ref` quando existir, garantindo mensagens do lead correto.
- `api/routes/process.py`
  - Gate de pausa agora le o lead por `ctx.lead.ref` quando disponivel, nao apenas por `lead_id` externo.
- `dashboard/app/messages/page.tsx`
  - Se o filtro global muda e o lead selecionado nao pertence a persona atual, a selecao/mensagens/sidebar sao limpos.
  - Sidebar so busca conhecimento quando ainda existe `selectedLead` da persona carregada.
- Validacao:
  - `python -m py_compile services\supabase_client.py core\context_builder.py api\routes\process.py services\knowledge_graph.py api\routes\leads.py api\routes\messages.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.
  - Tock: Allan `lead_ref=122`, persona correta, `context_builder` com 8 KB chunks, chat-context com 26 nodes e 15 KB entries para Modal.
  - Prime: Teste Prime Bulk `lead_ref=125`, persona correta, `context_builder` com 19 KB chunks, chat-context com 179 nodes e 154 KB entries Prime.
  - Filtro de listas: Tock retorna apenas Allan; Prime retorna apenas Teste Prime Bulk.

## Sessao 2026-04-30 - teste real Prime Higienizacao em massa

### Pedido retomado

O usuario pediu um teste real para cadastrar `Prime Higienizacao` com 5 produtos diferentes, 10 copys e 50 FAQs. O objetivo era validar cadastro de conhecimentos, relacoes do grafo, mensagens persistidas no banco e chat-context/sidebar sem WhatsApp real nem n8n.

### Alteracoes aplicadas

- Criado `tests/integration_prime_bulk_real.py`.
  - Gera cenario deterministico e parametrizavel por CLI:
    - `--products` default 5.
    - `--copies` default 10.
    - `--faqs` default 50.
    - `--lead-ref`, `--create-test-lead`, `--skip-messages`.
    - `--bootstrap` e `--write-artifacts` para caminhos mais pesados.
  - Dados do cenario:
    - persona/brand `prime-higienizacao`, cor azul, regiao Novo Hamburgo.
    - briefing geral, tom serio/direto/regional/clean/seguro, regra de precos.
    - produtos:
      - Higienizacao de Cadeiras Prime - R$ 100,00 por cadeira.
      - Higienizacao de Sofas Prime - R$ 200,00 por sofa.
      - Higienizacao de Poltronas Prime - R$ 180,00 por poltrona.
      - Higienizacao de Colchoes Prime - R$ 250,00 por colchao.
      - Impermeabilizacao Prime - +30%.
    - 10 copys distribuidas pelos produtos.
    - 50 FAQs distribuidas pelos produtos.
    - 82 edges no grafo: brand/produto/tom/regra/copy/FAQ/same_topic_as.
  - O modo apply real cria/reusa lead de teste dedicado com `--create-test-lead` e salva mensagens inbound/outbound reais em `messages`.
  - O apply rapido grava `knowledge_items`, `knowledge_nodes`, `knowledge_edges` e mensagens. `--bootstrap` e `--write-artifacts` foram deixados opcionais porque o caminho completo com artifact/version por item ficou lento demais para o bulk.

### Erros encontrados

- `lead_ref=91003` nao existia em `leads`, entao `messages.lead_ref` falhou por FK. Corrigido com `--create-test-lead` e validacao explicita de lead existente.
- O primeiro apply completo com artifact/bootstrap por item ficou lento e bateu timeout depois de varios minutos. Corrigido com cache de existencia de tabelas e modo bulk rapido padrao, mantendo flags para testar bootstrap/artifacts separadamente.

### Comandos executados e resultados

- `python -m py_compile tests\integration_prime_bulk_real.py` - PASS.
- `python tests\integration_prime_bulk_real.py --dry-run --products 5 --copies 10 --faqs 50` - PASS.
  - Plano: 69 itens, 5 produtos, 10 copys, 50 FAQs, 82 edges, 6 mensagens.
- `python -u tests\integration_prime_bulk_real.py --apply --products 5 --copies 10 --faqs 50 --lead-ref 91003` - FAIL.
  - Motivo: FK de `messages.lead_ref`; lead 91003 inexistente.
- `python -u tests\integration_prime_bulk_real.py --apply --products 5 --copies 10 --faqs 50 --create-test-lead` - PASS.
  - Lead de teste real usado: `lead_ref=125`.
  - Validou tabelas `knowledge_items`, `knowledge_nodes`, `knowledge_edges`.
  - Validou persona, 5 produtos, 10 copys, 50 FAQs, produtos com preco estruturado.
  - Validou mensagens inbound/outbound persistidas no banco.
  - Validou `chat_context` com brand Prime, relacoes para sidebar e links nos nodes.
  - Relatorio: `test-artifacts/prime_bulk_real_test.json`.

### Pendencias reais

- Este run de massa nao executou `--bootstrap` nem `--write-artifacts`; portanto nao mede o caminho completo de artifact/version para os 69 itens. Isso ficou separado por flag porque o caminho completo e lento no Supabase atual.
- Para validar canonico completo em massa, o proximo passo tecnico e otimizar/batchar artifacts e versions em vez de fazer uma sequencia de chamadas por item.
- `cd dashboard; npm.cmd run build` - compilou, depois falhou em `Running TypeScript` com `spawn EPERM`, mesmo bloqueio de ambiente Windows observado antes.

### Estado atual do banco / aplicacao

- A migration 009 parece aplicada, mas a view `v_knowledge_curation_backlog` aplicada e uma versao antiga sem `artifact_id`.
- Para destravar `--require-applied`, reexecutar `supabase/migrations/009_knowledge_curation_architecture.sql` inteira ou pelo menos recriar a view `v_knowledge_curation_backlog` da versao atual do arquivo.
- A migration 010 foi criada no repo e passa checks estaticos, mas ainda precisa ser aplicada se o banco nao tiver `knowledge_validation_rules`.

### Pendencias reais

1. Reexecutar a view/migration 009 atualizada para que `--require-applied` passe.
2. Aplicar `supabase/migrations/010_knowledge_validation_rules.sql` se ainda nao foi aplicada.
3. Rodar `tests/integration_moosi_winter26_graph.py --apply --catalog-url <URL_REAL>` quando houver URL configurada do catalogo/produto.
4. Criar/ajustar E2E WhatsApp especifico (`tests/e2e_whatsapp_moosi_winter26_graph.py`) apos a infra de dados passar em `--apply`.
5. Futuro: rota universal `/knowledge/node/[id]` + endpoint `GET /knowledge/nodes/{id}` para detalhe rico; por enquanto o 404 de `/knowledge/kb/<id>` foi removido da sidebar.

## Sessao 2026-04-30 - correcao SQL migration 010

### Erro reportado

Ao aplicar `supabase/migrations/010_knowledge_validation_rules.sql`, o Supabase retornou:

`ERROR: 42601: syntax error at or near "," LINE 165 ... jsonb_extract_path(t.metadata, VARIADIC string_to_array(field_path, '.'), 'amount')`

### Causa

No PostgreSQL, `VARIADIC` precisa ser o ultimo argumento da chamada de funcao. Portanto `jsonb_extract_path(..., VARIADIC string_to_array(...), 'amount')` e sintaxe invalida.

### Correcao aplicada

- `supabase/migrations/010_knowledge_validation_rules.sql`
  - A view `v_knowledge_validation_failures` agora calcula `observed_value` e `observed_text` com operadores JSONB:
    - `metadata #> string_to_array(field_path, '.')`
    - `metadata #>> string_to_array(field_path, '.')`
  - Checagens de `currency_object` usam `observed_value->'amount'`, `observed_value->>'amount'`, etc.
  - `v_knowledge_products_missing_price` usa CTE `product_prices` e `price->...`, evitando `jsonb_extract_path(..., VARIADIC ..., 'amount')`.
  - Casts numericos continuam protegidos por `CASE` e so rodam quando `jsonb_typeof(...) = 'number'`.

- `tests/integration_knowledge_curation_architecture.py`
  - Adicionado check contra o padrao invalido `VARIADIC string_to_array(field_path, '.'),`.
  - Adicionado check exigindo uso de `#>`/`#>>` para caminhos dinamicos.

## Sessao 2026-04-30 - documentacao do fluxo de conhecimento

- O usuario perguntou se havia um arquivo que explicasse claramente o fluxo do conhecimento. Foi identificado que o conteudo existia, mas estava espalhado entre `memory.md`, README, services e migrations.
- Criado `docs/knowledge-flow.md` como documento canonico do fluxo e hierarquia atual do conhecimento/grafo.
- O documento cobre:
  - camadas operacional, grafo semantico e curadoria canonica;
  - entrada via KB Classifier, upload manual e vault sync;
  - fila `knowledge_items`, base ativa `kb_entries`, grafo `knowledge_nodes`/`knowledge_edges`;
  - hierarquia de `knowledge_node_type_registry`;
  - relacoes de `knowledge_relation_type_registry`;
  - bootstrap do grafo, `/knowledge/chat-context`, artifacts, versions, proposals e regras da migration 010;
  - relacao com n8n, fluxo completo esperado, testes existentes e pendencias conhecidas.
- Atualizado `README.md` no topo com link para `docs/knowledge-flow.md`.

## Sessao 2026-04-30 - correcao Prime Bulk KB/grafo/approve

- O usuario reportou inconsistencias no ultimo teste `Teste Prime Bulk`:
  - conhecimentos apareciam como validados na contagem, mas nao apareciam claramente na sidebar/side panel;
  - respostas inseridas pelo teste eram genericas: `Resposta teste Prime: consultei o grafo de conhecimento, precos e FAQs relacionados.`;
  - filtro de grafo por persona parecia sumir com os dados;
  - approve manual em `/knowledge/queue/{id}/approve` retornou 500 no frontend.
- Causas/achados:
  - `tests/integration_prime_bulk_real.py` criava `knowledge_items` aprovados e `knowledge_nodes`, mas nao promovia tudo para `kb_entries` por padrao. Isso deixava o agente textual dependente do fallback/grafo, nao da KB ativa.
  - O teste inseria respostas mockadas genericas, sem usar preco/FAQ do cenario.
  - O bulk approve do frontend usava `Promise.all`, podendo disparar varias promocoes em paralelo. Como o grafo usa upsert manual `select -> insert`, isso pode gerar corrida em constraints unicas.
  - `api/routes/graph.py` buscava todas as `kb_entries` mesmo quando havia filtro de persona; agora passa `persona_id` ao buscar KB para o grafo filtrado.
- Correcoes aplicadas:
  - `tests/integration_prime_bulk_real.py` agora promove por padrao cada item para `kb_entries(status='ATIVO')`, com `source='manual'` por causa do check constraint da tabela.
  - O teste valida que todos os itens foram promovidos para KB ativa e que `services.knowledge_service.search_kb_text()` encontra conhecimento Prime com preco (`R$ 100,00`).
  - As respostas de teste agora sao deterministicas e baseadas no cenario, incluindo produto, preco e FAQ relacionada; o teste falha se encontrar o placeholder generico antigo no run atual.
  - `dashboard/app/knowledge/quality/page.tsx` agora aprova/promove lote sequencialmente, evitando corrida de upsert no backend.
  - `services/supabase_client.py` trata violacao de unique constraint em `upsert_knowledge_node` e `upsert_knowledge_edge` como sucesso idempotente quando a linha ja existe.
  - `api/routes/knowledge.py` envolve approve/promote em `try/except` e retorna `502` com detalhe quando a promocao falha, em vez de 500 opaco.
  - `api/routes/graph.py` filtra `kb_entries` por persona quando `persona_slug` e informado.
- Verificacao:
  - `python -m py_compile tests\integration_prime_bulk_real.py api\routes\knowledge.py api\routes\graph.py services\supabase_client.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.
  - `python -u tests\integration_prime_bulk_real.py --apply --products 5 --copies 10 --faqs 50 --create-test-lead` - PASS.
  - Resultado real do grafo filtrado:
    - `prime-higienizacao`: 262 nodes, 796 edges, `ki_items=69`, `kb_entries=94`, `semantic_nodes=98`, `semantic_edges=536`.
    - `tock-fatal`: 51 nodes, 72 edges.
    - Todos: 478 nodes, 1031 edges.

## Sessao 2026-04-30 - sidebar de conhecimento Prime

- O usuario reportou que o bot ja respondia coerentemente com a KB, mas a sidebar de mensagens nao carregava "conteudo/conhecimento relacionado" para os conhecimentos Prime recentes. Tock Fatal/Allan carregava.
- Diagnostico:
  - O backend ja retornava conhecimento para o lead Prime `125`: `179` nodes e `145+` entradas de KB.
  - A sidebar chamava `api.knowledgeChatContext(selectedId, lastClientText)` sem passar `persona_id`, ficando dependente de matching lexical.
  - `knowledge_graph.get_chat_context()` tambem nao inferia `persona_id` via `lead_ref` quando o frontend nao mandava.
  - O array `kb_entries` do `chat_context` so projetava `faq` e `copy`; produtos/brand/briefing/rule/tone promovidos para KB nao apareciam como cards de conteudo.
  - A secao "Conhecimentos relacionados" exclui tipos principais (`product`, `faq`, `copy`, etc.), entao ela naturalmente ficava vazia para conhecimento estruturado correto.
- Correcoes aplicadas:
  - `services/knowledge_graph.py`: `get_chat_context()` agora resolve `lead_ref -> lead.persona_id` quando `persona_id` nao e enviado e inclui `lead.interesse_produto` na consulta.
  - `services/knowledge_graph.py`: `kb_entries` agora inclui qualquer node vindo de `source_table='kb_entries'`, nao apenas `faq`/`copy`.
  - `services/knowledge_graph.py`: quando um KB row e encontrado, `node_type` passa a ser derivado de `kb_entries.tipo/categoria`, evitando classificar brand/produto como `mention`.
  - `dashboard/app/messages/page.tsx`: a chamada de `knowledgeChatContext` agora passa `selectedLead.persona_id` e usa `selectedLead.interesse_produto` como fallback de query.
  - `dashboard/app/messages/page.tsx`: adicionada secao "Base ativa" para exibir KB cards que nao sao FAQ/Copy (brand, product, briefing, rule, tone, etc.).
- Verificacao:
  - `python -m py_compile services\knowledge_graph.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.
  - Probe `knowledge_graph.get_chat_context(lead_ref=125, persona_id=None, user_text=None)`:
    - termos detectados incluem Prime + 5 produtos;
    - `nodes=179`, `kb_entries=154`, `edges=120`;
    - tipos em KB: `faq=125`, `copy=20`, `product=5`, `brand=1`, `tone=1`, `rule=1`, `briefing=1`.

### Validacao

- `python -m py_compile tests/integration_knowledge_curation_architecture.py` - PASS.
- `python tests/integration_knowledge_curation_architecture.py` - PASS em modo normal.
- O teste ainda avisa que `v_knowledge_curation_backlog` aplicada no banco esta stale sem `artifact_id`; isso e pendencia da migration 009, nao da 010.

## Sessao 2026-04-30 - mock Prime Higienizacao sem WhatsApp/n8n

### Pedido retomado

O usuario pediu um teste novo, automatico, para simular do zero um cliente chamado `Prime Higienizacao`, sem WhatsApp real e sem fluxo n8n. O teste deveria mockar os dados, cadastrar persona/brand/conhecimentos em varios niveis, validar o bot/classificador com exemplos conhecidos, validar distancia entre nos no grafo e demonstrar o conteudo da sidebar lateral.

### Dados estruturados usados

- Fixture: `tests/fixtures/knowledge_prime_higienizacao.json`.
- Persona: `prime-higienizacao`.
- Brand: cor predominante azul.
- Briefing: casal na regiao de Novo Hamburgo, servicos de qualidade para estofados, sofas, cadeiras e similares.
- Tom: serio, direto ao ponto, regional, clean e seguro.
- Servicos/produtos:
  - `higienizacao-cadeiras`: R$ 100,00 por cadeira.
  - `higienizacao-sofas`: R$ 200,00 por sofa.
  - `impermeabilizacao`: acrescimo de 30%.
  - `plano-dia-inteiro`: R$ 1.500,00 pelo dia inteiro.
- Conhecimentos complementares: regra de precos, FAQ e copy regional.

### Alteracoes aplicadas

- `tests/integration_prime_higienizacao_mock.py` criado.
  - Usa uma `_FakeStore` em memoria como backend Supabase.
  - Monkeypatcha `services.supabase_client`.
  - Reaproveita o `services.knowledge_graph.bootstrap_from_item()` e `get_chat_context()` reais.
  - Simula o fluxo `pending -> approved` para cada `knowledge_item`.
  - Cria artifacts canonicos mockados com versions para provar convergencia sem fonte paralela.
  - Aplica as edges esperadas da fixture.
  - Envia mensagens mockadas, sem WhatsApp/n8n.
  - Gera resposta deterministica de bot a partir do `chat_context`.
  - Monta snapshot da sidebar lateral com Brand, Briefing, Produtos, Tom/Regras e Busca por similaridade.
  - Valida slugs, tipos, `graph_distance`, `path`, precos estruturados e idempotencia.

### Comandos executados e resultados

- `python -m py_compile tests\integration_prime_higienizacao_mock.py` - PASS.
- `python tests\integration_prime_higienizacao_mock.py --scenario tests\fixtures\knowledge_prime_higienizacao.json` - PASS.
  - Gerou `test-artifacts/prime_higienizacao_mock_test.json`.
  - Validou 10 knowledge_items, 10 artifacts canonicos mockados, nodes, edges, produtos com preco, mensagem mockada, resposta e sidebar.
- `python tests\smoke_knowledge_graph.py` - FAIL por caminho de import (`ModuleNotFoundError: No module named 'services'`) ao executar como arquivo direto.
- `python -m tests.smoke_knowledge_graph` - PASS. Esse e o formato correto/recomendado pelo proprio teste.

### Pendencias reais

- Este teste e propositalmente offline/mockado. Ele nao prova envio real por WhatsApp, nem roteamento n8n, nem persistencia Supabase.
- Para transformar o mock em E2E real, o proximo passo e criar modo `--apply` equivalente usando Supabase/local API e, depois, plugar o caminho real do bot via `api/routes/process.py` ou endpoint de chat-context.

## Sessao 2026-04-30 - sidebar com relacoes e links de conversa

### Pedido retomado

O usuario pediu que, por enquanto, a sidebar traga todas as relacoes, que cada card tenha um link real para a conversa real e que cada mensagem exista no banco de dados. Como o teste Prime e mockado, "banco" aqui foi tratado como `_FakeStore.messages_by_ref`, mantendo a separacao explicita de que nao toca Supabase real.

### Alteracoes aplicadas

- `tests/integration_prime_higienizacao_mock.py`
  - `insert_message()` agora retorna e armazena mensagem com `message_id`, `canal`, `status` e `created_at`.
  - Cada pergunta mockada salva mensagem inbound/client e resposta outbound/assistant.
  - O snapshot da sidebar ganhou secao `Todas as relacoes`, contendo todas as edges do grafo com origem, destino, relation_type e link de conversa.
  - Todo card de node/similaridade/relacao recebe `conversation_link` no formato `/messages/<lead_ref>?focus=<node_type>:<slug>`; relacoes tambem recebem `edge=<edge_id>`.
  - O teste valida que a sidebar expoe todas as relacoes, que cards apontam para `/messages/<lead_ref>` e que todas as mensagens simuladas foram persistidas no mock database.

- `dashboard/app/messages/page.tsx`
  - Adicionado tipo `KnowledgeEdge`.
  - Sidebar passa a renderizar a secao `Relações do grafo`.
  - `NodePill`, `SimilarCard`, `KbCard` e `AssetCard` aceitam `leadRef` e preferem link para `/messages/<leadRef>?focus=...` quando a sidebar esta dentro de uma conversa.
  - `RelationCard` mostra origem -> destino, relation_type/peso e linka para a conversa com `focus` + `edge`.
  - `KnowledgeSidebar` recebe `leadRef={selectedId}`.

### Comandos executados e resultados

- `python -m py_compile tests\integration_prime_higienizacao_mock.py` - PASS.
- `python tests\integration_prime_higienizacao_mock.py --scenario tests\fixtures\knowledge_prime_higienizacao.json` - PASS.
  - Gerou `test-artifacts/prime_higienizacao_mock_test.json`.
  - Validou 6 mensagens mockadas armazenadas: 3 inbound + 3 outbound.
  - Validou cards com `conversation_link` e todas as relacoes na sidebar.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.

## Sessao 2026-05-01 - filtro de persona consolidado + sidebar Prime e2e

### Pedidos do usuario

1. Corrigir caso de leads de clientes diferentes aparecendo com filtro errado.
2. Garantir que selecionar Tock Fatal lista apenas leads Tock (Allan).
3. Garantir que selecionar Prime lista apenas leads Prime (Teste Prime Bulk).
4. Garantir que sidebar/agente consultem apenas o galho/neuronio da persona do lead aberto.
5. Reprocessar leads orfaos (Jose Rodrigues, Carol vieram via Sofia/Tock e estavam sem persona_id).
6. Re-rodar e2e Prime Bulk validando sidebar.

### Verificacoes iniciais

A maior parte da estrutura ja existia das sessoes anteriores: `/leads` e `/messages/conversations` aceitam `persona_id`/`persona_slug`, `get_conversations` agrupa por `lead_ref`, dashboard tem seletor global e effects de limpeza ao trocar persona, `context_builder` usa `ensure_lead_for_persona`, `get_chat_context` bloqueava lead sem persona.

Validacao inicial:
- `python -m py_compile services/supabase_client.py core/context_builder.py api/routes/process.py services/knowledge_graph.py api/routes/leads.py api/routes/messages.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- `/leads?persona_id=tock` -> apenas Allan (122).
- `/leads?persona_id=prime` -> apenas Teste Prime Bulk (125).
- `/messages/conversations` filtrado idem.

### Endurecimento de bloqueio sem persona

`services/knowledge_graph.py:get_chat_context` so bloqueava quando `lead_ref` estava setado e persona_id ausente. Caso `lead_ref=None` + `persona_id=None`, caia em `_detect_terms` -> `list_knowledge_nodes_by_type(persona_id=None)` que retorna nodes de todas as personas. Vazamento global potencial.

Correcao: bloquear sempre que `persona_id` nao puder ser resolvido. Mensagem do summary diferencia "Lead sem persona vinculada" vs "Persona nao especificada".

### Backfill de leads orfaos

Auditoria do banco identificou 4 leads sem persona_id, todos com mensagens da Sofia (bot Tock):
- 119 Deia Hermann
- 120 Alik Kunde (mensionou "Juliet 24K", mas KB context de modal -> Tock)
- 121 Carol
- 124 Jose Rodrigues

Atualizado `persona_id = 75140d57-c57d-419c-9088-6aae73de26a1` (tock-fatal) para os quatro.

Validacao pos-backfill:
- `/leads?persona_id=tock` -> 5 leads: Allan + Carol + Jose + Deia + Alik.
- `/messages/conversations?persona_id=tock` -> 5 conversas, todas agrupadas por `lead_ref`.
- `/leads?persona_id=prime` -> 1 lead: Teste Prime Bulk (sem vazamento Tock).

### E2E Prime Bulk

`python tests/integration_prime_bulk_real.py --apply --create-test-lead --bootstrap --products 5 --copies 10 --faqs 50` - PASS.
- 484 checks ok, 0 falhas.
- 5 produtos, 10 copies, 50 FAQs com persona Prime, prices estruturados.
- Mensagens inbound/outbound persistidas, replies deterministicos com preco e FAQ relacionada.
- KB ativa promovida; `search_kb_text("Quanto custa Higienizacao de Cadeiras Prime?")` retorna chunks com `R$ 100,00`.
- chat_context contem brand Prime, edges para sidebar, link_target em todos os nodes.

### Sidebar Prime nao carregava no dashboard - causa raiz

Sintoma: usuario reportou que abrir o lead Prime nao mostrava conhecimento na sidebar; logs do Next.js mostravam `Failed to proxy http://localhost:8000/knowledge/chat-context?lead_ref=125&... Error: socket hang up ECONNRESET` e o browser recebia 500.

Hipotese inicial errada: deep-link `/messages/[leadId]/page.tsx` que nao tem KnowledgeSidebar. Descartada apos o usuario mostrar logs do proxy.

Causa real: N+1 em `services/knowledge_graph.py:get_chat_context`. Para cada um dos 157 `kb_entry_nodes` do Prime, fazia `supabase_client.get_kb_entry(sid)` em serie. 157 * ~300ms = 49s. O dev proxy do Next.js (timeout default ~30s) dropava antes do FastAPI responder.

Tock so tinha 15 kb_entries, completava em ~3s, por isso so Prime quebrava.

Profile via wrapper de monkeypatch:
- get_kb_entry: 157 chamadas, 47s (antes do fix).
- get_knowledge_neighbors: 2 chamadas, 2.5s.
- get_lead_by_ref: 1 chamada, 1.8s.
- find_knowledge_nodes: 6 chamadas, 1.4s.
- list_knowledge_nodes_by_type: 1 chamada, 0.2s.

### Fix N+1

`services/supabase_client.py`: novo `get_kb_entries_by_ids(ids)` que faz `in_("id", chunk)` em chunks de 200.

`services/knowledge_graph.py:get_chat_context`: troca o loop com `get_kb_entry` por uma chamada batched antes do loop, depois consulta `kb_rows_by_id.get(str(sid))` em memoria.

### Validacao pos-fix

| caso | antes | depois |
|---|---|---|
| Prime lead 125 (direto :8000) | 49.0s | 7.3s |
| Prime lead 125 (via proxy :3000) | 500/timeout | 6.5s · 200 |
| Tock Allan 122 (via proxy) | 3-5s · 200 | 3.9s · 200 |

Conteudo do payload Prime: 181 nodes (10 product, 129 faq, 20 copy, 2 brand, 2 briefing, 2 tone, 2 rule), 158 kb_entries, todos persona `f5174d34...`. Tock: 25 nodes, todos persona `75140d57...`. Sem cross-contamination.

### Otimizacoes futuras possiveis (nao aplicadas)

- `find_knowledge_nodes` 6 chamadas (uma por termo) = 1.4s. Pode virar 1 query com OR clauses.
- `get_knowledge_neighbors` 2 hops = 2.5s. Segundo hop pode ser opcional via param/limit.

6.5s pelo proxy ja esta dentro do timeout, entao essas otimizacoes ficam para quando virar gargalo de UX.

### Arquivos alterados nesta sessao

- `services/knowledge_graph.py` - bloqueio universal sem persona_id; consumo de `get_kb_entries_by_ids` no lugar do loop N+1.
- `services/supabase_client.py` - nova funcao `get_kb_entries_by_ids`.
- `memory.md` - este append.

Banco: leads 119/120/121/124 com `persona_id` tock-fatal.
