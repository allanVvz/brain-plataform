# Brain AI — Progresso UI/UX

## Concluido
- Fase 1: tokens liquid glass, tema, hydration fix.
- Fase 2: Leads consolidado CRM + CSV/Bulk, botao Iniciar conversa.
- Fase 3: PreflightPanel unificado.

## Em execucao
- Fase 4: Leads -> Messages focado.

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
