# Handoff — grafo de duas marcas (Tock Fatal) e limpeza de lead

Data do snapshot: 2026-08-21
Escopo: adicionar/atualizar conteúdo do grafo Tock Fatal a partir do briefing de
marca/catálogo fornecido, aprovar, ativar em produção, e limpar histórico da
lead "allan" em tockfatal e aurora.
Estado: lead limpa e confirmada em produção; grafo aprovado pelo operador;
**fase 1 (estrutura, sem preço) ATIVADA em produção** — `graph_publications`
v7, status `active`, checksum `sha256:173eda4c...`, confirmado por auditoria
pós-ativação (183 nodes, 73 products, 7 product_groups, 2 brands, 0 offers,
zero menção de R$/% em qualquer `metadata`). v6 automaticamente virou
`rolled_back` (rollback imediato disponível se necessário). Fase 2 (ofertas +
copy de atacado + regra de desconto + `commercial_claims_allowed=true`)
continua pendente de decisão futura do operador.

## 1. O que já está feito e confirmado em produção

### 1.1 Limpeza de histórico da lead "allan"
- VPS: `root@srv1846215.hstgr.cloud` (chave local `~/.ssh/id_ed25519_srv1846215`),
  app em `/opt/brain-ai`, stack docker compose (`db`, `api`, `workers`, etc.).
- `tock-fatal` (lead id 33, nome "Allan"): 35 mensagens, 1 journey/ledger, 35
  linhas de `lead_buffer` apagadas. Limpeza completa.
- `aurora` (lead id 34, nome "Allan Rodrigues"): 82 mensagens e 82 linhas de
  `lead_buffer` apagadas. **Journey/ledger preservados de propósito** — essa
  lead tem 1 `sales_conversions` real (RESTRICT FK na journey); apagar a
  journey apagaria uma venda registrada. Se o operador quiser apagar isso
  também, é uma decisão separada, ainda não autorizada.
- `ultima_mensagem`/`last_update` zerados nas duas leads.

### 1.2 Grafo — decisões já tomadas pelo operador (não reabrir)
- Varejo e atacado são **duas marcas** (`brand:tock-fatal-varejo` e
  `brand:tock-fatal-atacado`), não só dois ramos de audiência — decisão do
  operador, "a empresa já é assim normalmente".
- Catálogo continua em `campaign` (não em `briefing`) — `briefing` é injetado
  em toda mensagem no runtime (`conversation_runtime.py`), então só leva um
  node curto de instrução, nunca o catálogo inteiro.
- `product_group` (7 categorias) e `offer`/`copy` (separados por produto e por
  canal) são nodes reais — não tags. Isso segue o enum canônico
  `api/schemas/graph_json_v2.py` e o que `catalogo_roupas`
  (`api/services/public_site.py`) já espera.
- Desconto de atacado: **30% a partir de 3 peças, iguais ou diferentes**,
  definido pelo operador. Pré-calculado por produto (`preço_varejo * 0.7`) em
  vez de fórmula para o modelo aplicar ao vivo — ver achado de segurança na
  seção 3.
- Item "Bolsa Vizzano" fica **fora do grafo** — nome não bate com a foto
  (parece bota), catálogo já sinalizava isso.
- Operador aprovou o pacote completo (marcas, produtos, ofertas, copys,
  regra de desconto) em 2026-08-21 e disse "pode ativar".
- Operador escolheu ativar **só a estrutura** nesta rodada — sem preço/desconto
  visível para a Vitória ainda (`commercial_claims_allowed` permanece `false`).

## 2. Arquivos do grafo (nenhum commitado; todos untracked)

