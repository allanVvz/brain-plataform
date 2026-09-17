# AGENTS.md - Brain AI

## Operacao de producao sem Docker local

A operacao corrente e exclusivamente em producao. Nao subir, inspecionar ou
usar uma stack Docker local para implementar, auditar ou testar este projeto.

### Regras rigidas
- Nunca executar `docker`, `docker compose` ou equivalentes na maquina local.
- Nao apontar testes ou o dashboard para backends locais ou legados.
- O dashboard deve usar `/api-brain`; em producao,
  `NEXT_PUBLIC_API_BASE_URL=/api-brain` e `API_INTERNAL_BASE_URL` aponta para o
  backend final aprovado.
- Comecar qualquer operacao produtiva por auditoria read-only e dry-run.
- Um deploy compativel e reversivel exige uma unica autorizacao. Ela cobre
  candidate, cutover atomico, verificacao e rollback automatico da mesma
  release. Migration e limpeza destrutiva continuam exigindo autorizacoes
  proprias e nunca sao implicadas pelo deploy.
- Mudancas de conversa devem ser testadas somente pelo WA Validator
  direto/interno, sem WhatsApp real.
- Publicacao de GraphBundle e conteudo nunca pausa binding, persona, IA ou
  worker. Stage e validacao usam a publicacao candidata; ativacao e CAS e a
  publicacao anterior continua ativa quando qualquer etapa falha.
- Release compativel de API/runtime usa blue/green sem pausa. Release compativel
  de worker para novos claims, drena o worker antigo por no maximo 45 segundos
  e inicia o novo; webhooks continuam persistindo no buffer nesse intervalo.
- Pausa global e excepcional: use-a somente para migration destrutiva, contrato
  de fila incompativel sem dual compatibility ou incidente ativo comprovado de
  duplicidade, persona errada ou outbound comercial sem proof. Falha de um
  turno pausa no maximo a lead afetada. Limpeza de uma lead/conversa usa a trava
  do claim, lock da lead e checagem de trabalho em voo; ela nao pausa personas
  ou workers nao envolvidos.
- Retencao e limpeza permanecem em dry-run ate autorizacao especifica. Nunca
  inferir permissao para apagar dados a partir de uma autorizacao de deploy.
  Uma limpeza aprovada continua exigindo escopo exato, dry-run, lock local e
  confirmacao de que a lead nao possui buffer em processamento/proof antes do
  commit.
- Consentimentos e eventos de auditoria imutaveis nao sao "historico de
  conversa" e nao podem ser apagados por uma limpeza operacional. Se eles
  impedirem a exclusao fisica da lead, o dry-run deve bloquear antes de mutar;
  anonimização ou mudanca de retencao exige uma decisao legal e migration
  autorizadas separadamente.

### Auditoria
1. Confirmar SHA, release, health/readiness e o estado operacional no escopo da
   operacao via endpoints e scripts oficiais de producao. Readiness
   conversacional deve provar uma transacao sintetica; health HTTP isolado nao
   comprova que o caminho de decisao esta funcional.
2. Executar dry-run da operacao solicitada e registrar contagens/IDs tecnicos
   nao secretos.
3. Revisar o resultado antes de qualquer mutacao produtiva adicional.
4. Para conversas, executar sessoes sinteticas diretas e comprovar proof,
   ledger, exactly-once e ausencia de outbound real.

### Trava de simplicidade

- Classificar a mudanca antes de testar ou publicar: `documentation`,
  `dashboard`, `graph`, `service`, `worker` ou `migration`.
- Uma mudanca normal tem um dono, um workflow, uma imagem ou publicacao, uma
  verificacao e um rollback. Graph-only nao constroi imagem, nao sincroniza n8n
  e nao reinicia servico; dashboard nao toca VPS; um servico compativel nao
  dispara release dos demais.
- Nunca fazer deploy para diagnosticar. O mesmo digest deve passar no candidate
  isolado da VPS antes do unico cutover produtivo.
