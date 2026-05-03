# Memory

## Preferencias do usuario

- Sempre salvar o contexto relevante da conversa neste arquivo (`memory.md`) para retomadas futuras.
- Usar este arquivo como memoria operacional do projeto antes de responder sobre estado atual, integracoes ou decisoes ja tomadas.

## Contexto salvo em 2026-05-02 (Atualização)

### Diagnóstico de comportamento da Sofia (Criar)

- Identificado que a interação Sofia/Crawler pode resultar em pedidos de dados manuais quando a confiança do `catalog_crawler.py` é baixa.
- Este comportamento é **esperado** e faz parte das regras antialucinação do `kb_intake_service.py`.
- A regra "QUANDO FALTAR INFORMAÇÃO" obriga a agente a admitir falha na captura automática em vez de inventar dados.
- **Melhoria (2026-05-02):** Implementada Tool `fetch_shopify_json_tool` para capturar dados precisos via `/products.json`, aumentando a confiança para sites Shopify (como Tock Fatal).
- **Melhoria (2026-05-02):** O crawler foi decomposto em ferramentas (`tools`) para facilitar manutenção e chamadas isoladas.
- **Melhoria (2026-05-02):** O backend agora retorna `proposed_entries` no chat, permitindo que o front-end renderize Conhecimentos como Cards individuais.
- **Melhoria (2026-05-02):** Implementado `tests/e2e_shopify_instant_cards.py` para validar a extração automática de cards via API Shopify (`products.json`) na primeira mensagem da sessão.
- **Melhoria (2026-05-02):** Ajustada a lógica de `_should_crawl` para que o crawler seja acionado automaticamente na primeira mensagem da sessão, se uma URL e blocos selecionados estiverem presentes no contexto inicial, sem a necessidade de uma saudação específica como "Oi".
- **Melhoria (2026-05-02):** O `_SYSTEM_PROMPT` foi atualizado para instruir a Sofia a oferecer proativamente ideias de melhorias ou como aumentar o conhecimento após a geração inicial de cards.
- **Rollback (2026-05-02):** Removido suporte hardcoded ao cliente `tock-fit`. Identificado que novas marcas surgidas em diálogos devem ser tratadas dinamicamente como dados do grafo, não como entidades fixas de código.
- **Correção (2026-05-02):** Corrigido erro de runtime 400 no `save()` (missing title) implementando lógica de fallback que extrai o título da sessão a partir do primeiro card do `knowledge_plan` ou da URL da fonte.
- **Melhoria (2026-05-02):** Refatorado `save()` para ser "orientado a plano". Se um `knowledge_plan` existir na conversa, o sistema agora parseia e salva cada entrada como um arquivo individual no vault, evitando perda de dados em extrações em massa (como os 27 cards da Tock Fatal).
- **Arquitetura (2026-05-02):** Estabelecida a regra de que o `kb_intake_service.py` deve conter apenas clientes de infraestrutura base. Novos Brands/Sub-brands descobertos no chat (como Tock Fit) devem fluir para o grafo via `knowledge_plan` sem alterar mapeamentos estáticos (`_VAULT_CLIENT_FOLDERS`).
- **Diretriz de UI (2026-05-02):** Mensagens da Sofia devem usar Markdown rico para suportar o novo componente de toggle "View/Code" no front-end.
- **Diretriz de Dados (2026-05-02):** Sofia instruída a ser expansiva na geração de cards (regras/FAQs) para atingir volumes maiores (20+) conforme solicitado.
- **Estado Atual (2026-05-02):** Sistema configurado para extração automática e geração de conhecimento rico. Sofia instruída a lidar com brands dinâmicas via grafo e suporte visual para Markdown rico no chat.
- O teste de referência para sucesso total (leitura + geração de árvore completa) continua sendo o `e2ellm005`.

### Próximos Passos Sugeridos

- Validar a renderização visual dos `proposed_entries` no front-end React.
- Se o crawler falhar consistentemente em URLs específicas, revisar as heurísticas de extração em `services/catalog_crawler.py`.
- Melhorar a mensagem de erro da Sofia para indicar se o problema foi timeout, bloqueio de robôs ou apenas falta de dados estruturados (JSON-LD) no HTML.

## Contexto salvo em 2026-05-02

### Backfill RAG da base legada

- Criado `services/knowledge_rag_backfill.py` para reprocessar conhecimento legado em `knowledge_rag_entries`, `knowledge_rag_chunks` e `knowledge_rag_links`.
- Fontes cobertas:
  - Obsidian vault via varredura read-only;
  - `knowledge_items`;
  - `kb_entries`;
  - `knowledge_nodes`/`knowledge_edges`.
- A rotina e idempotente por `(persona_id, canonical_key)`, reaproveita `classify_intake()`, cria chunks pendentes de embedding, espelha cada entry de volta no grafo com `knowledge_graph.bootstrap_from_item(source_table='knowledge_rag_entries')` e converte edges existentes em `knowledge_rag_links`.
- Detalhe importante: `kb_entries.produto` e tratado como dica de matching contra produtos canonicos do grafo, nao como criacao explicita de novo slug, para evitar duplicar produtos como `higienizacao-cadeiras-prime` vs `higienizacao-de-cadeiras-prime`.
- Criado endpoint administrativo `POST /knowledge/rag/backfill` em `api/routes/knowledge.py`.
  - Body: `persona_id` ou `persona_slug`, `include_vault`, `vault_path`, `limit_items`, `limit_nodes`.
  - Recomendacao operacional: rodar por persona em producao.
