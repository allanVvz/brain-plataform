# BRA-24 QA Lead Release Gate

Date: 2026-05-26  
Issue: BRA-24  
Owner role: QA Lead  
Scope: regressao de runs `done` sem entrega verificavel no grafo AI Brain.

## 1. QA Strategy

- Objetivo: impedir promocao de PR/deploy quando tarefas de grafo/conhecimento forem concluídas sem evidencia verificavel no grafo de QA ou sem bloqueio explicito com causa.
- Abordagem: gate em camadas com contrato automatizado (smoke + rota), validacao manual dirigida por risco e trilha de auditoria por run.
- Invariantes protegidas:
  - conhecimento aprovado precisa refletir em `knowledge_nodes` e `knowledge_edges`;
  - FAQ so chega a Embed quando aprovado;
  - Tree View usa apenas edges `main`;
  - run de escopo `graph|knowledge` so fecha como `done` com work product de grafo.

## 2. Required Test List (Release-Critical)

1. `python tests/smoke_bra24_regression_guardian.py`
2. `pytest tests/test_qa_contract_routes.py -q`
3. `pytest tests/test_vzlupas_preflight_contract.py -q`
4. `pytest tests/test_qa_real_graph_insertion.py -q`
5. `pytest tests/integration_faq_edge_direction_contract.py -q`
6. `pytest tests/integration_knowledge_ui_hierarchy.py -q`

## 3. Blocking Criteria

1. Bloquear PR/deploy se qualquer run `graph|knowledge` terminar `done` sem `graph_node`, `graph_edge`, `graph_snapshot` ou `qa_graph_assertion`.
2. Bloquear PR/deploy se run `blocked` nao declarar `blocker.owner` e `blocker.action`.
3. Bloquear PR/deploy em qualquer recorrencia critica `KG-001`, `KG-002`, `KG-005` ou `KG-007`.
4. Bloquear PR/deploy se Tree View incluir edge nao-`main`.
5. Bloquear PR/deploy se houver falha automatizada em testes de invariante de grafo/FAQ/embed.

## 4. Coverage Checklist

- [x] Graph validation com cobertura automatizada.
- [x] Regra FAQ->Embed com cobertura automatizada.
- [x] Catalog ingest com cobertura de caso invalido.
- [x] Tree View e Graph View com cobertura de comportamento.
- [x] SDR/Closer grounding com cenarios em suites de integracao/e2e.
- [x] Bloqueios de release explicitos e auditaveis.

## 5. Manual QA Checklist

1. Validar um run de tarefa de grafo com status `done` contendo evidencias de node+edge no artefato do run.
2. Validar um run bloqueado contendo causa explicita (`owner` + `action`) sem mascarar como sucesso parcial.
3. Confirmar no dashboard que Tree View nao renderiza arestas de referencia no fluxo vertical principal.
4. Confirmar que desconectar edge nao apaga node e nao remove KB/Asset destrutivamente sem regra explicita.
5. Confirmar que seletor de persona respeita autorizacao por `user_persona_access` em usuario nao-admin.

## 6. Automated QA Checklist

1. Smoke BRA-24 passa no host QA.
2. Contratos de rota QA passam sem `xfail` para invariantes duras.
3. Preflight invalido nao pode resultar em UI healthy.
4. Fixtures possuem casos validos + invalidos para fechamento de run com e sem evidencia.
5. Falha automatizada publica erro legivel (nao silencioso) para gate de CI.

## 7. Risk-Based Validation Matrix

| Risk ID | Regra | Impacto | Deteccao | Gate |
|---|---|---|---|---|
| KG-007 | run `done` sem evidencia de grafo | release sem entrega verificavel | smoke BRA-24 + auditoria de run | blocker |
| KG-002 | FAQ nao aprovada em Embed | KB contaminada | validators de hierarquia | blocker |
| KG-001 | product->embed proibido | quebra de arquitetura semantica | validators + contrato de rota | blocker |
| KG-003 | Tree com edge referencia | decisao operacional incorreta | validator de tree + e2e visual | blocker |
| KG-005 | ingest cria embed direto | bypass de aprovacao | contrato de rota/ingest | blocker |
| KG-006 | migracao sem rollback | alto custo de recuperacao | checklist de PR | warning alto |

## 8. QA Agent Assignments

1. QA/Test Engineer
- Manter e expandir suite automatizada dos testes listados em "Required Test List".
- Adicionar casos negativos para novos `relation_type` sem criar regras paralelas.
- Entregar log de execucao com comando + resultado pass/fail por suite.

2. QA/E2E Validator
- Cobrir fluxos de usuario: Criar conhecimento -> validar -> conectar -> verificar reflexo em Graph/Tree.
- Validar fluxos finais de Embed/Gallery sem conexoes indevidas.
- Anexar evidencias de UI e payload de rede por persona QA.

3. QA Regression Guardian
- Manter `docs/qa/BRA-24-known-bug-registry.md` como fonte canonica de recorrencias.
- Atualizar `tests/fixtures/bra24_regression_fixture.json` e smoke guard conforme novos incidentes.
- Escalar imediatamente recorrencia critica para bloqueio de release.

## 9. Release Gate Summary

- Gate BRA-24: `PASS` somente quando todos os testes criticos passam e nao existe recorrencia critica aberta.
- Gate BRA-24: `BLOCKED` com qualquer hit em `KG-001`, `KG-002`, `KG-005`, `KG-007` ou run `done` sem evidencia de grafo.
- QA Lead nao aprova release: handoff obrigatorio para Release Manager apos gate `PASS`.
- Proximo handoff operacional: PR & Deploy Agent executar checklist de smoke antes de merge/deploy.
