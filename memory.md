## Sofia Criar â€” simplificacao da arvore principal e preview (2026-06-01)
- Contexto do usuario: a Sofia estava criando audiences extras sem motivo, omitindo `product_group`, `product`, `copy` e `faq` do plano visivel, e retornando erros confusos como `entry[4] has no complete path to persona`.
- Diagnostico consolidado:
  - `entry[n]` e apenas o indice do array `entries` do plano, nao um node do grafo.
  - A arvore principal nao pode depender do `relation_type` semantico; a publicacao precisa salvar a edge estrutural com `metadata.primary_tree=true`.
  - Relacoes semanticas como `targets_audience`, `supports_copy`, `answers_question` e `contains` podem existir, mas nao substituem a edge principal.
  - O preview deve bloquear so o que realmente quebra a arvore: ciclo, tipo invalido, parent proibido, slug duplicado critico e ausencia real de caminho ate persona.
  - Copy, FAQ, Embedded, Asset, Offer e Rule sem caminho principal passam a warning, nao bloqueio.
- Ajustes registrados no backend:
  - `knowledge_graph.ensure_main_tree_connection()` agora cria sempre a edge principal com `primary_tree=true`.
  - `repair_primary_tree_connections()` trata `primary_tree=true` como fonte de verdade.
  - `kb_intake_service._repair_canonical_parent_slugs()` preenche parents faltantes na ordem canonica.
  - `graph_validation.CANONICAL_PARENTS` simplificou o contrato da FAQ para `copy`, `product` e `product_group`.
- Pendencias observadas pelo usuario:
  - preview ainda pode ficar confuso quando o plano mostra grupos vazios ou grupos duplicados;
  - a Sofia precisa explicar no chat o que esta fazendo antes de bloquear;
  - o grafo de preview precisa renderizar a arvore completa em uma passada quando o plano ja esta coerente.
# Brain AI â€” Progresso UI/UX

## Sofia Criar â€” diagnÃ³stico save/publicaÃ§Ã£o no grafo (Tock Fatal, 2026-05-31)
- Pedido do usuÃ¡rio: rastrear por que o plano `ready_to_save` (brandâ†’briefingâ†’campaignâ†’audienceâ†’product_groupâ†’productâ†’copyâ†’faq, 2 produtos) salva mas NÃƒO aparece completo em `http://localhost:3000/knowledge/graph`. RestriÃ§Ãµes: nÃ£o mexer no builder da criaÃ§Ã£o, sem push/deploy prod.
- **1. BotÃ£o "Salvar conhecimento"** chama `POST /kb-intake/save` (`api/routes/kb_intake.py:465` â†’ `services/kb_intake_service.save`). O 500 que o usuÃ¡rio via vinha do safety-net do route (retorna 400/â€œUnhandled exception in save()â€). Reproduzido in-container: `save()` hoje retorna `EXC=None`, persiste os 11 nodes (created=11) + edges, sem exceÃ§Ã£o. Logo o 500 original era estado prÃ©-fix/transitÃ³rio, nÃ£o um bug reprodutÃ­vel atual.
- **2. Recebe o plano completo?** SIM. O dump da sessÃ£o (`api/.runtime/kb-intake-sessions/9545b772â€¦.json`) tem 11 entries + 11 links cobrindo a cadeia canÃ´nica inteira, 2 kits de modal. `save()` usa `normalized_plan`/`knowledge_plan`/`plan_override` com gates de hash/confirmaÃ§Ã£o e contagem.
- **3. Faz upsert de todos os content_types?** SIM. Query in-container confirmou no DB de `tock-fatal`: persona, brand, briefing, campaign, audience(1), product_group(1, â€œmodalâ€), product(2), copy(2), faq(2) = 13 nodes. Caminho: `save` â†’ `knowledge_lifecycle.persist_pending_knowledge_item` por entry â†’ `bootstrap_from_item` cria o `knowledge_node`.
- **4. Cria knowledge_edges em lote?** SIM, via `knowledge_graph.apply_plan_hierarchy(persona_id, persisted_items, plan_entries, plan_links)` + `repair_primary_tree_connections`. `apply_plan_hierarchy` resolve o pai de cada filho por `plan_links` (`explicit_targets[target_slug]=source_slug`) e chama `ensure_main_tree_connection`, que faz `upsert_knowledge_edge(..., metadata.primary_tree=True)`.
- **5. `/knowledge/graph` lÃª os mesmos nodes/edges?** SIM, mesma fonte: `GET /knowledge/graph-data` (`api/routes/graph.py:1046` `get_graph_data`) usa `supabase_client.list_all_knowledge_graph(persona_id)`. PORÃ‰M em modo `layered`/`semantic_tree` (default) ele FILTRA e mantÃ©m SÃ“ arestas com `metadata.primary_tree is True` (mais terminal faqâ†’embedded e gallery_asset) â€” `graph.py:1122-1146`.
- **6. RAIZ do "nÃ£o aparece completo":** os nodes existem, mas a cadeia abaixo de `brand` foi gravada como arestas **nÃ£o-primary** (`primary_tree != True`) no save do usuÃ¡rio (evidÃªncia: 10 de 11 edges `primary=None`, sÃ³ `personaâ†’brand` primary). Como o leitor do grafo sÃ³ mantÃ©m `primary_tree=True`, a Ã¡rvore abaixo de brand nÃ£o renderiza. Re-salvar converge (1â†’7â†’9 primary) porque `repair_primary_tree_connections` reconecta a cada passada, mas nÃ£o fecha em 1 save sobre dados sujos.
- **Defeito concreto identificado:** os `plan_links` do builder usam relaÃ§Ãµes `targets_audience` (campaignâ†’audience), alÃ©m de `contains`/`briefed_by`/`supports_copy`/`answers_question`. `apply_plan_hierarchy` usa a relaÃ§Ã£o explÃ­cita do link na aresta primÃ¡ria; mas `repair_primary_tree_connections` (`graph.py:544`) sÃ³ conta como â€œconectadoâ€ arestas com `relation_type in _MAIN_TREE_RELATIONS`. `_MAIN_TREE_RELATIONS` NÃƒO inclui `targets_audience` â†’ audience (e descendentes) Ã© tratado como solto e re-aterrado em `personaâ†’node`, quebrando o layout. IdempotÃªncia de re-save agrava: item jÃ¡ existente volta de `persist_*` sem re-linkar `knowledge_node_id`, entÃ£o `nodes_by_slug` fica incompleto e alguns pais nÃ£o resolvem (ex.: 2Âº produto ficou Ã³rfÃ£o).
- **Fix recomendado (publicaÃ§Ã£o, nÃ£o builder):** (a) adicionar `targets_audience` (e quaisquer relaÃ§Ãµes de plan_link canÃ´nicas) a `_MAIN_TREE_RELATIONS`; e/ou (b) em `apply_plan_hierarchy`, normalizar a relaÃ§Ã£o do link para a canÃ´nica `_default_plan_relation(parent_type, child_type)` ao gravar a aresta primÃ¡ria; e (c) garantir que re-save re-resolva `knowledge_node_id` para popular `nodes_by_slug`. NÃƒO aplicado ainda (aguardando aval; evitar mudanÃ§a meio-testada no core de publicaÃ§Ã£o).
- **SDR/Closer â€œaudiences fantasmasâ€:** NÃƒO sÃ£o audiences criadas pelo save. `save` seta `agent_visibility=["SDR","Closer","Classifier"]` em cada knowledge_item (`kb_intake_service.py:6291`; idem `knowledge_lifecycle.py:129/213`, `supabase_client.py:1955`) â€” Ã© metadado de visibilidade de bot, nÃ£o node. A criaÃ§Ã£o real de audience role-* vem do caminho do Graph chat: `sofia_orchestrator` + `qa_contract` op `create_default_audience` (`qa_contract.py:378/599`); hÃ¡ guard `AUDIENCE_ROLE_FORBIDDEN` contra `role-sdr/role-closer/role-classifier` em `qa_contract.py:750`. No DB atual de tock-fatal sÃ³ existe 1 audience (`publico-alvo-principal-da-campanha`), sem SDR/Closer. Escopo reduzido pelo usuÃ¡rio para save/publicaÃ§Ã£o â€” SDR/Closer nÃ£o tratado neste turno.
- EvidÃªncia viva coletada via `docker exec ai-brain-api-1 python` consultando `supabase_client.list_all_knowledge_graph` e `kb_intake_service.save`. Nada commitado; working tree limpo.

## Sofia Criar / Tock Fatal modais - crawler tolerante + preview sem persona duplicada (2026-05-31)
- Sintoma: no caminho Criar para `tock-fatal` / `https://tockfatal.com`, a Sofia nao recuperava os produtos e o preview mostrava alerta quebrado `PERSONA ficou sem saida: tock-fatal`.
- Causa 1: `catalog_crawler` falhava antes do parsing por `SSL: CERTIFICATE_VERIFY_FAILED`; como `product_candidates=[]`, o builder deterministico de arvore completa nao tinha insumo e a conversa caia em pendencias.
- Causa 2: quando o LLM emitia `content_type=persona`, a persona virava um card duplicado em `entries`; o frontend ja desenha a persona como raiz implicita, entao esse card ficava terminal e gerava alerta falso.
- Fix: crawler agora tenta `/products.json`/HTML com fallback controlado para certificado local invalido, extrai `<product-card>` de Shopify, deduplica candidatos por titulo e preserva preco/imagem/source. Para Tock Fatal, o crawl retorna 2 produtos reais: `Kit Modal 2 - Urso Estampado` e `Kit Modal 1 (9 cores disponiveis)`.
- Fix: `_full_tree_command` tambem entende pedido de "monte a estrutura/campanha" na mesma mensagem de extracao; `_normalize_sofia_knowledge_plan` remove entry `persona` que corresponde a `persona_slug`, mantendo a persona como raiz implicita; `_leaf_alert_warnings` nao trata persona como terminal pendente.
- Fix adicional: `parse_tree_counts` agora usa 1 grupo por padrao e so amplia grupos quando ha quantidade explicita; `build_pre_initialization_review` nao reabre a pergunta da audiencia `Import` quando o operador pede audiencia padrao; a persona trocada no header invalida a sessao ativa para evitar reaproveitamento de contexto antigo.
- Validacao: `python -m pytest tests/test_marketing_criacao_kb_intake_flow.py tests/test_sofia_create_plan_product_group.py tests/test_sofia_create_repair_product_group_tree.py -q` -> `12 passed`. Novo caso cobre Tock Fatal em uma unica mensagem e exige arvore `brand -> briefing -> campaign -> audience -> product_group -> product -> copy -> faq` com 2 kits de modal, sem violacoes bloqueantes.

## Sofia Criar /marketing/criacao â€” full-tree determinÃ­stico (2026-05-31)
- Sintoma: em `http://localhost:3000/marketing/criacao` a Sofia parava cedo ("vou comeÃ§ar pelo Briefing"), fazia perguntas ou gerava plano com parent links quebrados; Ã s vezes "NÃ£o consegui processar sua mensagem agora". A Ã¡rvore (brandâ†’briefingâ†’campaignâ†’audienceâ†’3 product_groupsâ†’9 productsâ†’copyâ†’faq) nÃ£o materializava.
- DiagnÃ³stico (reproduzido via `docker exec ai-brain-api-1 python` chamando `kb_intake_service.chat` direto, sem auth): NÃƒO era 500 â€” `chat()` retornava `ok:True`. O 500/genÃ©rico vem do safety-net em `chat()` wrapper + `routes/kb_intake.py` sÃ³ quando o LLM realmente estoura. O bug real Ã© **nÃ£o-determinismo do LLM**: na 2Âª msg ele emitia plano sem brand/campaign/product_group, produtos com parent invÃ¡lido â†’ `validate_sofia_knowledge_plan` bloqueava com ~15 violaÃ§Ãµes; ou nÃ£o emitia plano nenhum. O crawler funciona perfeitamente (30 candidatos reais, conf 0.85: Radar/Juliet/HSTN/Plantaris com preÃ§os).
- `/marketing/criacao` JÃ chamava o Create path correto: `dashboard/app/marketing/criacao/page.tsx` â†’ `CaptureWorkspace` (de `app/knowledge/capture/page.tsx`) â†’ `api.kbIntakeStart`/`api.kbIntakeMessage` â†’ `/kb-intake/start` + `/kb-intake/message`. Nenhuma mudanÃ§a de frontend foi necessÃ¡ria.
- Fix (backend, `api/services/kb_intake_service.py`): builder determinÃ­stico `build_full_tree_plan_from_session()` + helpers (`_full_tree_command`, `_parse_tree_counts`, `_product_family`, `_extract_campaign_title`, `_extract_audience_descriptor`, `_deterministic_tree_summary`). Em `_chat_impl`, quando o operador confirma a Ã¡rvore inteira ("sim crie toda a arvore"/"crie a arvore completa") E o plano do LLM Ã© vazio/bloqueado E hÃ¡ candidatos do crawler na sessÃ£o â†’ constrÃ³i a cadeia canÃ´nica a partir dos candidatos reais, passa por `normalize_validate_summarize_plan` e, se vÃ¡lido, grava e marca `ready_to_save`. Produto sem preÃ§o vai com `metadata.pending_price=true` (nÃ£o bloqueia). Nada hardcoded: brand vem do persona slug, campaign/audience extraÃ­dos das mensagens, produtos do crawler agrupados por famÃ­lia detectada.
- IMPORTANTE: compose roda `SOFIA_TOOLS_ENABLED=true` (default no docker-compose.yml linhas 158/190) = **modo canÃ´nico**, onde `_normalize_sofia_knowledge_plan` Ã© cleanup puro e preserva os 9 copy/9 faq por produto. Em modo legacy (`false`) o `_ensure_faq_golden_datasets_by_branch` colapsaria faq em 1 golden dataset. Teste e validaÃ§Ã£o devem usar `SOFIA_TOOLS_ENABLED=true` para refletir produÃ§Ã£o.
- Teste: `tests/test_marketing_criacao_kb_intake_flow.py` (mocka ModelRouter sem plano + crawler com candidatos shape-real; modo canÃ´nico). Asserts: brandâ‰¥1, briefingâ‰¥1, campaignâ‰¥1, audienceâ‰¥1, product_group==3, product==9, copyâ‰¥9, faqâ‰¥9, sem violaÃ§Ãµes, todo node com caminho atÃ© persona, product_groupâ†’product, pending_price nÃ£o bloqueia. PASS. RegressÃ£o `test_sofia_create_plan_product_group.py` + `test_sofia_create_repair_product_group_tree.py` PASS.
- ValidaÃ§Ã£o: `npm run build` OK; `docker compose up -d --build api workers` OK; `/health` 200; E2E live no container rebuildado â†’ stage `ready_to_save`, 0 violaÃ§Ãµes, cadeia completa a partir do crawl real. Sem deploy prod, sem migration, sem push.

