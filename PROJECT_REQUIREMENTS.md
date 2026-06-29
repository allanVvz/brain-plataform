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
- Webhooks externos devem ser publicos somente quando explicitamente definidos
  como entrada externa. Todo webhook de n8n/Meta deve validar token, assinatura
  ou segredo compartilhado antes de persistir ou disparar resposta.
- Segredos de n8n, Meta, webhook e tokens inbound/outbound nunca podem aparecer
  em respostas GET, logs, eventos SSE ou payloads enviados ao browser.

Testes obrigatorios:

- Usuario A nao ve nem acessa persona B.
- Usuario sem `can_edit` nao publica, aplica patch, reindexa, importa ou faz rollback
  de grafo.
- Payload com `body.persona_slug != graph_json.persona_slug` retorna 422.
- Rotas QA retornam 403 em producao.
- Nenhum teste ou fixture deve depender de segredo real.
- GET de routing/integracao deve mascarar segredo e retornar apenas flags de presenca.
- Webhook com token invalido deve retornar 401 e nao persistir mensagem.

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

## 11. WhatsApp, Meta Business e n8n self-hosted

WhatsApp e o canal operacional de atendimento. Meta Business e a origem oficial
do numero/catologo. n8n self-hosted e o executor de automacoes de entrada/saida.
Brain AI e o motor de inteligencia, persistencia, roteamento, memoria e
observabilidade.

### 11.1 Conceitos obrigatorios

- `telefone`/numero celular do lead e o identificador humano do contato.
- `whatsapp_phone_number_id` e o identificador Meta/WhatsApp Business do numero
  remetente que deve responder aquele lead.
- Um lead deve carregar o `whatsapp_phone_number_id` que recebeu a conversa.
- Toda mensagem persistida deve carregar `whatsapp_phone_number_id` quando o
  canal for WhatsApp e o dado estiver disponivel.
- `agents.whatsapp_number` e o numero E.164 do bot/agente quando aplicavel.
- `agents.whatsapp_contact_name` e usado para E2E via WhatsApp Web.
- `workflow_bindings.whatsapp_phone_number_id` e fallback/default por persona ou
  workflow.
- `personas.process_mode` define o modo da persona:
  - `internal`: Brain AI classifica, responde e persiste.
  - `n8n`: Brain AI persiste inbound e delega a resposta ao n8n.
- `personas.outbound_webhook_url` e o webhook n8n usado para enviar resposta
  humana/operador ao WhatsApp, em ambos os modos.
- `personas.inbound_webhook_token` e o segredo esperado em `X-Webhook-Token`
  quando n8n chama `POST /process`.

### 11.2 Onboarding Meta/WhatsApp a partir de numero celular

O produto deve permitir configurar uma persona para operar com um numero
WhatsApp Business real. O numero celular bruto nao basta: o sistema deve resolver
e persistir os IDs oficiais da Meta.

Requisitos de configuracao:

- Receber numero em formato E.164, display name e persona destino.
- Associar o numero a uma conta WhatsApp Business/Meta Business.
- Persistir o `whatsapp_phone_number_id` retornado pela Meta.
- Persistir, quando disponivel, `business_id`, `waba_id`, `catalog_id` e nome do
  contato/bot para validacao E2E.
- Validar se o numero esta ativo e apto a enviar/receber mensagens.
- Nao usar numero pessoal como substituto de `phone_number_id` no roteamento.
- Permitir multiplos numeros por instancia, desde que cada lead/mensagem carregue
  o `phone_number_id` correto.

Estado atual no repo:

- Existe suporte a `whatsapp_phone_number_id` em `leads`, `messages` e
  `workflow_bindings` via migration `012_lead_whatsapp_phone_number_id.sql`.
- Existe seed legado para Tock Fatal com `phone_number_id=949967854877404`.
- Existe mapeamento E2E bot->contato em `config/bot_contact_map.json`.
- Ainda falta um fluxo completo de onboarding Meta WhatsApp por numero celular
  com verificacao/registro oficial de WABA/phone_number_id.

