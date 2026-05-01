# Prompt para Claude: Estruturacao de Conhecimento e Validacao em Grafo

Voce esta trabalhando no repositorio `ai-brain`. Continue exatamente do estado atual salvo em `memory.md` e use este arquivo como fonte de verdade da sessao.

## Regra obrigatoria de memoria

1. Antes de alterar qualquer arquivo, leia `memory.md`.
2. Durante a execucao, registre em `memory.md` toda decisao relevante, erro encontrado, correcao aplicada, comando de teste e resultado.
3. Antes de finalizar, releia `memory.md` e confirme que o resumo da sessao atual foi salvo.
4. Nunca imprima secrets do `.env`, especialmente `SUPABASE_SERVICE_KEY`.

## Ponto de partida

O trabalho atual esta na migration:

- `supabase/migrations/009_knowledge_curation_architecture.sql`

Estado conhecido:

- A migration 009 cria a camada canonica de curadoria:
  - `knowledge_node_type_registry`
  - `knowledge_relation_type_registry`
  - `knowledge_artifacts`
  - `knowledge_artifact_versions`
  - `agent_prompt_profiles`
  - `knowledge_curation_runs`
  - `knowledge_curation_proposals`
  - views `v_knowledge_lineage` e `v_knowledge_curation_backlog`
- A rotina de teste principal e:
  - `tests/integration_knowledge_curation_architecture.py`
- A rotina ja valida:
  - SQL estatico da migration
  - auditoria do banco atual
  - ausencia de `ON CONFLICT` com alvo de expressao para artifact hash
  - ausencia de `ON CONFLICT (source_table, source_id)` contra indice parcial
  - backfills explicitos por `WITH ki_current AS` e `WITH kb_current AS`
  - offset de `version_no` para versoes vindas de `kb_entries`
- O ambiente local ainda nao tinha `psql`, Supabase CLI, `psycopg`, `psycopg2`, nem `DATABASE_URL`/`SUPABASE_DB_URL`, entao a migration nao foi aplicada localmente por agente.
- O ultimo resultado conhecido de `python tests/integration_knowledge_curation_architecture.py --require-applied` falhou porque a migration ainda nao estava aplicada no Supabase:
  - faltando `knowledge_node_type_registry`
  - faltando `knowledge_relation_type_registry`
  - faltando `knowledge_artifacts`
  - faltando `knowledge_artifact_versions`
  - faltando `agent_prompt_profiles`
  - faltando `knowledge_curation_runs`
  - faltando `knowledge_curation_proposals`

## Objetivo

Validar de ponta a ponta a arquitetura de dados de conhecimento em grafo, antes de trocar a logica de resposta do n8n para este sistema.

O foco nao e ainda fazer a resposta do WhatsApp ficar perfeita. O foco e provar que a infraestrutura de dados esta correta:

- conhecimento entra pela fila/classifier/vault
- vira artefato canonico
- gera versoes auditaveis
- cria ou atualiza nos do grafo
- cria arestas com relacoes configuraveis
- identifica duplicatas sem criar verdades paralelas
- conecta conhecimento a persona, entidade, brand, produto, campanha, tom, briefing, copy, FAQ e assets
- aparece no dashboard como grafo e na sidebar de conhecimento
- nao redireciona para rotas inexistentes ao expandir ou clicar em conhecimento

## Regras de arquitetura

1. Nada hardcoded de cliente, produto, palavra-chave, dominio, link, "modal", "catalogo" ou `tockfatal.com`.
2. Produto, entidade, brand, campanha, briefing, copy, FAQ, asset, tom, nivel, importancia e peso devem ser configuraveis.
3. O agente curador deve ser o mesmo papel logico do KB Classifier/Curator:
   - mesmo prompt profile
   - mesmas ferramentas/skills
   - capacidade de detectar duplicata
   - capacidade de propor merge antes de aplicar mudanca destrutiva
4. Fila, KB, vault/Git e grafo nao podem ser fontes paralelas de verdade. Devem convergir em `knowledge_artifacts`.
5. `knowledge_items` e `kb_entries` continuam existindo por compatibilidade operacional, mas devem apontar para o artefato canonico.
6. `knowledge_nodes` deve representar a visao navegavel em grafo.
7. `knowledge_edges` deve representar relacoes semanticas configuraveis por registry.
8. Toda mutacao relevante precisa ser auditavel por run/proposal/version.

## Trabalho esperado

### 1. Validar/aplicar migration 009

Execute:

```powershell
python tests/integration_knowledge_curation_architecture.py
```

Se a migration ainda nao estiver aplicada, instrua explicitamente o operador a aplicar `supabase/migrations/009_knowledge_curation_architecture.sql` no Supabase SQL Editor ou forneca suporte para:

