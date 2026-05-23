# VZ Lupas — Relatório E2E

Run TS: `1779530167` · Persona: `vz-lupas` (`46872921-6390-4d49-ae13-6eeb75bf4d21`)
API: `http://127.0.0.1:8001` · Dashboard: `http://127.0.0.1:3000` · Supabase: `qhnepdcqtkjjslqqiyvp` (ai-brain-qa)

## Resumo executivo

3 testes em série, todos verde no backend e no banco. 100% dos nodes
criados aparecem no `/knowledge/graph`, 100% dos assets uploadados aparecem
em `/knowledge/assets`, e 100% das operações geraram eventos na trilha de
auditoria (`/logs`). 1 bug encontrado e corrigido durante a execução:
`product_group` caía em `general_note` por gap no `ALLOWED_CONTENT_TYPES`
de `knowledge_rag_intake.py`.

## T1 — 1 node brand

- Plano: `entries=1` (brand "VZ Lupas")
- Resultado: HTTP 200, `nodes_created=2`, `edges=2` (brand + auto-campaign de organização)
- Tabela: `knowledge_nodes` ganhou `vz-lupas-brand-t1-1779530167` (node_type=brand, status=validated)

## T2 — 1 galho (espinha)

- Plano: 6 entries + 5 links explícitos
  `brand → briefing → campaign → audience → product_group → product`
- Resultado: HTTP 200, `nodes_created=6`, `edges=11` (5 explícitas + 6 auto via `belongs_to_persona`/`contains`)
- Relations canônicas confirmadas: `brand_has_briefing`, `briefing_has_campaign`, `campaign_has_audience`, `audience_has_product_group`, `product_group_has_product`

## T3 — grafo + imagens

- Plano: 12 entries (3 product_groups + 9 products) + 9 links `product_group_has_product`
- Resultado: HTTP 200, `nodes_created=13`, `edges=22`
- 3 PNGs gerados (Pillow) e uploadados via `/assets/upload`:
  - `img_sol.png` → branch `vz-pg-sol-t3-...` → asset_id `d9ff8d7b-...` ✓
  - `img_grau.png` → branch `vz-pg-grau-t3-...` → asset_id `115b88de-...` ✓
  - `img_clipon.png` → branch `vz-pg-clipon-t3-...` → asset_id `88adfa4b-...` ✓

## Estado final do banco

| Tabela                       | Count |
|------------------------------|-------|
| knowledge_nodes              | 27    |
| knowledge_edges              | 52    |
| knowledge_items              | 6     |
| knowledge_intake_messages    | 21    |
| assets                       | 3     |
| system_events (audit)        | 6     |

Breakdown por `node_type`:

| node_type      | count | origem                                       |
|----------------|-------|----------------------------------------------|
| product        | 10    | 9 de T3 + 1 de T2                            |
| product_group  | 4     | 3 de T3 + 1 de T2 (após fix)                 |
| asset          | 3     | 3 uploads de T3                              |
| campaign       | 3     | 1 explícita (T2) + 2 auto (T1, T3)           |
| brand          | 2     | 1 T1 + 1 T2                                  |
| persona        | 1     | root                                          |
| briefing       | 1     | T2                                            |
| audience       | 1     | T2                                            |
| embedded       | 1     | sistema                                       |
| gallery        | 1     | sistema                                       |

## Frontend (screenshots em `tmp/sofia_e2e/`)

- `ss_01_after_login.png` — login admin@local.dev / Brain2026! → `/` ✓
- `ss_02_capture.png` — `/knowledge/capture` carrega com persona "VZ Lupas" selecionada ✓
- `ss_03_graph.png` — `/knowledge/graph` mostra rede vasta de nodes da persona ✓
- `ss_04_assets.png` — `/knowledge/assets` lista as 3 imagens VZ Lupas (Sol/Grau/ClipOn) no topo ✓
- `ss_05_logs.png` — `/logs` audit tab mostra eventos `knowledge_rag_plan_intake_created`, `product_group_approved`, `asset_pending`, etc ✓

## Bug encontrado e corrigido

**`product_group` → `general_note`** em `api/services/knowledge_rag_intake.py`

`CONTENT_LEVELS` não listava `product_group` (nem `offer` nem `gallery`), apesar de migration 039 os ter como tipos canônicos. Sem o tipo no set `ALLOWED_CONTENT_TYPES`, `classify_intake` caía no fallback `general_note`. Fix: adicionar os 3 tipos ao dict.

Após fix, todos os 4 product_groups do teste aparecem com `node_type=product_group` corretamente.

## Integração com landing page

- `/api/menu/vz-lupas` → 404 "Collection not found: cardapio-baita-v14"
  (route é hardcoded à coleção do Baita Cardápio; vz-lupas não é onboarded
  nesse pipeline de landing — esperado, não é regressão)
- `/knowledge/products?persona_id=vz-lupas` → 10 produtos com preços e
  status `validated` ✓ (esse é o contrato genérico que outras landing pages
  podem usar)

## Integração validada

- ✓ Frontend (`/knowledge/capture`, `/graph`, `/assets`, `/logs`) renderiza os 27 nodes
- ✓ Backend (`/knowledge/intake/plan`, `/assets/upload`, `/knowledge/products`) responde 200
- ✓ Banco (knowledge_nodes/edges/assets/intake_messages/system_events) com counts batendo
- ✓ Auditoria (`/logs`) registra cada operação
- ✓ Assets pipeline (Storage + signed URLs + gallery_has_asset edge + parent_edge)
- ⚠ `/api/menu/{slug}` é Baita-specific (não bloqueia este teste)