### 11.3 Integracao Meta Business

Meta tem dois papeis distintos e nao devem ser confundidos:

- Catalogo Meta/WhatsApp Business para importar produtos.
- WhatsApp Business Platform para enviar/receber mensagens.

Catalogo Meta ja e uma integracao user-managed:

- UI: Tools -> Meta.
- Campos atuais: `business_id`, `catalog_id`, `access_token`.
- Backend: `/integrations/user/meta`, `integration_service.validate_meta`.
- Importacao de produtos: `product_import_service` via Graph API.
- Token deve ser criptografado e nunca ecoado ao frontend.
- Produtos importados entram como `pending_validation`.
- Importacao Meta nunca conecta diretamente ao Embedded nem gera FAQ aprovada.

Requisitos ainda pendentes para Meta WhatsApp messaging:

- Registrar/validar webhook Meta ou documentar oficialmente que n8n e o unico
  receptor do webhook Meta.
- Validar assinatura da Meta quando Brain AI receber webhook direto.
- Mapear payload inbound da Meta para `LeadEvent`.
- Preservar `message_id`, `telefone`, `nome`, `persona_slug`, `canal`,
  `mensagem` e `whatsapp_phone_number_id`.
- Tratar mensagens duplicadas por `message_id`.
- Registrar falhas de envio/entrega em `messages.status` e eventos de sistema.

### 11.4 n8n self-hosted

n8n deve ser self-hosted e tratado como executor operacional, nao como fonte de
verdade de conhecimento.

Requisitos:

- `N8N_BASE_URL` e `N8N_API_KEY` configuram observabilidade/API do n8n.
- `n8n_client.get_executions`, `get_workflows`, `get_execution` e `ping` devem
  funcionar contra a instancia self-hosted.
- `N8nMirrorWorker` espelha execucoes em `n8n_executions`.
- `HealthCheckWorker` deve reportar saude do n8n em `integration_status`.
- `messages/send` deve postar resposta humana para o webhook n8n configurado na
  persona ou no agent legado.
- Payload outbound para n8n deve incluir:
  - `lead_ref`
  - `lead_id`
  - `persona_id`
  - `telefone`
  - `whatsapp_phone_number_id`
  - `agent_id`
  - `bot_name`
  - `sender_id`
  - `texto`
  - `message_id`
- Quando `outbound_webhook_secret` existir, o payload deve ser assinado com HMAC
  SHA-256 em `X-Hub-Signature-256` e timestamp.
- Quando `process_mode=n8n`, `POST /process` deve:
  - validar `X-Webhook-Token` se configurado;
  - resolver/criar lead da persona;
  - persistir inbound em `messages`;
  - retornar `agent_used=N8N_DELEGATED`;
  - nao gerar resposta propria.
- Quando `process_mode=internal`, `POST /process` deve classificar, escolher
  agente, gerar resposta e persistir outbound.
- Se o lead estiver `ai_paused=true`, `/process` nao deve responder.
- Se nao houver agente para o role atual, `/process` deve pausar o lead e
  retornar handoff humano.
- A tabela `chat_history` existe para memoria do node Postgres Chat Memory do n8n;
  se o workflow depender dela, migration `046_chat_history_n8n_memory.sql` e
  obrigatoria.

### 11.5 Fluxo canonico de mensagens

Inbound Meta/n8n para Brain:

```text
WhatsApp/Meta -> n8n webhook -> POST /process -> leads/messages -> resposta ou delegacao
```

Outbound operador para WhatsApp:

```text
Dashboard /messages -> POST /messages/send -> messages(status=pending)
-> n8n webhook outbound -> WhatsApp/Meta -> messages(status=sent|failed)
```

Fluxo direto de validacao sem WhatsApp:

```text
WA Validator run-direct -> POST /process -> resposta do agente -> analise
```

