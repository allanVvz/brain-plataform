# AI Brain — Progresso UI/UX

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
- O AI Brain exige login para todas as telas internas do dashboard.
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

# AI Brain - Deploy e Operacao

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
