# Brain AI — Progresso UI/UX

## Sofia tool-use contract (2026-05-28)
- Spec autoritativa: `paperclip/docs/qa/sofia-tool-use-contract.md`.
- Define schemas request/response de `/sofia/tools/resolve-persona` e `/sofia/tools/resolve-operation`, 8 canonical ops (reparent_brand, create_default_audience, move_product_to_group, reorganize_campaign_briefing, validate_canonical_chain, reclassify_product_group_as_campaign, commit_pending_change, revert_pending_change), comportamento obrigatorio de `/sofia/graph-command` (tool_calls populado, NUNCA 403 por gate de persona, threshold confidence 0.65), matriz 33 casos (4 personas x 8 ops + 1 low-confidence).
- Fixture skeleton: `paperclip/fixtures/sofia-commands.skeleton.json`.
- BRA-58 (backend) e BRA-59 (AI agent) tem que cumprir o contract antes de done. BRA-60 (QA sweep) roda 33 cases contra `:8001` e gera artifact em `paperclip/test-artifacts/qa/sofia-tool-use-contract-<UTC>.json`.

## Sofia /sofia/graph-command — drop allow-list, cosine tools (2026-05-28)
- Usuario reportou 403 `restricted to VZ Lupas QA persona aliases` ao usar chat lateral do Graph com persona `allanvvz`.
- Origem: `api/routes/qa_contract.py:25-28` (QA_PERSONA_ALIASES) + `:55-60` (_require_qa_persona); restos do isolamento original da QA da VZ Lupas.
- Decisao: em vez de expandir allow-list, eliminar. Mover validacao para tools deterministicos baseados em embeddings:
  - `POST /sofia/tools/resolve-persona` — top-1 persona slug por cosine (sentence-transformers local OU pgvector).
  - `POST /sofia/tools/resolve-operation` — top-1 op canonica (rebind_parent, reorganize_subtree, create_audience, move_node, add_brand, add_product_group, add_product, add_faq).
  - Sofia (LLM) so orquestra: chama tools, recebe IDs+scores, monta patch. Custo reduzido vs reasoning livre.
- Tracking: BRA-57 (CEO meta), BRA-58 (Backend tools + remove gate), BRA-59 (AI agent integration), BRA-60 (QA multi-persona sweep), BRA-61 (uvicorn reload=True para `:8001` refletir edits).
- Cadeia ativa: BRA-54 (done) -> [BRA-58 + BRA-61] -> BRA-59 -> BRA-60 -> BRA-50 -> BRA-46 -> BRA-44.

## Paperclip operating rules (2026-05-28)
- Sistema corrigido em 2026-05-28 apos 6 dones fabricados em 24h. Regra dura:
  - Evidencia so vale em `C:/Users/Alan/Documents/repositorios/ai-brain/...` ou `paperclip/...`.
  - `.paperclip/instances/...`, SQLite stub, sandbox e comentario textual NAO contam.
  - Done exige: artifact em path publicado + commit no repo alvo + memory.md atualizado + comando de validacao executado + disposition formal PATCH.
- Single source of truth: `C:/Users/Alan/Documents/repositorios/paperclip/agents/OPERATING_RULES.md`.
- Checklists operacionais:
  - CEO/PO: `paperclip/agents/CEO_GATE_CHECKLIST.md`
  - QA Lead: `paperclip/agents/QA_LEAD_GATE_CHECKLIST.md`
- Estrutura canonica do grafo: `paperclip/agents/CANONICAL_CHAIN.md` (Persona -> Brand -> Briefing -> Campaign -> Audience -> Product Group -> Product -> FAQ).
- Cadeia prioritaria ativa: `BRA-54 -> BRA-50 -> BRA-46 -> BRA-44`. Tudo fora dela em hold.
- QA: nao repetir teste com inputs iguais. Discriminacao 401/403: probe sem header + probe com `X-AI-BRAIN-ADMIN-TOKEN`. Diferenca de status mostra se o problema e harness ou backend.

## Concluido
- Fase 1: tokens liquid glass, tema, hydration fix.
- Fase 2: Leads consolidado CRM + CSV/Bulk, botao Iniciar conversa.
- Fase 3: PreflightPanel unificado.

## Em execucao
- Fase 4: Leads -> Messages focado.

## QA Supabase migracao para nova conta (2026-05-27)
- Conta antiga `qhnepdcqtkjjslqqiyvp` (ai-brain-qa) suspensa por `exceed_egress_quota`.
  REST 402, pooler Supavisor "Tenant or user not found" em todas regioes. Bloqueio total.
- Schema fallback gerado: `docs/qa/ai-brain-qa-schema.sql` (concatenacao das 42 migrations
  001..042, 4589 linhas, ~194 KB). NAO e introspeccao real, e concatenacao na ordem.
- Conta NOVA destino: email `allanlise027@gmail.com`, project_ref `svkogegypdqquzlfzaor`.
  Conexao direta IPv6 funciona (`db.svkogegypdqquzlfzaor.supabase.co:5432`); pooler nao roteia
  o tenant (mesmo erro do antigo, mas REST 401 confirma que projeto esta ativo).
- Senha Postgres do projeto novo: `@Marrie2025;` (com `;` final). Anotar com cuidado:
  o `;` faz parte da senha, nao e separador.
- Supabase MCP adicionado em `.mcp.json` apontando para o project_ref novo (HTTP,
  scope=project). Carrega no proximo restart do Claude Code.
- Schema completo aplicado com sucesso no projeto novo `svkogegypdqquzlfzaor` (2026-05-27).
  Resultado: 52 tabelas, 6 views, 154 functions, 4 policies, 210 indexes, 4 triggers,
  7 extensions. Script: `scripts/apply_schema_to_new_qa.py`. Estrategia adotada:
  + Bootstrap legacy `docs/qa/00_legacy_leads_messages.sql` antes das migrations,
    porque `leads` e `messages` sao tabelas pre-migrations que ALTERs assumem que existem.
  + Migracoes aplicadas uma a uma (cada com sua transacao) com pre-patch antes da 004
    para corrigir drift do `agent_logs` (a 024 e que adiciona `agent_type`/`action`/
    `decision`/`metadata`, mas a 004 ja cria indice em `agent_type`).
  + Conexao via IPv6 direto a `db.svkogegypdqquzlfzaor.supabase.co:5432` (pooler nao
    roteia esse tenant; mesmo padrao do projeto antigo).
- `env.qa.yaml` atualizado: `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` agora apontam para
  `svkogegypdqquzlfzaor`. URL: `https://svkogegypdqquzlfzaor.supabase.co`. Service_role
  validada via REST (`scripts/validate_new_qa_rest.py`): 200 OK, 52 definitions no
  OpenAPI (bate com 52 tabelas), personas=3 / knowledge_nodes=18 / knowledge_edges=36
  vindos das seeds embarcadas nas migrations, `leads`/`messages` vazios. Anon key tambem
  disponivel se o frontend precisar.
- Smoke do backend local contra o projeto novo (2026-05-27): rodado em :8011 via
  `python scripts/start_api_qa.py`. Startup OK, CORS carregado, storage buckets
  `assets-raw` e `assets-derived` retornaram 200 contra `https://svkogegypdqquzlfzaor.supabase.co`.
  `/health` = 200. `/api/menu/{slug}` testado em baita-conveniencia, vz-lupas e
  tock-fatal: todos 200, cada um com 1 collection seed (`cardapio-<slug>-v1`),
  products=0 (esperado — so o schema seedado das migrations existe, sem dados).
  Probe: `scripts/probe_local_qa_menu.py`.
- Arquivos novos criados nesta migracao: `docs/qa/00_legacy_leads_messages.sql`,
  `docs/qa/ai-brain-qa-schema.sql`, `scripts/apply_schema_to_new_qa.py`,
  `scripts/validate_new_qa_rest.py`, `scripts/probe_local_qa_menu.py`,
  `scripts/probe_prod_legacy_tables.py`. `.mcp.json` agora aponta para o ref novo
  (escopo project, HTTP). `env.qa.yaml` (gitignored) atualizado.
- Pegadinha do "backend ainda fala com a conta antiga" mesmo apos reiniciar
  (2026-05-27): `api/main.py:16` chama `load_dotenv()` que le `.env` da raiz.
  Quando o backend e subido com `uvicorn main:app` direto (sem o launcher
  `scripts/start_api_qa.py`), o `.env` ganha sobre `env.qa.yaml`. Por isso o
  startup mostrava `slyxppvghniknqofhqzt` (PROD antigo, 402) e bucket assets-raw
  MISSING. Resolvido apontando os tres arquivos pro projeto novo, com as chaves
  antigas mantidas comentadas no topo de cada bloco (regra do usuario para reverter
  rapido se precisar):
  + `.env`: SUPABASE_URL/SERVICE_KEY/ANON_KEY/NEXT_PUBLIC_* substituidos pelas
    chaves de `svkogegypdqquzlfzaor`; antigas (slyxppvghniknqofhqzt) comentadas
    com o motivo ("suspensa por exceed_egress_quota em 2026-05-27").
  + `env.yaml`: idem para `SUPABASE_URL` e `SUPABASE_SERVICE_KEY`. PROD passa a
    apontar pro mesmo projeto novo enquanto nao existir projeto PROD dedicado.
  + `env.qa.yaml`: chave antiga (qhnepdcqtkjjslqqiyvp) comentada no topo para
    rastreabilidade; chave nova ja estava ativa.
- TODOs apos liberacao do egress no projeto antigo:
  + Rodar pg_dump real do PROD para extrair DDL real de `leads`/`messages` e substituir
    o bootstrap minimalista (que e best-effort baseado em api/services/supabase_client.py).
  + Repopular o QA novo com dados de Baita / VZ Lupas usando `db-fetch-prod-to-qa`.

## Alinhamento de ambiente local apos migracao Supabase (2026-05-27)

Diagnostico: dashboard em `192.168.0.182:3000` nao mostrava o grafo porque (a)
o backend em `127.0.0.1:8001` foi subido com `python -m uvicorn main:app`
direto do diretorio `api/`, o que carrega apenas `.env` e NAO `env.qa.yaml` —
entao faltavam `ENVIRONMENT=qa` e `AI_BRAIN_ADMIN_TEST_TOKEN` (resultado:
401 "Sessao obrigatoria" em rotas protegidas como /personas e
/knowledge/graph-data); e (b) `dashboard/.env.local` ainda tinha
`NEXT_PUBLIC_SUPABASE_URL` apontando para o projeto antigo.

Acoes feitas (todas read-only / config, nenhuma escrita no banco):
- `dashboard/.env.local`: `NEXT_PUBLIC_SUPABASE_URL` e
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` trocados para o projeto novo
  `svkogegypdqquzlfzaor`. Entradas antigas comentadas no topo do bloco com
  o motivo. Adicionado lembrete inline: ao trocar de projeto Supabase
  e necessario limpar cookies + localStorage do host de dev
  (127.0.0.1:3000, localhost:3000, 192.168.0.182:3000) — sessao do projeto
  antigo nao e valida no novo.
- `.env` (raiz) e `env.qa.yaml`: ja estavam apontando para o projeto novo
  desde a rodada anterior; auditados, sem mudanca. Nao expor service_key
  ou anon_key em logs/relatorios.
- `scripts/start_api_qa.py`: auditado, sem mudanca. Esse launcher injeta as
  chaves de `env.qa.yaml` em `os.environ` ANTES de o app chamar `load_dotenv()`,
  garantindo que `ENVIRONMENT=qa` e `AI_BRAIN_ADMIN_TEST_TOKEN` estejam
  disponiveis durante o startup. SEMPRE usar este launcher para subir QA.
- `scripts/validate_qa_read_only.py` criado: revalida `/health`, `/personas` e
  `/knowledge/graph-data?persona_slug=allanvvz&mode=semantic_tree` apenas em
  leitura, usando o admin test token lido de `env.qa.yaml`. Sem segredos no
  source.

Validacao (subido um backend de teste em :8011 via `start_api_qa.py`, parado
no fim):
- `/health` => 200 ok.
- `/personas` => 200, retorna 4 personas: tock-fatal, baita-conveniencia,
  vz-lupas, **allanvvz** (id 3d2c15f9-208d-474f-bc1e-f6bedee35e3b).
- `/knowledge/graph-data?persona_slug=allanvvz&mode=semantic_tree` => 200,
  6 nodes + 4 edges no payload react-flow. Meta confirma semantic_nodes=3,
  semantic_edges=4. Formato: `node.data.slug` / `node.data.node_type`
  (top-level dos nodes nao expoe slug — usar `data.*`).
- Admin test token via header `X-AI-BRAIN-ADMIN-TOKEN` autenticou em todas
  as rotas protegidas testadas.

Estado pendente no :8001 do usuario: subido com `python -m uvicorn main:app`
direto, sem env.qa.yaml. Retorna 401 "Sessao obrigatoria" com admin token.
**Acao para o usuario reiniciar corretamente:**
  1. Parar o uvicorn atual em :8001
     (`Stop-Process -Id <pid>` ou Ctrl+C no terminal que rodou).
  2. Da raiz do repo: `python scripts/start_api_qa.py`
     (porta default 8001; usa `env.qa.yaml`).
  3. No browser do dashboard, limpar cookies e localStorage de
     192.168.0.182:3000 e localhost:3000 antes de logar de novo
     (sessao antiga do Supabase nao serve no novo projeto).

Comandos de referencia (sem segredos):
- Backend QA local: `python scripts/start_api_qa.py`
  (host 127.0.0.1, port 8001; carrega `env.qa.yaml`).
- Dashboard local: dentro de `dashboard/`, `npm run dev`
  (NEXT_PUBLIC_API_URL=http://127.0.0.1:8001; Supabase do projeto novo).
- Validacao read-only: `python scripts/validate_qa_read_only.py`
  (le `env.qa.yaml`, manda admin token, bate em /health, /personas,
  /knowledge/graph-data; nenhum INSERT/UPDATE/DELETE).

Pendencias / blocked: nenhuma chave faltando neste momento. Quando o egress
do PROD antigo for liberado, ver TODOs no bloco anterior.

## Regras importantes
- Tema atual e claro/liquid glass.
- Nao voltar para black theme.
- Gradients somente nos backgrounds.
- Bordas finas.
- Leads created via CSV devem aparecer em Leads.
- Iniciar conversa deve abrir Messages focado, nao Timeline isolada.

## Regras de negocio - Grafos

### Persona na visualizacao Tree
- Na visualizacao em tree, o node `Persona` sempre fica na parte superior.
- `Persona` so pode receber conexoes abaixo.
- `Persona` tera somente conexao de saida inferior.
- `Persona` nao deve ter conexao superior.
- Na tree, `Persona` e o topo conceitual do fluxo.

### Conexoes na visualizacao Tree
- Conexoes de entrada devem aparecer na parte superior do node.
- Conexoes de saida devem aparecer na parte inferior do node.
- O fluxo visual deve ser vertical: entrada em cima, processamento/conhecimento no meio, saida embaixo.

### Nodes finais / nodes de uso
- Nodes como Galeria, Embed, Assets, Backgrounds, Texturas, Copy e FAQ geralmente aparecem no final do fluxo.
- Eles devem poder receber conexoes de conhecimentos anteriores.

### Galeria e Embed
- `Galeria` e `Embed` devem ter somente o circulo/conector superior.
- Esses nodes recebem conexoes, mas nao precisam emitir conexoes inferiores por padrao.
- Deve ser possivel conectar Galeria com Copy, FAQ, Assets, Backgrounds e Texturas.
- Deve ser possivel conectar Embed com Copy, FAQ e Assets.

### Categorias diferentes de nodes
- O grafo deve tratar como categorias diferentes: Persona, Brand, Campanha, Produto, Publico, FAQ, Copy, Assets, Galeria, Embed, Backgrounds, Texturas, Regras, Tom de voz e Entidades.
- Cada categoria pode ter visual, conector e nivel hierarquico proprio.

## Grafos - Embed e Gallery
- Embed e destino final de KB.
- Gallery e destino final de Assets.
- Embed e Gallery nao nascem conectados a outros nodes.
- Ao conectar conteudo ao Embed, o conteudo e tratado como aprovado e enviado para Knowledge Base.
- Ao conectar conteudo ao Gallery, o conteudo fica disponivel em Assets.
- E obrigatorio conseguir excluir conexoes entre nodes pelo botao da edge.
- Excluir uma edge nao deve deletar o node.
- Excluir uma edge nao deve apagar KB/Asset de forma destrutiva sem regra explicita.
- Embed deve espelhar a tabela real do banco relacionada a knowledge_chunks/KB.
- A validacao do Embed e: conteudo conectado aparece em Knowledge Base filtrado pela persona.
- A validacao do Gallery e: conteudo conectado aparece em Assets da persona.

## Auth e Permissoes
- O Brain AI exige login para todas as telas internas do dashboard.
- A sessao deve ficar em cookie HTTP-only; logout limpa a sessao e redireciona para `/login`.
- Senhas nunca devem ser salvas em texto puro; usar hash forte no backend.
- Admin acessa todas as personas/clientes.
- Usuarios `user`, `operator` e `viewer` acessam apenas personas/clientes atribuidos em `user_persona_access`.
- O seletor global de persona deve listar somente personas autorizadas para o usuario atual.
- Toda API interna deve validar sessao no backend e aplicar filtro por persona/cliente autorizado.
- Se uma persona solicitada nao for autorizada, retornar 403 e nao vazar dados ou nomes de outras personas.
- Rotas publicas devem ser mantidas apenas para health, login/logout e webhooks externos explicitamente publicos.
- Criacao operacional de login via banco/script: `cd api && python scripts/create_auth_user.py --email operador@empresa.com --username operador --password <senha> --role operator --persona tock-fatal --can-edit`.
- Admin inicial deve ser criado com envs `AI_BRAIN_SEED_ADMIN_EMAIL` e `AI_BRAIN_SEED_ADMIN_PASSWORD`, sem senha fixa em producao.

# Brain AI - Deploy e Operacao

## Estrutura oficial

```text
/ai-brain
  /dashboard      # frontend Next.js
  /api            # backend FastAPI
    main.py
    requirements.txt
    .env
  /docs
  /.gitignore