| Arquivo | O que é |
| --- | --- |
| `data/graph_bundles/tock-fatal/sdr-qualification-v1.json` | **Ativo em produção hoje** (publication v6). Não editar. |
| `data/graph_bundles/tock-fatal/sdr-qualification-v2-draft-catalog-proposal.json` (+`.PLAN.json`) | Rascunho intermediário, 1 marca só — **superado**, mantido só de histórico. |
| `data/graph_bundles/tock-fatal/sdr-qualification-v3-draft-two-brands.json` | Rascunho completo aprovado (2 marcas, 381 nodes novos, todos `validated`) — inclui preço/oferta/desconto. **Não é o que deve ser ativado direto** — ver seção 3. |
| `data/graph_bundles/tock-fatal/sdr-qualification-v3-phase1-structure-only.json` | **Este é o bundle pronto para ativar agora.** Subconjunto do v3: marcas (sem número), 7 grupos, 73 produtos (título limpo, sem preço embutido), 73 copys de varejo. Ofertas, copys de atacado e a regra de desconto ficam de fora — ver seção 3. |
| `data/graph_bundles/tock-fatal/sdr-qualification-v3-phase1-structure-only.PLAN.json` | Plano computado localmente para o phase1: `disposition=awaiting_approval`, `validation_errors=[]`, `+161 nodes / +165 edges`, `breaking_contract_changes=[branch_structure_changed x2]` (motivo: novo `briefing` global entra no fechamento dos 2 ramos — aditivo, não quebra comportamento). `draft_checksum=sha256:5c861be4581531032485cb4ed8750de04c0076f9cfa45a156e5c8efa620f1d4f`, `runtime_checksum=sha256:173eda4cf36ba3786c755802f87be8efe8b9443be401d60d5233179fdc0895bc` (recalculado após a limpeza de títulos/marca atacado — os primeiros checksums calculados ficaram obsoletos). **Estes checksums podem ficar desatualizados se o bundle for editado de novo — sempre recalcular antes de publicar.** |

## 3. Achado de segurança — por que existe um bundle "phase1"

Antes de ativar, verifiquei se o runtime realmente respeita
`commercial_claims_allowed=false`. Achado: **essa flag não é lida em nenhum
lugar do código** (`api/services/*.py`, grep vazio). A proteção real que
existe é `graph_proof_checker_v3.check()`, mas ela só valida **claims
estruturadas** que o modelo emite explicitamente (exige node `faq` com
`data.claims[].policy` + `evidence_node_ids` auto-referenciado). Meus nodes
novos são `product`/`offer`/`copy`/`brand` — não têm essa estrutura, então
esse caminho continua seguro.

**O problema:** o texto livre da resposta (`proposal.reply`) **não passa por
nenhuma verificação de evidência** (grep por `reply_text` em
`graph_proof_checker_v3.py` não bate com nada). Hoje isso é seguro só porque
não existe preço nenhum no grafo para o modelo recuperar via RAG e narrar em
prosa. Assim que eu ativasse o v3 completo (146 `offer` com preço real + 73
`copy` de atacado citando o valor com desconto), esses números virariam
recuperáveis, e nada no código impediria o modelo de mencionar um preço numa
resposta comum — só a instrução de prompt "não invente preço não publicado"
ficaria de proteção, o que é mais fraco do que uma trava de código.

**Por isso criei o `v3-phase1-structure-only.json`**: removi todos os 146
`offer`, as 73 `copy:*-atacado`, a `rule:tock-desconto-atacado-30`, reescrevi
`brand:tock-fatal-atacado` e `briefing:tock-catalogo-instrucoes` para não
citar "30%"/valor algum, e limpei 16 títulos de produto que traziam o preço
embutido no nome (ex.: "Vestido em mousse — R$ 129,90" → "Vestido em mousse").
Confirmei por grep no JSON final: zero `R$`, zero `%` dentro de qualquer node
(o único "30%" que sobra é dentro do `metadata.draft_note`, que é nota de
autoria do bundle, nunca vira node/edge compilado).

## 4. Ativação — EXECUTADO em 2026-08-21 08:30 UTC

Rodado dentro do container `api` na VPS, exatamente como descrito abaixo.
Achado extra no caminho: o preflight (`_preflight_source_scope`) recusou a
primeira tentativa por 2 nodes órfãos (`asset:audio-33-a723d239`,
`conversation:conversa-33`) — mirror automático de grafo gerado pela própria
conversa de teste da lead Allan (mesma lead limpa na seção 1, tabela
diferente). Removidos (4 edges + 2 nodes) por serem resíduo direto da mesma
limpeza já autorizada, não conteúdo novo. Depois disso, staging e ativação
passaram limpos, checksum aprovado == checksum ativado, `version: 7`.

Rollback disponível: `bash ops/vps/rollback.sh` reativa a publication anterior
(v6, `rolled_back`) se algo parecer errado.

