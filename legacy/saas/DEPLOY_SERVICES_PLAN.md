# Relatório Técnico: Plano de Deploy para Produção (Revisado)

Este documento detalha as alterações arquiteturais necessárias para desacoplar o projeto de dependências locais e prepará-lo para o deploy em produção, corrigindo inconsistências do plano anterior e adotando uma abordagem faseada e mais segura.

## O que não fazer agora

Antes de detalhar o plano, é crucial alinhar sobre o que **não** deve ser feito para evitar os problemas de instabilidade da ferramenta de edição que bloquearam o progresso anterior:

- Não continuar refatorações grandes com a ferramenta de edição, especialmente em arquivos Python.
- Não mexer em vários arquivos Python de uma vez; focar em um de cada vez, validando com `py_compile`.
- Não salvar conhecimento diretamente na base de conhecimento (`KB`) a partir do sync; todos os novos itens devem passar pela fila de validação (`pending_validation`).
- Não expor nenhum segredo (`GITHUB_TOKEN`, `SUPABASE_SERVICE_ROLE_KEY`, etc.) no código do frontend.
- Não depender de `C:\Ai-Brain` ou qualquer outro caminho local absoluto em código que irá para produção.
- Não forçar testes E2E do fluxo completo (ex: WhatsApp) antes que o backend mínimo (`/health`) esteja estável e acessível publicamente.

---

## 1. Ordem Segura de Implementação (Revisada)

A abordagem deve ser incremental para garantir estabilidade a cada passo.

1.  **Restaurar Backend Funcional**: Garantir que todos os arquivos (`.py`) no projeto compilam sem erros de sintaxe (`python -m py_compile ...`). Se necessário, fazer rollback de arquivos corrompidos a partir do Git.
2.  **Criar Client de API Central no Frontend**: Refatorar o `dashboard` para ter um client de API central em `dashboard/lib/api.ts` que gerencia a `NEXT_PUBLIC_API_URL`.
3.  **Remover `localhost` Hardcoded**: Substituir qualquer `localhost` no código do frontend pelo novo client de API.
4.  **Criar Endpoint `/health` no Backend**: Implementar um endpoint `/health` simples que não tenha nenhuma dependência externa, apenas retorne `{"status": "ok"}`.
5.  **Preparar Backend para Deploy (Dockerfile)**: Criar um `Dockerfile` para a aplicação Python que permita o deploy em um contêiner.
6.  **Publicar Backend Mínimo**: Fazer o deploy do backend mínimo (apenas com o endpoint `/health`) no Cloud Run ou serviço similar.
7.  **Conectar Frontend e Backend**: Configurar a `NEXT_PUBLIC_API_URL` no ambiente da Vercel para apontar para o backend em produção e validar a comunicação.
8.  **Refatorar o Acesso ao Vault (Fase 1)**: Somente após a conexão F-B estar validada, iniciar a refatoração do `services/vault_sync.py` para suportar a leitura do GitHub via `git clone`.
9.  **Religar Pipeline de Conhecimento**: Conectar o fluxo de `vault_sync` para criar itens com status `pending_validation`.
10. **Testar Fluxos Dependentes**: Por último, testar os fluxos mais complexos como Sofia/WA Validator, agora que a base da arquitetura está estável.

## 2. Frontend (Vercel)

### Correção 1: Padronizar Variável de API

O projeto deve padronizar o uso de `NEXT_PUBLIC_API_URL` para configurar o endereço do backend. Qualquer uso da variável antiga `NEXT_PUBLIC_AI_BRAIN_URL` deve ser migrado. O arquivo `dashboard/next.config.js` deve ser o ponto central dessa configuração no lado do Next.js.

### Correção 2: Centralizar Lógica de API em `dashboard/lib/api.ts`

A recomendação anterior de verificar a variável de ambiente em `layout.tsx` é arriscada, pois pode quebrar o Server-Side Rendering (SSR) ou o build. A abordagem correta é:

- Criar ou ajustar um client de API central em `dashboard/lib/api.ts`.
- Este arquivo será o único responsável por ler `process.env.NEXT_PUBLIC_API_URL`.
- Se a variável estiver ausente, o client de API deve lançar um erro claro ou retornar um estado de erro que possa ser tratado pelas páginas e componentes que o consomem, exibindo uma mensagem como "Backend não configurado. Defina NEXT_PUBLIC_API_URL.".
- Todas as chamadas de API no `dashboard` (ex: `knowledge`, `vault`, `capture`) devem usar este client, eliminando `localhost` hardcoded e centralizando a lógica.

## 3. Backend (Cloud Run)

### Correção 3: Requisitos para Deploy em Contêiner

Para deploy em serviços como o Cloud Run, o backend Python deve seguir estas regras:

- **Escutar em `0.0.0.0`**: O servidor (uvicorn) deve ser iniciado para aceitar conexões de qualquer IP, não apenas `localhost`.
- **Usar Variável `$PORT`**: A porta na qual o servidor escuta deve ser lida da variável de ambiente `PORT`, que é injetada pelo Cloud Run.
- **Configurar CORS**: O `api/main.py` deve ler uma variável de ambiente `ALLOWED_ORIGINS` (ex: `"https://seu-dominio.vercel.app,http://localhost:3000"`) para configurar o CORS e permitir requisições do frontend.
- **Responder ao `/health`**: O contêiner deve expor o endpoint `/health` para que o Cloud Run possa verificar se a aplicação está saudável.
- **Não depender de arquivos locais**: O estado da aplicação não pode depender de arquivos no sistema de arquivos local que não façam parte do contêiner.
- **Build do Frontend**: O build do frontend não deve exigir um backend rodando.

## 4. Estratégia para Vault no GitHub (Faseado)

A leitura do Vault do GitHub será feita em duas fases para acelerar o deploy e reduzir riscos.

### Fase 1: Solução Pragmática (`git clone`)

A implementação inicial será a que já desenvolvemos em `services/vault_sync.py`, usando `git clone` via `subprocess`. É crucial documentar os riscos desta abordagem:

- **Exige `git` no contêiner**: O `Dockerfile` do backend deve incluir a instalação do `git`.
- **Performance**: O clone pode ser lento, impactando o tempo de início de um sync.
- **Falhas**: Pode falhar se o repositório for muito grande ou a rede instável.
- **Limpeza**: Exige tratamento cuidadoso de diretórios temporários.

### Fase 2: Solução Ideal (Adapters)

A arquitetura final e mais limpa envolve a criação de uma camada de abstração com adapters, que seria implementada após a Fase 1 estar em produção e validada:

- **`services/vault_source_service.py`**: Um serviço que define uma interface comum para fontes de dados (ex: `list_files()`, `read_file(path)`).
- **`services/local_vault_adapter.py`**: Uma implementação da interface que lê do sistema de arquivos local usando `OBSIDIAN_LOCAL_PATH`.
- **`services/github_vault_adapter.py`**: Uma implementação que usa a API do GitHub (com `requests` ou `httpx`, evitando `subprocess`) para listar e ler arquivos diretamente, o que é mais eficiente e robusto.
- O `vault_sync.py` passaria a usar o `VaultSourceService` para obter os arquivos, sem nunca saber qual adapter está sendo usado por baixo.

## 5. Papel do `kb_intake_service.py` (Corrigido)

O `kb_intake_service.py` **não deve ser desabilitado** em modo GitHub. Seu papel é ser um serviço de ingestão agnóstico à fonte.