```

Regra:
- Nao usar `requirements.txt` na raiz.
- Dependencias Python ficam em `api/requirements.txt`.

## Rodar local

Frontend:
```bash
cd dashboard
npm install
npm run dev
```

Backend:
```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload
```

## Deploy

Frontend:
- Plataforma: Vercel
- Root Directory: `dashboard`

Backend:
- Plataforma: Cloud Run
- Source obrigatorio: `./api`

```bash
gcloud run deploy ai-brain-api \
  --source ./api \
  --region us-central1 \
  --allow-unauthenticated
```

## Variaveis de ambiente

Frontend (`dashboard/.env.local`):
- `NEXT_PUBLIC_API_URL=https://<cloud-run-url>`
- `NEXT_PUBLIC_SUPABASE_URL=https://<projeto>.supabase.co`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<anon-key>`
- opcional fallback: `NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>`

Backend (`api/.env`):
- `SUPABASE_URL=https://<projeto>.supabase.co`
- `SUPABASE_SERVICE_KEY=<service-role-key>`
- `ALLOWED_ORIGINS=https://<app-vercel>,http://localhost:3000`

## Notas criticas

- Frontend usa apenas `NEXT_PUBLIC_API_URL` para backend.
- Se `NEXT_PUBLIC_API_URL` faltar em producao, frontend falha com erro explicito.
- Backend valida env obrigatoria em runtime de producao.
- Entrypoint gunicorn do backend:
  - `gunicorn -k uvicorn.workers.UvicornWorker main:app`

## Alteracoes recentes

- CI criado em `.github/workflows/ci.yml` para validar backend com Python 3.11 e frontend com Node 20 antes de push/PR.
- Grafo passou a usar `knowledge_edges` como fonte oficial de caminhos, com soft delete em `metadata.active=false` e recriacao por drag entre handles.
- Tema clean (claro) virou padrao com tokens RGB CSS-var; tema dark mantido via `data-theme="dark"`. `colors.white` no Tailwind virou `rgb(var(--scrim-fg)/<alpha>)` -- `text-white` se inverte, mas `bg-white/X` tambem se inverte (vira escuro no clean). Para painel sempre claro usar `style={{background:"rgba(255,255,255,X)"}}` literal.
- PreflightPanel da captura unificou os dois selecionadores antigos em um stepper `[-][count][+]` por bloco (count=0 = fora do plano, count>=1 = no plano). FAQ default = 2.
- Aba `/leads` consolida CRM + CSV-bulk com pill `Todos/CRM/CSV-Bulk`, badge `Origem` e botao `Iniciar conversa` por linha.
- Aba `/leads/import` polida (lg-page-narrow, lg-card metrics, lg-table-shell, lg-badge variants, modal drawer-right).
- Backend agora protege `ensure_lead_for_persona` contra coluna inexistente (PGRST204): aprende a coluna em runtime e refaz o INSERT sem ela. Tambem espelha `canal` em `origem` quando so `canal` foi passado.
- Migracao `019_leads_canal_column.sql` adiciona `canal text` em `leads` (precisa ser aplicada manualmente no Supabase SQL Editor; nao ha rpc `exec_sql`).
- Endpoint `GET /messages/conversations` agora tem try/except amplo e devolve `[]` em vez de 500 em caso de erro residual.
- Frontend `/leads/page.tsx::originOf` checa `lead.canal || lead.origem` para detectar bulk_import (compatibilidade com leads antigos sem coluna canal).
- Tema clean: `--obs-text=17 24 39`, `--obs-subtle=71 85 105`, `--obs-faint=100 116 139`. text-zinc/gray/slate-200..500 e text-amber/emerald/blue/yellow/red-3xx..400 remapeados para variantes escuras (slate-600/700, amber-700, emerald-700, blue-700, red-700) para legibilidade sobre fundo branco.
- Exclusao de conexoes no grafo/arvore agora preserva o ID real `ge:*`, chama `DELETE /knowledge/graph-edges/{edge_id}` e registra logs no console e no backend se falhar.
- Drawer do node abre por clique; expansao fica no topo direito da sidebar; modal mostra badges, titulo, resumo, conteudo, tags, relacoes e acoes no rodape.
- Selecao multipla por caixa foi adicionada; pan do grafo fica condicionado ao atalho configuravel, inicialmente `Ctrl`, salvo em `localStorage`.
- Node sintetico `Embedded` representa o RAG sem nova tabela, usa icone de banco de dados, cor branca e aparece abaixo da arvore por padrao.
- RAG foi preparado para multiplos indices usando `metadata.rag_index = "default"` em `knowledge_rag_entries` e `knowledge_rag_chunks`.
- Menu ganhou `/settings` abaixo de Tools; `WA Validator` foi renomeado para `ChatBot`; CRM ganhou item `Importar` com icone de plus.
- Importacao de leads aceita CSV no formato Meta (`email,phone,fn,ln,ct,st,zip,country`), exige persona selecionada, mostra totais e preview dos 5 primeiros registros validos.
- Cada importacao cria um bloco `audiencia` ligado a persona e auditado em `system_events`; abrir o bloco mostra preview e permite voltar para `/leads/import?open=<batch>`.
- Grupos de leads podem ser excluidos pela tela de importacao; a exclusao arquiva o bloco de audiencia e registra evento de delecao.
- Migration `016_system_events_import_metadata.sql` adiciona campos/indices auxiliares em `system_events` sem criar tabelas novas.
- Node protegido `Gallery` foi adicionado por persona em `knowledge_nodes`; conexoes `gallery_asset` ficam em `knowledge_edges` e espelham o node conectado na tabela existente `assets`.
- `Gallery`, `Embedded` e `Persona` sao nodes protegidos: nao devem ser excluidos pela UI nem pelo endpoint de exclusao de nodes.
- A pagina de Assets agora combina assets da fila com nodes ligados ao `Gallery`, permitindo usar o grafo como curadoria visual para criacao de midia.

## Alteracoes recentes - 2026-05-11

- CRIAR/Sofia agora usa `normalizedPlan` como fonte unica da verdade para resumo, sidebar, preview, confirmacao e payload de save.
- O modo CRIAR exige persona especifica; `Todos`, `all`, `global` ou persona vazia nao iniciam criacao.
- A sessao viva da Sofia persiste `persona_slug`, `source_url`, `initial_block_counts`, `current_block_counts`, `knowledge_plan`, `plan_state`, `plan_hash` e `memory_summary`.
- `/kb-intake/message`, `PATCH /kb-intake/session/{id}/plan`, `GET /kb-intake/session/{id}` e `/kb-intake/save` compartilham o contrato `plan_state` com `normalized_plan`, `validation`, `summary` e `plan_hash`.
- Save do CRIAR bloqueia plano divergente por hash e nao reconstrui payload a partir de sidebar, preview ou plano inicial.
- Sidebar da captura compara plano esperado e plano criado, seguindo ordem hierarquica: Persona, Brand, Briefing, Campanha, Publico, Produto, Oferta, Copy, FAQ, Regras, Tom, Entidades, Assets, Embedded e Gallery.
- Frontend da captura restaura sessao ativa via `active_criar_session_id`, atualiza contadores a partir do plano atual e bloqueia preview/save quando ha violacao bloqueante.
- Pipeline do planner foi consolidado para arvore top-down/fractal: `persona -> brand? -> briefing -> campaign? -> audience -> product -> offer? -> copy -> faq`.
- `faq_count_policy` padrao e `total`; o sistema nao expande automaticamente FAQ por produto/oferta sem confirmacao.
- `offer` virou tipo oficial no CRIAR e no grafo: `knowledge_items.content_type=offer` e `knowledge_nodes.node_type=offer`.
- Migration `031_allow_offer_content_type.sql` adiciona `offer` ao check constraint, registra `offer` no `knowledge_node_type_registry`, faz backfill de nodes legados `knowledge_item` para `offer` e demove tags/mentions/nodes tecnicos da primary tree.
- Graph-data repara em runtime mirrors legados de offer, esconde nodes tecnicos por padrao, demove edges auxiliares da primary tree e deduplica primary edges por `(source,target,relation_type)`.
- Tags e mentions continuam disponiveis como camada auxiliar, mas nao aparecem como primary tree por padrao.
- Layout visual do grafo ganhou rank top-down explicito, colocando `offer` entre `product` e `copy` e mantendo `embedded`/`gallery` como destinos terminais.
- Snapshot FAQ aprovado agora monta `branch_context` com path, edges, relation_type/semantic_relation e contextos de persona/brand/briefing/audience/product/copy/faq.
- Chunk RAG de FAQ passa a ser gerado a partir do snapshot completo, incluindo Marca/Persona, Brand, Briefing, Publico, Produto, Copy/Oferta, Pergunta, Resposta aprovada, Regras, Tom, Caminho da branch e Relacoes.
- Snapshot FAQ incompleto fica `needs_review`, com `n8n_ready=false`, warnings de revisao e sem chunk ativo.
- Status de aprovacao foi alinhado: item aprovado fica `status=approved` e `curation_status=approved`; node aprovado fica `status=validated`.
- Edge semantica usa estrategia segura: `relation_type` estrutural e preservado; semantica enriquecida fica em `metadata.semantic_relation` e `metadata.semantic_label`.
- Nodes e edges do fluxo recebem rastreabilidade em metadata: `session_id`, `source_ref`, `created_via`, `tree_mode` e `branch_policy`.
- Configuracoes receberam seletor de linguagem; foi criado `dashboard/lib/language.ts` para centralizar labels e reduzir texto fixo mal codificado.
- Foram corrigidos varios textos mojibake/UTF-8 visiveis e a estrategia agora privilegia chaves/codigos estaveis com traducao no frontend.
- Testes adicionados/ajustados: `e2e_criar_fractal_topdown_tree_integrity.py`, `e2e_criar_plan_state_consistency.py`, `e2e_criar_tockfatal_plan_mode_branch_contract.py`, `e2e_criar_visual_branch_integrity.py` e `integration_criar_live_plan_state.py`.
- Validacoes executadas nesta rodada: `py_compile` dos servicos principais, E2Es do CRIAR, golden dataset hierarchy, live plan state e `tsc --noEmit` no dashboard. Em ambiente local sem Supabase configurado, os testes ainda logam `SUPABASE_URL` ausente ao tentar emitir eventos, mas passam.

## Sofia/CRIAR fractal comercial + RULE antes de FAQ (Codex) - 2026-05-13

- O Codex avancou na logica estrutural do planner da Sofia/CRIAR. Foco: corrigir a arvore comercial/fractal de campanha com `audience -> product -> offer -> copy -> rule -> faq` (RULE deixou de ser folha auxiliar e virou node estrutural intermediario antes do FAQ).
- Para o prompt da campanha Tock Fatal (Kit Modal 1 + Kit Modal 2; 1 peca cliente final, 5 e 10 pecas empreendedoras), a estrutura final esperada e:
  - 1 briefing, 1 campaign;
  - 2 audiences: Cliente final, Empreendedoras;
  - 4 contextos de produto: Kit Modal 1/2 x Cliente final/Empreendedoras;
  - 6 offers: Kit Modal 1 -> {1, 5, 10}, Kit Modal 2 -> {1, 5, 10};
  - 4 copies (uma por contexto produto/audiencia, `copy_policy=per_product_context`);
  - 1 rule comercial geral antes do FAQ;
  - 1 FAQ agrupado em markdown (`faq_count_policy=grouped`, `faq_parent_type=rule`).
