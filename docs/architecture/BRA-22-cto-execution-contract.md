# BRA-22 CTO Architecture + Execution Contract

Date: 2026-05-27
Issue: BRA-22 - Adicionar teste automatizado que prova insercao real no grafo QA
Scope: arquitetura e sequenciamento para validar insercao real no grafo QA sem mocks.

## 1) Technical Architecture Decision

- Stack preservada: FastAPI (`/api`) + Next.js (`/dashboard`) + Supabase Postgres/pgvector + Cloud Run + Vercel.
- AI Brain permanece fonte canonica de inteligencia validada.
- Catalog permanece fonte operacional/comercial; nao e dono de embeddings.
- Regra imutavel aplicada no backend:
  - FAQ aprovada -> pode gerar Embed.
  - Product -> Embed direto deve falhar.
  - FAQ nao aprovada -> Embed deve falhar.
- Persistencia no grafo continua obrigatoria:
  - se entrou em KB/RAG, deve existir em `knowledge_nodes`;
  - se ha relacao semantica, deve existir em `knowledge_edges`.

## 2) Service Boundaries + Data Ownership

- Catalog ingest (`POST /api/catalog/ingest`): recebe entrada bruta e cria/atualiza itens de conhecimento.
- Graph generation (`POST /api/graph/generate`): materializa knowledge em nodes/edges.
- Approval (`POST /api/faq/approve`): unica porta para mudar FAQ a estado aprovavel para Embed.
- Embed generation (`POST /api/embeds/generate`): exige precondicao de FAQ aprovada.
- Semantic tree read (`GET /knowledge/graph-data?mode=semantic_tree`): evidencia oficial de visualizacao do grafo.

## 3) API + Contract Outline (BRA-22)

- Positive path:
  1. ingest real com `runId` unico;
  2. graph generate real;
  3. approve FAQ;
  4. generate embed;
  5. consultar semantic_tree e validar nodes/edges do `runId`.
- Negative paths obrigatorios:
  - Product -> Embed: erro esperado (4xx/validador de regra).
  - FAQ nao aprovada -> Embed: erro esperado (4xx/validador de regra).

## 4) Sequenced Implementation (owner handoff)

1. QA/Test Engineer
- Garantir runtime preconditions:
  - `QA_REAL_GRAPH_INSERTION_TEST=1`
  - `AI_BRAIN_ADMIN_TEST_TOKEN` valido
  - API local ativa
- Executar `python -m pytest -q -rs tests/test_qa_real_graph_insertion.py` sem skip.

2. Backend Engineer + Graph Validator/Migration Agent
- Se houver falha por contrato/rota, corrigir backend sem migracao destrutiva.
- Preservar regras de aprovacao FAQ->Embed e bloqueio de Product->Embed.

3. QA Lead
- Validar evidencia final do teste (nao-skip, pass/fail real).
- Confirmar que semantic_tree mostra nodes/edges do `runId`.

## 5) Risks + Validation Plan

Riscos:
- Falta de `AI_BRAIN_ADMIN_TEST_TOKEN` invalida execucao real e gera falso progresso (skip).
- Frontend-only checks sem validacao backend mascaram regressao de regra.
- Mudancas ad hoc no grafo sem contrato podem quebrar Tree view.

Gates:
- Gate 1: teste executa sem skip.
- Gate 2: dois casos negativos falham como esperado.
- Gate 3: caso positivo cria Embed e aparece no semantic_tree.
- Gate 4: evidencias anexadas (comando + output + ids/contagens).

## 6) Release/Disposition Guidance

- Sem token admin valido, BR-22 permanece `blocked` por bloqueador de ambiente.
- `done` so e permitido quando o teste real roda sem skip e comprova persistencia no grafo.

## 7) Resume Delta (2026-05-27)

- Wake reason: `issue_reopened_via_comment`.
- Latest board confirmation manteve o mesmo bloqueador operacional:
  - `AI_BRAIN_ADMIN_TEST_TOKEN` ausente no runtime de execucao.
- Decisao de arquitetura permanece inalterada; sem migracao de stack ou schema.
- Encaminhamento ativo:
  - Unblock owner: `QA/Test Engineer`.
  - Unblock action: executar `python -m pytest -q -rs tests/test_qa_real_graph_insertion.py` com
    `QA_REAL_GRAPH_INSERTION_TEST=1`, token admin valido e evidencia nao-skip incluindo validacao do semantic_tree.