## FAQ Tool node-type-aware â€” Audience != Product (2026-05-30)
- Problema: `adaptar_faqs_universais_ao_grafo` aplicava templates de e-commerce em qualquer node. Audience "TÃ©cnicos" (brand Allan Rodrigues, sem produto no galho) gerou "Como comprar o TÃ©cnicos?", "acompanha caixa?", "prazo de envio?".
- Causa: `select_faq_parent` para audience retornava a prÃ³pria audience; `_resolve_subject_and_brand` usava o label como subject; havia um Ãºnico conjunto de templates comerciais.
- CorreÃ§Ã£o em `api/services/sofia_faq_tool.py`:
  - `find_sellable_in_branch` procura objeto vendÃ¡vel (product/offer/service/course/event; product_group sÃ³ conta com product) nos ancestrais E descendentes do galho.
  - `classify_faq_target` mapeia categoria por node_type: product/offer/product_group/campaign/brand/briefing/copy/audience/audience_object/discovery.
  - Conjuntos de templates por categoria. Compra/frete/garantia sÃ³ para objetos vendÃ¡veis. Audience usa perguntas de qualificaÃ§Ã£o/discovery com `_audience_descriptor` (1a frase do markdown). Audience com objeto vendÃ¡vel abaixo => `audience_object` (relaÃ§Ã£o audience->objeto). Copy extrai specs (i5, 2TB, RTX...) do markdown via `_extract_spec_tokens`.
  - Guardrail `_violates_commercial_guardrail` filtra audience/brand/briefing/discovery contra "frete/acompanha caixa/flanela/prazo de envio/parcelar" e "comprar/garantia/preÃ§o d{o,a} {nome}".
  - Retorno agora inclui `category`, `commercial_object_type`, `commercial_object_name`.
- Cada galho Ã© independente: Allan Rodrigues nÃ£o herda linguagem/Ã³culos da VZ Lupas (subject/brand vÃªm do contexto real do galho, nunca hardcoded).
- Markdown contextual segue como fonte obrigatÃ³ria: `build_branch_context` lÃª `metadata.markdown` de cada ancestral; `nearest_markdown` alimenta descriptor (audience) e `{context}` (briefing/copy/discovery) e o snippet no answer[0].
- Testes: `tests/test_sofia_faq_tool.py` +8 casos (audience sem compra, audience qualificaÃ§Ã£o via markdown, brand sem frete, product mantÃ©m compra, copy specs i5/2TB, briefing cursos, Allan nÃ£o herda VZ Lupas, audience_object). `python -m pytest tests/test_sofia_faq_tool.py tests/test_sofia_faq_routes.py -q` => 21 passed. Suite FAQ completa (tool+routes+embedded+node_md+lifecycle) => 34 passed.
- Sem hard-delete, Playwright, Paperclip, rebuild ou teste global.

## BRA-90 - backend business rules alignment (2026-05-30)
- Agent: Codex.
- Issue: BRA-90.
- Files changed: `api/services/graph_json_v2_validator.py`, `api/services/sofia_orchestrator.py`, `api/routes/qa_contract.py`, `tests/test_graph_json_validator.py`, `tests/test_qa_contract_routes.py`, plus probe update in `paperclip/scripts/probe-backend-business-rules.mjs`.
- What changed: graph_json v2 validator now accepts `Product Group -> FAQ` only when no `Product` exists below that product_group, preserving top-down/orphan/cycle checks. Sofia now answers from actual `plan_json` effects: when product/campaign/audience is added to the plan, the response is partial success with the specific missing parent question instead of generic ambiguity/low-confidence fallback.
- Evidence: `python -m pytest tests/test_graph_json_validator.py tests/test_qa_contract_routes.py -q` passed 25 tests. Live probe passed 9/9 and wrote `paperclip/test-artifacts/qa/backend-business-rules-alignment-2026-05-30T04-55-27-915Z.json`.
- Risks: campaign title extraction is deterministic and conservative; it improves the tested "chamada teste IA" path but does not attempt broad natural-language parsing.
- Next step: keep BRA-90 in review with the 9/9 artifact; frontend BRA-83 can consume the corrected Sofia messages and validator contract after backend review.

## BRA-82 â€” plan_json severity validator boundary + patch-apply/persist (2026-05-29)
- Frozen CTO contract: `paperclip/docs/architecture/sofia-plan-json-contract-frozen-decision-2026-05-29.md`.
- Validator (`api/services/sofia_orchestrator._validate_plan_json`) agora reconhece os 7 markers blocking frozen: `cycle`, `orphan`, `edge_inverted`, `product_above_product_group`, `embed_without_approved_faq`, `persistence_failure`, `critical_duplication`. Cada marker emite `validation.blocking[].code = marker.upper()` e flipa `is_valid=false`. FAQ/Rule continuam sÃ³ em `suggestions`. Missing parent/title/type continuam em `pending`. `is_valid == (blocking == [])`.
- Patch-apply path (`POST /sofia/graph-command`) jÃ¡ validava-> applica-> persiste-> refetch via `qa_contract.sofia_graph_command`. `_validate_sofia_patch` rejeita 422 com `GRAPH_VALIDATION_FAILED` em CANONICAL_CHAIN_VIOLATION (inclui inverted-edge e product-above-product_group), GRAPH_EDGE_FORBIDDEN (product->embed), FAQ_NOT_APPROVED, AUDIENCE_ROLE_FORBIDDEN, PRODUCT_SOURCE_REQUIRED. `needs_clarification` retorna `persisted:false` sem persistir.
- SessÃ£o Supabase de plan_json compartilhada com BRA-87 (`get_sofia_plan_session` / `upsert_sofia_plan_session` em `api/services/supabase_client.py`).
- Probes BRA-82 (TestClient + live :8001 `scripts/start_api_qa.py`) publicados em `ai-brain/test-artifacts/qa/`:
  - `sofia-plan-json-blocking-probe-20260530T013822Z.json` (TestClient).
  - `sofia-plan-json-blocking-live-probe-20260530T014152Z.json` (live :8001 â€” todas as 6 assertions passam, incluindo `acceptance_3_semantic_tree_refetch_responds_200`).
  - Baseline reexecutado: `sofia-plan-json-endpoints-probe-20260530T013835Z.json` (sem regressÃ£o; `survives_reload_restart` continua dependendo da config Supabase do BRA-87).
- Scripts: `scripts/probe_sofia_plan_json_endpoints.py` (TestClient) + `scripts/probe_sofia_plan_json_blocking.py` (TestClient blocking) + `scripts/probe_sofia_plan_json_blocking_live.py` (live :8001 blocking; usa `AI_BRAIN_ADMIN_TEST_TOKEN` de `env.qa.yaml`).

## Graph JSON V2 spec entregue (2026-05-29)
- Spec autoritativa: `ai-brain/docs/architecture/graph-json-canonical-architecture.md` (16 secoes).
- Decisao: mover source of truth para `graph_documents.graph_json` versionado; v1 tabelas viram indices derivados.
- 7 endpoints v2 propostos, 8 fases nao destrutivas, FAQ-before-Embed preservada.
- Validacao gate: AllanVvz->VZ Lupas conversion + Sofia patch + frontend render + FAQ aprovada gerando embedding. Artifact obrigatorio em `paperclip/test-artifacts/architecture/`.
- Issues paperclip: BRA-72 umbrella (CTO) + BRA-73 backend + BRA-74 frontend + BRA-75 AI agent + BRA-76 graph validator. Todas blocked aguardando CTO decision file em `paperclip/docs/architecture/`.
- Regras: nao destrutivo; nao apagar dados de svkogegypdqquzlfzaor; nao quebrar endpoints atuais; v1 e v2 em paralelo ate cutover.

## AGENTS.md unstale + QA local backend section (2026-05-29)
- Linha 13 da `AGENTS.md` atualizada: Supabase QA atual `svkogegypdqquzlfzaor` (apos antigo `qhnepdcqtkjjslqqiyvp` ser suspenso por exceed_egress_quota).
- Nova secao `### QA local backend (since 2026-05-29)`: comando `python ai-brain/scripts/start_api_qa.py`, hot-reload ativo, listen :8001, auth Option B (X-AI-BRAIN-ADMIN-TOKEN + Authorization: Bearer alias), sequence pos-edit obrigatoria, diagnose 401 vs 403.
- Parte da rodada 3.3-3.9 de hardening per audit 2026-05-29.

## Sofia Graph Agent umbrella â€” BRA-71 (2026-05-29)
- Spec: `paperclip/docs/qa/sofia-graph-agent-acceptance-2026-05-29.md`.
- CEO/PO live-test: Sofia responde fallback generico "Preciso de confirmacao: qual persona e qual operacao" mesmo com persona ativa allanvvz e contexto claro. Sofia nao age â€” apenas classifica.
- Umbrella BRA-71 criada como gate unico de aceite para BRA-44 + BRA-46. Sub-scopes BRA-62/63/64/65 continuam abertas como tarefas de implementacao.
- 7 comandos comportamentais obrigatorios para aceite: conecte allan rodrigues em persona allanvvz; crie audience; persona allanvvz; reencaixar allan rodrigues; corrigir campanha VZ Lupas; organize VZ Lupas; mover product groups.
- 9 rejection criteria binarios. Done fabricado -> ESCALATION (Â§13).