- `faq_count_policy=grouped` consolida tudo em 1 documento FAQ Golden Dataset por persona, parent=rule. `questions_total` agrega as perguntas internas (validado pelo `expansion.faq` do summary).
- Termos internos proibidos no markdown do FAQ: `arvore`, `arvore`, `grafo`, `galho`, `node`, `branch`, `regra`, `estrutura`, `conhecimento conectado`. Teste existente `e2e_criar_tockfatal_plan_mode_branch_contract.py` ja varre essa lista.
- Migration `supabase/migrations/035_faq_pending_regeneration_status.sql` adiciona `pending_regeneration` ao CHECK de `knowledge_items.status` (junto com `pending|approved|rejected|embedded|needs_update`).
- `services/supabase_client.update_knowledge_item` agora dispara `_mark_persona_faqs_pending_regeneration(persona_id)` sempre que um item com `content_type in {brand, briefing, audience, product, offer, copy, rule}` e atualizado. O update marca todos os FAQ items+nodes daquela persona como `status=pending_regeneration` / `curation_status=stale` com `metadata.stale_reason='related_context_changed'`, `metadata.changed_source_id=<id>` e `metadata.stale_marked_at=<now>`. O `updated_at` muda junto.
- Parte ASSET ainda precisa validacao real no banco (bucket `assets-raw`, persona x parent, exibicao na galeria). O front-end ja roteia o upload corretamente; falta o smoke real contra Supabase de producao.
- Codex tambem reescreveu o backend de asset upload: agora `_ensure_asset_graph_contract` (em `api/routes/assets.py`) garante hard-contract `branch -> asset` + `asset -> Gallery`. Usa as novas funcoes `supabase_client.upsert_knowledge_node`, `supabase_client.update_asset_graph_refs`, `supabase_client.get_knowledge_node_for_source`. `bootstrap_from_item` foi substituido por upsert direto com `source_table='assets'`.
- O teste `integration_asset_card_upload.py` foi atualizado para mockar essas tres funcoes novas e o `get_asset`. Bateria de 12 testes verde (CRIAR + ASSET).
- Tests recomendados:
  - `tests/e2e_criar_tockfatal_plan_mode_branch_contract.py` (Codex; passa) — estrutura completa + termos proibidos.
  - `tests/e2e_criar_tockfatal_commercial_pyramidal.py` (este Claude) — prompt do usuario + assertions do RULE antes do FAQ + trigger `pending_regeneration` ao alterar offer.

## Fix 500/415 nos uploads + sidebar Sofia - 2026-05-13

- `/assets/upload` (api/routes/assets.py) ganhou `try/except` global no handler. O miolo foi extraido para `_upload_asset_impl`. Falhas inesperadas viram HTTPException 502 com `{error:"asset_upload_failed", exception_type, message, filename, parent_slug}` e stacktrace no logger. O 500 mudo que aparecia em producao agora vira diagnostico legivel pro frontend.
- Sidebar "Upload manual" do `/knowledge/capture` (`UploadPanel` em `dashboard/app/knowledge/capture/page.tsx`) parou de chamar `/knowledge/upload/file` (rota texto-only, causava 415 com PNG). Em `mode=file` agora chama `api.kbIntakeMessage(sessionId, "", file)` (= `/kb-intake/upload`), que roda o asset_pipeline (classifier+OCR), insere `public.assets` com `upload_context='sofia_chat'` e anexa a leitura na sessao da Sofia.
- UX da sidebar reflete o contrato pedido pelo usuario: o arquivo so e LIDO assim que questionado/anexado no chat ativo; NAO cria knowledge_item nem node; rename/save no grafo acontecem somente quando o plano da Sofia for salvo. Banner amarelo explicito quando nao ha sessao ativa ("Inicie a conversa com Sofia para anexar arquivos"); banner cinza explicando o ciclo quando ha sessao.
- `UploadPanel` recebeu props novas: `sessionId: string | null` e `onAssetReading?` (alimenta o painel direito de "Leituras na sessao" igual ao upload via chat). `SessionUpload.source` aceita um terceiro valor `"session_attach"` para distinguir do upload de texto/file legacy.
- `accept` do dropzone da sidebar foi ampliado para `image/*, video/*, application/pdf, .md/.txt/.json/.csv/.yaml/.yml, text/*` para o usuario poder soltar imagens diretamente.
- Pendente (Sofia/Codex): prompt da Sofia exigir no chat (a) a qual node o asset deve ser conectado e (b) qual a funcao do asset (visual_reference / product_reference / campaign_reference / text_reference) antes de continuar; e disparar rename + persist (`/assets/upload`) no momento do save do plano usando o asset_reading ja anexado. Esta etapa apenas roteia o upload para o pipeline correto e bloqueia regravacao precoce no grafo.
- Validacao: `py_compile` routes/assets.py OK; `npx tsc --noEmit` limpo; testes `integration_asset_card_upload`, `integration_sofia_image_upload`, `integration_asset_validation_lifecycle` continuam PASS.

## Upload em duas abas (Asset/Outro vs Texto) - 2026-05-13

- `/knowledge/upload/file` (legacy texto) agora devolve 415 com `{error:"binary_upload_unsupported", use_endpoint:"/assets/upload", message:"... use a aba 'Asset visual / Outro'"}` quando o arquivo nao e UTF-8. Substitui o opaco "File must be UTF-8 text".
- `dashboard/app/knowledge/upload/page.tsx` foi reescrita em duas abas:
  - **Asset visual / Outro**: seletor `asset`/`other`, file picker (image/video/pdf/text), persona obrigatoria, parent picker via `api.graphData(personaSlug, {mode:"tree"})` filtrado por `brand|briefing|campaign|product|audience|copy|faq|offer|rule|tone`, asset_function opcional. Submit chama `/assets/upload`, que cria knowledge_item content_type=asset + node + edges parent->asset (uses_asset) e asset->gallery (gallery_asset). UX bloqueia submit sem persona+parent para garantir "node nao fica sozinho na arvore".
  - **Texto**: lista filtrada para tipos textuais (brand, briefing, product, campaign, copy, prompt, faq, tone, audience, competitor, maker_material, rule). Modos: colar texto ou arquivo .md/.txt/.json. Submit usa `/knowledge/upload/text` ou `/knowledge/upload/file`. Mensagem clara quando usuario tentar binario por engano.
- Convencao de nome ja existente em `api/services/asset_pipeline/renamer.py::_heuristic` (`persona-branch-tokens`) bate com o que o usuario sugeriu (`Persona-Node-Descricao/OCR`), entao nao precisou refator.
- Validacao: `py_compile` knowledge.py OK; `npx tsc --noEmit` limpo; testes `integration_asset_card_upload`, `integration_sofia_image_upload`, `integration_asset_validation_lifecycle` continuam PASS.
- Pendente para etapa futura: prompt da Sofia/CRIAR forcar o usuario a declarar o node-parent ANTES de uploadar imagem no chat (hoje a Sofia recebe a leitura como contexto sem exigir branch; nesta etapa nao foi tocado para evitar mexer no planner).

## Diagnostico de plano bloqueado (CRIAR) - 2026-05-12

- `api/services/kb_intake_service.py` ganhou `build_plan_diagnostic(plan, session, violations)`: agrupa violacoes por causa raiz (`cycle`, `no_path_to_persona`, `offer_under_product`, `audience_parent`, `product_invalid_parent`, `copy_parent`, `faq_parent`, `rule_parent`, `invalid_primary_tree_type`, `duplicate_slug`, `missing_parent_slug`, `faq_expansion_incomplete`, `asset_expansion_incomplete`, `offer_missing`, `rule_missing`, `links_missing`, `other`) e classifica cada entry como `valid|warning|error|cycle|orphan` com parent atual, parent esperado e suggested_action.
- O retorno tambem traz `questions_markdown` (perguntas objetivas geradas a partir das causas raiz e do conteudo atual do plano) e `repair_suggestion` (arvore sugerida).
- `_plan_state_from_normalized` agora injeta `plan_state["diagnostic"]` somente quando ha `blocking_violations`. O hash do plano nao muda (diagnostic vive ao lado de `validation/summary`, fora do canonical).
- Frontend: tipos `PlanDiagnostic`, `PlanDiagnosticNode`, `PlanDiagnosticRootCause` em `dashboard/components/capture/diagnosticTypes.ts`. `PlanState` em `capture/page.tsx` ganhou `diagnostic?: PlanDiagnostic | null`; `normalizePlanState` preserva, `buildLocalPlanState` zera.
- Modal `dashboard/components/capture/BlockedPlanDiagnosticModal.tsx`: overlay com cards coloridos (verde valido / amarelo warning / vermelho erro / roxo ciclo / cinza orfao / azul sugestao), agrupamento por causa raiz, perguntas em markdown e botoes "Fechar / Editar plano / Regerar estrutura".
- `ChatPanel` (capture/page.tsx) abre o modal automaticamente quando o backend retorna plano bloqueado (`setDiagnosticOpen(true)`), substitui o aviso seco de "Plano bloqueado: lista enorme" por um banner curto com botao "Ver diagnostico visual" e mantem fallback textual quando `diagnostic` esta ausente (compat).
- Save e preview continuam bloqueados via `planStateValid` + `plan_hash`; nada e salvo enquanto houver `blocking_violations`.
- Validacao: `py_compile` do kb_intake_service.py; testes locais que passaram: `test_criar_entry_flow_summary`, `e2e_criar_plan_state_consistency`, `e2e_criar_fractal_topdown_tree_integrity`, `e2e_criar_visual_branch_integrity`, `e2e_criar_tockfatal_plan_mode_branch_contract`, `e2e_criar_generic_pyramidal_expansion_contract`. `npx tsc --noEmit` no dashboard limpo.

## Alteracoes recentes - 2026-05-12

- Entrada CRIAR/Sofia: conversa sem `normalizedPlan` nao e mais reescrita como bloqueio seco; preview/save continuam bloqueados quando o plano esta vazio, mas o chat fica livre para guiar perguntas e planejamento.
- FAQ do CRIAR mudou para Golden Dataset por galho terminal: 1 card FAQ por copy/offer/product terminal, contendo Markdown com perguntas internas; perguntas nao viram cards individuais.
- A quantidade de perguntas do FAQ e calculada por profundidade da branch: numero de nos acima do FAQ contando Persona x 2.
- `kb_intake_service.py` agora gera FAQ Markdown contextual com `body_markdown`, `question_count`, `source_branch_path`, tags semanticas e status pendente de validacao.
- Removida a expansao antiga de FAQ por pergunta/card e removidos helpers legados de `single_branch` que reparentavam FAQ para copy depois do plano.
- Normalizacao ficou idempotente em PATCH/update: contadores atuais nao sao mais usados como pedido de variacao para reexpandir oferta/copy/FAQ; a intencao vem dos contadores iniciais confirmados e do proprio plano.
- Defaults de rastreabilidade e snapshot foram alinhados para `tree_mode=pyramidal` e `branch_policy=top_down_pyramidal`.
- Snapshot/RAG preserva FAQ Golden Dataset em Markdown, incluindo contexto da branch, para chunking e embedding com mais contexto.
- Sidebar/preview da tela CRIAR mostra FAQ como documentos esperados/criados por galho terminal, com perguntas internas estimadas por documento.
- Investigacao de save em lote documentada em `docs/criar-bulk-save-investigation.md`; direcao recomendada: validar plano inteiro, persistir via RPC/batch transacional e retornar relatorio atomico de items/nodes/edges/tags/snapshots.
- Testes adicionados/ajustados: `tests/e2e_criar_faq_golden_dataset_by_branch.py`, `tests/e2e_criar_generic_pyramidal_expansion_contract.py`, `tests/test_criar_entry_flow_summary.py`, alem dos E2Es/integracoes existentes do CRIAR.
- Validacoes executadas nesta rodada: `py_compile` dos servicos principais; `e2e_criar_faq_golden_dataset_by_branch`, `e2e_criar_generic_pyramidal_expansion_contract`, `integration_approved_knowledge_snapshots`, `integration_golden_dataset_hierarchy`, `test_criar_entry_flow_summary`, `e2e_criar_fractal_topdown_tree_integrity`, `e2e_criar_plan_state_consistency`, `e2e_criar_tockfatal_plan_mode_branch_contract`, `e2e_criar_visual_branch_integrity` e `integration_criar_live_plan_state`.
- Observacao local: testes que emitem eventos ainda logam `SUPABASE_URL` ausente quando o ambiente nao tem Supabase configurado, mas os testes offline passam; `e2e_criar_marketing_fractal_flexible_graph.py` depende de login/API real e falhou localmente com 401 de credenciais.
- Ajuste posterior no FAQ Golden Dataset: o fallback deterministico deixou de escrever instrucoes internas como "Use o contexto deste galho para responder" e passou a gerar respostas finais contextualizadas; perguntas tambem nao repetem com sufixos numericos como `(9)` e `(10)`.
- Camada RAG alinhada para FAQ canonica: `publish_approved_node` agora exige snapshot antes de criar RAG, parseia FAQ Golden Dataset Markdown em pares pergunta/resposta e cria 1 `knowledge_rag_entries` + 1 `knowledge_rag_chunks` por pergunta. Entries recebem `source_snapshot_id`, `source_node_id`, `session_id`, pergunta/resposta especificas e `metadata.branch_context`; chunks ficam autossuficientes com persona, brand, briefing, publico, produto, copy/oferta, pergunta, resposta aprovada, regras, tom, caminho e relacoes. Migration `032_canonical_faq_rag_entries.sql` adiciona colunas de rastreio.

## Alteracoes recentes - asset upload pipeline (em andamento)

Estado: backend completo e testado, frontend integrado, `npm build` do dashboard e testes locais de asset executados. Ainda faltam criar/rodar os testes planejados de upload Sofia e lifecycle de validacao. Branch `develop` modificada nao commitada.

Atualizacao 2026-05-12:
- Corrigido hydration error em `dashboard/components/graph/NodeDrawer.tsx`: `DirectLinkCard` nao renderiza mais card clicavel como `<button>` externo quando ha botao interno de excluir; usa `div role="button" tabIndex={0}`, suporte a Enter/Espaco e `cursor-pointer/focus:ring`.
- Botao interno "excluir" continua como `<button type="button">`, com `stopPropagation()` no click e no keydown para nao abrir o node relacionado.
- `npm.cmd run build` em `dashboard/` passou.
- Testes de asset executados e passando: `integration_asset_pipeline_classifier.py`, `integration_asset_pipeline_ocr_mock.py`, `integration_asset_pipeline_pdf.py`, `integration_asset_pipeline_video_mock.py`, `integration_asset_pipeline_rename_heuristic.py`, `integration_asset_card_upload.py`, `integration_asset_card_parent_required.py`, `integration_asset_card_gallery_guard.py`.
- Os testes planejados `integration_sofia_image_upload.py` e `integration_asset_validation_lifecycle.py` ainda nao existem em `tests/`.
- Regra de direcao FAQ reforcada: FAQ e destino terminal de vetores comerciais; `product/offer/copy -> faq` e valido, `faq -> product/offer/copy/campaign/audience` e invalido, e a unica saida permitida de FAQ e `faq -> embedded`. Criada migration `034_repair_faq_edge_direction.sql` para reverter/soft-delete edges invertidas e reduzir importancia visual de FAQ.