- Criado `tests/integration_knowledge_rag_backfill.py`:
  - Testa Tock Fatal e Prime Higienizacao com fontes misturadas;
  - valida produtos e FAQs em RAG entries;
  - valida chunks;
  - valida links semanticos;
  - valida `get_chat_context()` retornando produto + FAQ por persona, sem quebrar grafo/sidebar.
- Validacao executada:
  - `python -m py_compile services\knowledge_rag_backfill.py services\knowledge_rag_intake.py services\knowledge_graph.py services\supabase_client.py api\routes\knowledge.py tests\integration_knowledge_rag_backfill.py tests\integration_knowledge_rag_intake.py tests\integration_knowledge_ui_hierarchy.py` - PASS.
  - `python tests\integration_knowledge_rag_backfill.py` - PASS.
  - `python tests\integration_knowledge_rag_intake.py` - PASS.
  - `python tests\integration_knowledge_ui_hierarchy.py` - PASS.
  - `python -m tests.smoke_knowledge_graph` - PASS, com warnings ja conhecidos de fallback por ausencia de `SUPABASE_URL`.
  - `python tests\integration_prime_higienizacao_mock.py --scenario tests\fixtures\knowledge_prime_higienizacao.json` - PASS.

### Captura de novos conhecimentos para Tock Fatal

- Pedido do usuario: desenhar fluxo end-to-end de insercao de novos conhecimentos, usando Tock Fatal como persona, com pre-confirmacao antes de iniciar modelo, uploads manuais acumulados na sessao, uso do espaco lateral da aba Capturar, e raw MD de marketing em grafo a partir do site da Tock Fatal.
- Pesquisa feita no site publico:
  - `https://tockfatal.com/`
  - `https://tockfatal.com/pages/catalogo-modal`
  - `https://tockfatal.com/products.json`
  - produtos encontrados: `Kit Modal 1 (9 cores disponiveis)` e `Kit Modal 2 - Urso Estampado`.
  - Sitemap confirma produtos/paginas/collections/blogs; robots.txt permite sitemap e bloqueia checkout/cart/admin/search.
- Criado `docs/tock-fatal-modal-marketing-graph.md`:
  - raw MD com brand, campanhas, audiencia atacado/varejo, produtos, cores, FAQs, regras e copys hierarquizadas como grafo;
  - inclui precos confirmados: unidade R$ 59,90, kit 5 R$ 249,00, kit 10 R$ 459,00;
  - inclui cores confirmadas do Kit Modal 1: vermelho, vinho, bege, nude, off white, verde claro, azul claro, azul marinho e preto;
  - marca `tricots` e `cropped-de-modal` como `pending_source`, pois nao foram confirmados nas paginas publicas.
- Alterada `dashboard/app/knowledge/capture/page.tsx`:
  - upload manual movido para a esquerda;
  - uploads feitos na sessao aparecem abaixo de "Enviar para validacao";
  - uploads da sessao entram no contexto inicial do agente;
  - painel central agora tem pre-confirmacao de persona, objetivo, fonte e grafo esperado antes de iniciar modelo;
  - sidebar direita mostra fonte, pipeline, subnodes esperados e uploads legiveis pelo agente.
- Alterado `api/routes/kb_intake.py` e `services/kb_intake_service.py`:
  - `POST /kb-intake/start` agora aceita `initial_context`;
  - sessao guarda contexto inicial confirmado pelo operador;
  - prompt do KB Classifier foi estendido para fluxo Capturar/Marketing Graph, pedindo fontes, entries, links semanticos e riscos antes de salvar;
  - modelos expostos no intake agora usam `ModelRouter.AVAILABLE_MODELS` com fallback Claude.
- Alterado `dashboard/lib/api.ts`:
  - `kbIntakeStart(model, initial_context)` envia contexto inicial ao backend.
- Validacao executada:
  - `python -m py_compile services\kb_intake_service.py api\routes\kb_intake.py api\routes\knowledge.py services\knowledge_rag_backfill.py services\knowledge_rag_intake.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.
  - `python tests\integration_knowledge_rag_intake.py` - PASS.
  - `python tests\integration_knowledge_rag_backfill.py` - PASS.

### Ajuste: agente da Captura deve perguntar quando nao souber

- O usuario esclareceu que o importante e a dinamica: se o modelo da aba Capturar nao souber uma informacao necessaria, ele deve interagir com o usuario perguntando, nao inventar nem salvar.
- Ajustado `services/kb_intake_service.py`:
  - prompt agora tem secao "QUANDO FALTAR INFORMACAO";
  - regra: nao preencher por suposicao, nao finalizar classificacao e manter `complete=false`;
  - perguntar no maximo 3 perguntas curtas;
  - perguntar especialmente sobre persona, tipo, titulo canonico, fonte, produto/campanha/publico, preco/cores/disponibilidade/politica/prazo e confirmacao humana para salvar.
- Ajustado `api/routes/kb_intake.py`:
  - mensagem inicial diz que o agente pergunta o que falta antes de propor grafo ou salvar.
- Ajustado `dashboard/app/knowledge/capture/page.tsx`:
  - pre-confirmacao informa que se faltar dado o agente deve perguntar antes de propor;
  - contexto inicial enviado ao agente inclui essa regra;
  - sidebar/pipeline ganhou etapa "perguntar lacunas".
- Validacao executada:
  - `python -m py_compile services\kb_intake_service.py api\routes\kb_intake.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.
  - `python tests\integration_knowledge_rag_intake.py` - PASS.

## Contexto salvo em 2026-05-01

### Sidebar de conhecimento nas mensagens