```powershell
$env:DATABASE_URL="postgresql://..."
python tests/integration_knowledge_curation_architecture.py --apply --require-applied
```

Depois valide:

```powershell
python tests/integration_knowledge_curation_architecture.py --require-applied
```

Se aparecer erro SQL novo, corrija a migration de forma idempotente e rode novamente a rotina local.

### 2. Criar rotina de validacao ponta a ponta do conhecimento completo

Criar ou aprimorar um teste que cadastre um conhecimento completo via fluxo de classifier/curator, cobrindo:

- persona
- entidade
- brand
- produto
- campanha
- tom
- briefing
- copy
- FAQ
- asset

O teste deve ser parametrizavel por CLI/env. Nao usar strings fixas de negocio dentro da logica de validacao.

Validar no banco:

- existem artefatos canonicos para cada tipo esperado
- `knowledge_items.artifact_id` e/ou `kb_entries.artifact_id` apontam para `knowledge_artifacts`
- existem versoes em `knowledge_artifact_versions`
- existem nos correspondentes em `knowledge_nodes`
- existem arestas esperadas em `knowledge_edges`
- nivel/importancia/confianca foram preenchidos por config/defaults, nao por hardcode espalhado
- duplicata do mesmo conhecimento nao cria novo artefato canonico; deve criar nova versao ou proposta de merge

### 3. Validar grafo e dashboard

Investigar e corrigir o fluxo da sidebar/detalhe de conhecimento:

- Clicar em conhecimento na sidebar nao pode redirecionar para pagina inexistente.
- Se ainda nao houver pagina universal, criar rota ou drawer universal para detalhe de conhecimento.
- O dashboard deve conseguir visualizar conteudo selecionado como grafo.
- A visualizacao principal para conhecimento deve ser grafo, nao arvore.
- Validar que a sidebar mostra categorias de conhecimento e nos relacionados:
  - Produtos
  - FAQs
  - Briefings
  - Campanhas
  - Copies
  - Assets
  - Tom/Regras
  - Pendentes/nao validados

Criar teste Playwright ou teste de API/dashboard quando possivel para garantir que links nao retornam 404.

### 4. Reprocessamento da base

Propor e, se seguro, implementar rotina de dry-run para reprocessar toda a base:

- ler `knowledge_items`, `kb_entries`, vault/Git quando disponivel
- agrupar por canonical key/hash
- detectar duplicatas
- gerar proposals de curadoria
- nao executar mutacoes destrutivas sem proposta auditavel
- emitir relatorio com contagens por persona, tipo, status, backlog reason e missing graph

O primeiro modo deve ser `dry_run`. O modo `apply` deve ser explicito.

### 5. Testes minimos obrigatorios

Rodar e registrar em `memory.md`:

```powershell
python tests/integration_knowledge_curation_architecture.py
python tests/integration_knowledge_curation_architecture.py --require-applied
```

Se houver novo teste de fluxo completo, rodar tambem:

```powershell
python <novo_teste> --dry-run
python <novo_teste> --apply
```

Se houver dashboard/dev server:

```powershell
npm run lint
npm run test
```

ou os comandos equivalentes reais do projeto. Se algum comando nao existir, registrar isso no resultado.

## Criterios de aceite

Considere concluido somente quando:

1. `memory.md` foi lido no inicio e atualizado no final.
2. Migration 009 passa nos checks estaticos.
3. Migration 009 esta aplicada ou existe instrucao precisa do bloqueio que impede aplicar.
4. Rotina `--require-applied` passa quando a migration estiver aplicada.
5. Existe teste parametrizavel para conhecimento completo ou plano tecnico com arquivos/rotas exatos se ainda houver bloqueio.
6. Duplicatas sao tratadas como artefato canonico + versoes/proposals, nao como verdades separadas.
7. Grafo mostra nos e arestas por tipo configuravel.
8. Sidebar/detalhe de conhecimento nao abre rota inexistente.
9. Nenhuma regra depende de "modal", "catalogo", `tockfatal.com` ou qualquer cliente/produto fixo.
10. Resultado final lista arquivos alterados, comandos executados e pendencias reais.

## Postura

Atue como arquiteto de dados. Procure erros conceituais que dificultariam implantacoes futuras:

- fontes de verdade duplicadas
- IDs instaveis
- dependencia acidental de titulo/texto
- acoplamento entre dashboard e tipos fixos
- grafo sem lineage
- fila sem auditoria
- classificador que aplica mudanca sem proposal
- teste que passa por substring hardcoded mas nao valida estrutura

Corrija com escopo pequeno e verificavel. Nao faca refactors grandes sem necessidade. Nao reverta alteracoes existentes do usuario.