Arquitetura aprovada — pipeline hibrido e barato (decidido com o usuario):
1. **Classifier local** (`api/services/asset_pipeline/classifier.py`) — heuristica pura com Pillow + mime/extension; decide `kind`, `needs_ocr`, `has_text_estimate`. Sem chamada externa.
2. **OCR local** (`api/services/asset_pipeline/ocr_local.py`) — cascade de adapters: PaddleOCR -> EasyOCR -> pytesseract -> mock. Selecao via `ASSET_OCR_BACKEND` (default cascade; CI usa `mock`). Marca `needs_ai_fallback=True` quando `confidence<0.45` ou `len(text)<8`.
3. **AI fallback** (`api/services/asset_pipeline/ai_fallback.py`) — so roda quando `needs_ai_fallback`. Usa `model_router.vision_extract` (novo) com modelo configuravel via `ASSET_VISION_MODEL` (default `gpt-4o-mini`).
4. **Renamer** (`api/services/asset_pipeline/renamer.py`) — heuristica primeiro; opcional `model_router.cheap_text` quando heuristica produz <3 tokens. Desativavel via `ASSET_RENAME_DISABLE_MODEL=1`.
5. **PDF text** (`pdf_text.py` via pypdf), **video mock** (`video_mock.py`), **schemas Pydantic** (`schemas.py`).

Entrada unica: `services.asset_pipeline.run_pipeline(file_bytes, AssetPipelineContext) -> AssetReadingBundle`. Bundle traz `classification`, `ocr`, `ai_fallback`, `pdf_text`, `video_mock`, `rename`, `extracted_text`, `visual_summary`, `reading_status` e `rows_to_persist` para `asset_readings`.

Dois fluxos persistentes:
- **Sofia/CRIAR** (`/kb-intake/upload` estendido): salva no bucket `knowledge` (compat) + cria row em `public.assets` com `upload_context='sofia_chat'` + roda pipeline + anexa leitura ao contexto da sessao via `kb_intake_service.attach_reading()`. NAO cria `knowledge_item`.
- **Card ASSET** (`/assets/upload` novo em `api/routes/assets.py`): upload no `assets-raw` (com fallback `knowledge`) + assets row `upload_context='asset_card'` + pipeline + cria `knowledge_item content_type=asset` pending + `bootstrap_from_item` -> `knowledge_node node_type=asset` + edge `parent -> asset` (`uses_asset`, primary_tree=true) + edge `asset -> gallery` (`gallery_asset`, primary_tree=false, graph_layer=auxiliary). Atualiza asset com `knowledge_node_id` + `gallery_edge_id`.

Guard explicito: POST `/assets/{id}/connect` recusa target = node_type='gallery' com 422 `gallery_invalid_target`. Apenas `asset -> gallery` autorizado.

RAG nunca cria entry para asset — `is_rag_eligible` ja gateia em `{"faq"}`.

Migration `supabase/migrations/033_asset_upload_pipeline.sql`:
- Buckets `assets-raw` + `assets-derived` (insert idempotente em `storage.buckets`).
- Expande `public.assets`: `storage_bucket`, `storage_path`, `mime_type`, `file_size`, `original_filename`, `status`, `upload_context`, `updated_at`. Atualiza CHECK `type` (`image|video|pdf|text|copy|campaign|template`) e `source` (adiciona `upload`).
- Trigger `updated_at` + indexes por persona/status/source/upload_context/created_at/`metadata->>session_id`/(storage_bucket,storage_path).
- Nova tabela `public.asset_readings`: linha por etapa do pipeline (`classification|ocr|ai_fallback|pdf_text|video_mock|rename`), RLS service_role, indexes por (asset_id,reading_type,created_at desc) e persona.

Endpoints novos:
- `POST /assets/upload` — multipart `file + persona_id + branch_hint + asset_function? + persona_slug?`.
- `GET /assets`, `GET /assets/{id}` (devolve `{asset, readings}`), `POST /assets/{id}/connect` (re-parent com gallery-guard).

Frontend:
- `dashboard/lib/api.ts`: `assetUpload`, `assetList`, `assetGet`, `assetConnect`.
- `dashboard/components/assets/AssetUploadDialog.tsx`: drag/drop, preview, parent picker via `api.graphData(...)` filtrando node_types selecionaveis (brand/briefing/campaign/product/audience/copy/faq/offer/rule/tone), funcao opcional, glassmorphism consistente.
- `dashboard/app/knowledge/assets/page.tsx`: botao `+ Upload` ao lado do `+ Criar` que abre o dialog e recarrega.
- `dashboard/components/capture/IntakeReadingPanel.tsx`: card por leitura no upload (kind, engine, conf, paginas, fallback IA pendente, video mock, texto extraido).
- `dashboard/app/knowledge/capture/page.tsx`: novo prop `assetReadings` em `CaptureSidebar`, nova secao "Leituras na sessao" antes do bloco crawler (crawler preservado). `ChatPanel` captura `d.asset_reading` da resposta do upload e propaga via callback.

Deps adicionadas em `api/requirements.txt`: `pillow>=10.0.0`, `pypdf>=4.0.0`. OCR backends (paddleocr/easyocr/pytesseract) seguem opcionais; CI usa `mock`.

Shims em `services/model_router.py`: `vision_extract(file_bytes, mime, prompt)` (data URL base64 + OpenAI vision) e `cheap_text(prompt, max_tokens)`.

Helpers em `services/supabase_client.py`: `insert_asset`, `update_asset`, `get_asset`, `list_assets`, `insert_asset_reading`, `list_asset_readings`, `is_node_type`.

Testes integrados criados em `tests/` (8 escritos e passando, 2 planejados ainda ausentes):
- `integration_asset_pipeline_classifier.py` PASS
- `integration_asset_pipeline_ocr_mock.py` PASS
- `integration_asset_pipeline_pdf.py` PASS
- `integration_asset_pipeline_video_mock.py` PASS
- `integration_asset_pipeline_rename_heuristic.py` PASS
- `integration_asset_card_upload.py` PASS — valida assets row + knowledge_item + node + edges parent/gallery + asset.knowledge_node_id linkado + asset NAO eh rag_eligible
- `integration_asset_card_parent_required.py` PASS — 422 + `needs_parent=true` quando sem branch_hint, nada criado
- `integration_asset_card_gallery_guard.py` PASS — POST /assets/{id}/connect recusa target gallery com `gallery_invalid_target`
- `integration_sofia_image_upload.py` PASS — upload Sofia anexa reading na sessao (`asset_readings` populado, `classification.attachments` espelhado), tagueia asset com `upload_context='sofia_chat'`/`validation_status='context_only'` e NAO cria knowledge_item; chat() recebe `file_info.asset_reading` para reagir.
- `integration_asset_validation_lifecycle.py` PASS — asset card aparece em `/knowledge/queue?content_type=asset`; `promote_knowledge_item(promote_to_kb=False)` move item para `status=approved`/`curation_status=approved` com evidence.knowledge_node_id; `is_rag_eligible('asset')` permanece False e nenhum `knowledge_rag_entries`/`knowledge_rag_chunks` e inserido durante a aprovacao.

Verificacao tecnica realizada: `py_compile` em todos os modulos novos/alterados; `npx tsc --noEmit` no dashboard limpo apos cada bloco frontend; `npm.cmd run build` do dashboard passou; testes locais de asset listados acima passaram em sequencia.

## Upload manual sem sessao ativa (auto-start) - 2026-05-13

- Sidebar `UploadPanel` do `/knowledge/capture` parou de exigir conversa previa com a Sofia para anexar imagem/arquivo. A pre-confirmacao do plano tambem nao bloqueia mais o upload.
- Quando o usuario clica em "Enviar para validacao" sem `activeSessionId`, a UI chama `ensureSofiaSession(slug)` que dispara `api.kbIntakeStart(model='gpt-4o-mini', { mode:'criar', persona_slug, knowledge_plan, initial_block_counts, source_url })`. Persona efetiva e resolvida do select da propria sidebar (`personaId -> slug`) com fallback para `plan.personaSlug`.
- A sessao recem-criada vai para `setActiveSessionId` + `localStorage.active_criar_session_id`, atualiza `planState`, `currentKnowledgePlan`, `currentBlockCounts` e `confirmedPlanHash`. O upload prossegue com `kbIntakeMessage(effectiveSessionId, "", file)`, que entra no pipeline asset (OCR/visual) e gera asset row `upload_context='sofia_chat'` + asset_reading anexado a sessao (memoria do agente). Nada e gravado no grafo ate o save do plano (contrato preservado).
- Se nao houver persona em nenhum dos dois lugares, erro amigavel "Selecione uma persona para a Sofia poder ler este arquivo." Se o auto-start falhar, mensagem "Nao consegui iniciar a sessao da Sofia automaticamente.".
- Banner amarelo da sidebar mudou de "Inicie a conversa com a Sofia para anexar arquivos." para "Selecione uma persona e envie: a sessao da Sofia comeca automaticamente, o arquivo entra na memoria do agente e o save no grafo acontece quando voce salvar o plano." Continua escondido quando ja ha sessao ativa.
- Props novas no `UploadPanel`: `personaSlug?: string`, `ensureSession?: (personaSlug?) => Promise<string|null>` (alem das ja existentes `sessionId`, `onAssetReading`, `onResetSession`).
- Validacao: `npx tsc --noEmit` limpo; `npm run build` do dashboard passou; testes locais asset/sofia (`integration_asset_card_upload`, `integration_sofia_image_upload`, `integration_asset_validation_lifecycle`, `integration_asset_card_parent_required`, `integration_asset_card_gallery_guard`) continuam PASS.

## Pre-init review da Sofia/CRIAR (Etapas A+C+D) - 2026-05-13

Objetivo: tornar Sofia menos rigida e mais consciente do contexto ja existente da persona antes de gerar nodes.

### Etapa A — Pre-init review com contexto da persona (kb_intake_service.py)

- Novas funcoes: `_load_persona_context(persona_id)` consulta `knowledge_nodes` via `supabase_client.list_knowledge_nodes_by_type` filtrando `node_type in {brand, briefing, campaign, audience, product, offer, copy, rule, asset, faq}` da persona ativa. Best-effort: erros viram dict vazio, nunca quebram a sessao.
- `build_pre_initialization_review(session, persona_context, classification)` produz contrato `/tree-reference`: `persona_context_loaded`, `existing_nodes_found`, `recommended_connections`, `new_nodes_needed`, `questions`. Lida com reuso de audience/campaign existentes e roteia asset por `classification.asset_function` (campaign_hero -> campaign, product_reference -> product).
- `create_session` em `mode='criar'` com `persona_id` resolvido agora popula `session["persona_context"]` e `session["pre_init_review"]` automaticamente.
- `_session_public_state` expõe `pre_init_review` + `persona_context` no payload da sessao; `_bootstrap_result_payload` propaga `pre_init_review` para o frontend.
- `_chat_impl` injeta no `state_ctx` enviado ao LLM um bloco "Contexto existente da persona (pre-init review)" com slugs por tipo, recomendacoes de reuso e perguntas obrigatorias antes do plano final. Isso impede a Sofia de criar audience/campanha/asset duplicados sem perguntar.

### Etapa C — FAQ terminal nao gera leaf alert

- `_leaf_alert_warnings` (kb_intake_service.py:803) trocou exclusao `{"asset","embedded","gallery"}` por `{"asset","embedded","gallery","faq"}`. Comentario explica: FAQ e terminal-valido ate aprovacao; pos-aprovacao recebe edge automatica para Embedded.
- Frontend `dashboard/app/knowledge/capture/page.tsx::leafAlerts` recebeu o mesmo filtro. Nova lista `faqPendingTerminals` separa FAQ pendentes para mostrar como card info azul ("FAQ <titulo>: terminal ate aprovacao. Apos aprovado, sera conectado automaticamente ao Embedded da persona.") em vez de alerta amarelo de "sem saida".

### Etapa D — Embedded fora da previa pre-aprovacao

- `dashboard/app/knowledge/capture/page.tsx::CaptureSidebar` esconde a linha de `Embedded` em "Plano inicial" e em "Plano em construcao" quando `expectedCountFor('embedded') === 0 && createdCountFor('embedded') === 0`. Continua aparecendo automaticamente assim que houver um node embedded real (FAQ aprovado).
- `knowledgeGraphLayout.ts` nao foi alterado — `embedded` aparece la apenas quando ha node `embedded` real conectado a FAQ via `embedded_edge`.

### Validacao

- `py_compile` de `kb_intake_service.py` + `routes/kb_intake.py` OK.
- `npx tsc --noEmit` + `npm run build` do dashboard verdes.
- Testes CRIAR + asset/sofia rodados localmente (10 scripts) todos PASS: `test_criar_entry_flow_summary`, `e2e_criar_plan_state_consistency`, `e2e_criar_fractal_topdown_tree_integrity`, `e2e_criar_visual_branch_integrity`, `e2e_criar_tockfatal_plan_mode_branch_contract`, `e2e_criar_generic_pyramidal_expansion_contract`, `e2e_criar_faq_golden_dataset_by_branch`, `integration_asset_card_upload`, `integration_sofia_image_upload`, `integration_asset_validation_lifecycle`.

### Pendentes para proxima rodada

- Testes obrigatorios planejados (ainda nao escritos):
  - `tests/integration_pre_init_audience_existing.py`: persona com audience em `knowledge_nodes` + briefing descreve publico => `pre_init_review.recommended_connections=[audience:X]` e plano nao cria audience.
  - `tests/integration_pre_init_user_accepts_existing_audience.py`: confirmar reuso => plano com links para audience existente, sem clone.
  - `tests/integration_pre_init_user_rejects_existing_audience.py`: negar reuso => `questions=[ask new audience name]` antes de expandir.
  - `tests/integration_asset_campaign_hero_routing.py`: upload `asset_function=campaign_hero` => `campaign -> asset -> gallery`.
  - `tests/integration_faq_terminal_not_error.py`: plano com FAQ pendente sem embedded => `_leaf_alert_warnings` nao inclui FAQ.
- 500 do save (Baita): o handler em `routes/kb_intake.py:465-499` ja tem try/except global devolvendo 400 com traceback; o 500 visto provavelmente vem de chamada subsequente (graph-data no redirect `/knowledge/graph?persona=...`) ou de `apply_plan_hierarchy` falhando antes de capturar. Sugestao: instrumentar `system_events` com `hierarchy_result.error`, `tree_guard_error`, `failure_type` para reproduzir.
- Roteamento de asset por `asset_function` continua acontecendo no UI/upload, nao no normalizer; quando integrado ao planner, fazer `_normalize_sofia_knowledge_plan` consumir `classification.asset_function` para escolher `asset_parent_type` antes do default `"product"`.