- A sidebar em `dashboard/app/messages/page.tsx` estava correta em carregar dados, mas ruim em priorizacao: para a Prime Higienizacao ela exibia quase todo o grafo expandido (ex.: 183 nos), incluindo tags, mentions, copys e FAQs repetidas, em vez de mostrar o conhecimento mais proximo da mensagem.
- Correcao aplicada: a sidebar agora calcula relevancia por tipo, distancia no grafo, termos detectados, slug/titulo/resumo/tags/aliases/preco e validacao.
- A secao antiga "Nos do grafo" foi substituida por:
  - "Conhecimento principal": um unico card mais relevante.
  - "Mais proximos": lista curta de ate 6 cards, sem `tag`, `mention` e `persona`.
- Produtos, campanhas, briefings, regras/tom, base ativa, FAQs, copies, similares, assets e pendentes agora sao limitados em quantidade para evitar despejar o grafo inteiro na sidebar.
- Cenario esperado: se a mensagem for "Quanto custa Higienizacao de Cadeiras Prime?", o card principal deve tender ao node `product` de `Higienizacao-Cadeiras-Prime`, exibindo preco/fatos; se a mensagem estiver apenas no nivel da marca Prime Higienizacao, o card principal deve tender ao node `brand`.

### Pendencia de UX do filtro global

- O filtro superior de personas aparece em todas as abas, mas em telas com seletor dedicado de persona, como a aba Persona, isso causa ambiguidade.
- Ja foi adicionado "Todos" como opcao default do filtro global para a aba Mensagens nao parecer filtrada por Tock Fatal quando mostra todas as conversas.
- Pendente: revisar por tela se o filtro global deve aparecer, ficar desabilitado ou ser escondido quando a tela tiver seletor proprio de persona. Esta decisao deve ser feita com contexto das demais telas antes de nova mudanca ampla.

### Entrada de KB database-first para RAG

- Criada a migration `supabase/migrations/013_knowledge_rag_intake.sql` com quatro tabelas novas:
  - `knowledge_intake_messages`: inbox bruto de qualquer conhecimento recebido.
  - `knowledge_rag_entries`: unidade canonica consultavel por RAG, com `question`, `answer`, `content`, `summary`, `semantic_level`, `tags`, `products`, `campaigns`, `metadata`, `embedding`.
  - `knowledge_rag_chunks`: chunks embedaveis por entrada.
  - `knowledge_rag_links`: relacoes semanticas/hierarquicas entre entradas RAG.
- Criado `services/knowledge_rag_intake.py`:
  - classificador deterministico inicial para conteudos FAQ-like;
  - extrai `Pergunta:/Resposta:` ou pergunta na primeira linha;
  - detecta preco simples em `R$` ou percentual;
  - tenta vincular produto comparando texto contra nodes `product` existentes no grafo da persona;
  - cria entrada RAG, chunk pendente de embedding e espelha no grafo via `knowledge_graph.bootstrap_from_item(source_table='knowledge_rag_entries')`.
- Criado endpoint `POST /knowledge/intake` em `api/routes/knowledge.py`.
- Adicionados helpers em `services/supabase_client.py` para inserir intake, upsert de RAG entry, substituir chunks e criar links.
- Criado teste offline `tests/integration_knowledge_rag_intake.py`, validando o caminho FAQ -> RAG entry -> chunk -> graph mirror com Prime Higienizacao.
- Validacao executada:
  - `python -m py_compile services\knowledge_rag_intake.py services\supabase_client.py api\routes\knowledge.py tests\integration_knowledge_rag_intake.py` - PASS.
  - `python tests\integration_knowledge_rag_intake.py` - PASS.
- Pendente operacional: aplicar `013_knowledge_rag_intake.sql` no Supabase antes de usar `POST /knowledge/intake` contra banco real.

### Validacao ponta a ponta da sidebar hierarquizada + grafo

- Pedido do usuario: validar e corrigir a integracao entre sidebar de conhecimentos, busca por produtos/FAQs, filtro global do header e aba Grafos em niveis.
- Correcao aplicada em `dashboard/components/graph/GraphView.tsx`:
  - o ReactFlow atualizava `nodes` quando o payload mudava, mas nao atualizava `edges`;
  - isso podia deixar conexoes antigas ao trocar filtro/foco/persona;
  - agora `setEdges(styledEdges)` roda sempre que as edges estilizadas mudam.
- Correcao aplicada em `dashboard/components/graph/NodeDrawer.tsx`:
  - o drawer agora aceita `focusPath` e `onFocusHere`, que ja eram enviados pela pagina Grafos;
  - adiciona botao de foco/centralizacao e bloco "Caminho semantico";
  - resolve o erro TypeScript da aba Grafos.
- Criado `tests/integration_knowledge_ui_hierarchy.py`:
  - valida estaticamente que o header tem opcao `Todos`, defaulta para `Todos` quando nao ha persona salva, e limpa `ai-brain-persona-id`;
  - valida que a aba Mensagens usa o filtro do header para `leads` e `conversations`;
  - valida que a sidebar possui "Conhecimento principal" e "Mais proximos";
  - valida que o grafo oculta tags/mentions por default, possui modo `semantic_tree` e atualiza edges;
  - valida backend offline com uma persona Tock e uma Prime:
    - Tock retorna produto `modal` + FAQ;
    - Prime retorna produto `higienizacao-cadeiras-prime` + FAQ;
    - cada persona exclui produto da outra;
    - graph-data em `Todos` inclui produto de ambas;
    - graph-data filtrado por persona isola corretamente;
    - focus em produto Prime retorna `focus_path`, levels de produto/FAQ e tiers strong/structural.