- **Leitura**: A responsabilidade de ler arquivos (seja do Vault local ou do GitHub) é exclusivamente do `vault_sync.py` (ou dos futuros adapters).
- **Ingestão**: O `vault_sync.py`, ao encontrar um arquivo novo ou modificado, deve chamar uma função no `kb_intake_service.py`, passando o **conteúdo e os metadados** do arquivo.
- **Processamento**: O `kb_intake_service` recebe esse payload e o processa, criando um `knowledge_item` com status `pending_validation` no banco de dados.
- **Restrição**: A única funcionalidade que deve ser restrita ao modo `local` é a de **escrever de volta** para o disco do Vault (ex: `_write_file`, `_git_ops`). Essa ação pode retornar um erro `NotImplementedError` se `VAULT_SOURCE_MODE` for `github`.

## 6. Endpoints Mínimos de Produção

O backend em produção deve expor, no mínimo, os seguintes endpoints para ser funcional:

- `GET /health`: Para health checks.
- `POST /knowledge/sync`: Para disparar o sync do Vault (agora sem parâmetros de caminho).
- `GET /knowledge/queue`: Para o dashboard ler a fila de validação.
- (Endpoints de manipulação da fila: `GET`, `PATCH`, `POST /approve`, etc.).

## 7. Checklist de Deploy

- [ ] Backend compila localmente (`python -m py_compile ...`).
- [ ] `Dockerfile` do backend é criado e o build passa.
- [ ] `docker run` local do backend sobe e o endpoint `/health` responde.
- [ ] Dashboard builda localmente (`npm run build`).
- [ ] Backend é publicado no Cloud Run.
- [ ] CORS (`ALLOWED_ORIGINS`) é configurado no Cloud Run para permitir o domínio da Vercel.
- [ ] Segredos privados (`GITHUB_TOKEN`, `SUPABASE_SERVICE_ROLE_KEY`) são configurados no Cloud Run.
- [ ] `VAULT_SOURCE_MODE=github` e as variáveis do repositório do Vault estão configuradas.
- [ ] Frontend é publicado na Vercel.
- [ ] `NEXT_PUBLIC_API_URL` e as chaves públicas do Supabase estão configuradas na Vercel.
- [ ] Acesso ao dashboard em produção funciona e chama o backend em produção.
- [ ] Disparar um sync via API busca um item do Vault do GitHub e o insere com status `pending_validation`.
- [ ] O item aparece na fila de validação no dashboard.
- [ ] A aprovação de um item na fila o move para o estado `approved`/`embedded`.
- [ ] O fluxo da Sofia/WA Validator continua funcionando (pode ser testado por último).

## 8. Como conectar este repo ao Brain AI Vault em nuvem

Use `VAULT_SOURCE_MODE=github` no backend publicado. Nesse modo, o sync le o
Vault pela API do GitHub e nao depende de clone, volume local ou caminho
`C:\Ai-Brain`.

Variaveis no Cloud Run:

- `VAULT_SOURCE_MODE=github`
- `GITHUB_VAULT_REPO=owner/ai-brain-vault`
- `GITHUB_VAULT_BRANCH=main`
- `GITHUB_VAULT_ROOT=` se o vault estiver na raiz, ou o subdiretorio do vault
- `GITHUB_TOKEN=` token com acesso read-only ao repositorio do vault
- `SUPABASE_URL` e `SUPABASE_SERVICE_KEY`
- `ALLOWED_ORIGINS=https://seu-dashboard.vercel.app,http://localhost:3000`

Fluxo esperado:

1. O operador chama `POST /knowledge/sync`.
2. O backend lista arquivos via GitHub API.
3. Cada arquivo vira `knowledge_items.status=pending`.
4. `knowledge_graph.bootstrap_from_item()` espelha as entries em
   `knowledge_nodes` e `knowledge_edges`.
5. O dashboard mostra a fila de validacao e o grafo por camadas.

No frontend/Vercel:

- `NEXT_PUBLIC_API_URL=https://sua-api-cloud-run.run.app`
- As chamadas do navegador usam `/api-brain/*`; o `next.config.js` faz rewrite
  para `NEXT_PUBLIC_API_URL`.