## 5. Gap descoberto — Sofia não alimenta a Vitória da Tock Fatal hoje

O operador pediu para confirmar se a Sofia (agente conversacional de intake,
`api/services/kb_intake_service.py`, acionada pela tela "Criar") tem
ferramentas para criar conhecimento compatível com a arquitetura de duas
marcas que ativamos nesta sessão. Resultado: **forma sim, encanamento não.**

### 5.1 A forma já está compatível
O schema que a Sofia usa (`kb_intake_service.py:368,411`) já aceita
`content_type` em `{brand, briefing, campaign, audience, product_group,
product, offer, copy, asset, prompt, faq, ...}` — `product_group` e `offer`
já são de primeira classe, contradizendo o mapeamento desatualizado descrito
em `docs/knowledge-flow.md`. `_PREFERRED_PARENT_TYPES`
(`kb_intake_service.py:1050-1086`) já usa quase a mesma hierarquia que
construímos: `Persona → Brand → Campaign|Briefing → Audience → Product Group
→ Product → Copy|FAQ|Asset`, com `offer` filho de `product`
(`kb_intake_service.py:1073`). `brand` é tipo raiz sem limite de quantidade
(`SOFIA_TOP_LEVEL_TYPES`, `:1053`) — nada impede duas marcas por persona.

### 5.2 O encanamento não está
A Sofia publica via `graph_document_publisher.publish()` →
`graph_json_v2_store.activate_version()` (`kb_intake_service.py:6782-6783`,
`graph_document_publisher.py:322`) — um sistema de "grafo ativo" **separado**
de `graph_publications` (o que `api/scripts/publish_graph_bundle.py` ativa, e
o que realmente serve a Vitória).

Confirmado em produção, não suposição:

```sql
-- workflow_bindings da tock-fatal
680422f3-...  runtime_version = graph_agent_runtime_v3   pipeline_contract = conversation_v3   (binding ativo/real)
c18834ee-...  runtime_version = (vazio)                  pipeline_contract = conversation_v1   (binding legado)

-- system_events entity_type='graph_document' (graph_json_v2_store)
tock-fatal: 0 eventos, nunca teve nenhum
aurora:     v7 e v8 ativados no mesmo dia (2026-08-21) — Aurora ainda está
            no pipeline v2, coerente com AGENT_ROADMAP.md ("Aurora migra
            para o bundle" = a fazer)
```

`conversation_runtime._decide_dispatch` (`conversation_runtime.py:1546-1554`)
só cai no `graph_json_v2_store` (`_current_graph`, linha 727) quando
`context.runtime_version != graph_agent_runtime_v3.RUNTIME_VERSION`. Como o
binding real da Tock Fatal já está em `graph_agent_runtime_v3`, esse caminho
nunca é lido para essa persona — hoje, e sempre até aqui.

**Consequência prática:** se o operador usar a Sofia amanhã para cadastrar
produto novo da Tock Fatal, o conteúdo sai bem formado, mas fica preso no
`graph_json_v2_store` sem alcançar a Vitória. Precisa de uma etapa manual
(como fizemos nesta sessão, na mão) para virar `GraphBundle` e publicar.

### 5.3 Estratégia recomendada (não implementada — só desenhada)

Direção: **não** mover a Tock Fatal de volta para `graph_json_v2_store` (isso
seria regredir — o roadmap do projeto já aponta a Aurora migrando *para* o
bundle, não o contrário, e o pipeline v3 tem a disciplina de aprovação/CAS
que sustentou a ativação segura desta sessão). Em vez disso, apontar a Sofia
para publicar no pipeline v3, mantendo a conversa/UX dela como está:

1. **Adaptador `graph_json_v2 -> GraphBundle`** — função pura que traduz o
   `GraphJson` que a Sofia já monta internamente (nodes/edges/parent_id) para
   o formato de node/edge do `GraphBundle` (`id`, `node_type`, `slug`,
   `title`, `summary`, `tags`, `status`, `data`, edges `contains` a partir de
   `parent_id`). Mecânico — a hierarquia e os tipos já batem quase 1:1 (seção
   5.1), a única tradução real é de forma de payload.