- Ajustado `tests/integration_prime_higienizacao_mock.py` para monkeypatchar `get_kb_entries_by_ids` no fake store e remover warnings de tentativa de acesso real ao Supabase durante teste offline.
- Validacao executada:
  - `python tests\integration_knowledge_ui_hierarchy.py` - PASS.
  - `python tests\integration_prime_higienizacao_mock.py` - PASS.
  - `python tests\integration_knowledge_rag_intake.py` - PASS.
  - `python -m py_compile api\routes\graph.py api\routes\knowledge.py services\knowledge_graph.py services\knowledge_rag_intake.py services\supabase_client.py tests\integration_knowledge_ui_hierarchy.py tests\integration_prime_higienizacao_mock.py` - PASS.
  - `cd dashboard; npx.cmd tsc --noEmit` - PASS.

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

### Capturar com blocos selecionaveis

Pedido:
- Remover a necessidade de o operador escrever um "Grafo esperado" manual.
- Na aba Capturar, mostrar blocos selecionaveis para os tipos de conhecimento mapeados.
- Quando um bloco for selecionado, o modelo deve perguntar lacunas especificas antes de propor entries, links, copys ou salvar.
- Se a conversa mudar, os blocos tambem podem mudar.

Alteracoes:
- `dashboard/app/knowledge/capture/page.tsx`
  - removeu `expectedGraph`/`DEFAULT_EXPECTED_GRAPH`;
  - adicionou `KNOWLEDGE_BLOCKS` para brand, briefing, campaign, audience, product, entity, copy, faq, rule, tone e asset;
  - `CapturePlan` agora usa `selectedBlocks`;
  - pre-confirmacao exibe cards selecionaveis por bloco;
  - contexto inicial enviado ao agente inclui "Blocos de conhecimento solicitados";
  - sidebar reaproveita o espaco mostrando blocos selecionados em vez de subnodes fixos;
  - botao de iniciar exige confirmacao e ao menos um bloco selecionado.
- `services/kb_intake_service.py`
  - prompt ganhou secao "BLOCOS SELECIONADOS NA CAPTURA";
  - define lacunas minimas por bloco e instrui o modelo a nao exigir IDs de grafo escritos pelo operador;
  - orienta atualizar os blocos quando o objetivo mudar durante a conversa.
- `api/routes/kb_intake.py`
  - welcome menciona entries, links e copys em vez de apenas grafo.

Validacao:
- `python -m py_compile services\kb_intake_service.py api\routes\kb_intake.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- `python tests\integration_knowledge_rag_intake.py` - PASS.

### Criar unificado em Marketing

Pedido:
- A experiencia nao deve iniciar como "KB Classifier".
- Renomear "KB Classifier" para "Criar".
- Unificar a captura/classificacao com a aba `marketing/criacao`.
- Adicionar duas ferramentas no header da tela Criar.
- Mover o menu para a subcategoria Marketing e posicionar Marketing acima de Knowledge.

Alteracoes:
- `dashboard/app/layout.tsx`
  - Marketing agora aparece antes de Knowledge;
  - item `/marketing/criacao` virou `Criar`;
  - item `/knowledge/capture` saiu da sidebar.
- `dashboard/app/marketing/criacao/page.tsx`
  - adicionou header de ferramentas;
  - aba `Criar` embute o workspace de captura/conhecimento;
  - aba `Gerar copy` mantem a criacao de marketing antiga.
- `dashboard/app/knowledge/capture/page.tsx`
  - exporta `CaptureWorkspace` para reuso;
  - header do agente virou `Criar`;
  - removeu a mensagem de sistema visivel "Plano carregado...";
  - modo embutido usa altura total do painel.
- `api/routes/kb_intake.py`, `services/kb_intake_service.py`, `dashboard/app/knowledge/intake/page.tsx`, `dashboard/app/validacao/tools/page.tsx`
  - nomes user-facing alterados de `KB Classifier` para `Criar`.
- `dashboard/app/knowledge/assets/page.tsx`
  - atalhos antigos de captura apontam para `/marketing/criacao`.

Validacao:
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- `python -m py_compile services\kb_intake_service.py api\routes\kb_intake.py` - PASS.
- `python tests\integration_knowledge_rag_intake.py` - PASS.
- `GET http://localhost:3000/marketing/criacao` - 200.

### Identidade Sofia/Zaya no Criar

Decisao de produto registrada pelo usuario:
- `Criar` e o nome da ferramenta/tela, nao da agente conversacional.
- A agente padrao atual deve ser `Sofia`.
- Sofia e uma agente de inteligencia marketing comercial.
- A primeira fala nao deve ser "oi eu sou Criar".
- A abertura esperada e: "Ola! Eu sou a Sofia. Aprendi bastante sobre marketing para te ajudar a construir conhecimento para tua marca."
- Futuramente, de forma organica durante a conversa, podera entrar `Zaya`, agente de marketing visual.
- Zaya nao precisa estar ativa agora, mas o backend deve ficar preparado para perfis de agente.

Alteracoes:
- `services/kb_intake_service.py`
  - adicionou `AGENT_PROFILES` com `sofia` e `zaya`;
  - `create_session()` agora aceita `agent_key`, default `sofia`;
  - sessao guarda `agent_key`, `agent_name`, `agent_role` e `agent_greeting`;
  - prompt deixou de dizer que a agente e `Criar`;
  - prompt instrui que, se precisar se apresentar, deve usar a agente ativa e nunca dizer que e Criar.
- `api/routes/kb_intake.py`
  - `StartBody` aceita `agent_key`, default `sofia`;
  - `/kb-intake/start` retorna `agent` e usa o greeting da Sofia no welcome.
- `README.md`
  - documentou a regra de identidade das agentes no Criar.