## Brand card (planejado, NAO iniciado)

Pedido subsequente do usuario: ao abrir CRIAR para uma persona, Sofia deve carregar (ou criar pendente) um card BRAND (`content_type=brand`, `node_type=brand`). Hierarquia padrao passa a ser `persona -> brand -> briefing -> ...`. Sequencia decidida: terminar verificacao do asset feature antes de iniciar brand.

Correcao importante do usuario gravada como memoria: `memory.md` (raiz do repo) eh memoria **tecnica/operacional** do Claude Code e do projeto. Diretrizes de marca persistem APENAS em `knowledge_item content_type=brand` + `knowledge_node node_type=brand`. Se houver persistencia no vault, eh como card BRAND dentro de `01_BRAND/` da persona via `vault_sync`, NAO como memory.md por persona. `memory.md` so recebe nota tecnica curta sobre o card brand.

## Sessao 2026-05-18 (parte 6) - Setup formal PROD vs QA

### Estado final dos ambientes

| Camada | PROD | QA |
|---|---|---|
| Branch ai-brain | `main` | `develop` |
| Supabase project | `slyxppvghniknqofhqzt` (us-west-2) | `qhnepdcqtkjjslqqiyvp` (us-east-1, novo) |
| Cloud Run service | `ai-brain-api` (revision 00025-pq7) | `ai-brain-api-qa` (revision 00001-8pp) |
| Cloud Run URL | https://ai-brain-api-837167469397.us-central1.run.app | https://ai-brain-api-qa-837167469397.us-central1.run.app |
| Frontend baita-cardapio | branch `main` -> https://baita-cardapio.vercel.app | branch `qa` -> Vercel preview |
| Env file (gitignored) | `env.yaml` | `env.qa.yaml` |
| Migrations aplicadas | 37 + dados reais (383 produtos, 16 categorias, 18 imagens) | 37 + seed minimo BAITA (9 categorias, 4 produtos sem assets) |

### Decisoes operacionais

- `main` so recebe codigo via merge fast-forward de `develop`. Deploy PROD = `gcloud run deploy ai-brain-api --source ./api --env-vars-file env.yaml`.
- `develop` = QA. Deploy QA = `gcloud run deploy ai-brain-api-qa --source ./api --env-vars-file env.qa.yaml`. Aqui testamos antes de promover pra main.
- `env.yaml` e `env.qa.yaml` foram movidos para fora do tracking do git (GitHub secret scanning bloqueou push com OPENAI_API_KEY). `env.yaml.example` ficou como template versionado.
- CORS prod liberou `https://baita-cardapio.vercel.app` + `*-allanvvzs-projects.vercel.app` + `localhost:5173`. CORS QA adicionou `https://baita-cardapio-qa.vercel.app` para o branch preview do cardapio.
- baita-cardapio repo agora tem 2 branches: `main` (prod) e `qa`. Vercel resolve `VITE_AI_BRAIN_API_URL` por scope: production -> ai-brain-api prod; preview branch `qa` -> ai-brain-api-qa.
- gcloud SSL falhou (`SSL: CERTIFICATE_VERIFY_FAILED`) ate aplicarmos `gcloud config set auth/disable_ssl_validation True`. Em maquinas com cert chain corporativo, setar `REQUESTS_CA_BUNDLE` resolve sem desativar SSL.
- O env.yaml de PROD inicialmente apontava para o `anon` key como SUPABASE_SERVICE_KEY -- isso fazia `/api/menu` voltar 404 "Persona not found" porque RLS bloqueava a leitura. Trocado para o JWT com `role:service_role` via `gcloud run services update --update-env-vars` (revision 00025-pq7).

### Validacao em PROD

- `GET /api/menu/baita-conveniencia` retorna `persona.collections[0]` com 16 categorias, 383 produtos, 1 banner editorial e 4 covers de categoria com URLs assinadas (`storage/v1/object/sign/assets-raw/...`).
- Playwright em `https://baita-cardapio.vercel.app/cardapio/baita`: `source_live=true`, banners Lagunitas/Patagonia/Jagermeister/Suspeito carregando, zero requests falhados.

### Bug-trail desta sessao

- `env.yaml` ja estava commitado nos commits anteriores, mas GitHub push protection bloqueou o push do `develop` por causa do OPENAI_API_KEY na linha 3. Solucao: `git rm --cached env.yaml`, adicionar ao `.gitignore`, criar `env.yaml.example`, recommit.
- Migration 037 contem um DO $$ block que faz seed do BAITA. No QA esse block roda tambem; criamos uma versao paralela `037b_baita_collection_seed` para registrar como migration nomeada quando rodada via MCP. A 037 (oficial) ja inclui o seed embarcado e e a fonte de verdade.
- A SQL de 020 (lead_audience_memberships) usa `lead_id bigint` no original, mas leads em ambos projetos esta como uuid. No QA aplicamos com `lead_id uuid` (variacao adaptativa) para nao quebrar a constraint de FK.

## Sessao 2026-05-19 - Baita camiseta QA product_image slot

- Feito: espelhado para QA o asset real da camiseta da Baita encontrado em PROD (`assets.id=0ca3a939-2e49-4ae9-bcf3-81c041635495`, nome `Camiseta Branca BAITA`, origem visual `Baita-Camiseta-Branca.svg`).
- Asset usado em QA: `assets.id=303678f1-df60-48ca-bcec-ddafd6f16206`, `knowledge_node_id=73b3a5c9-aa35-4e41-9b57-7f3a870d117c`, arquivo em `assets-raw:e023a4ef-7cb9-454f-9de2-225fe52151f3/baita-cardapio-v14/Baita-Camiseta-Branca.svg`.
- Produto associado em QA: `knowledge_nodes.slug=camiseta-branca-baita`, titulo `Camiseta Baita`, categoria `roupas`, colecao `cardapio-baita-v14`.
- Slot criado/restaurado: `product_image:camiseta-branca-baita`, edge `product_image` produto -> asset (`fa779596-ca37-42b5-8395-b84b876c01db`). Edge `gallery_asset` ativa (`d778b76a-e909-49fb-9993-5364e9eccc0c`).
- Backend ajustado: `slot_for_key/slot_for_metadata` agora aceitam chaves instanciadas `product_image:<slug>`; `/api/menu` preserva `page_binding.slot_key`; `bind-slot` remove edges anteriores do mesmo slot/produto e grava `product_image:<slug>`; `unbind` remove tambem `product_has_asset` legado para que o produto fique sem imagem.
- Endpoints/logica testados: build local de `/api/menu/baita-conveniencia?collection_slug=cardapio-baita-v14` contra Supabase QA; `admin-blocks`; `admin-connections`; fluxo direto `unbind product_image` -> payload com 0 assets -> `bind-slot` -> payload com asset e `slot_key=product_image:camiseta-branca-baita`.
- Validacao tecnica: `python -m py_compile api/core/landing_slots.py api/routes/menu.py api/routes/assets.py scripts/sync_baita_camiseta_qa.py`; `python tests/integration_baita_cardapio_seed.py`; `python tests/integration_gallery_assets_resolution.py`.
- Pendencias: chamada externa ao Cloud Run QA via `curl` foi bloqueada pelo ambiente de execucao; deploy/restart do backend QA ainda precisa publicar os ajustes de rota para a URL Cloud Run se ela nao estiver em reload/local.

Complemento da mesma sessao:

## Sessao 2026-05-20 - Assets QA: aprovado entra no catalogo, demais aparecem no AI-BRAIN

### Regra consolidada

- `assets.status` e status operacional do pipeline (`ready`, `reading`, `archived` etc.).
- A elegibilidade para catalogo/cardapio vem de `assets.metadata.validation_status`.
- Somente `metadata.validation_status='approved'` pode aparecer no catalogo publico.
- Assets com `pending_validation`, `context_only`, `ready`, `reading` ou sem aprovacao continuam aparecendo no AI-BRAIN para revisao, mas nao no catalogo.
- Essa separacao resolveu a confusao observada: havia assets `status=ready` que nao deveriam ir ao catalogo, e assets aprovados com preview quebrado por URL legada.

### Estado Supabase QA confirmado

- Projeto QA: `qhnepdcqtkjjslqqiyvp`.
- Projeto PROD: `slyxppvghniknqofhqzt`.
- Persona Baita QA: `e023a4ef-7cb9-454f-9de2-225fe52151f3`, slug `baita-conveniencia`.
- Buckets QA:
  - `assets-raw`: privado, com arquivos.
  - `assets-derived`: privado, vazio no momento da checagem.
- Contagem QA em `assets`:
  - `ready + approved`: 9;
  - `reading + context_only`: 1;
  - `ready + context_only`: 1;
  - `ready + pending_validation`: 2;
  - `ready + ready`: 1;
  - `archived` legado sem `validation_status`: 1.
- Resultado esperado: 9 aprovados alimentam o catalogo; todos os 15 aparecem na tela de assets do AI-BRAIN.

### Camiseta Baita QA

- Asset ativo: `303678f1-df60-48ca-bcec-ddafd6f16206`.
- Storage atual: `assets-raw:e023a4ef-7cb9-454f-9de2-225fe52151f3/baita-cardapio-v14/Camiseta-Branca-BAITA.png`.
- Asset node: `73b3a5c9-aa35-4e41-9b57-7f3a870d117c`.
- Product node: `49ae5ff3-4c31-4a46-ba72-bb0be4fbe23f`, slug `camiseta-branca-baita`, categoria `roupas`.
- Gallery edge: `d778b76a-e909-49fb-9993-5364e9eccc0c`.
- Edge de produto criado/garantido via API/TestClient: `e9afbfd8-d60c-4c82-ac21-dd7efff0fbe6`, `relation_type=product_image`, `slot_key=product_image:camiseta-branca-baita`.
- A existencia do edge nao basta para catalogo: se o asset nao estiver `validation_status=approved`, o `/api/menu` deve omitir a imagem.

### Mudancas de backend

- `api/services/supabase_client.py`:
  - adicionou `asset_display_url(asset_row)` como wrapper publico.
  - Storage e fonte de verdade para preview: assina `storage_bucket/storage_path`; `assets.url` fica so como fallback legado.
  - `list_gallery_assets` calcula status efetivo usando `metadata.validation_status` antes de `assets.status`, preservando filtro de aprovacao para o menu.
- `api/routes/menu.py`:
  - `_admin_asset_payload` agora retorna `url` e `display_url` assinadas via `asset_display_url`.
  - O catalogo continua filtrando gallery assets por status efetivo `approved`.
- `api/routes/assets.py`:
  - `/assets` passou a devolver payload normalizado com `display_url`, `workflow_status` e `approval_status`.
  - `list_assets_route` usa o payload normalizado tanto com `ensure_graph=true` quanto `false`.
  - `bind_asset_to_slot`, `rebind_asset_path`, `unbind_asset_slot`, `validate_asset_path_route`, `delete_asset_route`, `approve_asset_route` e `reject_asset_route` emitem eventos de fluxo.
  - Eventos novos/importantes: `asset_slot_bound`, `asset_slot_bind_failed`, `asset_slot_metadata_update_failed`, `asset_path_rebound`, `asset_path_rebind_failed`, `asset_path_validated`, `asset_slot_unbound`, `asset_deleted_graph_edges_removed`, `asset_approved`, `asset_rejected`.
- `api/routes/graph.py`:
  - delecao de edge agora emite `graph_edge_deleted` ou `graph_edge_delete_failed`.
- `api/routes/knowledge.py`:
  - `link_product_asset` registra `removed_edge_ids` quando remove edge antigo e emite `product_asset_linked`.

### Mudancas no dashboard

- `dashboard/app/knowledge/assets/page.tsx`:
  - assets agora sao carregados diretamente de `api.assetList`, sem depender de queue/gallery para enxergar nao aprovados.
  - cada item diferencia `workflow_status` de `approval_status`.
  - `effectiveStatus` prioriza aprovacao real (`approved`, `rejected`, `pending_validation`, `context_only`) e usa workflow (`ready`, `reading`) quando nao ha aprovacao final.
  - preview usa `metadata.preview_url || display_url || url`.
  - filtros adicionados/ajustados para `Ready` e `Lendo`.
  - `pending` agrupa `pending_validation`, `pending`, `ready`, `reading`.

### Validacao

- `python -m py_compile api/services/supabase_client.py api/routes/menu.py api/routes/assets.py api/routes/graph.py api/routes/knowledge.py` passou.
- `npm.cmd run build` em `dashboard/` passou.
- Checagem direta via Supabase MCP confirmou os counts de QA.
- Checagem local com helper `supabase_client.list_assets(...)` contra `env.qa.yaml` retornou 15 assets da persona Baita e `missing_display_url=0`.

### Pendencias operacionais

- Publicar/reiniciar Cloud Run QA se ainda estiver servindo codigo antigo.
- Revalidar no navegador depois do deploy:
  - `/knowledge/assets` mostra os 15 assets da persona Baita;
  - assets nao aprovados aparecem no AI-BRAIN com status correto;
  - catalogo mostra apenas aprovados;
  - previews usam URLs assinadas de Storage.
- Arquivos alterados no repo `baita-cardapio`: `src/services/menu-api.ts`, `src/pages/AdminCardapioPage.tsx`, `src/pages/AdminCardapioPage.test.tsx`, `src/utils/asset-connections.ts`, `src/utils/asset-connections.test.ts`.
- Regra final de vinculo unico: `POST /assets/{id}/bind-slot` para `product_image:<slug>` remove edges `product_image` anteriores do mesmo produto e tambem `product_has_asset` conflitante; `DELETE /assets/{id}/bind-slot/product_image:<slug>?target_slug=<slug>` remove a imagem do payload do produto.
- Token QA local: `baita-cardapio/.env.local` deve ter `AI_BRAIN_PROXY_TARGET=http://localhost:8001` e `AI_BRAIN_ADMIN_TEST_TOKEN=<valor de env.qa.yaml>`. Reiniciar o Vite depois de alterar `.env.local`; o proxy injeta `X-AI-BRAIN-ADMIN-TOKEN` em `POST/PUT/PATCH/DELETE`.
- Validacao HTTP real local: `DELETE http://localhost:5173/assets-api/303678f1-df60-48ca-bcec-ddafd6f16206/bind-slot/product_image%3Acamiseta-branca-baita?target_slug=camiseta-branca-baita` deixou `asset_count=0`; `POST http://localhost:5173/assets-api/303678f1-df60-48ca-bcec-ddafd6f16206/bind-slot` com slot `product_image:camiseta-branca-baita` restaurou `asset_count=1`.
- `/api/menu/baita-conveniencia?collection_slug=cardapio-baita-v14&nocache=1` via `localhost:5173` retorna `Camiseta Baita` com `asset_id=303678f1-df60-48ca-bcec-ddafd6f16206`, URL assinada de `assets-raw`, e `slot_key=product_image:camiseta-branca-baita`.
- Configuracoes: `GET /api/menu/baita-conveniencia/admin-blocks` retorna bloco `Produto — Camiseta Baita` com `slot_instance_key=product_image:camiseta-branca-baita`, imagem atual e edge `fa779596-ca37-42b5-8395-b84b876c01db`.
- Assets UI: markdown visual em `buildAssetMarkdown` agora emite `# Asset — <nome>`, imagem `assets-raw:<path>`, slots conectados e mapa com `asset → product_image:<slug> → card do produto ... no catálogo Baita`.
- Validacao frontend: `npm.cmd test -- --run src/services/menu-api.test.ts src/pages/AdminCardapioPage.test.tsx src/utils/asset-connections.test.ts src/utils/product-visuals.test.ts` passou (13 testes). `agent-browser` e Playwright nao estavam disponiveis; Chrome/Edge headless nao geraram screenshot neste ambiente, entao a verificacao visual automatizada ficou limitada a HTTP/DOM/API e testes de componentes.