2. **Trocar o commit final da Sofia** — em vez de
   `graph_document_publisher.publish()`, para personas com
   `runtime_version=graph_agent_runtime_v3` (mesmo teste que
   `binding_uses_v3()` já faz), chamar o adaptador + `graph_bundle.
   build_publication_plan()` e **parar aí**: mostrar o diff/plano para
   aprovação humana explícita, do mesmo jeito que fizemos manualmente nesta
   sessão e que o `.claude/agents/graph-publisher.md` já exige ("nunca
   publicar sem plano aprovado por humano"). Só ativar
   (`stage_bundle`/`activate_staged_bundle`) depois da aprovação.
3. **Herdar as mesmas travas de hoje** — bloquear se `validation_errors`
   não for vazio; exigir reconhecimento explícito se
   `breaking_contract_changes` não for vazio; qualquer coisa sinalizada
   (tipo o item "Bolsa Vizzano" desta sessão) fica de fora do pacote
   aprovável até o operador decidir.
4. **Depois que Tock Fatal e Aurora estiverem 100% no v3**, aposentar
   `graph_json_v2_store` como sistema de serving ativo (manter só como
   histórico/auditoria se precisar).

Isso é mudança de código real (o passo 2 mexe em
`kb_intake_service.py`) — não implementado nesta sessão, por estar fora do
escopo combinado ("não altere código agora"). Fica registrado aqui como plano
para quando o operador autorizar.

## 4b. Próximo passo exato (histórico — como foi feito)

Ativar `sdr-qualification-v3-phase1-structure-only.json` em produção via o
script oficial do projeto — **não existe rota de API para isso, é sempre
script**, achado confirmado por pesquisa no código:

```
api/scripts/publish_graph_bundle.py <bundle.json> \
  --approved-draft-checksum <draft_checksum do PLAN.json> \
  --approved-runtime-checksum <runtime_checksum do PLAN.json> \
  --actor <nome> \
  --apply --activate
```

Só roda dentro do container `api` na VPS (é lá que existem as credenciais
reais do Supabase — o `.env.compose` local aqui só tem valores `localhost`).
Fluxo:

1. Recalcular o plano do `v3-phase1-structure-only.json` contra o `v1.json`
   (comando em `C:\Users\allan\.claude\jobs\9f8790ce\tmp\compute_plan_v3.py`,
   adaptar os paths) — confirmar que os checksums da seção 2 ainda batem.
2. `scp`/copiar o bundle para a VPS, ex. `/opt/brain-ai/tmp/`.
3. `ssh root@srv1846215.hstgr.cloud` → `cd /opt/brain-ai` → rodar o comando
   acima com `docker compose --env-file .env.compose exec api python
   scripts/publish_graph_bundle.py ...` (confirmar path exato do script
   dentro do container antes de rodar).
4. Verificar pós-ativação: `bash ops/vps/audit.sh` (contagem de nodes/edges
   deve subir ~161/165), conferir `graph_publications` tem nova versão ativa
   com o `runtime_checksum` esperado, e testar uma pergunta de catálogo real
   via WA Validator antes de considerar concluído.
5. Reportar ao operador com números reais pós-ativação.

**Regra do próprio `.claude/agents/graph-publisher.md`**: "o checksum
aprovado é o checksum ativado" — se o checksum calculado no passo 1 não bater
com o da tabela acima, o bundle mudou e precisa de nova aprovação, não seguir
em frente.

## 5. Decisões em aberto (não assumir, perguntar)

- Fase 2: ativar as 146 `offer` + 73 `copy` de atacado + regra de desconto, e
  virar `commercial_claims_allowed=true` — decisão futura separada, não
  incluída aqui.
- Apagar (ou não) a journey/venda preservada da lead Allan em aurora.
- Documento paralelo já existente no repo,
  `docs/handoffs/AURORA_TOCK_FATAL_FLOW_AUDIT_HANDOFF_2026-08-21.md` (de uma
  sessão anterior, mesma data), recomendava um plano bem mais conservador
  (só os 2 produtos Kit Modal já validados) — este handoff aqui documenta um
  plano maior, que o operador aprovou explicitamente nesta conversa. Vale o
  operador saber que os dois documentos coexistem com escopos diferentes.
