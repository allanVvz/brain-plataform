# AI Brain Project Requirements

Este arquivo e o contrato raiz de requisitos do projeto. Ele deve orientar implementacao,
review e testes. Quando houver conflito entre uma mudanca nova e este documento, a
mudanca deve ser bloqueada ate que o requisito seja atualizado conscientemente.

## 1. Objetivo do produto

A AI Brain organiza conhecimento comercial em um grafo hierarquico por persona.
O grafo deve permitir que Sofia e os agentes de IA criem, editem, validem,
publiquem e consultem conhecimento com origem rastreavel, contexto herdado,
validacao humana e isolamento por usuario/persona.

O sistema nao pode permitir conhecimento solto, produto fora do galho comercial,
FAQ em camada errada, conexao indevida com Embedded, vazamento entre personas ou
uso de credenciais expostas ao browser.

## 2. Stack e operacao local

- O projeto deve rodar local-first com Docker Compose.
- API local: `http://localhost:8000`.
- Dashboard local: `http://localhost:3000`.
- Postgres local: `localhost:54322`.
- Gateway Supabase-compativel local: `localhost:54321`.
- Supabase Cloud, Cloud Run ou outro SaaS nao podem ser obrigatorios para o fluxo local.
- Arquivos de runtime, logs e artefatos locais nao devem ser commitados.

## 3. Autenticacao, privacidade e seguranca

- Login deve usar `app_users` local e cookie HTTP-only assinado.
- Usuario nao admin so pode ver personas atribuidas em `user_persona_access`.
- Admin pode ver todas as personas.
- Rotas que leem dados de persona devem chamar validacao de acesso por `persona_slug`
  ou `persona_id`.
- Rotas que mutam grafo/persona devem exigir admin ou `can_edit=true`.
- Sessao Sofia/KB intake deve pertencer ao usuario que a criou; outro usuario nao
  pode ler nem mutar essa sessao.
- Chaves OpenAI/Anthropic devem ser armazenadas como integracoes de usuario,
  criptografadas no backend.
- O frontend nunca pode receber chaves secretas, nem por `NEXT_PUBLIC_*`, payload
  de API, log ou HTML renderizado.
- Token admin de QA so pode funcionar fora de producao.
- Toda rota QA/destrutiva deve ser bloqueada em producao.

Testes obrigatorios:

- Usuario A nao ve nem acessa persona B.
- Usuario sem `can_edit` nao publica, aplica patch, reindexa, importa ou faz rollback
  de grafo.
- Payload com `body.persona_slug != graph_json.persona_slug` retorna 422.
- Rotas QA retornam 403 em producao.
- Nenhum teste ou fixture deve depender de segredo real.

## 4. Fonte de verdade do grafo

Graph JSON v2 e a fonte canonica para o grafo publicado quando existir documento
v2 publicado. O v1 (`knowledge_nodes`, `knowledge_edges`, RAG e tabelas antigas)
permanece como indice derivado/fallback enquanto a migracao nao tiver corte final.

Requisitos:

- `schema_version` deve ser `"2.0"`.
- Deve existir exatamente um node `persona`.
- O slug do node `persona` deve ser igual a `graph_json.persona_slug`.
- Nao pode haver node orfao.
- Nao pode haver ciclo.
- Nao pode haver slug duplicado dentro do mesmo `node_type`.
- Todo node nao-persona deve ter `parent_id` valido.
- Toda aresta primaria deve espelhar o `parent_id` do target.
- Publish deve validar antes de persistir evento ou reindexar.
- `apply-patch` deve salvar versao local validada.
- `publish` deve registrar evento versionado e reindexar as tabelas derivadas.
- `rollback` deve criar uma nova versao a partir de versao antiga, nao apagar historico.

Endpoints obrigatorios:

- `GET /graph-documents/current`
- `GET /graph-documents/versions`
- `GET /graph-documents/events`
- `POST /graph-documents/apply-patch`
- `POST /graph-documents/publish`
- `POST /graph-documents/import-json`
- `POST /graph-documents/rollback`
- `POST /graph-documents/reindex`

## 5. Cadeia canonica de negocio

A hierarquia preferida do grafo comercial e:

```text
persona
-> brand
-> briefing
-> campaign
-> audience
-> product_group
-> product
-> offer
-> copy
-> faq
-> embedded
```

Regras de opcionalidade:

- `briefing` e opcional, mas quando existe entra em serie, nunca paralelo.
- `product_group` e opcional; quando existe no galho, produtos daquele grupo devem
  ficar abaixo dele.
- `product` pode ficar abaixo de `product_group` ou diretamente abaixo de `audience`
  quando nao houver grupo aplicavel.
- `offer` e opcional e deve ficar abaixo de `product`.
- `copy` e opcional e deve ficar em serie abaixo do card que contextualiza a mensagem.
- `faq` deve ficar no menor node valido disponivel.
- `embedded` e node final e so recebe FAQ aprovada.