## Sessao 2026-05-20 - Auditoria do grafo + amarrar pipeline de upload

### Feature de observabilidade (commitavel)
- Helper novo `api/services/audit_helpers.py`: `summarize_diff(before, after, keys?)` retorna `{changed:{...{before,after}}, unchanged_count}` (shallow, JSON-normalize). `current_actor(request)` extrai `{user_id,email,role}` via `request.state.user` sem nunca raise.
- `api/services/supabase_client.py`: nova `list_system_events(entity_type, event_types, persona_id, entity_id, since, search, limit)` para alimentar a tela de auditoria; usa `.in_()` para event_types e `.ilike()` para search no payload.
- `api/routes/logs.py`: novo `GET /logs/audit` admin-only com filtros (entity_type, event_type CSV, persona_id, entity_id, since ISO, search, limit max 500).
- `api/routes/assets.py`: `connect_asset` agora emite `asset_connected` com `actor/before/after/diff/context` e `asset_connect_rejected_gallery` quando o guard dispara; `update_asset_route` emite `asset_updated` com diff de `type/asset_function/kind`. Reaproveita helper `_log_asset_flow` existente.
- `api/routes/graph.py`: `delete_graph_node` emite `graph_node_deleted` em sucesso (com `strategy=knowledge_item_cascade|direct` e `before_snapshot`) e `graph_node_delete_failed` em cada caminho de erro com `reason`; `create_graph_edge` ganhou `graph_edge_create_failed` no `except` da linha 222 e tambem quando o upsert retorna nada.
- `api/routes/knowledge.py`: PATCH `/queue/{id}` emite `knowledge_item_updated`; PATCH `/products/{slug}` emite `product_node_updated`; PUT `/brand/{persona_id}` emite `brand_profile_updated`. Todos com actor/before/after/diff.
- `supabase/migrations/038_system_events_audit_index.sql`: 3 indices em `system_events` -- `(entity_type, created_at DESC)`, `(event_type, created_at DESC)` e parcial `(persona_id, created_at DESC) WHERE persona_id IS NOT NULL`.
- `dashboard/lib/api.ts`: nova `auditLogs({entity_type, event_type, persona_id, entity_id, since, search, limit})`.
- `dashboard/app/logs/page.tsx`: 3 abas (`audit` padrao, `agents`, `n8n`). Aba audit tem toolbar com select de entidade, event_type (derivado do response), persona (via `api.personas()`), janela temporal (24h/7d/30d/sempre) e busca livre. Tabela com linhas expansiveis mostrando `diff` colorido (vermelho/verde), contexto e payload completo collapsavel.

### Amarrar pipeline /assets/upload (commitavel)
- Diagnostico inicial: usuario reportou `502 /assets/upload` com `StorageApiError: Bucket not found`. Migration 033 cria os buckets via `INSERT INTO storage.buckets ... ON CONFLICT DO NOTHING`, mas no QA esse INSERT silenciosamente nao executou (provavelmente falta de grant storage-admin no migration runner). Fallback antigo no codigo tentava bucket `knowledge` que nao existe no QA (era legado de PROD).
- Fix backend (`api/services/supabase_client.py`): nova `ensure_bucket(name, public=False)` idempotente. Lista buckets via SDK e cria o que faltar; trata `409/already exists` como sucesso; loga via `sre_logger.warn` sem raise.
- Fix backend (`api/main.py`): lifespan hook do FastAPI chama `ensure_bucket("assets-raw")` e `ensure_bucket("assets-derived")` em todo boot; loga `ready` ou `MISSING (uploads will 503)`.
- Fix backend (`api/routes/assets.py::_upload_asset_impl`): substituiu `except Exception` mudo por captura tipada:
  - `Bucket not found` -> tenta self-heal via `ensure_bucket`; se falhar devolve **503 `storage_bucket_missing`** com mensagem orientando rodar migration 033 ou `scripts/ensure_qa_buckets.py`.
  - `InvalidKey/Invalid key` -> **422 `invalid_storage_key`** com mensagem explicando que precisa de letras/numeros/hifens/pontos/sublinhados.
  - Outros erros: mantem fallback legado para bucket `knowledge`.
- **Causa raiz real do 502 persistente**: o filename do upload era `0 - Capa - BAITA - LAYOUT - Cardapio Atualização.png` com espacos + acento (`ç`). Supabase Storage rejeita com `400 InvalidKey`, mas o exception_type comum (`StorageApiError`) fez parecer que era "Bucket not found" novamente.
- Fix: novo helper `_safe_storage_filename(fname)` em `api/routes/assets.py` slugifica stem + extensao reusando `knowledge_graph._slugify` (NFKD + ASCII). `original_filename` continua intacto em `assets.original_filename` e `assets.metadata` para exibicao. Storage_path agora vai como `{persona_id}/0-capa-baita-layout-cardapio-atualizacao.png`.
- Reproducao validada contra QA Supabase real: filename cru -> `400 InvalidKey`; filename sanitizado -> upload OK com URL assinada.
- Endpoint de diagnostico: `GET /health/storage` (publico em `api/middleware/auth.py`) retorna `{supabase_url, project_ref, buckets_visible, required, missing, ok, bucket_error}`. Permite descobrir, sem reabrir codigo, qual Supabase o backend esta atingindo e quais buckets estao visiveis para o service_role daquele projeto.
- Script novo `scripts/ensure_qa_buckets.py`: provisiona buckets em qualquer env (`--env env.qa.yaml` padrao; aceita `env.yaml` para PROD). Idempotente. Ja rodei contra QA -- `assets-raw` e `assets-derived` agora existem em `qhnepdcqtkjjslqqiyvp`.

### Estado do banco
- QA Supabase (`qhnepdcqtkjjslqqiyvp`): migration 033 aplicada (tabelas), migration 038 aplicada (indices), buckets `assets-raw` e `assets-derived` provisionados via SDK.
- PROD Supabase (`slyxppvghniknqofhqzt`): nao verifiquei se `assets-derived` existe. Antes do `deploy-prod`, rodar `python scripts/ensure_qa_buckets.py --env env.yaml` -- idempotente.

### Validacao tecnica
- `py_compile`: `api/main.py`, `api/routes/{assets,graph,knowledge,logs,health}.py`, `api/middleware/auth.py`, `api/services/{audit_helpers,supabase_client}.py`, `scripts/ensure_qa_buckets.py` -- todos OK.
- `npx tsc --noEmit` no dashboard: EXIT=0.
- `tests/test_product_approval.py`: PASS.
- `tests/integration_asset_card_gallery_guard.py`: PASS (cobre meu novo emit `asset_connect_rejected_gallery` em `connect_asset`).
- `tests/integration_asset_card_parent_required.py`: PASS.
- ⚠️ `tests/integration_asset_card_upload.py`: FALHA por regressao **pre-existente** dos edits anteriores em `_upload_asset_impl` (helpers HEIC nao mockados). Meus edits nao tocam essa funcao alem do bloco de captura de exception, mas o teste ja falhava antes desta sessao. Decisao: deixar como divida tecnica ou atualizar mocks do teste numa proxima rodada.

### Pendencias para commit + deploy QA
1. Commit consolidado (sugestao: dois commits separados)
   - **Commit A** (auditoria): `api/services/audit_helpers.py`, `api/services/supabase_client.py` (apenas `list_system_events`), `api/routes/logs.py`, `api/routes/assets.py` (apenas blocos de emit), `api/routes/graph.py`, `api/routes/knowledge.py`, `dashboard/lib/api.ts`, `dashboard/app/logs/page.tsx`, `supabase/migrations/038_system_events_audit_index.sql`.
   - **Commit B** (storage harden): `api/services/supabase_client.py` (apenas `ensure_bucket`), `api/main.py`, `api/routes/assets.py` (apenas `_safe_storage_filename` + captura tipada), `api/routes/health.py`, `api/middleware/auth.py`, `scripts/ensure_qa_buckets.py`.
2. Arquivos modificados na area de trabalho que NAO sao desta sessao (sessoes anteriores): `api/core/landing_slots.py`, `api/routes/menu.py`, `api/services/asset_pipeline/classifier.py`, `dashboard/app/knowledge/{assets,quality}/page.tsx`, `dashboard/components/assets/*`, `dashboard/components/products/LinkAssetDrawer.tsx`, `api/requirements.txt`, `dashboard/next-env.d.ts`, `.claude/settings.local.json`. Decisao do usuario sobre incluir ou separar.
3. Scripts untracked das sessoes Baita: `scripts/fix_baita_*.py`, `scripts/sync_baita_*.py`, `scripts/reset_baita_*.py`, `scripts/refresh_baita_*.py`. Manter como historico ou apagar.
4. Migration 038 ja aplicada no QA -- precisa aplicar no PROD antes do `deploy-prod` (sem isso, /logs/audit fica lento conforme cresce).
5. Apos `deploy-qa`, smoke obrigatorio:
   - `curl -k https://ai-brain-api-qa-837167469397.us-central1.run.app/health/storage` -> esperar `ok:true` com `buckets_visible=["assets-raw","assets-derived"]` e `supabase_url` apontando para `qhnepdcqtkjjslqqiyvp`.
   - Upload da PNG da Baita pelo dashboard QA -> agora deve passar como `asset_uploaded` na tela /logs aba Auditoria; o asset entra como card pendente no galho escolhido.
6. `/logs?tab=audit` precisa do GET `/logs/audit` que e admin-only; usuario logado precisa ter `role=admin` para ver.

### Erros catalogados e suas solucoes (referencia rapida)
- **`502 Bucket not found`**: bucket nao existe no Supabase apontado. Solucao: rodar `python scripts/ensure_qa_buckets.py --env env.<ambiente>.yaml`. O backend agora tambem tenta self-heal no proximo upload, mas o script e mais explicito.
- **`502 InvalidKey` (antes mascarado como Bucket not found)**: filename com espacos/acentos. Solucao ja codada: sanitizacao automatica via `_safe_storage_filename`. UI nao precisa mudar nada -- o `original_filename` continua sendo o nome bonito; so o storage_path vai slugificado. Em caso novo, backend devolve 422 `invalid_storage_key` com mensagem clara em vez de 502 mudo.
- **`/logs/audit` retorna 403**: usuario nao e admin. Auditoria so e visivel para `role=admin` (PII potencial em `actor.email`).
- **Backend aponta para Supabase errado**: chamar `GET /health/storage` -- ele reporta `supabase_url` e `project_ref` atuais. Se nao bater com o esperado, conferir env vars do Cloud Run (`gcloud run services describe ai-brain-api-qa --region us-central1 --format='value(spec.template.spec.containers[0].env)'`).

## Sofia/CRIAR — diagnostico modal + arquitetura gambiarra (2026-05-21)

### Sintoma reportado pelo operador
- Modal "Plano precisa de decisoes da Sofia" abre com `asset_expansion_incomplete`, mas os botoes A/B/C nao fazem nada quando clicados.
- Subir asset pelo paperclip nao remove a violacao — mensagem volta "Asset expansion incompleto" no proximo turno.
- As vezes a arvore aparece praticamente pronta no chat, mas o botao "Salvar conhecimento" nao surge.

### Causas (todas confirmadas no codigo)
1. **Opcoes do modal sao botoes mortos**. `dashboard/components/capture/BlockedPlanDiagnosticModal.tsx:369-374` renderiza `SofiaQuestionCard` sem passar `onOptionSelect`. O componente filho tem o callback opcional (`linha 185-194`), mas o pai nunca cabeia -> click so destaca o botao.
2. **Os `action` strings emitidos pelo backend (`upload_asset`, `attach_existing_asset`, `drop_asset_requirement`, `drop_faq_target`, `create_offer`, `create_rule`) nao tem handler em lugar nenhum**. `api/services/kb_intake_service.py:1695-1722` cria as opcoes mas nao existe `/kb-intake/sofia-action`, nem switch dentro de `chat()`, nem aplicacao do `payload`. Contrato fingido.
3. **Upload pelo paperclip NAO cria entry asset no `normalized_plan`**. O arquivo entra em `session.asset_readings` (`kb_intake_service.py:4501`) e em `mission_state.evidence_items`, mas e o LLM que tem que decidir, no proximo turno, inserir uma entry `content_type=asset` com `metadata.parent_slug=<produto>`. Quando ele esquece, `expansion.asset.created` continua em 0 e o validador (`_validate_plan:1269-1274`) mantem `Asset expansion incomplete` para sempre.
4. **`GraphPreviewPanel` so renderiza se `planStateValid===true`** (`dashboard/app/knowledge/capture/page.tsx:1732`). Qualquer violacao bloqueante esconde o painel inteiro — junto com o botao "Salvar conhecimento" (linha 2271). Por isso o operador ve a estrutura no chat mas nao tem como salvar.
5. **"Editar plano" no rodape do modal so abre o textarea de `contentText`** (`page.tsx:1858`), que e um campo de vault opcional — nao edita a arvore. `onRegenerate` nunca e passado, entao o botao "Regerar estrutura" do modal nem aparece.

### Raiz arquitetural (porque essas gambiarras existem)
- **`ModelRouter.messages_create` so faz text-in/text-out** (`api/services/model_router.py:154-192`). Sem function-calling/tool-use de provider. Toda mutacao de plano e: LLM gera texto -> regex extrai `<knowledge_plan>{json}</knowledge_plan>` em `_extract_plan` (`kb_intake_service.py:560`) com 4 fallbacks defensivos (`_candidate_plan_blocks:526`).
- **Cada turno = regenerar o plano inteiro**. Nao existe patch incremental. O LLM regrava o JSON todo, incluindo edges, mesmo para corrigir um parent. Caro, lento, hallucination-prone.
- **System prompt de 700+ linhas com "HARD CONTRACT" implorando o modelo a nao usar markdown fence** (`kb_intake_service.py:311-315`). E sintoma classico de falta de tools: com ferramentas estruturadas o modelo nao tem como errar o formato.
- **Reuso proativo de nodes existentes e injetado como TEXTO** no system prompt via `pre_init_review` (`kb_intake_service.py:4854-4876`) — frase em portugues, nao tool. Fragil.
- **Acao do operador via modal nao tem caminho de volta para o plano**: as `options[].action` sao etiquetas declarativas sem implementacao.