Validacao:
- `python -m py_compile services\kb_intake_service.py api\routes\kb_intake.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- Chamada direta de `start_session(StartBody())` retornou `agent={"key":"sofia","name":"Sofia","role":"agente de inteligencia marketing comercial"}` e welcome iniciando com Sofia.

### Correção do fluxo Sofia para catálogo/crawler

Problema observado no diálogo:
- Sofia aceitou "leia no site todos os produtos" como se o sistema conseguisse interpretar perfeitamente o catálogo.
- Fez perguntas repetidas sobre dados que o usuário mandou coletar da fonte.
- Ao final, gerou só um resumo genérico ("Produtos Tock Fatal"), sem criar os vários conhecimentos correspondentes aos blocos selecionados: briefing, público, produto, entidades, copy e FAQ.
- Isso não constrói a árvore de conhecimento solicitada.

Decisão:
- Scraping/crawler de site deve ser tratado como captura bruta + parsing heurístico + score de confiança + validação humana.
- O sistema local não deve pressupor a mesma capacidade de navegação/interpretação deste chat.
- HTML inconsistente, JS, imagens, variações e preços incompletos devem gerar avisos/lacunas, não conhecimento ativo.
- Quando o usuário pedir para ler/coletar a fonte, Sofia deve usar o crawler se disponível; se não souber, deve perguntar ou pedir upload/evidência.
- Ao final, Sofia deve gerar diversos conhecimentos, cobrindo todos os blocos selecionados, e listar entries/links concretos antes de salvar.
- O bloco `copy` deve gerar copys quando houver informação suficiente.

Alterações:
- `services/catalog_crawler.py`
  - novo crawler heurístico de catálogo;
  - captura HTML/texto bruto;
  - extrai JSON-LD Product quando existir;
  - extrai candidatos por texto visível com heurísticas de produto/preço/cor;
  - retorna `confidence`, `confidence_label`, `warnings`, `stages`, `product_candidates` e `raw_text_preview`;
  - sempre marca validação humana como obrigatória.
- `api/routes/kb_intake.py`
  - nova rota `POST /kb-intake/crawl-preview`;
  - opcionalmente anexa o resultado à sessão.
- `services/kb_intake_service.py`
  - detecta pedidos como "leia/colete/site/produtos/catalogo";
  - roda crawler sobre a `fonte principal` do contexto inicial;
  - injeta resultado do crawler no system context da Sofia;
  - prompt passou a proibir a frase "li todos os produtos" quando a confiança for baixa/média ou os candidatos forem incompletos;
  - prompt exige proposta com status por entry: `confirmado`, `inferido`, `pendente_validacao`;
  - prompt exige vários conhecimentos por bloco selecionado, não resumo genérico;
  - aumentou `max_tokens` para 2400 para caber proposta com múltiplas entries.
- `dashboard/app/knowledge/capture/page.tsx`
  - sidebar agora mostra pipeline com crawler bruto, parsing/confiança, lacunas, árvore, geração de conhecimentos, validação humana e draft;
  - sidebar ganhou painel "Crawler da fonte" com estágios, confiança, warnings e número de candidatos;
  - o chat recebe `crawler` do backend e atualiza a visualização.
- `dashboard/lib/api.ts`
  - adicionou `kbIntakeCrawlPreview`.
- `docs/knowledge-flow.md`
  - documentou Criar/Sofia e a etapa de captura de site como evidência bruta.

Validação:
- `python -m py_compile services\catalog_crawler.py services\kb_intake_service.py api\routes\kb_intake.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.
- `python tests\integration_knowledge_rag_intake.py` - PASS.
- chamada direta de `crawl_catalog_url('not-a-url')` retorna `ValueError` esperado.

### E2E Tock Fatal catalogo -> KB -> grafo

Pedido:
- Concluir o teste que Claude iniciou.
- Escrever prompt/plano estruturado para E2E adicionando conhecimentos a partir do site Tock Fatal.
- Adicionar 3 produtos, 2 publicos, estrutura/grafo completo para Tock Fatal Atacado, com todos os cards adicionados a KB/grafo.
- O E2E deve gerar um print da arvore de conhecimento.

Implementacao:
- Criado `tests/e2e_tock_fatal_catalog_graph.py`.
- Criado `docs/e2e-tock-fatal-catalog-graph.md` com prompt, plano, comandos e resultado validado.
- Ajustado `services/knowledge_graph.py` para mapear `content_type='entity'` para node_type `entity`.

Estrategia do teste:
- Usa `run_token` em slugs/tags/titulos para isolar o subtree do baseline Tock Fatal.
- Abre `/marketing/criacao` com Playwright e salva screenshot.
- Insere conhecimentos por API:
  - brand;
  - campaign;
  - briefing;
  - 2 audiences;
  - 3 products;
  - entity;
  - 2 copies;
  - FAQs derivadas de blocos `Pergunta:/Resposta:` dentro dos produtos.
- Promove para KB os tipos aceitos pela fila legacy.
- Usa `/knowledge/intake` para tipos granulares da migration 013 quando a fila legacy nao aceita.
- Valida `/knowledge/graph-data` para Tock Fatal e captura `/knowledge/graph` em modo arvore.

Observacoes de execucao:
- `/knowledge/upload/text` retornou 500 para `content_type=entity`, `copy` e `faq` neste ambiente.
- Para `entity` e `copy`, o teste usa `/knowledge/intake`.
- Para FAQ, o teste usa FAQs derivadas a partir dos produtos, pois a rota direta de FAQ tambem falhou no banco atual.
- Um run completo `e2efix005` falhou por instabilidade de backend (`Server disconnected`) durante uma promocao, mas o run anterior `e2efix004` ja havia criado e validado o subtree.
- Playwright precisou permissao elevada no sandbox Windows para abrir Chromium e salvar screenshot.

