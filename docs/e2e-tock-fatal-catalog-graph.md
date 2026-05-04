# E2E Tock Fatal Catalog Graph

## Prompt do Teste

Sofia, quero criar conhecimento para Tock Fatal Atacado a partir da fonte:

```text
https://tockfatal.com/pages/catalogo-modal
```

Trate o site como captura bruta com parsing heuristico e validacao humana, nao como scraping perfeito.

Gere uma arvore de conhecimento completa para Tock Fatal Atacado com:

- briefing da captura;
- 3 produtos;
- 2 publicos: revendedoras e clientes finais;
- entidades de cores, precos e kits;
- copys para atacado e varejo;
- FAQs sobre preco, cores e kits;
- links semanticos entre marca, campanha, publicos, produtos, entidades, copys e FAQs.

Ao final, os conhecimentos devem estar adicionados a KB/grafo e deve existir um print da arvore de conhecimento.

## Plano E2E

1. Abrir uma sessao Sofia via `/kb-intake/start`.
2. Enviar o prompt completo para a LLM.
3. Exigir que a LLM gere um `knowledge_plan` estruturado com entries e links.
4. Validar que o plano da LLM contem:
   - pelo menos 3 produtos;
   - 2 publicos;
   - entidade;
   - pelo menos 2 copies;
   - pelo menos 2 FAQs;
   - pelo menos 8 links semanticos.
5. Abrir `/marketing/criacao` via Playwright e salvar evidencia visual da tela Criar.
6. Resolver a persona `tock-fatal` via API.
7. Criar um `run_token` unico para isolar os cards do teste.
8. Inserir os conhecimentos:
   - `brand`;
   - `campaign`;
   - `briefing`;
   - 2 `audience`;
   - 3 `product`;
   - `entity`;
   - 2 `copy`;
   - FAQs derivadas a partir de blocos `Pergunta:/Resposta:` dentro dos produtos.
9. Promover para KB os tipos aceitos pela fila legacy.
10. Usar `/knowledge/intake` para unidades RAG da migration 013 quando o legacy nao aceitar o tipo.
11. Validar `/knowledge/graph-data?persona_slug=tock-fatal`:
   - pelo menos 3 produtos;
   - pelo menos 2 publicos;
   - pelo menos 1 entidade;
   - cards de copy;
   - cards de FAQ;
   - edges semanticas conectando o subtree.
12. Abrir `/knowledge/graph` em modo arvore, focado na campaign criada.
13. Salvar screenshot da arvore em `test-artifacts/e2e-tock-fatal-catalog-graph/`.

## Comandos

Rodar sem browser:

```powershell
python -u tests\e2e_tock_fatal_catalog_graph.py --skip-browser
```

Rodar sem LLM apenas para debug de persistencia:

```powershell
python -u tests\e2e_tock_fatal_catalog_graph.py --skip-llm --skip-browser
```

Rodar completo com screenshot:

```powershell
python -u tests\e2e_tock_fatal_catalog_graph.py
```

Capturar screenshot de um run ja criado:

```powershell
python -u tests\e2e_tock_fatal_catalog_graph.py --screenshot-only --run-token e2efix004
```

## Resultado Validado

Run validado:

```text
e2ellm005
```

Artefatos:

```text
test-artifacts/e2e-tock-fatal-catalog-graph/report-e2ellm005.json
test-artifacts/e2e-tock-fatal-catalog-graph/criar-e2ellm005.png
test-artifacts/e2e-tock-fatal-catalog-graph/knowledge-tree-e2ellm005.png
```

Resumo do grafo:

```text
llm_entries:
  briefing: 1
  audience: 2
  product: 3
  entity: 1
  copy: 2
  faq: 2
llm_links: 8
token_nodes: 26
token_edges: 113
product: 3
audience: 2
entity: 1
copy: 2
faq: 6
```