- Necessidade de segundo redeploy corretivo, edicao manual de container/VPS,
  terceiro comando emergencial ou deploy de servico nao afetado e uma regressao
  arquitetural: interromper, preservar evidencias e corrigir o pipeline. Nao
  continuar empilhando deploys.
- Graph/content deve concluir em menos de 3 minutos e release compativel de um
  servico em menos de 8 minutos no p95. Ultrapassar a classe de impacto ou esses
  limites repetidamente bloqueia a release, nao justifica mais burocracia.
- Suites amplas ficam em nightly/advisory. O gate de uma release executa apenas
  contratos compartilhados, testes do componente afetado e um canario preciso
  do caminho real quando a conversa mudou.

## Regras de negocio - Grafos

### Persona na visualizacao Tree
- Na visualizacao em tree, o node `Persona` sempre fica na parte superior.
- `Persona` so pode receber conexoes abaixo.
- `Persona` tera somente conexao de saida inferior.
- `Persona` nao deve ter conexao superior.
- Na tree, `Persona` e o topo conceitual do fluxo.

### Conexoes na visualizacao Tree
- Conexoes de entrada devem aparecer na parte superior do node.
- Conexoes de saida devem aparecer na parte inferior do node.
- O fluxo visual deve ser vertical: entrada em cima, processamento/conhecimento no meio, saida embaixo.

### Nodes finais / nodes de uso
- Nodes como Galeria, Embed, Assets, Backgrounds, Texturas, Copy e FAQ geralmente aparecem no final do fluxo.
- Eles devem poder receber conexoes de conhecimentos anteriores.

### Galeria e Embed
- `Galeria` e `Embed` devem ter somente o circulo/conector superior.
- Esses nodes recebem conexoes, mas nao precisam emitir conexoes inferiores por padrao.
- Deve ser possivel conectar Galeria com Copy, FAQ, Assets, Backgrounds e Texturas.
- Deve ser possivel conectar Embed com Copy, FAQ e Assets.

### Categorias diferentes de nodes
- O grafo deve tratar como categorias diferentes: Persona, Brand, Campanha, Produto, Publico, FAQ, Copy, Assets, Galeria, Embed, Backgrounds, Texturas, Regras, Tom de voz e Entidades.
- Cada categoria pode ter visual, conector e nivel hierarquico proprio.

### Conversa (midia recebida no WhatsApp)
- `conversation` e um node por lead com conversa aberta, criado quando o cliente
  envia uma midia. Cadeia canonica: `campanha -> publico -> conversa -> asset`.
- A campanha e resolvida por `campaign_recipients`, nunca por
  `messages.campaign_id` (a constraint de 087 exige `direction='outbound'`).
- Sem campanha atribuivel, a conversa e criada fora da arvore primaria em vez de
  inventar uma campanha; o asset ainda chega a Gallery.
- Midia enviada pelo cliente nunca recebe `asset_function` nem slot de landing,
  e nunca entra no RAG (`is_rag_eligible` continua so `faq`).

## Grafos - Embed e Gallery
- Embed e destino final de KB.
- Gallery e destino final de Assets.
- Embed e Gallery nao nascem conectados a outros nodes.
- Ao conectar conteudo ao Embed, o conteudo e tratado como aprovado e enviado para Knowledge Base.
- Ao conectar conteudo ao Gallery, o conteudo fica disponivel em Assets.
- E obrigatorio conseguir excluir conexoes entre nodes pelo botao da edge.
- Excluir uma edge nao deve deletar o node.
- Excluir uma edge nao deve apagar KB/Asset de forma destrutiva sem regra explicita.
- Embed deve espelhar a tabela real do banco relacionada a knowledge_chunks/KB.
- A validacao do Embed e: conteudo conectado aparece em Knowledge Base filtrado pela persona.
- A validacao do Gallery e: conteudo conectado aparece em Assets da persona.