Pais permitidos no contrato compartilhado atual de Sofia/Create/Graph
(`api/services/graph_validation.py`):

| Node | Pais permitidos |
| --- | --- |
| brand | persona |
| briefing | brand, campaign |
| campaign | brand, briefing |
| audience | campaign, briefing, brand |
| product_group | audience |
| product | product_group, audience |
| offer | product |
| copy | product, product_group, campaign, audience |
| faq | copy, product, product_group |
| gallery | copy |
| embedded | faq |
| asset | lateral; nao faz parte da arvore primaria |

Observacao importante: documentos antigos mencionam FAQ diretamente em audience,
campaign, brand ou persona como excecao extrema. O contrato compartilhado de
Sofia/Create/Graph e mais restritivo: FAQ deve ficar em `copy`, `product` ou
`product_group`.

Gap atual: `api/services/graph_json_v2_validator.py` ainda e mais permissivo e
aceita FAQ em `audience`, `briefing`, `campaign`, `brand`, `persona` e `rule`.
Isso deve ser tratado como pendencia de hardening: ou o validador v2 passa a
seguir a regra restritiva, ou a excecao de FAQ em camada alta deve ser
formalizada aqui e coberta por testes.

## 6. Regras do Embedded

- Embedded e o node final do conhecimento.
- Embedded representa o destino consultavel pelo agente, mas nao deve ser atalho visual.
- Nao pode existir aresta visual direta:
  - persona -> embedded
  - brand -> embedded
  - briefing -> embedded
  - campaign -> embedded
  - audience -> embedded
  - product_group -> embedded
  - product -> embedded
  - offer -> embedded
  - copy -> embedded
- A unica origem valida para embedded e FAQ aprovada.
- FAQ `draft`, `pending_validation`, `rejected` ou `archived` nao pode conectar ao Embedded.
- Embeddings so podem ser gerados a partir de FAQ aprovada, nunca diretamente de
  produto, copy, briefing, asset ou catalogo.

Testes obrigatorios:

- `faq approved -> embedded` e aceito.
- `faq pending_validation -> embedded` e rejeitado.
- Qualquer `non_faq -> embedded` e rejeitado.
- Pipeline de embedding rejeita fonte que nao venha de FAQ aprovada.

## 7. FAQ e golden dataset

FAQ e a menor unidade validavel de conhecimento comercial.

Requisitos:

- FAQ gerada automaticamente nasce como `pending_validation`.
- FAQ so alimenta Embedded depois de aprovada.
- Alterar FAQ aprovada exige nova validacao.
- FAQ deve carregar:
  - `source_node_id`
  - `source_node_type`
  - `branch_path`
  - `validation_status`
  - contexto herdado do galho quando disponivel
- FAQ deve ser comercial, pratica e acionavel.
- FAQ deve priorizar compra, orcamento, agendamento, objecoes, preco, entrega,
  prazo, produto, servico, diferenciacao e atendimento.
- FAQ institucional sobre "como a IA pensa" nao deve ser prioridade do dataset comercial.

## 8. Sofia: caminhos obrigatorios

Create e Graph compartilham as mesmas regras centrais, taxonomia e validacao.
A diferenca e o tamanho da operacao e o prompt.

### Create path

- UI: `/knowledge/capture`
- Endpoints: `/kb-intake/start`, `/kb-intake/message`, `/kb-intake/save`
- Servico: `api/services/kb_intake_service.py`
- Uso: criar galhos completos, campanhas, grupos, produtos, copy e FAQ em massa.
- Deve usar `knowledge_taxonomy` e `graph_validation`.

### Graph path

- UI: `/knowledge/graph`
- Endpoint: `/sofia/graph-command`
- Servico: `api/services/sofia_orchestrator.py`
- Uso: editar cirurgicamente nodes existentes ou pequenos patches do grafo.
- Deve usar `knowledge_taxonomy` e `graph_validation`.
- A aba Graph deve mostrar Sofia de forma visivel; a interacao nao pode depender de
  descobrir um botao sem rotulo.

### Marketing path

- UI: `/marketing/criacao`
- Nao e o caminho de grafo/conhecimento.
- Testes de Sofia Graph ou Create nao devem usar a tela de marketing como substituto.

## 9. Anti-alucinacao de produtos

- Termos amplos como "oculos esportivos", "moda inverno", "linha premium" ou
  "lifestyle" sao contexto, nao produtos.
- Sofia so deve criar `product` quando houver sinal explicito:
  - lista de produtos reais;
  - quantidade explicita de produtos;
  - "use estes produtos";
  - "extraia do catalogo";
  - catalogo conectado.
- Sem sinal explicito, Sofia deve perguntar ou criar contexto, nao inventar produto.

Testes obrigatorios:

- Termo amplo nao vira product.
- Lista explicita vira products reais.
- Product group pedido explicitamente vira `product_group`.
- `product_group` nunca pode ficar abaixo de `product`.

## 10. UI do grafo