E2E real via WhatsApp Web:

```text
WhatsApp Web cliente/validador -> contato do bot -> fluxo real Meta/n8n/Brain
-> resposta no WhatsApp Web
```

Nao confundir as duas visoes:

- Aba de validacao WhatsApp: ponto de vista do cliente falando com o bot.
- Aba `/messages`: ponto de vista interno da marca/servidor.

### 11.6 Observabilidade e validacao WhatsApp

- `/wa-validator/*` deve gerar, rodar e analisar sessoes de validacao.
- `run-direct` testa o core via `/process`, sem WhatsApp.
- E2E WhatsApp Web deve usar perfil persistente e `config/bot_contact_map.json`.
- O teste E2E deve falhar se a resposta:
  - for vazia;
  - repetir a mensagem enviada;
  - contiver erro tecnico, `undefined`, `null`, traceback ou stacktrace;
  - nao tiver proximo passo comercial minimamente coerente.
- n8n sem execucoes recentes deve gerar alerta de saude.
- Alta taxa de mensagens inbound sem outbound deve gerar alerta de negocio.

Testes obrigatorios:

- `/process` em modo `n8n` com token correto persiste inbound e retorna
  `N8N_DELEGATED`.
- `/process` em modo `n8n` com token incorreto retorna 401 e nao persiste inbound.
- `/messages/send` usa `persona.outbound_webhook_url` antes do agent legado.
- `/messages/send` envia `whatsapp_phone_number_id` no payload do n8n.
- `n8n_client.send_to_webhook` assina payload quando recebe secret.
- `GET /personas/{slug}/routing` mascara tokens/secrets.
- Meta catalog valida `access_token`/`catalog_id` e nao ecoa token.
- Importacao Meta cria produtos pending e nao cria Embedded/FAQ aprovada.
- WA Validator `run-direct` retorna resposta nao vazia para persona com agente.
- E2E WhatsApp Web real deve ser marcado `blocked`, nao `passed`, quando n8n/Meta
  nao estiverem configurados.

Gaps atuais:

- Falta UI/fluxo completo para cadastrar numero celular e resolver WABA/
  `whatsapp_phone_number_id` via Meta.
- Falta contrato explicito de webhook direto da Meta para Brain AI, caso n8n nao
  seja o receptor primario.
- Falta teste focado para `/process` em `process_mode=n8n`.
- Falta teste focado para assinatura HMAC do webhook outbound.
- Falta reconciliacao automatica de status de entrega WhatsApp (`sent`,
  `delivered`, `read`, `failed`) a partir de callbacks Meta/n8n.

## 12. Requisitos de teste e review

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

## 13. Inteligencia operacional consolidada ate agora

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
- WhatsApp/n8n ja aparecem como core essencial no repo: `leads`, `messages`,
  `agents`, `persona_role_assignments`, `workflow_bindings`, `n8n_executions`,
  `personas.process_mode`, `whatsapp_phone_number_id`, `/process`,
  `/messages/send`, `/wa-validator/*` e `N8nMirrorWorker`.
- Meta ja existe como integracao user-managed para catalogo de produtos, mas nao
  como onboarding completo de numero WhatsApp Business.

## 14. Gaps conhecidos que precisam virar teste ou decisao

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
- Fechar decisao: Meta webhook direto no Brain AI ou Meta webhook sempre recebido
  pelo n8n self-hosted.
- Criar fluxo de cadastro de numero WhatsApp Business a partir de celular e
  persistencia de `whatsapp_phone_number_id`.
- Criar testes de roteamento n8n e assinatura de webhook.

## 15. Regra final de implementacao

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
10. Em WhatsApp, sempre preservar `telefone`, `lead_ref`, `message_id`,
    `persona_slug` e `whatsapp_phone_number_id` em todo salto Meta/n8n/Brain.
11. Em n8n, validar token/assinatura antes de aceitar inbound ou marcar outbound
    como enviado.
