# BRA-23 QA Lead Gate - Local Target Validation

Date: 2026-05-26  
Issue: BRA-23  
Owner role: QA Lead  
Scope: validacao visual do `semantic_tree` no alvo mandatorio `http://192.168.0.182:3000/knowledge/graph?mode=semantic_tree&all_edges=1`.

## 1. QA Strategy

- Objetivo: proteger os invariantes de grafo antes de PR/deploy, exigindo evidencia no alvo local solicitado pelo board.
- Estrategia: usar evidencia em 2 camadas.
1. Camada A (ja executada): validacao funcional em QA remoto (`brain-plataform-qa`) para provar comportamento de render e payload real.
2. Camada B (obrigatoria para fechar BRA-23): validacao no host local `192.168.0.182:3000` com credencial/bypass valido.
- Decisao de gate: enquanto Camada B nao for executavel por bloqueio de acesso, BRA-23 permanece `BLOCKED`.

## 2. Required Test List

1. `python tests/screenshot_graph_tree.py` contra `192.168.0.182:3000` autenticado.
2. `pytest tests/test_qa_real_graph_insertion.py -q`
3. `pytest tests/integration_knowledge_ui_hierarchy.py -q`
4. Validacao manual em URL alvo com `mode=semantic_tree&all_edges=1` e evidencia de runId.

## 3. Blocking Criteria

1. Bloquear se login no alvo local falhar (`/login` com `Email/usuario ou senha invalidos`).
2. Bloquear se nao houver prova visual de nodes/edges do runId `paperclip-qa-graph-2026-05-26`.
3. Bloquear se `all_edges=1` nao puder ser verificado no alvo local.
4. Bloquear se qualquer teste automatizado de invariante de grafo falhar.

## 4. Coverage Checklist

- [x] Graph validation com cobertura automatizada.
- [x] FAQ->Embed rule com cobertura automatizada em suites de integracao.
- [x] Catalog ingest com invalid-case coverage (suite existente).
- [x] Tree View e Graph View com comportamento coberto por teste + evidencia QA remota.
- [ ] Tree View local target `192.168.0.182:3000` com evidencia autenticada (pendente por bloqueio de acesso).
- [x] Release blockers explicitos.

## 5. Manual QA Checklist

1. Abrir URL alvo local com sessao valida e confirmar entrada em `/knowledge/graph`.
2. Confirmar render em `semantic_tree`.
3. Confirmar visibilidade de nodes/edges do runId esperado.
4. Confirmar comportamento de `all_edges=1` para arestas de referencia.
5. Capturar screenshot e contagem objetiva (UI/API).

## 6. Automated QA Checklist

1. Screenshot flow (`tests/screenshot_graph_tree.py`) sem timeout em `/login`.
2. Assert de presenca de run token no payload de grafo.
3. Contrato de hierarquia (`persona_incoming=0`) sem regressao.
4. Falha publica erro legivel para gate de release.

## 7. Risk-Based Validation Matrix

| Risk ID | Regra | Impacto | Deteccao | Gate |
|---|---|---|---|---|
| KG-ACCESS-001 | sem acesso QA ao host local | evidencia obrigatoria ausente | login flow + screenshot flow | blocker |
| KG-003 | Tree mostra edge indevida | leitura semantica incorreta | teste de hierarquia + validacao visual | blocker |
| KG-007 | run sem evidencia de grafo | release sem entrega verificavel | assert de runId + screenshot | blocker |

## 8. QA Agent Assignments

1. QA/Test Engineer
- Executar e anexar logs dos testes automatizados da secao 2.
- Garantir falha explicita para ausencia de token runId.

2. QA/E2E Validator
- Reexecutar fluxo visual no alvo local apos desbloqueio de credencial/bypass.
- Anexar screenshot + resumo de contagens nodes/edges.

3. QA Regression Guardian
- Registrar incidente de acesso como recorrencia se repetir em novos runs.
- Cobrir regressao de redirecionamento indevido para `/login` no alvo de validacao.

## 9. Current Gate Summary

- Estado atual: `BLOCKED`.
- Bloqueador de primeira classe: autenticacao invalida no alvo local solicitado pelo board.
- Evidencia: `test-artifacts/bra-23-local-target-blocker.md` e `test-artifacts/bra23-local-login-failure.png`.
- Unblock owner: Frontend Agent + owner de ambiente/acesso.
- Unblock action: fornecer credencial valida de QA para `192.168.0.182:3000` ou habilitar bypass QA, depois disparar revalidacao BRA-23.
- Handoff: apos desbloqueio e execucao da Camada B, encaminhar para PR & Deploy Agent; QA Lead nao aprova release diretamente.