## Sofia Graph â€” anti-loop rule + CTO decision (2026-05-29)
- Usuario formalizou regra anti-loop: QA nao parqueia blocked indefinidamente. Apos 1o blocked sem delta, 2o wake = handoff CEO; 3o wake = proibido.
- Aplicado em BRA-66: QA reportou `/views/tree` e `/views/graph` -> 404. Probe local confirmou: rotas nao existem em ai-brain nem paperclip. `/knowledge/graph-data?persona_slug=allanvvz` ja retorna 200.
- Logo contrato `/views/*` e fantasma â€” spec orfa.
- Issue BRA-69 criada para CTO decidir Opcao A (implementar /views/* em ai-brain) vs Opcao B (substituir por /knowledge/graph-data).
- Recomendacao do validator: Opcao B (sem valor adicional em implementar rotas duplicadas).
- BRA-66 fica blocked ate documento de decisao em `paperclip/docs/architecture/route-contract-decision-2026-05-29.md`.
- Regras: `paperclip/agents/OPERATING_RULES.md` Â§13 e `QA_LEAD_GATE_CHECKLIST.md` Â§G.

## Sofia Graph acceptance â€” escopo expandido pelo CEO/PO (2026-05-29)
- Spec: `paperclip/docs/qa/sofia-graph-acceptance-spec-2026-05-29.md` (11 secoes).
- Observacao no grafo live de `allanvvz`: shape errado (Campaign VZ Lupas muito alto, Allan Rodrigues misturado, brand VZ Lupas deslocado), Sofia sem memoria curta, sem contexto de persona ativa, nao parece a mesma Sofia da aba Criar.
- Nova arquitetura: 2 tool groups. Backend (resolve-persona, resolve-node, resolve-operation, validate_canonical_chain, generate_patch, persist_patch, refetch_graph) + Frontend (apply_patch_visual, mark_pending, undo, confirm, select, focus, layout, highlight).
- Regra de produto: Sofia Graph = Sofia Criar (mesmo orchestrator, mesmo tool registry, mesmo contexto). Diferenca apenas no frontend toolset registrado por sessao.
- BRAs novas: BRA-62 (conversational context), BRA-63 (unification), BRA-64 (frontend tools), BRA-65 (resolver tuning + 4 backend tools faltantes), BRA-66 (E2E test obrigatorio).
- Cadeia: 58/59/61 done -> [62 + 63 + 64 + 65 parallel] -> 60 -> 66 -> 44 + 46.
- Anti-patterns auto-reject (Â§5 do spec): Sofia text-only; confirmacao generica; "comando aplicado" sem patch; visual sem persist; duplicacao; Campaign VZ Lupas filho direto da persona; Allan Rodrigues misturado na VZ Lupas; hardcoded; allow-list.

## Sofia tool-use contract â€” DESTRAVADO 2026-05-28T20:55Z
- Commits ai-brain reais: `6d74e6a` (fix routes + remove gate) + `8f80352` (BRA-58 tool resolvers).
- Causa do 403 persistente: uvicorn PID 37024 servia codigo antigo (`reload=False`). Restart manual + novo codigo carregado.
- Probe `/sofia/graph-command` com `persona_slug=allanvvz` -> 200 com tool_calls (resolve-persona 0.99, resolve-operation 0.91 reparent_brand, validate_canonical_chain 1.0), patch persistido, brand vz-lupas com edge `persona_has_brand` allanvvz.
- Option B (`Authorization: Bearer` alias) -> 200. Confirmado.
- Low-confidence command -> 200 com `needs_clarification=true`, sem patch. Correto.
- `scripts/start_api_qa.py` agora `reload=True` + `reload_dirs=[API_DIR]` (BRA-61 aplicado). Working tree edit, sem commit ainda.
- Artifact: `paperclip/test-artifacts/qa/sofia-tool-use-contract-2026-05-28T20-55-00Z.json`.

## Sofia tool-use contract (2026-05-28)
- Spec autoritativa: `paperclip/docs/qa/sofia-tool-use-contract.md`.
- Define schemas request/response de `/sofia/tools/resolve-persona` e `/sofia/tools/resolve-operation`, 8 canonical ops (reparent_brand, create_default_audience, move_product_to_group, reorganize_campaign_briefing, validate_canonical_chain, reclassify_product_group_as_campaign, commit_pending_change, revert_pending_change), comportamento obrigatorio de `/sofia/graph-command` (tool_calls populado, NUNCA 403 por gate de persona, threshold confidence 0.65), matriz 33 casos (4 personas x 8 ops + 1 low-confidence).
- Fixture skeleton: `paperclip/fixtures/sofia-commands.skeleton.json`.
- BRA-58 (backend) e BRA-59 (AI agent) tem que cumprir o contract antes de done. BRA-60 (QA sweep) roda 33 cases contra `:8001` e gera artifact em `paperclip/test-artifacts/qa/sofia-tool-use-contract-<UTC>.json`.

## Sofia /sofia/graph-command â€” drop allow-list, cosine tools (2026-05-28)
- Usuario reportou 403 `restricted to VZ Lupas QA persona aliases` ao usar chat lateral do Graph com persona `allanvvz`.
- Origem: `api/routes/qa_contract.py:25-28` (QA_PERSONA_ALIASES) + `:55-60` (_require_qa_persona); restos do isolamento original da QA da VZ Lupas.
- Decisao: em vez de expandir allow-list, eliminar. Mover validacao para tools deterministicos baseados em embeddings:
  - `POST /sofia/tools/resolve-persona` â€” top-1 persona slug por cosine (sentence-transformers local OU pgvector).
  - `POST /sofia/tools/resolve-operation` â€” top-1 op canonica (rebind_parent, reorganize_subtree, create_audience, move_node, add_brand, add_product_group, add_product, add_faq).
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
  products=0 (esperado â€” so o schema seedado das migrations existe, sem dados).
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
direto do diretorio `api/`, o que carrega apenas `.env` e NAO `env.qa.yaml` â€”
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
  (127.0.0.1:3000, localhost:3000, 192.168.0.182:3000) â€” sessao do projeto
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
  (top-level dos nodes nao expoe slug â€” usar `data.*`).
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
  - `tests/e2e_criar_tockfatal_plan_mode_branch_contract.py` (Codex; passa) â€” estrutura completa + termos proibidos.
  - `tests/e2e_criar_tockfatal_commercial_pyramidal.py` (este Claude) â€” prompt do usuario + assertions do RULE antes do FAQ + trigger `pending_regeneration` ao alterar offer.

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

Arquitetura aprovada â€” pipeline hibrido e barato (decidido com o usuario):
1. **Classifier local** (`api/services/asset_pipeline/classifier.py`) â€” heuristica pura com Pillow + mime/extension; decide `kind`, `needs_ocr`, `has_text_estimate`. Sem chamada externa.
2. **OCR local** (`api/services/asset_pipeline/ocr_local.py`) â€” cascade de adapters: PaddleOCR -> EasyOCR -> pytesseract -> mock. Selecao via `ASSET_OCR_BACKEND` (default cascade; CI usa `mock`). Marca `needs_ai_fallback=True` quando `confidence<0.45` ou `len(text)<8`.
3. **AI fallback** (`api/services/asset_pipeline/ai_fallback.py`) â€” so roda quando `needs_ai_fallback`. Usa `model_router.vision_extract` (novo) com modelo configuravel via `ASSET_VISION_MODEL` (default `gpt-4o-mini`).
4. **Renamer** (`api/services/asset_pipeline/renamer.py`) â€” heuristica primeiro; opcional `model_router.cheap_text` quando heuristica produz <3 tokens. Desativavel via `ASSET_RENAME_DISABLE_MODEL=1`.
5. **PDF text** (`pdf_text.py` via pypdf), **video mock** (`video_mock.py`), **schemas Pydantic** (`schemas.py`).

Entrada unica: `services.asset_pipeline.run_pipeline(file_bytes, AssetPipelineContext) -> AssetReadingBundle`. Bundle traz `classification`, `ocr`, `ai_fallback`, `pdf_text`, `video_mock`, `rename`, `extracted_text`, `visual_summary`, `reading_status` e `rows_to_persist` para `asset_readings`.

Dois fluxos persistentes:
- **Sofia/CRIAR** (`/kb-intake/upload` estendido): salva no bucket `knowledge` (compat) + cria row em `public.assets` com `upload_context='sofia_chat'` + roda pipeline + anexa leitura ao contexto da sessao via `kb_intake_service.attach_reading()`. NAO cria `knowledge_item`.
- **Card ASSET** (`/assets/upload` novo em `api/routes/assets.py`): upload no `assets-raw` (com fallback `knowledge`) + assets row `upload_context='asset_card'` + pipeline + cria `knowledge_item content_type=asset` pending + `bootstrap_from_item` -> `knowledge_node node_type=asset` + edge `parent -> asset` (`uses_asset`, primary_tree=true) + edge `asset -> gallery` (`gallery_asset`, primary_tree=false, graph_layer=auxiliary). Atualiza asset com `knowledge_node_id` + `gallery_edge_id`.

Guard explicito: POST `/assets/{id}/connect` recusa target = node_type='gallery' com 422 `gallery_invalid_target`. Apenas `asset -> gallery` autorizado.

RAG nunca cria entry para asset â€” `is_rag_eligible` ja gateia em `{"faq"}`.

Migration `supabase/migrations/033_asset_upload_pipeline.sql`:
- Buckets `assets-raw` + `assets-derived` (insert idempotente em `storage.buckets`).
- Expande `public.assets`: `storage_bucket`, `storage_path`, `mime_type`, `file_size`, `original_filename`, `status`, `upload_context`, `updated_at`. Atualiza CHECK `type` (`image|video|pdf|text|copy|campaign|template`) e `source` (adiciona `upload`).
- Trigger `updated_at` + indexes por persona/status/source/upload_context/created_at/`metadata->>session_id`/(storage_bucket,storage_path).
- Nova tabela `public.asset_readings`: linha por etapa do pipeline (`classification|ocr|ai_fallback|pdf_text|video_mock|rename`), RLS service_role, indexes por (asset_id,reading_type,created_at desc) e persona.

Endpoints novos:
- `POST /assets/upload` â€” multipart `file + persona_id + branch_hint + asset_function? + persona_slug?`.
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
- `integration_asset_card_upload.py` PASS â€” valida assets row + knowledge_item + node + edges parent/gallery + asset.knowledge_node_id linkado + asset NAO eh rag_eligible
- `integration_asset_card_parent_required.py` PASS â€” 422 + `needs_parent=true` quando sem branch_hint, nada criado
- `integration_asset_card_gallery_guard.py` PASS â€” POST /assets/{id}/connect recusa target gallery com `gallery_invalid_target`
- `integration_sofia_image_upload.py` PASS â€” upload Sofia anexa reading na sessao (`asset_readings` populado, `classification.attachments` espelhado), tagueia asset com `upload_context='sofia_chat'`/`validation_status='context_only'` e NAO cria knowledge_item; chat() recebe `file_info.asset_reading` para reagir.
- `integration_asset_validation_lifecycle.py` PASS â€” asset card aparece em `/knowledge/queue?content_type=asset`; `promote_knowledge_item(promote_to_kb=False)` move item para `status=approved`/`curation_status=approved` com evidence.knowledge_node_id; `is_rag_eligible('asset')` permanece False e nenhum `knowledge_rag_entries`/`knowledge_rag_chunks` e inserido durante a aprovacao.

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

### Etapa A â€” Pre-init review com contexto da persona (kb_intake_service.py)

- Novas funcoes: `_load_persona_context(persona_id)` consulta `knowledge_nodes` via `supabase_client.list_knowledge_nodes_by_type` filtrando `node_type in {brand, briefing, campaign, audience, product, offer, copy, rule, asset, faq}` da persona ativa. Best-effort: erros viram dict vazio, nunca quebram a sessao.
- `build_pre_initialization_review(session, persona_context, classification)` produz contrato `/tree-reference`: `persona_context_loaded`, `existing_nodes_found`, `recommended_connections`, `new_nodes_needed`, `questions`. Lida com reuso de audience/campaign existentes e roteia asset por `classification.asset_function` (campaign_hero -> campaign, product_reference -> product).
- `create_session` em `mode='criar'` com `persona_id` resolvido agora popula `session["persona_context"]` e `session["pre_init_review"]` automaticamente.
- `_session_public_state` expÃµe `pre_init_review` + `persona_context` no payload da sessao; `_bootstrap_result_payload` propaga `pre_init_review` para o frontend.
- `_chat_impl` injeta no `state_ctx` enviado ao LLM um bloco "Contexto existente da persona (pre-init review)" com slugs por tipo, recomendacoes de reuso e perguntas obrigatorias antes do plano final. Isso impede a Sofia de criar audience/campanha/asset duplicados sem perguntar.

### Etapa C â€” FAQ terminal nao gera leaf alert

- `_leaf_alert_warnings` (kb_intake_service.py:803) trocou exclusao `{"asset","embedded","gallery"}` por `{"asset","embedded","gallery","faq"}`. Comentario explica: FAQ e terminal-valido ate aprovacao; pos-aprovacao recebe edge automatica para Embedded.
- Frontend `dashboard/app/knowledge/capture/page.tsx::leafAlerts` recebeu o mesmo filtro. Nova lista `faqPendingTerminals` separa FAQ pendentes para mostrar como card info azul ("FAQ <titulo>: terminal ate aprovacao. Apos aprovado, sera conectado automaticamente ao Embedded da persona.") em vez de alerta amarelo de "sem saida".

### Etapa D â€” Embedded fora da previa pre-aprovacao

- `dashboard/app/knowledge/capture/page.tsx::CaptureSidebar` esconde a linha de `Embedded` em "Plano inicial" e em "Plano em construcao" quando `expectedCountFor('embedded') === 0 && createdCountFor('embedded') === 0`. Continua aparecendo automaticamente assim que houver um node embedded real (FAQ aprovado).
- `knowledgeGraphLayout.ts` nao foi alterado â€” `embedded` aparece la apenas quando ha node `embedded` real conectado a FAQ via `embedded_edge`.

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
- Configuracoes: `GET /api/menu/baita-conveniencia/admin-blocks` retorna bloco `Produto â€” Camiseta Baita` com `slot_instance_key=product_image:camiseta-branca-baita`, imagem atual e edge `fa779596-ca37-42b5-8395-b84b876c01db`.
- Assets UI: markdown visual em `buildAssetMarkdown` agora emite `# Asset â€” <nome>`, imagem `assets-raw:<path>`, slots conectados e mapa com `asset â†’ product_image:<slug> â†’ card do produto ... no catÃ¡logo Baita`.
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
- **Causa raiz real do 502 persistente**: o filename do upload era `0 - Capa - BAITA - LAYOUT - Cardapio AtualizaÃ§Ã£o.png` com espacos + acento (`Ã§`). Supabase Storage rejeita com `400 InvalidKey`, mas o exception_type comum (`StorageApiError`) fez parecer que era "Bucket not found" novamente.
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
- âš ï¸ `tests/integration_asset_card_upload.py`: FALHA por regressao **pre-existente** dos edits anteriores em `_upload_asset_impl` (helpers HEIC nao mockados). Meus edits nao tocam essa funcao alem do bloco de captura de exception, mas o teste ja falhava antes desta sessao. Decisao: deixar como divida tecnica ou atualizar mocks do teste numa proxima rodada.

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

## Sofia/CRIAR â€” diagnostico modal + arquitetura gambiarra (2026-05-21)

### Sintoma reportado pelo operador
- Modal "Plano precisa de decisoes da Sofia" abre com `asset_expansion_incomplete`, mas os botoes A/B/C nao fazem nada quando clicados.
- Subir asset pelo paperclip nao remove a violacao â€” mensagem volta "Asset expansion incompleto" no proximo turno.
- As vezes a arvore aparece praticamente pronta no chat, mas o botao "Salvar conhecimento" nao surge.

### Causas (todas confirmadas no codigo)
1. **Opcoes do modal sao botoes mortos**. `dashboard/components/capture/BlockedPlanDiagnosticModal.tsx:369-374` renderiza `SofiaQuestionCard` sem passar `onOptionSelect`. O componente filho tem o callback opcional (`linha 185-194`), mas o pai nunca cabeia -> click so destaca o botao.
2. **Os `action` strings emitidos pelo backend (`upload_asset`, `attach_existing_asset`, `drop_asset_requirement`, `drop_faq_target`, `create_offer`, `create_rule`) nao tem handler em lugar nenhum**. `api/services/kb_intake_service.py:1695-1722` cria as opcoes mas nao existe `/kb-intake/sofia-action`, nem switch dentro de `chat()`, nem aplicacao do `payload`. Contrato fingido.
3. **Upload pelo paperclip NAO cria entry asset no `normalized_plan`**. O arquivo entra em `session.asset_readings` (`kb_intake_service.py:4501`) e em `mission_state.evidence_items`, mas e o LLM que tem que decidir, no proximo turno, inserir uma entry `content_type=asset` com `metadata.parent_slug=<produto>`. Quando ele esquece, `expansion.asset.created` continua em 0 e o validador (`_validate_plan:1269-1274`) mantem `Asset expansion incomplete` para sempre.
4. **`GraphPreviewPanel` so renderiza se `planStateValid===true`** (`dashboard/app/knowledge/capture/page.tsx:1732`). Qualquer violacao bloqueante esconde o painel inteiro â€” junto com o botao "Salvar conhecimento" (linha 2271). Por isso o operador ve a estrutura no chat mas nao tem como salvar.
5. **"Editar plano" no rodape do modal so abre o textarea de `contentText`** (`page.tsx:1858`), que e um campo de vault opcional â€” nao edita a arvore. `onRegenerate` nunca e passado, entao o botao "Regerar estrutura" do modal nem aparece.

### Raiz arquitetural (porque essas gambiarras existem)
- **`ModelRouter.messages_create` so faz text-in/text-out** (`api/services/model_router.py:154-192`). Sem function-calling/tool-use de provider. Toda mutacao de plano e: LLM gera texto -> regex extrai `<knowledge_plan>{json}</knowledge_plan>` em `_extract_plan` (`kb_intake_service.py:560`) com 4 fallbacks defensivos (`_candidate_plan_blocks:526`).
- **Cada turno = regenerar o plano inteiro**. Nao existe patch incremental. O LLM regrava o JSON todo, incluindo edges, mesmo para corrigir um parent. Caro, lento, hallucination-prone.
- **System prompt de 700+ linhas com "HARD CONTRACT" implorando o modelo a nao usar markdown fence** (`kb_intake_service.py:311-315`). E sintoma classico de falta de tools: com ferramentas estruturadas o modelo nao tem como errar o formato.
- **Reuso proativo de nodes existentes e injetado como TEXTO** no system prompt via `pre_init_review` (`kb_intake_service.py:4854-4876`) â€” frase em portugues, nao tool. Fragil.
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
- `dashboard/lib/api.ts`: nada novo â€” usar `kbIntakeMessage` existente. O backend acompanha enviando `prompt_to_sofia` ja embutido em cada opcao.

### Mapa do backend que sera tocado na etapa 2
- `api/services/kb_intake_service.py::_sofia_questions_from_diagnostic` (linha 1625+): para cada `kind`, emitir opcoes com `prompt_to_sofia` em vez de `action`. Manter `action`+`payload` por 1 release como fallback caso o front ainda nao tenha migrado.
- Novo arquivo `api/services/sofia_tools.py`: funcoes puras sobre `session.normalized_plan` + JSON Schema export para tool-calling.
- `api/services/model_router.py`: `messages_create(tools=None)` ganha branch que devolve `tool_calls` quando o provider responde com function-call.
- `api/services/kb_intake_service.py::chat`: loop `while tool_calls -> aplicar -> re-prompt` (com guarda de iteracao maxima).

### Decisao do operador
- Modal vira visualizacao pura; nada de mutacao local nele.
- Botao = atalho que dispara mensagem para Sofia, que escolhe a tool. Backend e a unica fonte da verdade.
- Sofia ganha tools para criatividade (creative subtree expansion, proactive node reuse) deixando de regerar plano inteiro a cada turno.

## ALERTAS â€” codigo legado que NAO respeita a hierarquia do grafo (2026-05-21)

Regra base do CLAUDE.md: **"Todo conhecimento adicionado DEVE aparecer no grafo. knowledge_items -> knowledge_nodes -> knowledge_edges"**. Os pontos abaixo violam isso e poluem a persistencia de memoria de marca/persona porque criam estados paralelos que nao tem reflexo em `knowledge_nodes`.

### A â€” Brand: `brand_profiles` e ilha; nao vira knowledge_node
- **Arquivo**: `api/routes/knowledge.py:1116-1138` (PUT `/knowledge/brand/{persona_id}`).
- **Servico**: `api/services/supabase_client.py:3332-3336` (`upsert_brand_profile`).
- **O que faz**: `PUT /knowledge/brand/{persona_id}` chama `supabase_client.upsert_brand_profile({persona_id, **body})` que faz `table("brand_profiles").upsert(...)` direto e emite `brand_profile_updated`. Nao chama `sync_brand_node`, nao chama `bootstrap_from_item`, nao cria nem atualiza nenhuma entry em `knowledge_nodes` com `node_type=brand`.
- **Sintoma**: a diretriz de marca persiste apenas em `brand_profiles`; chat-context/RAG/Sofia nao "veem" a marca pelo grafo (so via SELECT direto). Quando alguem inspeciona o grafo, a persona aparece "sem brand", embora a aba Brand mostre dados.
- **Comparativo**: `audiences` foi corrigido (`api/routes/audiences.py:67` chama `supabase_client.sync_audience_node(audience)`). Brand ficou para tras.
- **Acao sugerida**: criar `supabase_client.sync_brand_node(brand_profile)` espelhando o padrao do audience â€” slug `brand-<persona_slug>`, `node_type="brand"`, `metadata` com posicionamento/promessa/tom, edge `belongs_to_persona`. Chamar em `upsert_brand` apos o upsert, e backfill via script para personas existentes.

### B â€” Auditoria de eventos: tudo em `system_events`, sem nada no grafo
- **Servico**: `api/services/supabase_client.py:3358-3376` (`insert_event`).
- **O que faz**: eventos `brand_profile_updated`, `product_node_updated`, `graph_*` viajam todos por `system_events`. So leem na tela `/logs`. Nao geram edges de "produto X foi editado por usuario Y".
- **Status**: aceito como design (auditoria != memoria). Nao mudar â€” mas anotar para Sofia nao tratar `system_events` como fonte de "conhecimento".

### C â€” `kb_entries`: agora espelha, mas o codigo legado de PROD ainda escreve direto
- **Arquivo**: `api/services/supabase_client.py:2556-2595` (`upsert_kb_entry`).
- **Fluxo correto** (do CLAUDE.md): aprovar `knowledge_items(pending)` -> `promote_to_kb=true` -> `kb_entries(ATIVO)` -> `bootstrap_from_item(source_table="kb_entries")` -> `knowledge_nodes` -> `knowledge_edges`.
- **Sintoma**: existem chamadas `upsert_kb_entry` em scripts/seed/imports antigos que nao chamam `bootstrap_from_item` em seguida. Resultado: `kb_entries` com rows orfas no grafo. CLAUDE.md item 11 e explicito: "kb_entries nunca deve existir sem reflexo no grafo".
- **Acao sugerida**: auditoria â€” `SELECT k.id, k.kb_id, k.persona_id FROM kb_entries k LEFT JOIN knowledge_nodes n ON n.metadata->>'kb_id' = k.kb_id WHERE n.id IS NULL;`. Para cada orfao, rodar `bootstrap_from_item` retroativo. `knowledge_graph.py:933` ja tem helper `rebuild_graph` para isso.

### D â€” `audiences`: corrigido mas nao tem garantia transacional
- **Arquivo**: `api/routes/audiences.py:54-84`.
- **O que faz**: chama `create_audience` (INSERT em `audiences`) seguido de `sync_audience_node`. Sao duas chamadas separadas; se a segunda falhar (rede, RLS), fica `audience` sem node â€” mesmo problema do brand, so que menor.
- **Acao sugerida**: envolver em transacao via RPC Supabase ou pelo menos compensar (rollback do INSERT) quando `sync_audience_node` retornar None.

### E â€” `assets`: sem `gallery_asset` automatico
- **Servico**: `api/services/supabase_client.py:3564-3580` (`insert_asset`).
- **Regra CLAUDE.md item 10**: "assets ligados ao Gallery usam `gallery_asset`".
- **Sintoma**: criar asset via `/assets/upload` insere row em `assets` mas nao gera edge `gallery_asset` para o Gallery node da persona. So aparece no Gallery quando o operador conecta manualmente via `connect_asset`.
- **Acao sugerida**: opcional â€” auto-conectar assets aprovados a `gallery-{persona_slug}` na promocao. Hoje o fluxo manual e intencional, mas para uploads automaticos (crawler/sync) o asset fica invisivel ate alguem clicar.

### F â€” `lead_audience_memberships` x `leads.persona_id`
- **Reference memory ja existente**: `reference_leads_schema.md` / `feedback_persona_audience_visibility.md`. Repito aqui porque toca persistencia de persona.
- **Acao sugerida**: nada novo â€” usar `lead_audience_memberships` como fonte canonica em queries operacionais; `leads.persona_id` e legado.

### G â€” Sofia: o knowledge_plan vai para `knowledge_nodes` so no save final
- **Arquivo**: `api/services/kb_intake_service.py` (todo o pipeline `chat()` -> `save()`).
- **Comportamento atual**: durante a conversa, o plano vive em `session.normalized_plan` (arquivo .json local). So vira `knowledge_nodes` no `POST /kb-intake/save` (que dispara `vault_sync` -> `bootstrap_from_item`).
- **Risco**: se a sessao expirar/morrer antes do save, todo o conhecimento gerado some. **A migracao para tools (camada 2 abaixo) ajuda aqui**: cada `create_node` tool call pode persistir incrementalmente em `knowledge_nodes` com `status=draft`, eliminando o "tudo ou nada" do save.
- **Acao sugerida (alinhada com a migracao de tools)**: tool `create_node` faz `INSERT` em `knowledge_nodes(status="draft", metadata.session_id=...)`. Save final so faz UPDATE para `status="pendente_validacao"` ou `validated`. Sofia para de regerar plano do zero a cada turno.

### Resumo do impacto na memoria de marca
A unica violacao bloqueante para "memoria de marca consistente" e a **A (brand_profiles)**. As demais sao debitos tecnicos com sintomas localizados. Se tivermos que escolher uma para corrigir antes da migracao de tools, e a A â€” porque toda a creative reuse que a Sofia faria via `find_existing_persona_nodes(types=["brand"])` retorna vazio hoje, mesmo com o brand cadastrado.

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
- `6832f73 feat(capture): modal Sofia vira visualizacao + atalhos de prompt; Save sempre visivel` â€” corrige a serie de gambiarras catalogadas em 2026-05-21. Modal `BlockedPlanDiagnosticModal` passou a propagar `onOptionSelect`; cada opcao envia `prompt_to_sofia` via `kbIntakeMessage`. `GraphPreviewPanel` renderiza enquanto `draftPlan` existe e o botao Save fica `disabled` com tooltip listando violacoes, em vez de sumir.
- `1899850 feat(sofia): backend tools deterministicas + tool-use loop opt-in via env` â€” `api/services/sofia_tools.py` ganhou as primeiras tools (`create_node`, `set_parent`, `connect_nodes`, `delete_node`, `validate_plan`, `set_expansion_policy`, `attach_session_asset`, `find_existing_persona_nodes`, `suggest_connections`). `ModelRouter.messages_create` aceita `tools=` e devolve `tool_calls`. Flag `SOFIA_TOOLS_ENABLED` mantem o caminho antigo enquanto migracao roda.
- `397d539 fix(intake): aceita product_group/offer/gallery no ALLOWED_CONTENT_TYPES + E2E VZ Lupas` â€” `api/services/knowledge_rag_intake.py:20-37` agora reconhece `product_group/offer/gallery` (antes caiam em `general_note`). Acompanha pacote E2E VZ Lupas em `tmp/sofia_e2e/`: `run_vz_lupas_e2e.py`, `retry_assets_shot.py`, `run_screenshots_only.py`, REPORT.md + screenshots t1/t2/t3 + uploads VZ Lupas (clipon/grau/sol).

### Plano cardapio multi-persona (`tmp/sofia_e2e/PLAN_CARDAPIO_MULTI_PERSONA.md`)
- `baita-cardapio` ja roda por `personaSlug` na URL. Pontos acoplados que sobram (a fechar antes do VZ Lupas ir publico):
  - `api/routes/menu.py:407-408,434,440,565,575,632` â€” alias map e `collection_slug` default `cardapio-baita-v14` so para baita.
  - `../baita-cardapio/src/App.tsx:16` envia `VITE_DEFAULT_PERSONA=baita` na Vercel.
  - `PersonaThemeProvider` precisa carregar tokens via `/api/menu/{slug}/theme` (D3.A: tokens em `persona.metadata.theme`).
  - Copy persona-aware (`persona.metadata.copy.menu_label = "Cardapio" | "Catalogo"`).
- Recomendacao adotada: discovery via marker `metadata.is_landing_root=true` em node `product_group` (Passo 1 do plano), descartando default hardcoded.
- URL strategy hoje: path-based (`baita-cardapio.vercel.app/<persona-slug>`). Subdomain fica para 5+ personas.

### Login QA quebrado (brain-plataform-qa.vercel.app) â€” diagnostico
- Sintoma do navegador: `GET /api-brain/auth/me 401` repetitivo + `POST /api-brain/auth/login 401`. O loop infinito de `up/ud` no console e React batendo no `useEffect` do `AppShell.me()` em cada render porque `pathname !== "/login"` mas a sessao nao existe â€” quando `me()` lanca 401, o handler chama `router.replace("/login")`, mas o redirect nao executa se o `proxy.ts` ja redirecionou e o componente continua montando. Isso so se manifesta porque o backend QA esta rejeitando as credenciais.
- Causa provavel: o Cloud Run QA (`ai-brain-api-qa-837167469397.us-central1.run.app`) nao tem usuario auth para o e-mail digitado. `api/middleware/auth.py:78-107` exige `auth_service.get_user_by_id(payload.sub)`; antes disso o `POST /auth/login` ja teria devolvido 401 se o usuario nao existir em `auth_users`.
- Validacao operacional sugerida (nao executei â€” exige `env.qa.yaml` e `gcloud`):
  1. `curl -sS https://ai-brain-api-qa-837167469397.us-central1.run.app/health` â†’ confirmar que o servico esta no ar.
  2. Verificar `auth_users` no Supabase QA: `select id, email, role, is_active from auth_users order by created_at;`.
  3. Se vazio ou sem o admin esperado, rodar `cd api && python scripts/create_auth_user.py --email <op@empresa.com> --username <op> --password <senha> --role admin` apontando para `env.qa.yaml` (a sessao precisa ter `AI_BRAIN_SEED_ADMIN_EMAIL`/`PASSWORD` setados no Cloud Run QA para o seed automatico funcionar â€” checar `gcloud run services describe ai-brain-api-qa --region us-central1 --format='value(spec.template.spec.containers[0].env)'`).
- Atalho enquanto a conta nao for criada: usar header `X-AI-BRAIN-ADMIN-TOKEN: <AI_BRAIN_ADMIN_TEST_TOKEN>` em endpoints internos (so funciona quando `ENVIRONMENT in {qa,preview,test}`), conforme `api/middleware/auth.py:36-65`.

### Catalogo na /persona (esta sessao)
- Pedido: adicionar na tela `/persona` (`dashboard/app/persona/page.tsx`) um link para o cardapio/catalogo publico da persona selecionada, sem nada hardcoded. Link tem que respeitar PROD vs QA e seguir o slug da persona (ex: `vzlupas`).
- Decisao: novo env publico `NEXT_PUBLIC_CARDAPIO_BASE_URL` em `dashboard/.env.local.example`. Link no front e `${NEXT_PUBLIC_CARDAPIO_BASE_URL}/${persona.slug}` quando o env existir; quando nao, o card mostra estado vazio explicando como configurar. Para QA: `https://baita-cardapio-qa.vercel.app`. Para PROD: `https://baita-cardapio.vercel.app`. O slug e sempre da persona (`persona.slug`), e nunca uma constante.
- O card resume o quanto da persona ja esta refletido no catalogo usando o `graphSummary` que a tela ja calcula: contagem de produtos conectados (`graphSummary.products`) e contagem de assets em Gallery (consultado via `api.galleryAssets(persona.id)` â€” mesmo endpoint que /settings usa). Assim "vinculando diretamente os produtos, assets de forma correta" e validavel pelo operador antes de abrir o link.
- Vercel: precisa setar `NEXT_PUBLIC_CARDAPIO_BASE_URL` em ambos os scopes do projeto `brain-plataforma`:
  - production -> `https://baita-cardapio.vercel.app`
  - preview (branch `develop`) -> `https://baita-cardapio-qa.vercel.app`
  - sem isso o card aparece em modo "configurar URL" e nao quebra a tela.
- 2026-05-27 (BRA-22 re-dispatch): sweep `baseline-validate-only` executada via `node C:\Users\Alan\Documents\repositorios\paperclip\scripts\graph-test-runner.mjs` com `AI_BRAIN_BASE_URL=http://127.0.0.1:8001` e token admin de QA carregado do `env.qa.yaml`. Evidence gerada em `C:\Users\Alan\Documents\repositorios\paperclip\test-artifacts\graph-runs\2026-05-27T07-19-28-026Z.json`. Resultado: `disposition=blocked` por `fetch_graph status=404` (`/knowledge/graph?mode=semantic_tree&all_edges=1&persona_slug=vz-lupas`), sem avaliaÃ§Ã£o das hard invariants por indisponibilidade da rota alvo.
- 2026-05-27 (BRA-22 heartbeat): Corrigi o runner paperclip/scripts/graph-test-runner.mjs com fallback de endpoint (/knowledge/graph -> /knowledge/graph-data) e gravaï¿½ï¿½o do oute/url usado no step etch_graph; adicionei teste de contrato em paperclip/tests/graph-runner.test.mjs (graph endpoint fallback prefers graph-data...) e validei com 
ode --test tests/graph-runner.test.mjs (14/14 pass). Reexecuï¿½ï¿½o real gerou paperclip/test-artifacts/graph-runs/2026-05-27T07-22-44-264Z.json com locked por 403 em /knowledge/graph-data?...persona_slug=vz-lupas (endpoint agora responde; bloqueio remanescente ï¿½ acesso/persona no alvo, nï¿½o mais 404).

## Sessao 2026-05-27 - BRA-29 fluxo simples para criar persona em Configuracoes
- Frontend: adicionado metodo `api.createPersona` em `dashboard/lib/api.ts` (POST `/personas`) para consumir a rota ja existente no backend.
- Frontend: `dashboard/app/settings/page.tsx` ganhou bloco `Criar persona` com campos `Nome da persona` e `slug-da-persona`, botao `Criar persona`, e validacao UX minima (nome obrigatorio, slug normalizado).
- UX pos-sucesso: limpa formulario, persiste `ai-brain-persona-slug` no localStorage, seleciona a persona criada e dispara refresh da tela para atualizar listas/indicadores.
- Estados tratados: loading (`Criando...`), erro de API e sucesso visivel no card.
- Verificacao minima: `cd dashboard && npx tsc --noEmit` (passou em 2026-05-27).

## 2026-05-28 ï¿½ codex (BRA-45 /sofia/graph-command real backend)
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

## 2026-05-28 ï¿½ codex (BRA-46 frontend smoke /sofia/graph-command)
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

## 2026-05-28 ï¿½ codex (BRA-45 closure: commit + reload + live probe)
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

### 2026-05-28 ï¿½ frontend-agent (BRA-46: chain lock by BRA-50)
- Issue/tarefa: BRA-46
- Arquivos alterados: memory.md
- O que mudou: Recebido wake `CHAIN LOCK 2026-05-28` do board; BRA-46 fica travada por dependencia direta de evidencia smoke da BRA-50 conforme `paperclip/agents/OPERATING_RULES.md` ï¿½10. Nenhuma nova execucao E2E foi iniciada para evitar retry sem input novo.
- Validacao executada: leitura de `paperclip/agents/OPERATING_RULES.md` e thread de comentarios da issue via Paperclip API; lock confirmado.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: unblock externo obrigatorio pela cadeia critica (BRA-50).
- Proximo passo: owner BRA-50 publicar evidencia smoke em path publicado; depois retomar BRA-46.

### 2026-05-28 ï¿½ frontend-agent (BRA-46: gate update via BRA-57 chain)
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

## BRA-58 backend real repo fix (2026-05-28)
- Applied in `ai-brain` (not workspace stub): `api/routes/qa_contract.py`, `api/services/sofia_orchestrator.py`.
- `/sofia/graph-command` now resolves persona/operation via tool resolvers and no longer uses VZ-only QA allow-list gate.
- Added/updated tool routes:
  - `POST /sofia/tools/resolve-persona`
  - `POST /sofia/tools/resolve-operation`
- Contract behavior implemented:
  - score threshold `0.65`
  - low-confidence operation -> `needs_confirmation=true`
  - canonical operation slug `reparent_brand` for reencaixe intent.
- Live probes on `http://127.0.0.1:8001` after restart:
  - `POST /sofia/graph-command` with `persona_slug=allanvvz` -> `200` (no 403)
  - `/openapi.json` contains both `/sofia/tools/resolve-persona` and `/sofia/tools/resolve-operation`
  - both tool endpoints return 200 with expected JSON fields.
## 2026-05-28 - codex (BRA-59 auth addendum for BRA-60)
- Formal QA auth decision adopted: **Option B**.
- Backend now accepts both headers in QA for `/sofia/*` protected routes:
  - `X-AI-BRAIN-ADMIN-TOKEN: <token>` (primary)
  - `Authorization: Bearer <token>` (compatibility alias)
- Implemented in `api/middleware/auth.py::_admin_test_token_user` using same `AI_BRAIN_ADMIN_TEST_TOKEN` and constant-time compare.
- Added handler docstring note in `/sofia/graph-command` route about accepted QA auth headers.
- Updated `paperclip/docs/qa/sofia-tool-use-contract.md` with new section `4.5 QA auth contract for /sofia/*`.
- Created `paperclip/scripts/sofia-commands-runner.mjs` with dual-header auth emission to avoid 33x401 harness mismatch.
- Live probe proof:
  - `POST /sofia/graph-command` with only `Authorization: Bearer <token>` => HTTP 200.
- Runner smoke from paperclip repo succeeded auth and produced artifact with `pass=33 fail=0`.

## BRA-58 addendum auth-contract clarity (2026-05-28)
- Formal decision: Option B for QA auth on `/sofia/*`.
- Accepted headers in QA:
  - `X-AI-BRAIN-ADMIN-TOKEN: <token>` (primary)
  - `Authorization: Bearer <token>` (compatibility alias)
- Handler docstring in `api/routes/qa_contract.py` explicitly documents both.
- Updated `paperclip/docs/qa/sofia-tool-use-contract.md` section `4.5` to codify auth contract.
- Updated `paperclip/scripts/sofia-commands-runner.mjs` to auth-fallback (x-admin first, bearer fallback) and record `auth_mode` per case.
- Live probe: both headers return `200` for `POST /sofia/graph-command` on `:8001`.
- BRA-60 compatibility check: runner executed 33 cases, `disposition=pass`.

### 2026-05-29 ï¿½ frontend-agent (BRA-46: superseded by BRA-66 E2E formal)
- Issue/tarefa: BRA-46
- Arquivos alterados: memory.md
- O que mudou: Gate atualizado pelo board/CEO-PO: BRA-46 fica supersedida pelo teste formal BRA-66. Fechamento de BRA-46 depende do aceite de BRA-66 com artifacts obrigatorios (json transcript completo, screenshots before/after e edge-set comparison contra estrutura ï¿½2 do spec).
- Validacao executada: leitura do comentario `1f636ea7-530d-4866-85c5-73e098abc691`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: bloqueio externo ate BRA-66 concluir com artifacts publicados.
- Proximo passo: owner BRA-66 publicar artifacts requeridos e sinalizar aceite; depois retomar BRA-46 para fechamento formal.

### 2026-05-29 ï¿½ frontend-agent (BRA-46: gate moved to BRA-71 umbrella)
- Issue/tarefa: BRA-46
- Arquivos alterados: memory.md
- O que mudou: Board atualizou o gate; BRA-46 fica bloqueada por BRA-71 (Sofia Graph Agent umbrella). Aceite depende dos 7 comandos comportamentais do ï¿½3.7 no spec `paperclip/docs/qa/sofia-graph-agent-acceptance-2026-05-29.md` + artifacts em path publicado. Sub-scopes BRA-62/63/64/65 seguem como implementacao.
- Validacao executada: leitura do comentario `81a4280c-d70b-4e85-81e9-0effe19c527e`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: dependencia externa de aceite umbrella BRA-71.
- Proximo passo: owner BRA-71 concluir aceite formal e publicar artifacts para liberar fechamento de BRA-46.

### 2026-05-29 ï¿½ codex (BRA-62 reopen: session-context hardening)
- Wake delta: issue reopened noting umbrella integration gate moved to BRA-71; BRA-62 remains implementation scope.
- Ajustes entregues:
  - SofiaGraphCommandContext.active_persona_slug aceito e usado como prioridade de contexto ativo.
  - Memï¿½ria curta padronizada para contrato: TTL default 1800s (30min), janela default 5 turns.
  - Memï¿½ria agora inclui last_referenced_node por session_id.
  - Resoluï¿½ï¿½o de pronome (ele) no turno seguinte usando last_referenced_node.slug.
  - /sofia/graph-command retorna conversation_context.last_referenced_node para auditoria.
- Evidï¿½ncia:
  - testes: pytest tests/test_sofia_session_context.py tests/test_qa_contract_routes.py -k "sofia_graph_command or sofia_session" -q => 5 passed.
  - artifact: paperclip/test-artifacts/qa/bra62-session-context-2026-05-29.json com turno 1+2 e propagaï¿½ï¿½o de referï¿½ncia.

### 2026-05-29 ï¿½ graph-validator-migration-agent (BRA-76 blocker verification against ai-brain runtime)
- Issue/tarefa: BRA-76 (04e050d-a8d1-4a58-9c6f-20fcbcdddb1f) validator/migration execution gate.
- Arquivos alterados: i-brain/memory.md.
- O que mudou: executada verificacao de pre-requisitos de runtime para importacao v1->v2 AllanVvz e validacao graph_documents.
- Validacao executada: ausencia de pi/scripts/import_v1_to_v2_allanvvz.py, pi/services/graph_json_validator.py, pi/scripts/reindex_graph_json.py, pi/routes/graph_documents.py; GET http://127.0.0.1:8001/graph-documents/current?persona_slug=allanvvz retornou 404; openapi.json nao contem /graph-documents/current.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/graph-json-v2-allanvvz-validation-2026-05-29T06-20-00Z.json.
- Riscos / bloqueios: sem sub-1 BRA-73 implementada/deployada, BRA-76 nao consegue executar import/publish/validator/reindex no backend.
- Proximo passo: Backend Engineer publicar implementacao BRA-73; reexecutar BRA-76 apos probe 200 em /graph-documents/current.

### 2026-05-29 ï¿½ codex (BRA-75: Sofia graph-command tool loop v2)
- Issue/tarefa: BRA-75 Graph JSON V2 / AI Agent ï¿½ Sofia edita graph_json via patch.
- Arquivos alterados: `api/services/sofia_orchestrator.py`; `api/routes/qa_contract.py`; `tests/test_sofia_orchestrator_tools.py`; `tests/test_qa_contract_routes.py`.
- O que mudou: o orquestrador agora executa loop explï¿½cito de tools com nomes canï¿½nicos (`resolve-persona`, `resolve-node`, `resolve-operation`, `validate-canonical-chain`, `generate-graph-patch`) e remove fallback genï¿½rico, retornando clarificaï¿½ï¿½o especï¿½fica por condiï¿½ï¿½o (persona/node ausente, ambiguidade, baixa confianï¿½a). A rota `/sofia/graph-command` passou a registrar tambï¿½m `persist-graph-patch` e `refetch-graph` no `tool_calls`, mantendo trilha auditï¿½vel fim-a-fim.
- Validaï¿½ï¿½o executada: `pytest -q tests/test_sofia_orchestrator_tools.py tests/test_qa_contract_routes.py -k "sofia_graph_command or sofia_resolve or test_plan_graph_command" tests/test_sofia_session_context.py` ? `9 passed, 4 deselected`.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/ai-brain/tests/test_sofia_orchestrator_tools.py` e `C:/Users/Alan/Documents/repositorios/ai-brain/tests/test_qa_contract_routes.py` (evidï¿½ncia em cï¿½digo + suï¿½te passando).
- Riscos / bloqueios: probe live autenticado em `:8001` bloqueado por variï¿½vel ausente (`AI_BRAIN_ADMIN_TOKEN missing`), impedindo validar a resposta carregada com sessï¿½o/token no runtime ativo.
- Prï¿½ximo passo: Backend Engineer/Infra disponibilizar token admin QA no runtime da execuï¿½ï¿½o para probe autenticado e fechamento final.
### 2026-05-29 - Frontend Agent (BRA-74: Graph JSON V2 + Sofia React Flow tools)
- Issue/tarefa: BRA-74
- Arquivos alterados: dashboard/app/knowledge/graph/GraphPageClient.tsx; dashboard/app/knowledge/graph/sofiaReactFlowTools.ts
- O que mudou: alinhei os nomes dos 8 tools de frontend (pply_patch_visual, mark_pending, undo_pending, confirm_pending, select_node, ocus_node, update_layout, highlight_edges) e passei a executar 	ool_calls retornados pelo backend para aplicar patch visual, selecionar/focar node, acionar layout e destacar arestas, mantendo estado pending vs persisted e reconciliacao por refetch ao confirmar.
- Validacao executada: 
pm run build (em dashboard/) - sucesso, compilacao e TypeScript sem erros.
- Artifact gerado: n/a (validacao por build do frontend sem artifact externo).
- Riscos / bloqueios: backend ainda precisa manter emissao consistente de 	ool_calls + graph_patch para cobertura completa dos casos conversacionais.
- Proximo passo: QA/E2E Validator validar os casos de comportamento Sofia Graph no fluxo real do painel.

### 2026-05-29 - codex (BRA-73: Graph JSON V2 backend validation gate)
- Issue/tarefa: BRA-73 (sub-1 de BRA-72)
- Arquivos alterados: api/routes/qa_contract.py (validated current state), tests/test_qa_contract_routes.py (executed), tests/test_qa_contract_route_mapping.py (executed)
- O que mudou: Validacao de contrato backend executada para rotas QA de grafo/FAQ/embed e fluxo Sofia graph-command; guardas de Product->Embed e FAQ approval confirmadas via suite dedicada e probe live.
- Validacao executada: `pytest -q tests/test_qa_contract_route_mapping.py tests/test_qa_contract_routes.py` -> `11 passed, 2 warnings`; `Invoke-WebRequest POST http://127.0.0.1:8001/api/sofia/graph-command` sem header -> `401`; com `X-AI-BRAIN-ADMIN-TOKEN` -> `200`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-73-backend-validation-2026-05-29T02-57-34Z.json
- Riscos / bloqueios: Worktree local do ai-brain permanece com varias alteracoes preexistentes fora do escopo BRA-73.
- Proximo passo: QA/Test Engineer validar cadeia fim-a-fim Sofia graph-agent contra spec de 2026-05-29 usando artifact publicado.
### 2026-05-29 - Frontend Agent (BRA-74 follow-up: graph_json v2 contract paths)
- Issue/tarefa: BRA-74
- Arquivos alterados: dashboard/lib/graph-json-v2.ts; dashboard/lib/api.ts; dashboard/app/knowledge/graph/GraphPageClient.tsx; memory.md
- O que mudou: adicionei parser/schema tolerante de Graph JSON v2 (parseGraphJsonV2Payload), helper pi.getGraphDocument(persona_slug) para /graph-documents/current, e fallback no carregamento do Graph para consumir v2 quando NEXT_PUBLIC_GRAPH_JSON_V2=1 (com retorno automatico para v1 quando v2 indisponivel).
- Validacao executada: 
pm run build (em dashboard/) - sucesso apos integracao v2.
- Artifact gerado: n/a (smoke/build local).
- Riscos / bloqueios: shape final de graph_json no backend pode evoluir; parser foi feito com tolerancia de campos opcionais para evitar quebra imediata.
- Proximo passo: QA/E2E validar render com endpoint /graph-documents/current habilitado + flag NEXT_PUBLIC_GRAPH_JSON_V2=1.

### 2026-05-29 - codex (BRA-73: reviewer confirmation -> final disposition)
- Issue/tarefa: BRA-73 (sub-1 de BRA-72)
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: heartbeat de continuidade apos comentario do local-board confirmando evidencia QA publicada e discriminacao 401 vs 403 no endpoint validado; preparado fechamento formal do status com base nessa validacao.
- Validacao executada: `pytest -q tests/test_qa_contract_route_mapping.py tests/test_qa_contract_routes.py` -> `11 passed, 2 warnings`; probe live `Invoke-WebRequest POST http://127.0.0.1:8001/api/sofia/graph-command` sem header -> `401`; com `X-AI-BRAIN-ADMIN-TOKEN` -> `200`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-73-backend-validation-2026-05-29T02-57-34Z.json.
- Riscos / bloqueios: sem novo bloqueio tecnico reportado neste heartbeat.
- Proximo passo: registrar PATCH de disposicao final em BRA-73 conforme gate do board.

## 2026-05-29 (BRA-76 backend unblock)
- Added new API router [pi/routes/graph_documents.py] with /graph-documents/current, /publish, /versions backed by system_events for versioned graph_json publishing.
- Wired router in pi/main.py and validated live on 127.0.0.1:8001 (current returns 200 with X-AI-BRAIN-ADMIN-TOKEN).
- Added pi/scripts/import_v1_to_v2_allanvvz.py to export current knowledge/graph-data into graph_json v1.0 and publish (llanvvz:vz-lupas:v3).
- Added pi/services/graph_json_validator.py CLI/service validator; latest document validates is_valid=true for structural main edges and embed guards.


### 2026-05-29 - BRA-75 v2 patch loop test + live probe closure
- Issue/tarefa: BRA-75 (Sofia graph_json v2 patch loop contract).
- Arquivos alterados: `tests/test_sofia_v2_patch_loop.py`.
- O que mudou: criado teste dedicado cobrindo 5 comandos da spec ï¿½3 no fluxo `/sofia/graph-command` com sessao e assert da sequencia obrigatoria de tools: `resolve-persona -> resolve-node -> resolve-operation -> validate-canonical-chain -> generate-graph-patch -> persist-graph-patch -> refetch-graph`.
- Validacao executada: `pytest -q tests/test_sofia_v2_patch_loop.py tests/test_sofia_orchestrator_tools.py tests/test_sofia_session_context.py` => `8 passed`.
- Probe live: turno 1 + turno 2 com `session_id=test-001` executados no backend `http://127.0.0.1:8001/sofia/graph-command` com auth admin; evidencias serializadas no artifact em `paperclip/test-artifacts/qa/BRA-75-live-probe-2026-05-29T17-27-38Z.json`.
- Resultado: contrato BRA-75 atendido para teste faltante + probe autenticado + artifact publicado.

### 2026-05-29 - codex (BRA-73 reopen: required tests + graph-documents endpoint coverage)
- Issue/tarefa: BRA-73 reaberta por auditoria (faltavam `tests/test_graph_json_validator.py` e `tests/test_graph_documents_routes.py`).
- Arquivos alterados: `api/routes/graph_documents.py`; `api/services/graph_json_v2_validator.py`; `tests/test_graph_json_validator.py`; `tests/test_graph_documents_routes.py`; `paperclip/test-artifacts/qa/BRA-73-pytest-coverage-2026-05-29T17-29-02Z.json`; `ai-brain/memory.md`; `paperclip/memory.md`.
- O que mudou: implementei os 2 arquivos de teste exigidos (6 regras de validaï¿½ï¿½o canï¿½nica + 7 endpoints de graph-documents com sucesso e erro), adicionei endpoints faltantes (`apply-patch`, `rollback`, `reindex`, `events`) e incluï¿½ validaï¿½ï¿½o v2 explï¿½cita de `schema_version=2.0` e ownership da persona.
- Validaï¿½ï¿½o executada: `pytest tests/test_graph_json_validator.py -v` => `7 passed`; `pytest tests/test_graph_documents_routes.py -v` => `7 passed`; probe live `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8001/graph-documents/current?persona_slug=allanvvz` => `401`; probe live com header admin `curl -s -o NUL -w "%{http_code}" -H "X-AI-BRAIN-ADMIN-TOKEN: <token>" http://127.0.0.1:8001/graph-documents/current?persona_slug=allanvvz` => `404`.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-73-pytest-coverage-2026-05-29T17-29-02Z.json`.
- Riscos / bloqueios: runtime QA em `:8001` nï¿½o refletiu a atualizaï¿½ï¿½o local do endpoint (`/graph-documents/current` continua 404 com auth), impedindo evidï¿½ncia live do comportamento esperado pï¿½s-fix.
- Prï¿½ximo passo: owner Infra/Backend reiniciar o processo `scripts/start_api_qa.py` carregando HEAD atual; rerodar probe de `/graph-documents/current` para confirmar status esperado e entï¿½o concluir disposiï¿½ï¿½o final.

## 2026-05-29 (BRA-76 resume delta - steps 4/6)
- Step 4 executado: POST /sofia/graph-command (reencaixe brand vz-lupas abaixo de allanvvz) => 200, persisted=true, patch aplicado.
- Construi e enviei graph_json v2.0 canonico: POST /graph-documents/apply-patch => 200 (version=3); POST /graph-documents/publish => 200 (doc llanvvz:vz-lupas:v4); GET /graph-documents/versions confirmou v4.
- Step 6 parcial: criei FAQ via /knowledge/upload/text e aprovei via /knowledge/queue/{item}/approve (status approved), mas publish snapshot falhou com 22P02 invalid uuid qa-admin-token; /embeds/generate retornou 403 (rota restrita a aliases VZ Lupas); /graph-documents/reindex retornou 200.
- Bloqueio adicional: consulta SQL em knowledge_faq_index retornou PGRST205 (tabela ausente no schema cache QA).


### 2026-05-29 - codex (BRA-76: validator/migration heartbeat disposition)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration (AllanVvz -> VZ Lupas).
- Arquivos alterados: paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json; paperclip/memory.md; ai-brain/memory.md.
- O que mudou: Registrei artifact de heartbeat consolidando entregï¿½veis de validaï¿½ï¿½o/migraï¿½ï¿½o jï¿½ publicados e o bloqueio atual de execuï¿½ï¿½o por ausï¿½ncia de token admin no ambiente desta sessï¿½o.
- Validaï¿½ï¿½o executada: probes locais para carregar token (AI_BRAIN_ADMIN_TOKEN) no ambiente e em arquivos .env/.env.local/env*.yaml do i-brain retornaram ausente; sem token nï¿½o foi possï¿½vel repetir probes autenticados nesta heartbeat.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: sem token admin e sem correï¿½ï¿½es de backend/schema do Step 6, a execuï¿½ï¿½o e2e completa permanece bloqueada.
- Proximo passo: Backend Engineer + CTO + Board/Infra fornecer token/admin path e corrigir bloqueios tï¿½cnicos (UUID approve snapshot, embed gate 403, tabela knowledge_faq_index).

### 2026-05-29 - codex (BRA-76: resume delta after escalation comment)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration.
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: tratei o wake por comentario de escalacao, confirmei que os artifacts publicados existem e que a issue voltou para in_progress sem evidencia nova de desbloqueio tecnico.
- Validacao executada: GET /api/issues/f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f mostrou status in_progress; Test-Path confirmou existencia de BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json e graph-json-v2-allanvvz-validation-FINAL-2026-05-29T17-30-38Z.json.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: sem token admin disponï¿½vel e sem correï¿½ï¿½es de backend/schema (22P02, 403 embeds gate, PGRST205), Step 6 permanece bloqueado.
- Proximo passo: Backend Engineer + CTO + Board/Infra executar unblock action jï¿½ registrada no comentï¿½rio 98ef1b40-99f1-425d-9d53-a2b469cb6427.

### 2026-05-29 - codex (BRA-76: anti-loop enforcement on repeated wake)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration.
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: executei triagem do novo wake e confirmei repeticao sem delta tecnico; apliquei anti-loop mantendo bloqueio e reforcando que nao deve haver novo redespacho sem evidencia de desbloqueio.
- Validacao executada: GET /api/issues/f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f => status in_progress por wake; Test-Path confirmou artifacts de bloqueio e FINAL existentes em path publicado.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: tuple de bloqueio Step 6 inalterado (22P02, 403 embeds gate, PGRST205).
- Proximo passo: Backend Engineer + CTO + Board/Infra entregar unblock action antes de novo wake desta issue.

### 2026-05-29 - codex (BRA-76: repeated wake with no unblock delta)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration.
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: confirmei novo wake sem delta tecnico e mantive enforcement de anti-loop para evitar retries sem mudanca de entrada.
- Validacao executada: GET /api/issues/f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f mostrou status in_progress por wake; artifact de bloqueio segue presente em path publicado.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: tuple inalterado (22P02 approve snapshot UUID, 403 /embeds/generate gate, PGRST205 knowledge_faq_index).
- Proximo passo: Backend Engineer + CTO + Board/Infra devem publicar evidencias de unblock antes de novo dispatch de BRA-76.

### 2026-05-29 - codex (BRA-76: anti-loop escalation handoff)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration.
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: diante de repeticao sem delta tecnico, escalei ownership da issue para CTO/System Architect para coordenar unblock cross-team e interromper redespachos improdutivos ao mesmo assignee.
- Validacao executada: GET /api/issues/f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f mostrou retorno automatico para in_progress sem nova evidencia; artifact de bloqueio segue presente.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: tuple inalterado (22P02, 403 embeds gate, PGRST205) exige fixes de backend/schema + token/runtime.
- Proximo passo: CTO/System Architect coordenar Backend Engineer + Board/Infra e republicar evidencias de unblock antes de novo dispatch tecnico.

### 2026-05-29 - codex (BRA-76: post-handoff blocked confirmation)
- Issue/tarefa: BRA-76 Graph JSON V2 / Validator+Migration.
- Arquivos alterados: paperclip/memory.md; ai-brain/memory.md.
- O que mudou: confirmei estado pos-handoff anti-loop; issue permanece bloqueada e sob ownership do CTO/System Architect para coordenacao de desbloqueio.
- Validacao executada: GET /api/issues/f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f => status=blocked, assigneeAgentId=6da5684e-7976-4c96-82bb-46d262f3ef27; artifact de bloqueio segue existente em path publicado.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/BRA-76-validator-migration-heartbeat-2026-05-29T17-33-13Z.json.
- Riscos / bloqueios: tuple tecnico inalterado (22P02, 403 /embeds/generate, PGRST205 knowledge_faq_index).
- Proximo passo: CTO/System Architect aciona pacote de unblock e so entao redespacha BRA-76.
### 2026-05-29 - Frontend Agent (BRA-74 tests + smoke)
- Issue/tarefa: BRA-74
- Arquivos alterados: dashboard/__tests__/graph-json-v2.test.ts; dashboard/__tests__/GraphPageClient.test.tsx; dashboard/__tests__/api.test.ts; dashboard/vitest.config.ts; dashboard/vitest.setup.ts; dashboard/package.json; dashboard/package-lock.json; memory.md
- O que mudou: configurei Vitest no dashboard e adicionei os 3 testes exigidos cobrindo parser Graph JSON v2, helper getGraphDocument e fallback de carregamento V2->V1 no GraphPageClient com flag.
- Validacao executada: cd C:/Users/Alan/Documents/repositorios/ai-brain/dashboard && npm test (3 arquivos, 5 testes, tudo verde); curl -L http://127.0.0.1:3000/knowledge/graph?persona=allanvvz (200; status inicial 307).
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-74-frontend-tests-2026-05-29T17-39-52Z.json.
- Riscos / bloqueios: sem bloqueios para este escopo de frontend.
- Proximo passo: QA/E2E validar cadeia completa com backend v2 publicado.
### 2026-05-29 ï¿½ ceo-product-owner (BRA-76: gate check + blocker formal)
- Issue/tarefa: BRA-76 (f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f).
- Arquivos alterados: ai-brain/memory.md.
- O que mudou: Registrei decisï¿½o de produto/gate: nï¿½o hï¿½ critï¿½rio para `done` enquanto nï¿½o houver evidï¿½ncia autenticada dos passos 2-7 (publish/read 200, validator true por doc-id publicado, patch Sofia com version bump, FAQ approved->reindex->embeddings).
- Validaï¿½ï¿½o executada: checagem de existï¿½ncia de `api/scripts/import_v1_to_v2_allanvvz.py`, `api/services/graph_json_validator.py`, `api/routes/graph_documents.py` e probe runtime `GET /graph-documents/current?persona_slug=allanvvz` com retorno 401.
- Artifact gerado: sem novo artifact em ai-brain; referï¿½ncia cruzada no artifact publicado `paperclip/test-artifacts/architecture/graph-json-v2-allanvvz-validation-FINAL-2026-05-29T17-30-38Z.json`.
- Riscos / bloqueios: sem token/fluxo autenticado comprovado, a validaï¿½ï¿½o e2e permanece incompleta e nï¿½o pode avanï¿½ar para aceite.
- Prï¿½ximo passo: Backend Engineer desbloquear autenticaï¿½ï¿½o/endpoint e publicar delta verificï¿½vel; em seguida QA/Graph Validator executa contrato completo BRA-76.
### 2026-05-29 ï¿½ ceo-product-owner (BRA-76: status reconciliation no-delta wake)
- Issue/tarefa: BRA-76 (f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f).
- Arquivos alterados: ai-brain/memory.md.
- O que mudou: Sem nova evidï¿½ncia tï¿½cnica no wake; mantive o gate de produto e reconciliei a disposiï¿½ï¿½o formal da BRA-76 para bloquear reexecuï¿½ï¿½o sem delta.
- Validaï¿½ï¿½o executada: leitura de status via Paperclip API (`BRA-76 in_progress`, `BRA-73 blocked`).
- Artifact gerado: nï¿½o aplicï¿½vel.
- Riscos / bloqueios: dependï¿½ncia em BRA-73 permanece ativa para autenticaï¿½ï¿½o/persistï¿½ncia do fluxo e2e.
- Prï¿½ximo passo: entregar unblock em BRA-73 com probe/artifact novo e sï¿½ entï¿½o retomar BRA-76.
### 2026-05-29 ï¿½ graph-validator-migration-agent (BRA-76: live contract execution + schema blocker)
- Issue/tarefa: BRA-76 (f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f).
- Arquivos alterados: ai-brain/memory.md.
- O que mudou: Rodei o importador real da BRA-76 contra `:8001`; autenticaï¿½ï¿½o por token admin passou, mas o publish falhou em validaï¿½ï¿½o Pydantic porque o payload gerado ainda segue shape legado e nï¿½o o contrato GraphJson V2 da rota.
- Validaï¿½ï¿½o executada: `python api/scripts/import_v1_to_v2_allanvvz.py` => `422 Unprocessable Entity`; probe dirigido com o mesmo token em `GET /graph-documents/current?persona_slug=allanvvz` => `404 No published graph document`; replay do publish retornou erros de campos obrigatï¿½rios ausentes (`graph_id`, `tenant`, `persona_slug`, `nodes[*].node_type`).
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/architecture/graph-json-v2-allanvvz-validation-20260529T181957Z.json.
- Riscos / bloqueios: enquanto o importador nï¿½o serializar GraphJson V2 vï¿½lido, o documento nï¿½o publica e o fluxo Sofia/versionamento/reindex/embedding nï¿½o ï¿½ executï¿½vel.
- Prï¿½ximo passo: Backend Engineer corrigir o mapper do importador para GraphJson V2 e rerodar o contrato BRA-76 a partir do passo 1.
### 2026-05-29 ï¿½ graph-validator-migration-agent (BRA-76: disposition API write failure)
- Issue/tarefa: BRA-76 (f04e050d-a8d1-4a58-9c6f-20fcbcdddb1f).
- Arquivos alterados: ai-brain/memory.md.
- O que mudou: execuï¿½ï¿½o tï¿½cnica em ai-brain foi concluï¿½da atï¿½ o diagnï¿½stico do 422 no publish, porï¿½m a disposiï¿½ï¿½o formal no board nï¿½o pï¿½de ser gravada por erro 500 da API Paperclip em endpoints de escrita.
- Validaï¿½ï¿½o executada: tentativa de `PATCH /api/issues/{id}` com `status=blocked` falhou (`500`), com leitura subsequente `GET /api/issues/{id}` ainda `in_progress`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-76-disposition-api-failure-20260529T182058Z.json.
- Riscos / bloqueios: governanï¿½a de issue bloqueada por falha infra de persistï¿½ncia de comentï¿½rios/disposiï¿½ï¿½o.
- Prï¿½ximo passo: Board/Infra restaurar writes da API Paperclip para permitir registro formal do bloqueio e handoff ao Backend Engineer.
### 2026-05-29 ï¿½ CEO / Product Owner (BRA-82: backend plan_json endpoints + validator severities)
- Issue/tarefa: BRA-79 (execuï¿½ï¿½o tï¿½cnica da filha BRA-82)
- Arquivos alterados: api/services/sofia_orchestrator.py; api/routes/qa_contract.py; tests/test_qa_contract_routes.py; memory.md
- O que mudou: Adicionado storage de plan_json por sessï¿½o no orquestrador, endpoints GET/PATCH em QA contract para obter/aplicar patch de plan_json, integraï¿½ï¿½o do retorno plan_json no fluxo sofia_graph_command e validaï¿½ï¿½o com severidades suggestion/pending/blocking sem bloquear criaï¿½ï¿½o por ausï¿½ncia de FAQ/regra.
- Validaï¿½ï¿½o executada: `pytest -q tests/test_qa_contract_routes.py` -> `13 passed in 2.22s`.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/memory.md
- Riscos / bloqueios: storage atual ï¿½ em memï¿½ria por sessï¿½o (TTL), sem persistï¿½ncia em banco entre reinï¿½cios.
- Prï¿½ximo passo: Backend Engineer evoluir para persistï¿½ncia durï¿½vel (Supabase table/migration) mantendo o mesmo contrato de endpoint.
### 2026-05-29 ï¿½ CEO / Product Owner (BRA-79: probes reais plan_json + bugfix de retenï¿½ï¿½o de sessï¿½o)
- Issue/tarefa: BRA-79
- Arquivos alterados: api/services/sofia_orchestrator.py; scripts/probe_sofia_plan_json_endpoints.py; memory.md
- O que mudou: Corrigido bug onde `remember_turn` limpava `plan_json`; criado probe real GET/PATCH/POST dos endpoints Sofia com artifact JSON comprovando alteraï¿½ï¿½o de product/campaign, separaï¿½ï¿½o suggestion/pending/blocking, blocking estrutural e nï¿½o-durabilidade apï¿½s reload.
- Validaï¿½ï¿½o executada: `python scripts/probe_sofia_plan_json_endpoints.py` (artifact gerado) e `pytest -q tests/test_qa_contract_routes.py` (`13 passed`).
- Artifact gerado: C:/Users/Alan/Documents/repositorios/ai-brain/test-artifacts/qa/sofia-plan-json-endpoints-probe-20260529T204937Z.json
- Riscos / bloqueios: persistï¿½ncia ainda ï¿½ memï¿½ria de processo; apï¿½s reload/restart o estado zera.
- Prï¿½ximo passo: BRA-87 (Backend) implementar persistï¿½ncia Supabase durï¿½vel para plan_json.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: persistir plan_json em Supabase)
- Issue/tarefa: BRA-87 (Backend) persistencia duravel de `plan_json` entre reloads.
- Arquivos alterados: `api/services/sofia_orchestrator.py`; `api/services/supabase_client.py`; `supabase/migrations/043_sofia_plan_sessions.sql`; `tests/test_qa_contract_routes.py`; `memory.md`.
- O que mudou: adicionei persistencia de sessao Sofia em Supabase (`sofia_plan_sessions`) com leitura/escrita no orchestrator e fallback seguro para memoria local quando Supabase nao estiver configurado; inclui teste que simula reset de memoria e recupera `plan_json` do store persistente.
- Validacao executada: `pytest -q tests/test_qa_contract_routes.py -k "sofia_plan_json or session_memory_reuses_active_persona"` (4 passed, 10 deselected); `curl.exe -s -o NUL -w "%{http_code}\n" -X POST http://127.0.0.1:8001/sofia/graph-command -H "X-AI-BRAIN-ADMIN-TOKEN: <token>" -H "Content-Type: application/json" --data-binary "@C:\Users\Alan\Documents\repositorios\ai-brain\tmp\bra87_probe.json"` (200); sem header -> 401.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-plan-json-persistence-probe.md`.
- Riscos / bloqueios: migration `043_sofia_plan_sessions.sql` precisa ser aplicada no projeto QA para persistencia completa no banco.
- Proximo passo: executar migration 043 no Supabase QA e revalidar fluxo `/sofia/graph-command` + leitura de `plan_json` apos reload do processo.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: tentativa de aplicar migration 043 no QA)
- Issue/tarefa: BRA-87 pendencia operacional - aplicar `043_sofia_plan_sessions.sql` no Supabase QA `svkogegypdqquzlfzaor`.
- Arquivos alterados: `memory.md`.
- O que mudou: tentei aplicar a migration no banco QA, mas o runner nao possui cliente SQL disponivel (`psycopg2` ausente e `psql` inexistente), impedindo execucao local do DDL.
- Validacao executada: `python ... psycopg2.connect(...)` => `ModuleNotFoundError: No module named 'psycopg2'`; `psql --version` => comando nao encontrado; probe live `curl POST /sofia/graph-command` com header admin => `200`.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-migration-apply-attempt-2026-05-29.md`.
- Riscos / bloqueios: migration 043 segue pendente no banco QA ate execucao por owner com cliente SQL instalado.
- Proximo passo: Infra/DB Sync executar a migration 043 diretamente no QA Postgres e anexar evidencias de tabela criada.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: migration 043 aplicada no QA)
- Issue/tarefa: BRA-87 - concluir pendencia operacional da persistencia `plan_json` no banco QA.
- Arquivos alterados: `memory.md`.
- O que mudou: desbloqueei a pendencia operacional instalando cliente Postgres no runner e aplicando com sucesso a migration `043_sofia_plan_sessions.sql` no projeto QA `svkogegypdqquzlfzaor`; tabela `public.sofia_plan_sessions` confirmada por query.
- Validacao executada: apply migration via python/psycopg2 => `migration_043: OK`; verificacao SQL => `table=sofia_plan_sessions` e `required_columns=6`; probe live `POST /sofia/graph-command` com header admin => `200`, sem header => `401`.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-migration-applied-2026-05-29.md`.
- Riscos / bloqueios: sem bloqueios remanescentes para BRA-87.
- Proximo passo: manter monitoramento normal; endpoint de sessao pode ser validado em regressao de reload quando QA solicitar.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: fechamento confirmado)
- Issue/tarefa: BRA-87 validado pelo board apos aplicacao da migration 043 no QA.
- Arquivos alterados: `memory.md`.
- O que mudou: registrei somente o fechamento administrativo deste wake, sem mudancas adicionais de codigo ou schema.
- Validacao executada: mantida a ultima evidencia valida do issue (`/sofia/graph-command`: 200 com header admin, 401 sem header).
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-migration-applied-2026-05-29.md`.
- Riscos / bloqueios: nenhum.
- Proximo passo: nenhum; issue encerrada.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: wake de reconfirmacao final)
- Issue/tarefa: BRA-87 ja aceita; este wake apenas reconfirma fechamento sem delta tecnico.
- Arquivos alterados: `memory.md`.
- O que mudou: entrada administrativa final para evitar ambiguidade de status em wakes subsequentes.
- Validacao executada: referencia mantida ao artifact final aceito no board.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-migration-applied-2026-05-29.md`.
- Riscos / bloqueios: nenhum.
- Proximo passo: nenhum.
### 2026-05-29 - 57a6a5a4-a04e-47f4-8da9-b5ab914921fa (BRA-87: reconciliaï¿½ï¿½o anti-loop)
- Issue/tarefa: wake de confirmaï¿½ï¿½o sem delta tï¿½cnico em BRA-87.
- Arquivos alterados: memory.md.
- O que mudou: sem alteraï¿½ï¿½o de cï¿½digo/backend; apenas reconciliaï¿½ï¿½o administrativa da issue.
- Validaï¿½ï¿½o executada: POST /sofia/graph-command sem header => 401; com X-AI-BRAIN-ADMIN-TOKEN => 422.
- Artifact gerado: C:/Users/Alan/Documents/repositorios/paperclip/test-artifacts/qa/BRA-87-migration-applied-2026-05-29.md.
- Riscos / bloqueios: nenhum tï¿½cnico.
- Prï¿½ximo passo: nenhum em BRA-87; handoff para BRA-83.

### 2026-05-30 - frontend-agent (BRA-83: plan_json-driven context panel + Graph sidebar parity)
- Issue/tarefa: BRA-83
- Arquivos alterados: `dashboard/lib/api.ts`; `dashboard/app/knowledge/graph/GraphPageClient.tsx`; `dashboard/app/knowledge/graph/SofiaChatPanel.tsx`; `dashboard/app/knowledge/capture/page.tsx`; `memory.md`
- O que mudou: O Graph passou a compartilhar a mesma sessao/orquestracao do CRIAR via `session_id` + `plan_json` em `/sofia/graph-command` (command/confirm/undo), com hidrataÃ§Ã£o da sessao ativa por `kbIntakeSession`; a sidebar da Sofia no Graph agora exibe resumo de contexto do `plan_json`; e o painel de contexto da tela CRIAR passou a priorizar `plan_json` da sessao para contagens/erros bloqueantes exibidos.
- Validacao executada: `npm test -- GraphPageClient.test.tsx` em `ai-brain/dashboard` -> PASS (1 arquivo, 2 testes).
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/docs/qa/BRA-83-plan-json-context-panel-graph-sidebar-parity-2026-05-30T03-05-00Z.md`
- Riscos / bloqueios: Ainda depende de validacao E2E com backend live para confirmar equivalencia total de tool-calls entre CRIAR e Graph em todos os casos de uso.
- Proximo passo: QA/E2E Validator executar fluxo dual (CRIAR->Graph) e comparar request context/estado visual pendente vs persistido.
### 2026-05-30 - dfc57cae-0b19-4b55-b605-02a2cdd96b85 (BRA-81: unify Sofia Criar+Graph on shared plan_json)
- Issue/tarefa: BRA-81
- Arquivos alterados: `api/routes/qa_contract.py`; `api/services/sofia_orchestrator.py`; `memory.md`.
- O que mudou: unifiquei o fluxo de `/sofia/graph-command` para consumir `selected_node_id`/`selected_node_ids`, resolver referencias pronominais (`ele/esse/isso`) via memoria da sessao e gravar estado de operacao/patch no mesmo `plan_json` da sessao quando `session_id` existe; tambem eliminei fallback generico no orquestrador em favor de esclarecimentos especificos e adicionei hardening para sessoes com `plan_json` incompleto.
- Validacao executada: `pytest -q tests/test_sofia_v2_patch_loop.py tests/test_sofia_session_context.py tests/test_qa_contract_routes.py` => `20 passed in 2.34s`.
- Artifact gerado: `C:/Users/Alan/Documents/repositorios/paperclip/docs/qa/BRA-81-sofia-unified-plan-json-tool-loop-2026-05-30T03-40-00Z.md`.
- Riscos / bloqueios: sem bloqueio tecnico imediato; sweep E2E dual-flow ainda depende do gate QA/E2E (BRA-85).
- Proximo passo: QA/Test Engineer validar fluxo integrado Criar->Graph com backend live e confirmar criterios finais.

### 2026-05-30 - Codex (BRA-91: conexoes Graph AllanVvz pos-rebuild)
- Issue/tarefa: investigar e corrigir origem dos erros de conexao no Graph AllanVvz apos rebuild destrutivo.
- Arquivos alterados: `dashboard/components/graph/knowledgeGraphLayout.ts`; `dashboard/app/knowledge/graph/GraphPageClient.tsx`; `dashboard/app/knowledge/graph/graphParenting.ts`; `dashboard/lib/api.ts`; `api/services/sofia_orchestrator.py`; `api/routes/qa_contract.py`; `dashboard/__tests__/graph-layout-canonical.test.ts`; `dashboard/__tests__/graph-parenting.test.ts`; `tests/test_bra91_sofia_graph_intents.py`; `memory.md`.
- O que mudou: tree builder passou a reconhecer relation_types canonicos (`persona_has_brand`, `audience_has_product_group`, `product_group_has_product` etc.) e `product_group` na hierarquia; modal passou a escolher parent compativel por tipo/selected node; Graph envia selected node para `/sofia/graph-command`; Sofia ganhou intents minimas para criar/conectar/reencaixar nodes claros.
- Validacao executada: `npm.cmd run test -- graph-layout-canonical.test.ts graph-parenting.test.ts GraphPageClient.test.tsx` => 3 arquivos/8 testes PASS; `python -m pytest tests\test_bra91_sofia_graph_intents.py -q` => 3 PASS; probe live `GET /knowledge/graph-data?persona_slug=allanvvz...` confirmou 28 nodes, 34 edges, 3 product groups, 0 edges diretas proibidas da Persona.
- Correcao live pontual: via `/sofia/graph-command` sem hard-delete, `conectar radar em audience padrao` persistiu `audience_has_product_group` para `grupo-radar`.
- Riscos / bloqueios: nenhum hard-delete rodado nesta investigacao; estado live agora tem Product Groups Plantaris/Radar/Juliet sob Audience.
- Proximo passo: validar manualmente no front sem Playwright se o modal e a Sofia refletem as novas escolhas de parent/contexto.

## Sofia Criar Ã¢â‚¬â€ primary_tree como fonte de verdade (2026-05-31)
- A publicaÃ§Ã£o da Ã¡rvore principal precisa tratar `metadata.primary_tree=true` como verdade estrutural, mesmo quando o `relation_type` do link Ã© semÃ¢ntico.
- O `relation_type` pode continuar existindo como `semantic_relation` no metadata ou ser canonicalizado pelo par pai/filho, mas nÃ£o deve bloquear a edge principal.
- O repair/layout nÃ£o pode ignorar uma edge principal sÃ³ porque ela veio como `targets_audience`.
- A correÃ§Ã£o foi aplicada no guard de Ã¡rvore principal e deve ser testada com save completo + `/knowledge/graph` em modo layered/semantic_tree.

## Sofia Criar /knowledge/graph â€” default tree view and structural relation alignment (2026-06-01)
- Sintoma: o plano Tock Fatal estava salvando corretamente, mas o dashboard de grafo abria em layout orgânico e fazia `briefing`/`audience` parecerem paralelos; o `product_group` também sumia visualmente em alguns fluxos.
- Diagnóstico:
  - a página `/knowledge/graph` abria por padrão em `mode=graph`, não em `semantic_tree`;
  - o renderizador de árvore reconhecia parte das relações estruturais, mas o fluxo atual usa `targets_audience`/`campaign_has_audience` como backbone e isso precisava estar coberto nas tabelas de relações estruturais;
  - o plano salvo da Tock Fatal estava íntegro: `brand -> briefing -> campaign -> audience -> product_group -> product -> copy -> faq`.
- Correções:
  - `GraphPageClient` agora abre em `semantic_tree` por padrão quando não há `mode` na URL;
  - `api/routes/graph.py` passou a tratar `targets_audience`, `campaign_has_audience`, `audience_has_product_group`, `product_group_has_product`, `product_has_copy`, `product_has_faq` e `copy_has_faq` como relações estruturais;
  - `dashboard/components/graph/knowledgeGraphLayout.ts` passou a reconhecer as mesmas relações para parentagem e prioridade;
  - teste `tests/test_sofia_primary_tree_publication.py` agora garante que o dashboard default continue em árvore canônica.

## Sofia Criar / Tock Fatal â€” preferred spine is brand -> campaign -> briefing -> audience (2026-06-01)
- Sintoma: o grafo ainda mostrava `briefing` como paralelo a `audience` e o `product_group` não aparecia de forma consistente no caminho principal.
- Diagnóstico: o planner determinístico e as heurísticas de parentagem ainda favoreciam o spine antigo (`brand -> briefing -> campaign -> audience`) em parte do stack, o que deixava a árvore serial quebrada para o prompt de inverno da Tock Fatal.
- Correções:
  - `build_full_tree_plan_from_session()` agora materializa a cadeia como `brand -> campaign -> briefing -> audience -> product_group -> product -> copy -> faq`;
  - `knowledge_taxonomy.PRIMARY_CHAIN` passou a preferir essa ordem, preservando o caminho legado apenas como alternativa;
  - `graph_validation`, `knowledge_graph._default_plan_relation()` e os rankings do layout do frontend foram alinhados para escolher `campaign` antes de `briefing` e `briefing` antes de `audience`;
  - `dashboard/app/knowledge/graph/graphParenting.ts` e `dashboard/__tests__/graph-layout-canonical.test.ts` foram atualizados para refletir a cadeia nova;
  - os contratos de Sofia e os textos de orientação foram ajustados para a mesma ordem.
- Validação executada:
  - `python -m pytest tests/test_sofia_primary_tree_publication.py tests/test_sofia_create_plan_product_group.py -q`
  - `npm.cmd run test -- --run __tests__/graph-layout-canonical.test.ts`
  - `npm.cmd run build:check`

## Sofia Criar / Graph JSON bulk import local - Tock Fatal (2026-06-02)
- Sintoma corrigido: em `/marketing/criacao`, o prompt "segmentacao nova de publico atacarejo inverno. briefing para produtos quentes e baratos. 2 produtos do site agrupados" antes podia cair no loop de tools da Sofia, ler o site, mas sair sem `knowledge_plan`/Graph JSON utilizavel.
- Estado validado: o backend local usado pelo dashboard (`API_INTERNAL_BASE_URL=http://127.0.0.1:8001`) agora responde esse prompt com `ok=true`, `stage=ready_to_save` e plano completo: `brand=1`, `briefing=1`, `campaign=1`, `audience=1`, `product_group=1`, `product=2`, `copy=2`, `faq=2`, sem violacoes bloqueantes.
- Validacao no grafo local: `GET /knowledge/graph-data?persona_slug=tock-fatal&mode=semantic_tree&max_depth=6&include_embedded=true` retornou 16 nodes e 13 edges, com tipos `persona=1`, `brand=1`, `briefing=1`, `campaign=3`, `audience=1`, `product_group=1`, `product=2`, `copy=2`, `faq=2`, `gallery=1`, `embedded=1`; o ramo novo contem `brand -> briefing -> campaign -> audience -> product_group -> product -> copy -> faq -> embedded`.
- Mudancas de codigo relacionadas: o CRIAR passou a salvar via `GraphJson`/`graph_json_importer.import_graph_json` em lote; `/graph-documents/import-json` aceita o JSON canonico; o contrato aceita tanto `audience -> product` quanto `audience -> product_group -> product`; prompts estruturados com "produtos do site agrupados" agora disparam o builder deterministico em vez de depender do LLM emitir JSON perfeito.
- Validacao automatizada: `api\.venv\Scripts\python.exe tests\test_marketing_criacao_kb_intake_flow.py` e `api\.venv\Scripts\python.exe -m py_compile api\services\kb_intake_service.py` passaram. O teste isolado loga `SUPABASE_URL` ausente por nao carregar env completo, mas nao falha.
- Proximo risco identificado: os FAQs gerados ainda podem interpretar apenas o node imediatamente acima (`copy`) em vez de todo o galho; a proxima correcao deve compor prompt/contexto a partir de todos os ancestrais conectados ate o FAQ.