## Auth e Permissoes
- O Brain AI exige login para todas as telas internas do dashboard.
- A sessao deve ficar em cookie HTTP-only; logout limpa a sessao e redireciona para `/login`.
- Senhas nunca devem ser salvas em texto puro; usar hash forte no backend.
- Admin acessa todas as personas/clientes.
- Usuarios `user`, `operator` e `viewer` acessam apenas personas/clientes atribuidos em `user_persona_access`.
- O seletor global de persona deve listar somente personas autorizadas para o usuario atual.
- Toda API interna deve validar sessao no backend e aplicar filtro por persona/cliente autorizado.
- Se uma persona solicitada nao for autorizada, retornar 403 e nao vazar dados ou nomes de outras personas.
- Rotas publicas devem ser mantidas apenas para health, login/logout e webhooks externos explicitamente publicos.
- Criacao operacional de login via banco/script: `cd api && python scripts/create_auth_user.py --email operador@empresa.com --username operador --password <senha> --role operator --persona tock-fatal --can-edit`.
- Admin inicial deve ser criado com envs `AI_BRAIN_SEED_ADMIN_EMAIL` e `AI_BRAIN_SEED_ADMIN_PASSWORD`, sem senha fixa em producao.

## Output publico de site

- Toda memoria de campanha, produto, oferta, copy, FAQ, asset e brand deve poder
  ser reconstruida como site publico.
- O contrato publico atual e `/api/menu/{persona_slug}`. Ele deve preservar
  `persona.collections[]` e expor tambem o objeto `site`.
- A configuracao por persona fica em `personas.config.public_site`: `site_slug`,
  `site_name`, `format_key`, `default_collection_slug`, `whatsapp_phone` e
  `whatsapp_message_template`.
- `whatsapp_phone` e telefone publico para link `wa.me`; nao usar como substituto
  de `whatsapp_phone_number_id` Meta/n8n.
- Formatos fixos de output ficam em `public_site_formats`. A criacao desta tabela
  foi aprovada explicitamente para registry de formatos; novos formatos entram
  pelo banco/migration por enquanto, nao pela UI.
- Seeds obrigatorios: `cardapio`, `landing_page`, `catalogo_roupas`.
- Nunca expor token Meta, segredo n8n, chave OpenAI/Anthropic ou
  `whatsapp_phone_number_id` no payload publico do site.

## 1. Regra central

Brain AI e um sistema de CRM + Knowledge Graph + RAG.

Todo conhecimento adicionado DEVE aparecer no grafo.

Fonte operacional atual:

```text
knowledge_items -> knowledge_nodes -> knowledge_edges

Fonte canonica em evolucao:

knowledge_rag_entries -> knowledge_rag_chunks -> knowledge_nodes -> knowledge_edges

kb_entries existe por compatibilidade legacy.

2. Nao complexificar banco sem perguntar

Nao criar tabela nova sem antes perguntar.

Antes de propor nova tabela, tentar usar:

knowledge_items
knowledge_rag_entries
knowledge_rag_chunks
knowledge_nodes
knowledge_edges
metadata
node_type
relation_type
status

Preferir:

metadata para campos flexiveis;
node_type para novas categorias;
relation_type para novas relacoes;
views de compatibilidade em vez de tabelas novas;
repositories/adapters em vez de mudar schema cedo demais.
3. Estrutura fixa do projeto
/api        # FastAPI backend
/dashboard  # Next.js frontend

Regras:

api/requirements.txt
dashboard/lib/api.ts
.github/workflows/ci.yml

Nao usar:

requirements.txt na raiz;
backend fora de /api;
frontend fora de /dashboard;
segredo no Git.
4. Frontend chama backend

Nunca usar backend hardcoded:

http://localhost:8000

Sempre chamar:

/api-brain/...

via:

dashboard/lib/api.ts

Em producao:

NEXT_PUBLIC_API_BASE_URL=/api-brain
API_INTERNAL_BASE_URL deve apontar para o backend final aprovado.
5. Pipeline de conhecimento

Todo conhecimento segue este fluxo:

entrada bruta
-> knowledge_items ou knowledge_intake_messages
-> classificacao
-> validacao
-> knowledge_rag_entries
-> knowledge_rag_chunks
-> knowledge_nodes
-> knowledge_edges
-> grafo/sidebar/agentes/chat-context

Regra obrigatoria:

se entrou na KB/RAG, precisa existir como node no grafo
se tem relacao semantica, precisa existir como edge
6. Inserir conhecimento

Ao inserir conhecimento, sempre definir:

persona_id ou persona_slug:
node_type:
slug:
title:
summary ou content:
source:
status:
tags:
metadata:
relations:

Se faltar fonte, usar:

pending_source

Se faltar validacao humana, usar:

pending_validation

Se aprovado, usar:

validated
7. Tipos principais de node
persona
brand
campaign
product
briefing
audience
tone
rule
copy
faq
asset
tag
knowledge_item
kb_entry

Nao criar novo tipo se um desses resolver.

8. Relacoes principais
belongs_to_persona
part_of_campaign
about_product
answers_question
supports_copy
uses_asset
briefed_by
same_topic_as
derived_from
contains
has_tag
visible_to_agent
gallery_asset

Nao criar nova relacao se uma dessas resolver.

9. Regras de grafo

Todo conhecimento precisa gerar ou atualizar:

knowledge_nodes

Toda conexao precisa gerar ou atualizar:

knowledge_edges

Edge deve preservar:

source_node_id:
target_node_id:
relation_type:
confidence:
weight:
metadata:

Unicidade logica:

source_node_id + target_node_id + relation_type

Delete de edge:

DELETE /knowledge/graph-edges/{edge_id}

Preferir soft delete:

metadata.active=false
10. Nodes protegidos

Nao excluir pela UI nem por endpoint comum:

Persona
Embedded
Gallery

Regras:

Persona e raiz de escopo.
Embedded representa conhecimento RAG.
Gallery representa curadoria visual.
assets ligados ao Gallery usam gallery_asset.
11. Envio para KB legacy

Fluxo:

knowledge_items(status='pending')
-> approve
-> promote_to_kb=true
-> kb_entries(status='ATIVO')
-> bootstrap_from_item(source_table='kb_entries')
-> knowledge_nodes
-> knowledge_edges

Regra:

kb_entries nunca deve existir sem reflexo no grafo
12. Envio para RAG

Fluxo:

knowledge_intake_messages
-> knowledge_rag_entries
-> knowledge_rag_chunks
-> Embedded node
-> knowledge_nodes
-> knowledge_edges

Regras:

metadata.rag_index="default"

Cada knowledge_rag_entry deve representar uma unidade semantica clara.

Cada knowledge_rag_chunk deve pertencer a uma entry.

Todo RAG entry relevante deve aparecer no grafo.

13. Captura via Sofia/Criar

Sofia deve produzir:

entries estruturadas
links semanticos
fontes
status
lacunas
perguntas pendentes

Nao aceitar apenas resumo.

Antes de salvar, Sofia deve mostrar:

o que sera salvo;
em qual persona;
quais nodes serao criados;
quais edges serao criadas;
o que ficou pendente.
14. Captura de site

Site/crawler gera evidencia bruta, nao verdade ativa.

Fluxo:

URL
-> parsing heuristico
-> candidatos
-> score de confianca
-> lacunas
-> validacao humana
-> knowledge_items/RAG draft
-> grafo

Regras:

nao inventar produto;
nao inventar preco;
nao inventar cor;
nao inventar kit;
nao inventar URL;
separar fato confirmado de inferencia;
inferencia entra como pending_validation;
sem fonte entra como pending_source.
15. Exemplo de product node
persona_slug: tock-fatal
node_type: product
slug: kit-modal-1-9-cores-disponiveis
title: Kit Modal 1 - 9 cores disponiveis
status: pending_validation
summary: Blusa canelada de modal com tecido macio, modelagem ajustada e cores para revenda e varejo.
tags:
  - modal
  - inverno
  - revenda
metadata:
  product_type: Modal
  source_url: https://tockfatal.com/products/kit-modal-1-1-peca-9-cores-disponiveis
  price:
    unit:
      amount: 59.90
      currency: BRL
    kit_5:
      amount: 249.00
      currency: BRL
    kit_10:
      amount: 459.00
      currency: BRL
  colors:
    - vermelho
    - vinho
    - bege
    - nude
    - off white
    - verde claro
    - azul claro
    - azul marinho
    - preto
relations:
  - relation_type: belongs_to_persona
    target: tock-fatal
  - relation_type: part_of_campaign
    target: colecao-modais-de-inverno
  - relation_type: visible_to_agent
    target: atacado-revenda
16. Exemplo de FAQ node
persona_slug: tock-fatal
node_type: faq
slug: faq-precos-kits-modal
title: Quanto custa o Kit Modal?
status: pending_validation
content:
  pergunta: Quanto custa o Kit Modal?
  resposta: A unidade custa R$ 59,90, o kit com 5 pecas custa R$ 249,00 e o kit com 10 pecas custa R$ 459,00.
relations:
  - relation_type: answers_question
    target: kit-modal-1-9-cores-disponiveis
17. Exemplo de copy node
persona_slug: tock-fatal
node_type: copy
slug: copy-atacado-kit-modal-1
title: Copy atacado - Kit Modal 1
status: pending_validation
content: O Kit Modal 1 e uma escolha segura para giro rapido: blusa canelada, tecido macio e 9 cores faceis de combinar.
relations:
  - relation_type: supports_copy
    target: kit-modal-1-9-cores-disponiveis
  - relation_type: visible_to_agent
    target: atacado-revenda
18. Validacao minima

Produto precisa de:

persona
title
source
status
metadata
node no grafo

FAQ precisa de:

pergunta
resposta
target semantico
node no grafo
edge answers_question

Copy precisa de:

publico ou canal
target semantico
node no grafo
edge supports_copy

Asset precisa de:

arquivo ou URL
tipo visual
persona
node no grafo
edge uses_asset ou gallery_asset
19. Chat context

Endpoint:

GET /knowledge/chat-context?lead_ref=...&q=...

Deve usar:

mensagens recentes;
q, se enviado;
nodes canonicos;
edges;
distancia no grafo;
path;
fallback em kb_entries apenas se necessario.
20. Importacao de leads

CSV Meta:

email,phone,fn,ln,ct,st,zip,country

Regras:

persona obrigatoria;
criar bloco audience;
ligar audience a persona;
registrar em system_events;
exclusao arquiva audience, nao apaga historico.
21. Tabelas que nao remover sem auditoria
lead_context
lead_buffer
chat_history
agent_prompt_profiles
kb_intake
knowledge_artifacts
knowledge_artifact_versions
knowledge_curation_runs
knowledge_curation_proposals
knowledge_validation_rules
knowledge_rag_links
brand_profiles
campaigns
assets
pipeline_status

Remocao exige:

backup
0 referencias no codigo
0 chamadas externas
confirmacao n8n
observabilidade 2-4 semanas
rollback
22. Regras anti-hardcoded

Nao depender de string fixa de:

cliente
produto
campanha
dominio
FAQ

Usar:

persona_id
persona_slug
node_type
slug
relation_type
metadata
graph_distance
path
23. CI e deploy

Antes do push:

cd api
python -m py_compile main.py routes\*.py services\*.py core\*.py workers\*.py

cd ..\dashboard
npm run build

Deploy:

frontend: Vercel, root dashboard
backend: backend final aprovado
24. Regra final

Todo conhecimento deve responder:

de quem e?
que tipo e?
qual a fonte?
esta validado?
qual node cria?
quais edges cria?
entra na KB legacy?
entra no RAG?
aparece no grafo?

Se nao aparece no grafo, esta incompleto.

## 25. E2E de agentes, Evolution e n8n

- Mudancas em mensagens, workers, runtime de agentes, qualificacao, handoff,
  pause/resume, Evolution ou n8n devem usar a skill
  `.agents/skills/brain-agent-e2e/SKILL.md`.
- O E2E deve provar o caminho completo nos dois lados da conversa. Status
  `sent` ou `delivered` do provider nao substitui a mensagem persistida no
  destino.
- O WA Validator usa o worker real com provider `internal_validator` e sink
  interno, sem outbound ao WhatsApp. Ele pode atravessar binding comercial
  pausado porque nao envia ao cliente; nao pausar o transporte para QA.
- Cada inbound canonico pode gerar no maximo uma decisao e um outbound.
  Duplicidade, cascata, contexto da persona errada ou confirmacao indevida de
  preco/data/horario interrompem novos envios e exigem auditoria em `/logs`.
- Pareamento deve usar binding, telefone mascarado, IDs, mensagens e timestamps;
  nomes locais de lead podem ser diferentes entre as personas.
- O relatorio deve registrar IDs tecnicos nao secretos, direcoes, timestamps,
  status HTTP, latencias, versao/checksum do grafo, estado das IAs e screenshots.

## 26. Runtime conversacional unico e backend sem hardcoded

- `apps/conversation-runtime` e a unica fonte produtiva da decisao de conversa.
  Templates n8n antigos sao fixtures de auditoria e nao sao provisionaveis.
- O mesmo executor `interpret_then_respond` atende qualquer persona sem fork de
  nodes ou codigo. Binding fornece somente identidade e configuracao tecnica;
  a credencial do modelo fica cifrada na integracao existente da persona.
- Exports com nome de persona sao fixtures/legado de auditoria; nunca sao fonte
  de runtime ou provisionamento.
- Prompt comercial, servicos, produtos, precos, campos, politicas e copy vem de
  `personas.config`, binding, Graph JSON publicado e `context_cards` aprovados.
- Codigo de producao em `api/routes`, `api/services`, `api/core` e `api/workers`
  nao pode ramificar por cliente, persona, marca, produto, campanha, servico,
  dominio, FAQ ou nome de lead real.
- Nomes reais sao permitidos apenas em testes, fixtures, migrations pontuais,
  rotas explicitamente QA e exports legados sem influencia no runtime.
- Pause/resume deve fazer claim atomico do buffer e usar a identidade canonica
  do inbound como chave idempotente. Retry ou correlacao sintetica nao pode
  produzir uma segunda decisao/outbound.
- Mudanca de versao/checksum do grafo deve migrar ou invalidar estado
  incompatível antes da proxima pergunta. Nova intencao explicita deve substituir
  servico historico incompatível e recalcular campos faltantes.

## 27. Qualificacao de agendamento orientada pelo grafo

- Toda persona com `business_model=appointment` deve declarar no node Persona:
  `data.appointment_policy.required_fields` e
  `data.appointment_policy.field_questions`.
- Cada campo obrigatorio comum ou presente em `product.data.booking.required_fields`
  deve ter uma pergunta nao vazia no mapa da Persona.
- `field_questions` garante cobertura de autoria e identidade auditavel; nao e
  roteiro no modo agentic. Nesse modo o modelo pode escolher qualquer
  campo ainda perguntavel cujas dependencias estejam satisfeitas, e
  `missing_fields` mede somente completude.
- Somente o motor `deterministic`, quando escolhido explicitamente pelo
  binding, pode resolver a proxima pergunta por
  `field_questions[missing_fields[0]]`. O motor agentic e o proof nao podem
  anexar essa copy, selecionar uma FAQ unica ou substituir a fala do modelo.
- Grafo de agendamento incompleto deve falhar na validacao antes da publicacao.
- Sofia deve auxiliar o operador a preencher a matriz campo/pergunta, preservar
  fonte/status e nao copiar perguntas de outra persona ou exemplo.

## 28. Fronteiras de microsservicos e cutover

- `brain-plataform` conserva dashboard, gateway `/api-brain`, migrations,
  route map e manifests de release.
- `apps/conversation-runtime` e a unica fonte produtiva do runtime de conversa.
  Implementacoes em `api/services` e repositorios congelados sao apenas
  referencia/compatibilidade e nunca podem ser copiadas de volta para o
  microsservico.
- O conversation runtime e a unica autoridade da decisao agentic. O transport
  chama seu endpoint interno; n8n nao executa modelo, proof, commit nem
  fail-safe no caminho sincrono. O valor legado `n8n_agents`, enquanto existir
  em metadata antiga, e apenas compatibilidade de armazenamento e nao autoriza
  despacho para webhook n8n.
- Toda execucao agentic usa `interpret_then_respond`. `single_pass` e repair
  semantico nao sao caminhos produtivos. A primeira falha JSON/modelo/proof e
  terminalizada e auditada sem pausa; duas falhas consecutivas geram um unico
  handoff. Um turno bem-sucedido zera a sequencia.
- Control plane, conversation runtime e transport usam imagens, health,
  rollback e roles de banco independentes; nenhum importa codigo de outro.
- Contratos entre servicos vem somente de `brain-contracts` em versao exata.
- Deploy de servico nunca executa migration e readiness falha abaixo de
  `REQUIRED_SCHEMA_VERSION`.
- Cutover compativel usa dual compatibility, candidate e blue/green sem pausa.
  Falha de GraphBundle mantem a publicacao anterior e nao pausa a persona.

## Rollout de microsservicos

Comece sempre por `bash ops/vps/rollout-microservices.sh status` (somente
leitura). Ele compara o manifesto com o que roda, mostra o estado da pausa e
imprime a sequencia exata.

Ordem para release compativel:

1. `bash ops/vps/rollout-microservices.sh status`
2. validar o digest candidato na VPS sem trafego real
3. `gh workflow run "Integrated microservice release" --ref main -f manifest_sha=<sha> -f action=deploy -f services=<lista-sem-espacos>`
4. `bash ops/vps/rollout-microservices.sh status`

`prepare`/`finish` e pausa global sao permitidos somente quando o classificador
marcar `migration` ou `breaking_queue_contract`. Worker compativel usa drain
limitado no proprio workflow e rollback se nao drenar.

Antes do passo 3, confira se a entrada do servico afetado no manifesto aponta
para o SHA e digest do build atual. Renderize a atualizacao incremental com
`ops/microservices/render-monorepo-release-manifest.py --base-manifest ...`;
entradas dos demais servicos devem permanecer byte a byte iguais.

O preflight exige backup data-only com menos de 26h quando o impacto e
`migration`: `bash ops/vps/backup.sh`.

## 29. Release compativel deve permanecer simples

- Uma mudanca compativel em um servico constroi e promove somente esse servico.
- O manifesto preserva `sha`, digest, contrato e schema por servico; SHAs iguais
  entre servicos nao sao requisito de release.
- Runtime-only executa exatamente um build, um candidate isolado, um cutover e
  um canario WA interno. Gateway, control-plane e transport nao reiniciam.
- Candidate inicia no slot inativo sem consumidores de fila. Readiness e teste
  interno acontecem antes do cutover; workers drenam por no maximo 45 segundos.
- Falha antes do cutover nao altera trafego. Falha no canario posterior restaura
  automaticamente rota, workers, slot e digest anteriores.
- GraphBundle-only e dashboard-only nao constroem imagens nem executam rollout
  na VPS.
- `servico + sha` e a chave de deduplicacao. Disparos repetidos reutilizam a
  imagem imutavel e produzem no maximo uma promocao efetiva.
- Suites amplas sao nightly ou advisory. O gate compativel contem contratos
  compartilhados, testes do componente e um canario do caminho real.
- Migration e quebra de contrato de fila sao as unicas classes que permitem
  coordenacao ampliada, declarada antes do rollout.
- No primeiro sinal de redeploy corretivo, terceiro comando emergencial,
  sincronizacao manual de codigo na VPS ou deploy de servico nao afetado, parar
  a operacao e corrigir o pipeline. Complexidade operacional e defeito, nao
  procedimento normal.