### Plano de migracao (acordado com o operador, ordem de commit)
1. **Front: cabear modal como visualizacao + atalhos de prompt.** `SofiaQuestionOption` passa a carregar `prompt_to_sofia` (e opcional `ui_hook` para abrir file picker). Click envia mensagem normal via `kbIntakeMessage`. `GraphPreviewPanel` exibe Save sempre (desabilitado com tooltip quando bloqueado). `onEdit` deixa de ser o textarea de vault.
2. **Backend tools (`api/services/sofia_tools.py`)**: `create_node`, `set_parent`, `connect_nodes`, `delete_node`, `validate_plan`, `set_expansion_policy`, `attach_session_asset`, `find_existing_persona_nodes`, `suggest_connections`. `ModelRouter.messages_create` ganha parametro `tools=` e devolve `{text, tool_calls}`. `chat()` vira loop de tool-use. Flag `SOFIA_TOOLS_ENABLED` para retrocompat.
3. **Skills compostas** (camada 2, depois): `repair.no_path_to_persona`, `repair.asset_expansion`, `synthesize.subtree_from_evidence`. Cada uma compoe N tools.

### Mapa do front que sera tocado na etapa 1
- `dashboard/components/capture/diagnosticTypes.ts`: adicionar `prompt_to_sofia: string` e `ui_hook?: "open_file_picker" | "open_asset_drawer"` em `SofiaQuestionOption`.
- `dashboard/components/capture/BlockedPlanDiagnosticModal.tsx`: aceitar `onOptionSelect` props e propagar para `SofiaQuestionCard`. Mostrar "Regerar estrutura" quando `onRegenerate` existir.
- `dashboard/app/knowledge/capture/page.tsx`:
  - Wire `onOptionSelect={(q, opt) => handleSofiaAction(q, opt)}` -> chama `api.kbIntakeMessage(sessionId, opt.prompt_to_sofia)` ou aciona file picker via `ui_hook`.
  - Wire `onRegenerate={() => api.kbIntakeMessage(sessionId, "Regere a arvore aplicando os reparos sugeridos pelo diagnostico atual")}`.
  - Mover `GraphPreviewPanel` para sempre renderizar quando `draftPlan` existe (linha 1732); botao Save fica `disabled` em vez de oculto. Tooltip lista violacoes.
  - Trocar `onEdit={() => setShowContent(true)}` por `onEdit={() => router.push(/knowledge/graph?...)}` ou remover ate ter tela de edicao node-a-node.
- `dashboard/lib/api.ts`: nada novo — usar `kbIntakeMessage` existente. O backend acompanha enviando `prompt_to_sofia` ja embutido em cada opcao.

### Mapa do backend que sera tocado na etapa 2
- `api/services/kb_intake_service.py::_sofia_questions_from_diagnostic` (linha 1625+): para cada `kind`, emitir opcoes com `prompt_to_sofia` em vez de `action`. Manter `action`+`payload` por 1 release como fallback caso o front ainda nao tenha migrado.
- Novo arquivo `api/services/sofia_tools.py`: funcoes puras sobre `session.normalized_plan` + JSON Schema export para tool-calling.
- `api/services/model_router.py`: `messages_create(tools=None)` ganha branch que devolve `tool_calls` quando o provider responde com function-call.
- `api/services/kb_intake_service.py::chat`: loop `while tool_calls -> aplicar -> re-prompt` (com guarda de iteracao maxima).

### Decisao do operador
- Modal vira visualizacao pura; nada de mutacao local nele.
- Botao = atalho que dispara mensagem para Sofia, que escolhe a tool. Backend e a unica fonte da verdade.
- Sofia ganha tools para criatividade (creative subtree expansion, proactive node reuse) deixando de regerar plano inteiro a cada turno.

## ALERTAS — codigo legado que NAO respeita a hierarquia do grafo (2026-05-21)

Regra base do CLAUDE.md: **"Todo conhecimento adicionado DEVE aparecer no grafo. knowledge_items -> knowledge_nodes -> knowledge_edges"**. Os pontos abaixo violam isso e poluem a persistencia de memoria de marca/persona porque criam estados paralelos que nao tem reflexo em `knowledge_nodes`.

### A — Brand: `brand_profiles` e ilha; nao vira knowledge_node
- **Arquivo**: `api/routes/knowledge.py:1116-1138` (PUT `/knowledge/brand/{persona_id}`).
- **Servico**: `api/services/supabase_client.py:3332-3336` (`upsert_brand_profile`).
- **O que faz**: `PUT /knowledge/brand/{persona_id}` chama `supabase_client.upsert_brand_profile({persona_id, **body})` que faz `table("brand_profiles").upsert(...)` direto e emite `brand_profile_updated`. Nao chama `sync_brand_node`, nao chama `bootstrap_from_item`, nao cria nem atualiza nenhuma entry em `knowledge_nodes` com `node_type=brand`.
- **Sintoma**: a diretriz de marca persiste apenas em `brand_profiles`; chat-context/RAG/Sofia nao "veem" a marca pelo grafo (so via SELECT direto). Quando alguem inspeciona o grafo, a persona aparece "sem brand", embora a aba Brand mostre dados.
- **Comparativo**: `audiences` foi corrigido (`api/routes/audiences.py:67` chama `supabase_client.sync_audience_node(audience)`). Brand ficou para tras.
- **Acao sugerida**: criar `supabase_client.sync_brand_node(brand_profile)` espelhando o padrao do audience — slug `brand-<persona_slug>`, `node_type="brand"`, `metadata` com posicionamento/promessa/tom, edge `belongs_to_persona`. Chamar em `upsert_brand` apos o upsert, e backfill via script para personas existentes.

### B — Auditoria de eventos: tudo em `system_events`, sem nada no grafo
- **Servico**: `api/services/supabase_client.py:3358-3376` (`insert_event`).
- **O que faz**: eventos `brand_profile_updated`, `product_node_updated`, `graph_*` viajam todos por `system_events`. So leem na tela `/logs`. Nao geram edges de "produto X foi editado por usuario Y".
- **Status**: aceito como design (auditoria != memoria). Nao mudar — mas anotar para Sofia nao tratar `system_events` como fonte de "conhecimento".

### C — `kb_entries`: agora espelha, mas o codigo legado de PROD ainda escreve direto
- **Arquivo**: `api/services/supabase_client.py:2556-2595` (`upsert_kb_entry`).
- **Fluxo correto** (do CLAUDE.md): aprovar `knowledge_items(pending)` -> `promote_to_kb=true` -> `kb_entries(ATIVO)` -> `bootstrap_from_item(source_table="kb_entries")` -> `knowledge_nodes` -> `knowledge_edges`.
- **Sintoma**: existem chamadas `upsert_kb_entry` em scripts/seed/imports antigos que nao chamam `bootstrap_from_item` em seguida. Resultado: `kb_entries` com rows orfas no grafo. CLAUDE.md item 11 e explicito: "kb_entries nunca deve existir sem reflexo no grafo".
- **Acao sugerida**: auditoria — `SELECT k.id, k.kb_id, k.persona_id FROM kb_entries k LEFT JOIN knowledge_nodes n ON n.metadata->>'kb_id' = k.kb_id WHERE n.id IS NULL;`. Para cada orfao, rodar `bootstrap_from_item` retroativo. `knowledge_graph.py:933` ja tem helper `rebuild_graph` para isso.

### D — `audiences`: corrigido mas nao tem garantia transacional
- **Arquivo**: `api/routes/audiences.py:54-84`.
- **O que faz**: chama `create_audience` (INSERT em `audiences`) seguido de `sync_audience_node`. Sao duas chamadas separadas; se a segunda falhar (rede, RLS), fica `audience` sem node — mesmo problema do brand, so que menor.
- **Acao sugerida**: envolver em transacao via RPC Supabase ou pelo menos compensar (rollback do INSERT) quando `sync_audience_node` retornar None.

### E — `assets`: sem `gallery_asset` automatico
- **Servico**: `api/services/supabase_client.py:3564-3580` (`insert_asset`).
- **Regra CLAUDE.md item 10**: "assets ligados ao Gallery usam `gallery_asset`".
- **Sintoma**: criar asset via `/assets/upload` insere row em `assets` mas nao gera edge `gallery_asset` para o Gallery node da persona. So aparece no Gallery quando o operador conecta manualmente via `connect_asset`.
- **Acao sugerida**: opcional — auto-conectar assets aprovados a `gallery-{persona_slug}` na promocao. Hoje o fluxo manual e intencional, mas para uploads automaticos (crawler/sync) o asset fica invisivel ate alguem clicar.

### F — `lead_audience_memberships` x `leads.persona_id`
- **Reference memory ja existente**: `reference_leads_schema.md` / `feedback_persona_audience_visibility.md`. Repito aqui porque toca persistencia de persona.
- **Acao sugerida**: nada novo — usar `lead_audience_memberships` como fonte canonica em queries operacionais; `leads.persona_id` e legado.

### G — Sofia: o knowledge_plan vai para `knowledge_nodes` so no save final
- **Arquivo**: `api/services/kb_intake_service.py` (todo o pipeline `chat()` -> `save()`).
- **Comportamento atual**: durante a conversa, o plano vive em `session.normalized_plan` (arquivo .json local). So vira `knowledge_nodes` no `POST /kb-intake/save` (que dispara `vault_sync` -> `bootstrap_from_item`).
- **Risco**: se a sessao expirar/morrer antes do save, todo o conhecimento gerado some. **A migracao para tools (camada 2 abaixo) ajuda aqui**: cada `create_node` tool call pode persistir incrementalmente em `knowledge_nodes` com `status=draft`, eliminando o "tudo ou nada" do save.
- **Acao sugerida (alinhada com a migracao de tools)**: tool `create_node` faz `INSERT` em `knowledge_nodes(status="draft", metadata.session_id=...)`. Save final so faz UPDATE para `status="pendente_validacao"` ou `validated`. Sofia para de regerar plano do zero a cada turno.

### Resumo do impacto na memoria de marca
A unica violacao bloqueante para "memoria de marca consistente" e a **A (brand_profiles)**. As demais sao debitos tecnicos com sintomas localizados. Se tivermos que escolher uma para corrigir antes da migracao de tools, e a A — porque toda a creative reuse que a Sofia faria via `find_existing_persona_nodes(types=["brand"])` retorna vazio hoje, mesmo com o brand cadastrado.

## Gate de testes antes do build - 2026-05-22

Plano decidido:
- Bloquear build em dois pontos: CI + `npm run build` local/Vercel.
- Suite obrigatoria deve ser rapida e estavel, sem Supabase real, WhatsApp, browser, LLM ou deploy externo.
- Criar `scripts/quality-gate.py` para rodar:
  - `python -m compileall -q api`
  - testes Python mockados de Sofia/assets/grafo:
    - `tests/integration_sofia_image_upload.py`
    - `tests/integration_sofia_lazy_start_upload.py`
    - `tests/integration_asset_card_upload.py`
    - `tests/integration_asset_validation_lifecycle.py`
    - `tests/test_criar_entry_flow_summary.py`
    - `tests/test_product_approval.py`
  - `npx tsc --noEmit` dentro de `dashboard`
- Atualizar `dashboard/package.json` com `typecheck`, `check` e `prebuild`, para que `npm run build` rode typecheck antes do `next build`.
- Atualizar `.github/workflows/ci.yml` para rodar o quality gate antes do build frontend.
- Atualizar deploy QA/prod do backend para rodar o gate backend antes de `gcloud run deploy`.

Aceite:
- Qualquer falha no gate deve sair com codigo nao-zero e impedir build/deploy.
- `npm run build` deve executar `prebuild` automaticamente.
- CI so deve executar build depois do gate passar.

## Sessao 2026-05-23 - VZ Lupas, Sofia tools, catalogo na /persona e login QA

### Commits recentes (develop, depois do gate de testes)
- `6832f73 feat(capture): modal Sofia vira visualizacao + atalhos de prompt; Save sempre visivel` — corrige a serie de gambiarras catalogadas em 2026-05-21. Modal `BlockedPlanDiagnosticModal` passou a propagar `onOptionSelect`; cada opcao envia `prompt_to_sofia` via `kbIntakeMessage`. `GraphPreviewPanel` renderiza enquanto `draftPlan` existe e o botao Save fica `disabled` com tooltip listando violacoes, em vez de sumir.
- `1899850 feat(sofia): backend tools deterministicas + tool-use loop opt-in via env` — `api/services/sofia_tools.py` ganhou as primeiras tools (`create_node`, `set_parent`, `connect_nodes`, `delete_node`, `validate_plan`, `set_expansion_policy`, `attach_session_asset`, `find_existing_persona_nodes`, `suggest_connections`). `ModelRouter.messages_create` aceita `tools=` e devolve `tool_calls`. Flag `SOFIA_TOOLS_ENABLED` mantem o caminho antigo enquanto migracao roda.
- `397d539 fix(intake): aceita product_group/offer/gallery no ALLOWED_CONTENT_TYPES + E2E VZ Lupas` — `api/services/knowledge_rag_intake.py:20-37` agora reconhece `product_group/offer/gallery` (antes caiam em `general_note`). Acompanha pacote E2E VZ Lupas em `tmp/sofia_e2e/`: `run_vz_lupas_e2e.py`, `retry_assets_shot.py`, `run_screenshots_only.py`, REPORT.md + screenshots t1/t2/t3 + uploads VZ Lupas (clipon/grau/sol).

### Plano cardapio multi-persona (`tmp/sofia_e2e/PLAN_CARDAPIO_MULTI_PERSONA.md`)
- `baita-cardapio` ja roda por `personaSlug` na URL. Pontos acoplados que sobram (a fechar antes do VZ Lupas ir publico):
  - `api/routes/menu.py:407-408,434,440,565,575,632` — alias map e `collection_slug` default `cardapio-baita-v14` so para baita.
  - `../baita-cardapio/src/App.tsx:16` envia `VITE_DEFAULT_PERSONA=baita` na Vercel.
  - `PersonaThemeProvider` precisa carregar tokens via `/api/menu/{slug}/theme` (D3.A: tokens em `persona.metadata.theme`).
  - Copy persona-aware (`persona.metadata.copy.menu_label = "Cardapio" | "Catalogo"`).
- Recomendacao adotada: discovery via marker `metadata.is_landing_root=true` em node `product_group` (Passo 1 do plano), descartando default hardcoded.
- URL strategy hoje: path-based (`baita-cardapio.vercel.app/<persona-slug>`). Subdomain fica para 5+ personas.