- `/knowledge/graph` deve carregar Graph JSON v2 quando houver documento publicado.
- Se nao houver documento v2, pode cair para o grafo v1 sem quebrar a pagina.
- O painel Sofia deve estar visivel e utilizavel na aba Graph.
- O usuario deve conseguir enviar comando, ver resposta, ver estado pendente quando
  houver patch visual e confirmar/desfazer quando aplicavel.
- Node drawer deve permitir fluxo de FAQ no contexto do node correto.
- O grafo deve renderizar a hierarquia em ordem canonica.

Testes obrigatorios:

- Render da pagina Graph com Sofia visivel.
- Chamada frontend para `/sofia/graph-command` com `command` e `context`.
- Chamada para `/graph-documents/current?persona_slug=...`.
- Fallback v1 quando v2 nao existe.
- Edge/order visual de `audience -> product_group -> product`.

## 11. Requisitos de teste e review

Toda mudanca que tocar grafo, Sofia, FAQ, auth ou Graph JSON v2 deve incluir ou
atualizar testes cobrindo:

- Caso feliz.
- Falha de permissao.
- Falha de validacao de hierarquia.
- Falha de payload divergente ou incompleto.
- Nao regressao do fluxo oposto: Create e Graph devem continuar compartilhando regra.
- Se for UI, teste de componente ou browser-level que prove o controle visivel.
- Se for rota API, teste direto de funcao e, quando possivel, teste real com servidor local.

Comandos minimos antes de concluir mudanca relevante:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\api\.venv\Scripts\python.exe -B -m py_compile api\main.py api\routes\qa_contract.py api\routes\graph_documents.py api\services\graph_validation.py api\services\graph_json_v2_validator.py
.\api\.venv\Scripts\python.exe -B -m pytest tests\test_graph_json_v2_integration.py tests\test_graph_documents_routes.py tests\test_sofia_graph_product_group.py tests\test_sofia_graph_tree_contract.py -q
cd dashboard
npm run build
npm test
```

Observacao Windows: Vitest pode exigir execucao fora do sandbox quando Vite falhar
com `spawn EPERM`.

## 12. Inteligencia operacional consolidada ate agora

- A branch atual ja incorporou Graph JSON v2, Sofia Graph, `qa_contract.py`,
  `sofia_orchestrator.py`, FAQ generator, product import e testes de QA da branch auditada.
- A rota provisoria `api/routes/sofia_graph.py` foi removida; o contrato final e
  `/sofia/graph-command`.
- Graph JSON v2 roda em paralelo ao v1; ainda nao ha corte destrutivo.
- A validacao real confirmou Sofia retornando `plan_json.graph_json.schema_version = "2.0"`.
- `graph_documents` teve uma regressao de seguranca encontrada e corrigida:
  agora le por persona, escreve so com permissao de edicao e rejeita mismatch de persona.
- A aba Graph tinha Sofia implementada, mas escondida por padrao; foi corrigida para
  abrir visivel.
- Existe timeout quando todos os testes focados rodam em uma unica invocacao longa,
  embora os mesmos grupos passem separados. Isso e fragilidade de harness/estado global.
- O contrato atual ainda tem divergencias historicas em documentos antigos sobre FAQ
  em camadas altas. Este arquivo define a regra desejada para Sofia/Create/Graph
  como fonte raiz e registra o validador v2 permissivo como gap.

## 13. Gaps conhecidos que precisam virar teste ou decisao

- Decidir se FAQ em `audience`, `campaign`, `brand` ou `persona` volta a ser excecao
  permitida. Hoje o validador compartilhado bloqueia.
- Alinhar `graph_json_v2_validator.py` com `graph_validation.py` para FAQ em camada
  alta, ou documentar a excecao e adicionar testes binarios para ela.
- Criar teste browser-level para abrir `/knowledge/graph`, verificar texto
  "Sofia no Graph", enviar comando e observar resposta.
- Resolver timeout da invocacao pytest combinada.
- Revisar quais docs, artefatos QA e arquivos `tmp/sofia_e2e` devem permanecer versionados.
- Consolidar Graph JSON v2 persistido em tabela propria no futuro; hoje parte do MVP
  usa `system_events` e arquivos locais versionados.
- Garantir que pipeline de embedding esteja integralmente preso a FAQ aprovada em todos
  os caminhos legados.

## 14. Regra final de implementacao

Antes de salvar, publicar, renderizar ou alimentar agente:

1. Resolver persona e validar acesso.
2. Montar o galho desde persona ate o menor node disponivel.
3. Inserir briefing, offer e copy em serie, nunca em paralelo.
4. Validar parent/edge contra `graph_validation` e `graph_json_v2_validator`.
5. Criar FAQ como `pending_validation`.
6. Conectar ao Embedded somente depois de aprovacao.
7. Reindexar derivados somente apos publish valido.
8. Manter Create e Graph usando a mesma regra central.
9. Adicionar teste que falharia se a regra de negocio fosse quebrada.