Run validado:
- `python -u tests\e2e_tock_fatal_catalog_graph.py --skip-browser --run-token e2efix004` - PASS API/grafo.
- `python -u tests\e2e_tock_fatal_catalog_graph.py --screenshot-only --run-token e2efix004` - PASS com screenshot, executado com permissao elevada.
- `python -m py_compile tests\e2e_tock_fatal_catalog_graph.py services\knowledge_graph.py` - PASS.

Artefatos:
- `test-artifacts/e2e-tock-fatal-catalog-graph/report-e2efix004.json`
- `test-artifacts/e2e-tock-fatal-catalog-graph/criar-e2efix004.png`
- `test-artifacts/e2e-tock-fatal-catalog-graph/knowledge-tree-e2efix004.png`

Resumo do report `e2efix004`:
- `token_nodes`: 25
- `token_edges`: 139
- product: 3
- audience: 2
- entity: 1
- copy: 2
- faq: 6

### E2E Tock Fatal agora usa LLM obrigatoriamente

Pedido:
- O teste nao pode apenas representar a conversa com dados deterministicos.
- Deve usar a LLM/Sofia para cumprir o objetivo.
- Se a LLM nao cumprir, o teste deve falhar e os objetivos/prompts do agente devem ser ajustados.

Alteracoes:
- `services/kb_intake_service.py`
  - prompt ganhou secao "SAIDA ESTRUTURADA OBRIGATORIA PARA GERACAO";
  - quando operador pede gerar/criar arvore, Sofia deve emitir `<knowledge_plan>...</knowledge_plan>` com JSON;
  - exige entries por bloco selecionado;
  - exige cumprir quantidades minimas;
  - se pedir 3 produtos e crawler encontrar so 2, terceiro deve ser produto candidato `pendente_validacao`;
  - exige no minimo 2 FAQs para preco/kits e cores;
  - exige pelo menos 8 links semanticos;
  - aumentou `max_tokens` para 4000.
- `tests/e2e_tock_fatal_catalog_graph.py`
  - etapa LLM agora e obrigatoria por default;
  - abre sessao Sofia via `/kb-intake/start`;
  - envia prompt completo para gerar arvore de conhecimento;
  - parseia `knowledge_plan`;
  - falha se a LLM nao gerar 3 produtos, 2 publicos, entity, copy, FAQ, links e run_token;
  - `--skip-llm` ficou apenas para debug local;
  - `--screenshot-only` agora preserva/mescla report anterior em vez de sobrescrever detalhes da LLM.

Iteracoes de ajuste:
- Run `e2ellm001`: falhou porque Sofia gerou so 2 products.
  - Prompt ajustado para obrigar terceiro produto candidato quando crawler trouxer apenas 2.
- Run `e2ellm002`: falhou porque Sofia gerou so 1 FAQ.
  - Prompt ajustado para exigir pelo menos 2 FAQs: preco/kits e cores.