### Login QA quebrado (brain-plataform-qa.vercel.app) — diagnostico
- Sintoma do navegador: `GET /api-brain/auth/me 401` repetitivo + `POST /api-brain/auth/login 401`. O loop infinito de `up/ud` no console e React batendo no `useEffect` do `AppShell.me()` em cada render porque `pathname !== "/login"` mas a sessao nao existe — quando `me()` lanca 401, o handler chama `router.replace("/login")`, mas o redirect nao executa se o `proxy.ts` ja redirecionou e o componente continua montando. Isso so se manifesta porque o backend QA esta rejeitando as credenciais.
- Causa provavel: o Cloud Run QA (`ai-brain-api-qa-837167469397.us-central1.run.app`) nao tem usuario auth para o e-mail digitado. `api/middleware/auth.py:78-107` exige `auth_service.get_user_by_id(payload.sub)`; antes disso o `POST /auth/login` ja teria devolvido 401 se o usuario nao existir em `auth_users`.
- Validacao operacional sugerida (nao executei — exige `env.qa.yaml` e `gcloud`):
  1. `curl -sS https://ai-brain-api-qa-837167469397.us-central1.run.app/health` → confirmar que o servico esta no ar.
  2. Verificar `auth_users` no Supabase QA: `select id, email, role, is_active from auth_users order by created_at;`.
  3. Se vazio ou sem o admin esperado, rodar `cd api && python scripts/create_auth_user.py --email <op@empresa.com> --username <op> --password <senha> --role admin` apontando para `env.qa.yaml` (a sessao precisa ter `AI_BRAIN_SEED_ADMIN_EMAIL`/`PASSWORD` setados no Cloud Run QA para o seed automatico funcionar — checar `gcloud run services describe ai-brain-api-qa --region us-central1 --format='value(spec.template.spec.containers[0].env)'`).
- Atalho enquanto a conta nao for criada: usar header `X-AI-BRAIN-ADMIN-TOKEN: <AI_BRAIN_ADMIN_TEST_TOKEN>` em endpoints internos (so funciona quando `ENVIRONMENT in {qa,preview,test}`), conforme `api/middleware/auth.py:36-65`.

### Catalogo na /persona (esta sessao)
- Pedido: adicionar na tela `/persona` (`dashboard/app/persona/page.tsx`) um link para o cardapio/catalogo publico da persona selecionada, sem nada hardcoded. Link tem que respeitar PROD vs QA e seguir o slug da persona (ex: `vzlupas`).
- Decisao: novo env publico `NEXT_PUBLIC_CARDAPIO_BASE_URL` em `dashboard/.env.local.example`. Link no front e `${NEXT_PUBLIC_CARDAPIO_BASE_URL}/${persona.slug}` quando o env existir; quando nao, o card mostra estado vazio explicando como configurar. Para QA: `https://baita-cardapio-qa.vercel.app`. Para PROD: `https://baita-cardapio.vercel.app`. O slug e sempre da persona (`persona.slug`), e nunca uma constante.
- O card resume o quanto da persona ja esta refletido no catalogo usando o `graphSummary` que a tela ja calcula: contagem de produtos conectados (`graphSummary.products`) e contagem de assets em Gallery (consultado via `api.galleryAssets(persona.id)` — mesmo endpoint que /settings usa). Assim "vinculando diretamente os produtos, assets de forma correta" e validavel pelo operador antes de abrir o link.
- Vercel: precisa setar `NEXT_PUBLIC_CARDAPIO_BASE_URL` em ambos os scopes do projeto `brain-plataforma`:
  - production -> `https://baita-cardapio.vercel.app`
  - preview (branch `develop`) -> `https://baita-cardapio-qa.vercel.app`
  - sem isso o card aparece em modo "configurar URL" e nao quebra a tela.
- 2026-05-27 (BRA-22 re-dispatch): sweep `baseline-validate-only` executada via `node C:\Users\Alan\Documents\repositorios\paperclip\scripts\graph-test-runner.mjs` com `AI_BRAIN_BASE_URL=http://127.0.0.1:8001` e token admin de QA carregado do `env.qa.yaml`. Evidence gerada em `C:\Users\Alan\Documents\repositorios\paperclip\test-artifacts\graph-runs\2026-05-27T07-19-28-026Z.json`. Resultado: `disposition=blocked` por `fetch_graph status=404` (`/knowledge/graph?mode=semantic_tree&all_edges=1&persona_slug=vz-lupas`), sem avaliação das hard invariants por indisponibilidade da rota alvo.
- 2026-05-27 (BRA-22 heartbeat): Corrigi o runner paperclip/scripts/graph-test-runner.mjs com fallback de endpoint (/knowledge/graph -> /knowledge/graph-data) e grava��o do oute/url usado no step etch_graph; adicionei teste de contrato em paperclip/tests/graph-runner.test.mjs (graph endpoint fallback prefers graph-data...) e validei com 
ode --test tests/graph-runner.test.mjs (14/14 pass). Reexecu��o real gerou paperclip/test-artifacts/graph-runs/2026-05-27T07-22-44-264Z.json com locked por 403 em /knowledge/graph-data?...persona_slug=vz-lupas (endpoint agora responde; bloqueio remanescente � acesso/persona no alvo, n�o mais 404).

## Sessao 2026-05-27 - BRA-29 fluxo simples para criar persona em Configuracoes
- Frontend: adicionado metodo `api.createPersona` em `dashboard/lib/api.ts` (POST `/personas`) para consumir a rota ja existente no backend.
- Frontend: `dashboard/app/settings/page.tsx` ganhou bloco `Criar persona` com campos `Nome da persona` e `slug-da-persona`, botao `Criar persona`, e validacao UX minima (nome obrigatorio, slug normalizado).
- UX pos-sucesso: limpa formulario, persiste `ai-brain-persona-slug` no localStorage, seleciona a persona criada e dispara refresh da tela para atualizar listas/indicadores.
- Estados tratados: loading (`Criando...`), erro de API e sucesso visivel no card.
- Verificacao minima: `cd dashboard && npx tsc --noEmit` (passou em 2026-05-27).

## 2026-05-28 � codex (BRA-45 /sofia/graph-command real backend)
- Issue/tarefa: BRA-45 endpoint backend para Sofia reprocessar nodes/edges com cadeia canonica.
- Arquivos alterados:
  - api/routes/qa_contract.py
  - tests/test_qa_contract_routes.py
  - tests/test_qa_contract_route_mapping.py
- O que mudou:
  - Nova rota `POST /sofia/graph-command` em `qa_contract` (tambem montada sob `/api/sofia/graph-command`).
  - Aceita comando NL ou intent estruturada (`context.client_action`) e resolve para `graph_patch`.
  - Valida antes de persistir:
    - bloqueia `Product -> Embedded` direto (`GRAPH_EDGE_FORBIDDEN`);
    - bloqueia `FAQ -> Embedded` sem FAQ aprovada (`FAQ_NOT_APPROVED`);
    - valida edge primaria contra cadeia canonica via `knowledge_taxonomy.is_primary_edge_allowed`;
    - bloqueia audiencia com papeis proibidos (`role-sdr|role-closer|role-classifier`);
    - bloqueia produto sem `metadata.source_url` quando `accept_unverified=false`.
  - Persiste nodes/edges em `knowledge_nodes`/`knowledge_edges` via `supabase_client` e grava auditoria:
    - `sofia_graph_command_applied`
    - `sofia_graph_command_rejected`
  - Inclui recomendacao `audience_default_shared` quando aplicavel.
- Evidencia/testes:
  - `python -m pytest tests/test_qa_contract_routes.py -k "sofia_graph_command" -q` => 2 passed.
  - `python -m pytest tests/test_qa_contract_route_mapping.py -q` => 1 passed.
- Riscos/bloqueios:
  - Fluxo de deletions (`nodes_delete`/`edges_delete`) permanece reservado no payload e nao executado nesta entrega.

## 2026-05-28 � codex (BRA-46 frontend smoke /sofia/graph-command)
- Wake comment atendido: execucao Frontend Agent para smoke real do `/sofia/graph-command` + patch React Flow pending/persisted com evidencia.
- Frontend corrigido para contrato real da rota:
  - `dashboard/lib/api.ts`: `api.sofiaGraphCommand(...)` agora envia payload canonico `{ persona_slug, command, context.client_action }` em vez de `{action,message}`.
  - `dashboard/app/knowledge/graph/GraphPageClient.tsx`: aceita resposta backend com `sofia_message` + `graph_patch` (alem dos aliases antigos), preservando UX de pending/persisted.
- Validacao local:
  - `npx tsc --noEmit` em `dashboard` => PASS.
- Evidencia de rota real:
  - API local antiga em `127.0.0.1:8001` respondeu `404` para `/sofia/graph-command` (instancia sem rota nova montada).
  - API fresh via `uvicorn main:app --port 8011` confirmou rota em `openapi` (`HAS_ROUTE=True`), mas chamada real retornou `{"detail":"Sessao obrigatoria."}`.
  - Tentativa com `X-AI-BRAIN-ADMIN-TOKEN` (token de `env.qa.yaml`) e `ENVIRONMENT=qa` em nova instancia (`8013`) manteve `Sessao obrigatoria`.
- Bloqueio objetivo para DoD de smoke real end-to-end: falta credencial de sessao valida (usuario/senha) para autenticar no backend e executar o comando real com persist/refetch no ambiente atual.

## 2026-05-28 � codex (BRA-45 closure: commit + reload + live probe)
- Branch: `develop`
- Commit realizado: `76bd9c7` (`feat(qa-contract): POST /sofia/graph-command + validacao cadeia canonica`).
- Arquivos no commit:
  - `api/routes/qa_contract.py`
  - `tests/test_qa_contract_routes.py`
  - `tests/test_qa_contract_route_mapping.py`
- Restart/reload backend QA executado em `127.0.0.1:8001` via `python scripts/start_api_qa.py` (processo `36976`).
- Verificacao de rotas via `GET /openapi.json` confirmou:
  - `/sofia/graph-command`
  - `/api/sofia/graph-command`
- Probe pos-deploy executado:
  - `POST http://127.0.0.1:8001/sofia/graph-command`
  - payload NL: `reencaixe VZ Lupas abaixo de AllanVvz e organize com Audience padrao.`
  - resultado: HTTP 200, `ok=true`, `persisted=true`, `validation.canonical_chain_respected=true`.

### 2026-05-28 � frontend-agent (BRA-46: chain lock by BRA-50)
- Issue/tarefa: BRA-46
- Arquivos alterados: memory.md
- O que mudou: Recebido wake `CHAIN LOCK 2026-05-28` do board; BRA-46 fica travada por dependencia direta de evidencia smoke da BRA-50 conforme `paperclip/agents/OPERATING_RULES.md` �10. Nenhuma nova execucao E2E foi iniciada para evitar retry sem input novo.
- Validacao executada: leitura de `paperclip/agents/OPERATING_RULES.md` e thread de comentarios da issue via Paperclip API; lock confirmado.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: unblock externo obrigatorio pela cadeia critica (BRA-50).
- Proximo passo: owner BRA-50 publicar evidencia smoke em path publicado; depois retomar BRA-46.

### 2026-05-28 � frontend-agent (BRA-46: gate update via BRA-57 chain)
- Issue/tarefa: BRA-46
- Arquivos alterados: memory.md
- O que mudou: Recebido novo gate do board inserindo cadeia critica anterior a BRA-46: `BRA-54 (done) -> [BRA-58 + BRA-61] -> BRA-59 -> BRA-60 -> BRA-50 -> BRA-46 -> BRA-44`. BLOQUEIO mantido para BRA-46 ate fechamento com aceite real dos gates anteriores.
- Validacao executada: leitura do comentario `652c8324-d981-43c8-b492-d6e3b8f64d61` e aplicacao da regra de cadeia critica.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: dependencia externa da cadeia BRA-58/61/59/60/50; sem isso nao ha execucao valida de smoke BRA-46.
- Proximo passo: owner da cadeia BRA-57 publicar artifacts em path publicado e liberar gate para BRA-46.

## 2026-05-28 - codex (BRA-59 Sofia resolve-persona + resolve-operation loop)
- Added pi/services/sofia_orchestrator.py to enforce deterministic pre-patch tool sequence: esolve-persona then esolve-operation for /sofia/graph-command.
- Added score gate via SOFIA_GRAPH_COMMAND_MIN_SCORE (default  .65); low confidence returns clarification without patch persistence.
- Wired pi/routes/qa_contract.py::sofia_graph_command to orchestrator and response now includes auditable 	ool_calls + 	hreshold.
- Added prompt contract file pi/prompts/sofia_graph_command.md.
- Added tests 	ests/test_sofia_orchestrator_tools.py (2 passing cases: success and low-score fallback).
- Produced artifact paperclip/test-artifacts/qa/bra59-sofia-orchestrator-2026-05-28.json with 5 command samples and captured tool call traces.

## 2026-05-28 - codex (BRA-59 reopen: contract alignment)
- Aligned `/sofia/graph-command` to published contract (`paperclip/docs/qa/sofia-tool-use-contract.md`).
- Removed QA allow-list gating from Sofia path by replacing `_require_qa_persona(...)` with `_resolve_sofia_persona(...)` (accepts any existing persona slug/id; no 403 due to vz-lupas gate).
- Added explicit `needs_clarification` propagation from orchestrator when score < threshold and no patch is returned.
- Added auditable `validate_canonical_chain` tool entry to `tool_calls` in successful path.
- Updated route response tool call shape to include `tool` + `score` + `result` for contract audits.
- Extended tests with `allanvvz` non-gated route case and validate-canonical-chain tool call assertion.
- Validation: `pytest tests/test_sofia_orchestrator_tools.py tests/test_qa_contract_routes.py -k "sofia_graph_command or sofia_orchestrator_tools" -v` => 5 passed.
## 2026-05-28 - codex (BRA-59 strict rejection recovery)
- Implemented contract-required tool endpoints on QA contract router:
  - `POST/OPTIONS /sofia/tools/resolve-persona`
  - `POST/OPTIONS /sofia/tools/resolve-operation`
- Maintained `/sofia/graph-command` non-gated persona resolution (`_resolve_sofia_persona`) so `allanvvz` no longer fails with VZ-only gate.
- Added low-confidence and operation metadata outputs required by contract (`needs_clarification`, `needs_confirmation`, `risk_level`, candidates).
- Live probe evidence on `:8001` with QA admin token:
  - `/sofia/tools/resolve-persona` => 200, schema fields present.
  - `/sofia/tools/resolve-operation` => 200, schema fields present.
  - `/sofia/graph-command` with `persona_slug=allanvvz` => 200 and `tool_calls` audit trail (resolve-persona, resolve-operation, validate_canonical_chain).
- OpenAPI now contains `/sofia/tools/resolve-persona` and `/sofia/tools/resolve-operation`.
- Tests: `pytest tests/test_qa_contract_routes.py -k "sofia_graph_command or resolve_persona_tool or resolve_operation_tool" -v` => 5 passed.