- Run `e2ellm003`: Sofia gerou plano correto, mas usou bloco ```json em vez de `<knowledge_plan>`.
  - Prompt ajustado para exigir tags literais;
  - parser do teste ficou robusto para aceitar JSON fenced tambem, sem deixar de validar o conteudo.
- Run `e2ellm004`: PASS LLM + API/grafo sem browser.
- Run `e2ellm005`: PASS LLM + API/grafo e screenshot.

Run validado final:
- `python -u tests\e2e_tock_fatal_catalog_graph.py --skip-browser --run-token e2ellm005` - PASS.
- `python -u tests\e2e_tock_fatal_catalog_graph.py --screenshot-only --run-token e2ellm005` - PASS com Playwright/Chromium usando permissao elevada.
- `python -m py_compile services\kb_intake_service.py tests\e2e_tock_fatal_catalog_graph.py` - PASS.

Artefatos finais:
- `test-artifacts/e2e-tock-fatal-catalog-graph/report-e2ellm005.json`
- `test-artifacts/e2e-tock-fatal-catalog-graph/criar-e2ellm005.png`
- `test-artifacts/e2e-tock-fatal-catalog-graph/knowledge-tree-e2ellm005.png`

Resumo LLM no report `e2ellm005`:
- entries geradas pela Sofia:
  - briefing: 1
  - audience: 2
  - product: 3
  - entity: 1
  - copy: 2
  - faq: 2
- links LLM: 8

Resumo grafo `e2ellm005`:
- `token_nodes`: 26
- `token_edges`: 113
- product: 3
- audience: 2
- entity: 1
- copy: 2
- faq: 6

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

## Sessao 2026-05-01 - persona routing (internal vs n8n) + webhook config

### Pedido

Permitir escolher por persona (na aba Persona do dashboard) entre 2 modos:
- `internal`: AI Brain processa, responde e envia via webhook saida.
- `n8n`: AI Brain so persiste mensagens; n8n responde. Mensagens humanas (operador) sempre saem via webhook saida.

UX: 2 radios (mutuamente exclusivos) + botao engrenagem que abre drawer com campos de webhook (URL/secret/token).

### Plano completo (passo a passo, manter aqui caso sessao trave)

1. Migration `supabase/migrations/011_persona_routing.sql`:
   ```sql
   ALTER TABLE personas ADD COLUMN IF NOT EXISTS process_mode TEXT
     DEFAULT 'internal' CHECK (process_mode IN ('internal','n8n'));
   ALTER TABLE personas ADD COLUMN IF NOT EXISTS outbound_webhook_url TEXT;
   ALTER TABLE personas ADD COLUMN IF NOT EXISTS outbound_webhook_secret TEXT;
   ALTER TABLE personas ADD COLUMN IF NOT EXISTS inbound_webhook_token TEXT;
   ```

2. `services/supabase_client.py`:
   - `get_persona_routing(slug)` retorna {process_mode, outbound_webhook_url, outbound_webhook_secret, inbound_webhook_token}.
   - `update_persona_routing(slug, data)` faz update parcial.

3. `api/routes/persona.py` (criar router se nao existir):
   - `GET  /personas/{slug}/routing` retorna config.
   - `PATCH /personas/{slug}/routing` body {process_mode?, outbound_webhook_url?, outbound_webhook_secret?, inbound_webhook_token?}.
   - `POST /personas/{slug}/routing/test` envia payload mock no outbound webhook e retorna status.
   - Mascarar secret/token na resposta GET (so retorna boolean tem/nao tem).

4. `api/routes/process.py`:
   - No comeco, resolver persona via `event.persona_slug`.
   - Se `persona.process_mode == 'n8n'`:
     - Validar header `X-Webhook-Token == persona.inbound_webhook_token` (se configurado).
     - Persistir mensagem inbound via `supabase_client.insert_message` (sender_type='client').
     - Garantir lead via `ensure_lead_for_persona`.
     - Retornar `{"reply": null, "agent_used": "N8N_DELEGATED", "stage_update": ..., "score": 0}`.
   - Se `internal` (default): fluxo atual mantido.

5. `api/routes/messages.py:send_message`:
   - Resolver persona via lead.persona_id.
   - Preferir `persona.outbound_webhook_url` antes do `agent.n8n_webhook_url` (fallback).
   - Header `X-Webhook-Secret` com `persona.outbound_webhook_secret`.

6. `dashboard/lib/api.ts`:
   - `personaRouting(slug)` GET, `updatePersonaRouting(slug, body)` PATCH, `testPersonaRouting(slug)` POST.

7. `dashboard/app/persona/page.tsx`:
   - Card por persona (ja existe lista).
   - Radio group: Internal | n8n.
   - Botao Settings/engrenagem -> drawer.
   - Drawer: outbound_webhook_url, outbound_webhook_secret, inbound_webhook_token (gerar UUID se vazio quando mode=n8n), preview da URL `POST {NEXT_PUBLIC_AI_BRAIN_URL}/process` para colar no n8n, botao Testar webhook.

8. MCP setup (manual no `.claude/settings.json` global):
   - supabase: `npx -y @supabase/mcp-server-supabase` com SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY do .env.
   - google-sheets/gdrive: `npx -y @modelcontextprotocol/server-gdrive` com GDRIVE_CREDENTIALS_PATH.

### Como configurar dentro da aba Persona (UX final)

1. Abrir Dashboard -> Persona.
2. Selecionar persona desejada (Tock, Prime, etc.).
3. No bloco "Roteamento":
   - Marcar `Processar internamente (AI Brain)` ou `Processar via n8n`.
4. Clicar na engrenagem ao lado.
5. No drawer:
   - Preencher Webhook de saida (URL + secret) — usado nos dois modos para enviar mensagem humana.
   - Se modo=n8n: copiar Token de entrada e a URL `POST .../process` para colar no nodo HTTP do workflow n8n.
6. Salvar e clicar "Testar webhook" — payload mock e disparado no outbound URL e a resposta volta no UI.
7. Para cada persona, repetir.

### Ordem de implementacao desta sessao

- (1) migration arquivo criado (operador aplica no Supabase).
- (2) supabase_client helpers.
- (3) routes persona.
- (4)/(5) branch em process + send_message usando persona webhook.
- (6)/(7) dashboard ficam para sessao seguinte se acabar token.

### Continuidade apos limite do Claude - UI de routing finalizada

O usuario pediu para continuar de onde Claude parou. Estado encontrado:
- `dashboard/lib/api.ts` ja tinha os helpers `personaRouting`, `updatePersonaRouting`, `testPersonaRouting`.
- `dashboard/app/persona/page.tsx` ja tinha o card de "Roteamento de mensagens" com radios internal/n8n e botao engrenagem.
- Faltava o drawer da engrenagem e a possibilidade real de salvar/testar webhooks.

Alteracoes aplicadas:
- `api/routes/personas.py`
  - `PATCH /personas/{slug}/routing` continua mascarando secrets no retorno normal.
  - Quando `rotate_inbound_token=true`, a resposta inclui `inbound_webhook_token` uma unica vez para o operador copiar para o n8n.
- `dashboard/lib/api.ts`
  - Tipo de `personaRouting` agora aceita `inbound_webhook_token?: string`.
- `dashboard/app/persona/page.tsx`
  - Adicionado drawer de webhooks com:
    - campo `Webhook de saida`;
    - campo `Secret de saida`;
    - campo `Token de entrada n8n`;
    - botao `Rotacionar`;
    - preview do endpoint `POST .../api-brain/process`;
    - botao `Testar`;
    - botao `Salvar`;
    - mensagens de resultado.
  - Ao trocar de persona, limpa formulario/drawer/resultados para evitar vazar config visual entre clientes.
  - Ao salvar secret, limpa o campo de secret por seguranca.

Validacao:
- `python -m py_compile api\routes\personas.py api\routes\process.py api\routes\messages.py services\supabase_client.py` - PASS.
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.

Pendente operacional:
- Aplicar `supabase/migrations/011_persona_routing.sql` no Supabase antes de usar PATCH/Salvar routing.
- Depois configurar cada persona pela aba Persona ou via API.

### WhatsApp phone_number_id por lead

O usuario observou que o n8n usa `{{ $('WhatsApp Trigger').item.json.metadata.phone_number_id }}` para enviar WhatsApp, e que no handoff humano esse dado precisa vir da tabela porque o caminho `Webhook Tock Out` nao passa pelo `WhatsApp Trigger`.

Decisao:
- Guardar o `phone_number_id` responsavel pelo atendimento no lead.
- Tambem guardar em messages para auditoria.

Alteracoes:
- Criada migration `supabase/migrations/012_lead_whatsapp_phone_number_id.sql`:
  - `leads.whatsapp_phone_number_id TEXT`
  - `messages.whatsapp_phone_number_id TEXT`
- `schemas/events.py`: `LeadEvent.whatsapp_phone_number_id`.
- `services/supabase_client.py:ensure_lead_for_persona()`: aceita e persiste `whatsapp_phone_number_id`.
- `core/context_builder.py`: repassa `event.whatsapp_phone_number_id`.
- `api/routes/process.py`:
  - modo n8n persiste inbound com `whatsapp_phone_number_id`;
  - modo internal persiste outbound com `lead_data.whatsapp_phone_number_id`.
- `api/routes/messages.py:send_message()`:
  - salva mensagem humana com `lead.whatsapp_phone_number_id`;
  - envia no payload para n8n: `lead_id`, `telefone`, `whatsapp_phone_number_id`.

Validacao:
- `python -m py_compile schemas\events.py services\supabase_client.py core\context_builder.py api\routes\process.py api\routes\messages.py` - PASS.

Contrato n8n:
- No fluxo inbound, enviar ao AI Brain:
  - `whatsapp_phone_number_id: {{ $('WhatsApp Trigger').item.json.metadata.phone_number_id }}`
- No `Webhook Tock Out`, enviar WhatsApp humano usando:
  - `phoneNumberId: {{ $json.whatsapp_phone_number_id || $('Buscar Lead').item.json.whatsapp_phone_number_id }}`

### Ajuste Sofia bot phone_number_id

O usuario informou:
- Sender Phone Number / ID do Sofia bot: `949967854877404`.
- Esse valor deve ser salvo em `leads` para que toda resposta de operador seja associada ao numero correto do bot.

Alteracoes:
- `supabase/migrations/012_lead_whatsapp_phone_number_id.sql`
  - adiciona tambem `workflow_bindings.whatsapp_phone_number_id`;
  - seta `workflow_bindings.whatsapp_phone_number_id='949967854877404'` para persona `tock-fatal`;
  - backfill em todos os leads Tock sem valor para `949967854877404`.
- `services/supabase_client.py`
  - nova funcao `get_default_whatsapp_phone_number_id(persona_id)`;
  - `ensure_lead_for_persona()` usa o default do workflow binding quando o evento nao trouxer `whatsapp_phone_number_id`.
- `api/routes/messages.py`
  - `/messages/send` usa `lead.whatsapp_phone_number_id` ou fallback do binding da persona;
  - payload para n8n sempre inclui `whatsapp_phone_number_id` quando houver default.

Validacao:
- `python -m py_compile services\supabase_client.py api\routes\messages.py` - PASS.

### Aba Leads abrindo mensagens sem lead_ref

Problema reportado:
- Ao clicar em um lead pela aba Leads, a tela `/messages/[leadId]` mostrava:
  "Esta conversa nao tem lead_ref numerico — abra pela aba Mensagens via lead_ref para responder."

Causa:
- `dashboard/app/leads/page.tsx` linkava para `/messages/${lead.lead_id}`.
- `lead.lead_id` e o identificador externo/telefone, nao o `lead_ref` numerico usado por `/messages/send`.
- A pagina individual de mensagens so habilita resposta quando o path contem um numero curto que represente `leads.id`.

Correcao:
- Link da aba Leads alterado para `/messages/${lead.id}`.

Validacao:
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.

### Filtro superior de personas com estado Todos

Problema reportado:
- Header mostrava uma persona selecionada, como Tock Fatal, mas algumas telas carregavam dados de todos os leads.
- Isso criava desalinhamento: visualmente parecia filtrado, operacionalmente estava sem filtro.

Causa:
- `dashboard/app/layout.tsx` escolhia a primeira persona como default depois de carregar personas.
- Enquanto isso, telas como Mensagens/Leads interpretavam `persona_id` vazio como "sem filtro" e carregavam todos.

Correção:
- Filtro superior agora inclui opção `Todos`.
- Estado default do header é `Todos` (`persona=""`), não mais primeira persona/Tock.
- Quando `Todos` está selecionado:
  - remove `ai-brain-persona-slug`;
  - remove `ai-brain-persona-id`;
  - dispara evento `ai-brain-persona-change` com `id=""`.
- Telas que já usam `personaFilterId || undefined` continuam funcionando: vazio = todos.

Validação:
- `cd dashboard; npx.cmd tsc --noEmit` - PASS.

## Plano de Teste E2E - Bulk 20

- **Arquivo de Teste**: `tests/e2e_tock_fatal_bulk_20.py` (cópia de `e2e_tock_fatal_catalog_graph.py`)
- **Objetivo**: Testar a criação em massa de ~20 itens de conhecimento para a persona "tockfatal".
- **Estratégia Híbrida**:
    1.  **Validação da LLM**: O teste primeiro desafia a LLM (Sofia) a gerar um plano com mais de 20 itens, validando sua capacidade de planejamento em massa. O prompt foi ajustado para essa finalidade.
    2.  **Criação Determinística**: Em seguida, o teste utiliza uma lista expandida e fixa de 21 itens de conhecimento (5 produtos, 5 copys, 5 FAQs, etc.) dentro da função `knowledge_specs` para de fato criar os itens no sistema.
    3.  **Validação do Grafo**: A função `validate_graph` foi ajustada para verificar se os 21 itens foram criados corretamente no grafo de conhecimento.
    4.  **Evidência Visual**: O teste inclui a captura de tela da UI para evidência visual, como solicitado.
- **Status**: O script foi criado e está pronto para execução.
