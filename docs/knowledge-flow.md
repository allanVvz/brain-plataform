# Fluxo e Hierarquia do Conhecimento

Este documento descreve o fluxo atual de conhecimento do AI Brain e a hierarquia usada pelo grafo semantico. Ele reflete o estado do repositorio em 2026-04-30, principalmente as migrations `008`, `009` e `010`, os services `kb_intake_service`, `vault_sync`, `knowledge_graph` e as rotas `/knowledge`.

## Visao Geral

O conhecimento hoje passa por tres camadas:

1. **Camada operacional**
   - `knowledge_items`: fila de conhecimento vindo de upload manual, arquivo ou vault.
   - `kb_entries`: base ativa usada como fallback textual e contexto externo.
   - `knowledge_sources`, `sync_runs`, `sync_logs`: origem e auditoria de sync.

2. **Grafo semantico**
   - `knowledge_nodes`: entidades normalizadas como persona, brand, produto, campanha, FAQ, copy, asset, regra, tom, briefing etc.
   - `knowledge_edges`: relacoes entre nodes, como `about_product`, `part_of_campaign`, `answers_question`, `uses_asset`.

3. **Camada canonica de curadoria**
   - `knowledge_artifacts`: identidade canonica de um conhecimento, independente de quantas vezes ele foi importado.
   - `knowledge_artifact_versions`: historico de versoes por fonte.
   - `knowledge_curation_proposals`: propostas auditaveis de classificacao, merge, criacao de nodes/edges ou validacao.
   - `knowledge_node_type_registry`, `knowledge_relation_type_registry`, `knowledge_validation_rules`: ontologia e regras configuraveis.

O desenho desejado e: fontes brutas entram como `knowledge_items`, sao classificadas e validadas, viram `kb_entries` quando necessario, sao espelhadas em `knowledge_nodes`/`knowledge_edges`, e futuramente convergem sempre para `knowledge_artifacts` como identidade canonica.

## Fluxo de Entrada

### 1. Conversa com Criar/Sofia

Arquivo principal: `services/kb_intake_service.py`.

`Criar` e a ferramenta/tela. A agente conversacional padrao e Sofia, agente de inteligencia marketing comercial. Sofia conduz uma conversa para descobrir:

- cliente/persona;
- tipo de conteudo;
- se e asset visual ou texto;
- titulo;
- classificacao final;
- confirmacao para salvar.

Quando completo, o fluxo salva no vault local, tenta fazer `git add`, `git commit` e `git push`, e chama `run_sync()` para sincronizar o vault com o Supabase.

Fluxo:

```text
usuario -> Sofia/Criar -> arquivo no vault -> git commit/push -> vault_sync -> knowledge_items -> grafo
```

### 1.1. Captura de site/catalogo como evidencia bruta

Quando o operador pede para ler ou coletar um site, o sistema nao deve assumir scraping perfeito. A etapa correta e:

```text
URL -> crawler heuristico -> texto bruto/candidatos -> score de confianca -> lacunas -> validacao humana -> knowledge_items/RAG draft
```

Regras:

- crawler gera evidencia bruta, nao conhecimento ativo;
- produtos, precos, cores, kits e atributos extraidos automaticamente recebem confianca;
- quando a confianca for baixa/media ou houver campo ausente, Sofia deve perguntar ou marcar como `pendente_validacao`;
- ao final, Sofia deve propor varios conhecimentos, cobrindo todos os blocos selecionados no inicio;
- antes de salvar, a resposta deve listar entries e links semanticos concretos, nao apenas um resumo.

### 2. Upload Manual

Arquivo principal: `api/routes/knowledge.py`.

As rotas `/knowledge/upload/text` e `/knowledge/upload/file` criam um item na fila:

```text
upload -> knowledge_items(status='pending') -> knowledge_graph.bootstrap_from_item()
```

Mesmo antes de aprovar, o item ja pode ser espelhado no grafo como node pendente. Isso permite inspecao visual e descoberta de relacoes cedo, mas a validacao humana continua sendo necessaria.

### 3. Sync do Vault

Arquivo principal: `services/vault_sync.py`.

O sync varre arquivos do vault, detecta persona, tipo de conteudo, titulo, frontmatter e corpo. Para cada arquivo:

- cria ou atualiza `knowledge_items`;
- marca como `pending`;
- registra logs em `sync_logs`;
- espelha no grafo com `knowledge_graph.bootstrap_from_item()`.

Fluxo:

```text
vault local -> scan_vault/run_sync -> knowledge_items -> knowledge_nodes/knowledge_edges
```

## Fila de Conhecimento

Tabela principal: `knowledge_items`.

Estados relevantes:

- `pending`: aguardando revisao.
- `needs_persona`: precisa definir cliente/persona.
- `needs_category`: precisa definir tipo.
- `approved`: aprovado para uso.
- `embedded`: aprovado e promovido para KB.
- `rejected`: rejeitado.

Rotas relevantes:

- `GET /knowledge/queue`
- `GET /knowledge/queue/counts`
- `PATCH /knowledge/queue/{item_id}`
- `POST /knowledge/queue/{item_id}/approve`
- `POST /knowledge/queue/{item_id}/to-kb`
- `POST /knowledge/queue/{item_id}/reject`

Quando um item e aprovado com `promote_to_kb=true`, ele tambem vira `kb_entry` e o grafo e reprocessado a partir da entrada ativa.

## Base Ativa

Tabela principal: `kb_entries`.

Ela existe por compatibilidade operacional e fallback textual. Ainda e usada por:

- `/knowledge/context/{persona_slug}`;
- agentes que precisam de contexto textual formatado;
- integracoes externas como bot WhatsApp;
- fallback quando o grafo nao possui informacao suficiente.

Fluxo de promocao:

```text
knowledge_items aprovado -> kb_entries(status='ATIVO') -> bootstrap_from_item(source_table='kb_entries')
```

## Grafo Semantico

Tabelas principais:

- `knowledge_nodes`
- `knowledge_edges`

O grafo e criado pela migration `008_knowledge_graph.sql` e enriquecido pela migration `009_knowledge_curation_architecture.sql`.

### Node

Um `knowledge_node` representa uma unidade semantica consultavel:

- uma persona;
- uma marca;
- um produto;
- uma campanha;
- uma FAQ;
- uma copy;
- um asset;
- uma regra;
- um tom;
- um briefing;
- um item tecnico da fila;
- uma entrada tecnica da KB;
- uma tag.

Campos importantes:

- `persona_id`: escopo do cliente/persona.
- `source_table`: origem operacional, como `knowledge_items` ou `kb_entries`.
- `source_id`: linha original.
- `node_type`: tipo semantico.
- `slug`: identidade curta por tipo/persona.
- `title`: titulo legivel.
- `summary`: resumo ou trecho do conteudo.
- `tags`: marcadores auxiliares.
- `metadata`: dados estruturados, como preco, cores, aliases, arquivo, asset type.
- `status`: `active`, `pending`, `validated` etc.
- `artifact_id`: identidade canonica quando a migration `009` esta aplicada.
- `importance`, `level`, `confidence`: peso, nivel e confianca configuraveis.

### Edge

Um `knowledge_edge` representa relacao entre dois nodes.

Campos importantes:

- `source_node_id`
- `target_node_id`
- `relation_type`
- `weight`
- `confidence`
- `metadata`

O par `(source_node_id, target_node_id, relation_type)` e unico, evitando duplicar a mesma relacao.

## Hierarquia Atual dos Tipos

A hierarquia configuravel fica em `knowledge_node_type_registry`.

Ordem conceitual atual:

| Nivel | Tipo | Papel |
| --- | --- | --- |
| 0 | `persona` | raiz de escopo do cliente/persona |
| 10 | `entity` | cliente, organizacao, pessoa, lugar ou conceito nomeado |
| 20 | `brand` | identidade e posicionamento de marca |
| 30 | `campaign` | acao comercial ou comunicacao com objetivo proprio |
| 40 | `product` | produto, categoria, colecao ou oferta |
| 50 | `briefing` | contexto, estrategia, requisitos e instrucoes |
| 55 | `audience` | publico-alvo, segmento ou bucket de agente |
| 60 | `tone` | voz, estilo, vocabulario e restricoes |
| 65 | `rule` | politica ou regra executavel por agente |
| 70 | `copy` | texto reutilizavel para mensagens, posts ou anuncios |
| 75 | `faq` | pergunta e resposta operacional |
| 80 | `asset` | arquivo visual, video, logo, template ou material maker |
| 90 | `tag` | marcador auxiliar, nao deve ser fonte primaria de verdade |
| 95 | `knowledge_item` | espelho tecnico da fila |
| 95 | `kb_entry` | espelho tecnico da KB ativa |

Essa ordem nao e uma arvore rigida. O sistema deve ser lido como grafo: um produto pode pertencer a uma campanha, uma FAQ pode responder sobre um produto, uma copy pode apoiar uma campanha, um asset pode ser usado por uma copy, e todos podem pertencer a uma persona.

## Tipos de Relacao

A ontologia de relacoes fica em `knowledge_relation_type_registry`.

Relacoes principais:

| Relacao | Sentido esperado | Uso |
| --- | --- | --- |
| `belongs_to_persona` | conhecimento -> persona | escopo do cliente |
| `defines_brand` | briefing/rule/tone -> brand | define identidade da marca |
| `has_tone` | brand/campaign/product/copy -> tone | aplica tom de voz |
| `about_product` | conhecimento -> product | conteudo sobre produto |
| `part_of_campaign` | product/copy/asset/faq/briefing -> campaign | vinculo com campanha |
| `answers_question` | faq/kb_entry -> product/campaign/brand/entity | FAQ responde sobre algo |
| `supports_copy` | copy -> product/campaign/brand | copy apoia oferta/contexto |
| `uses_asset` | product/campaign/copy/brand -> asset | uso de material visual |
| `briefed_by` | product/campaign/copy/asset -> briefing | origem de briefing |
| `same_topic_as` | qualquer -> qualquer | similaridade de tema |
| `duplicate_of` | duplicado -> canonico | deduplicacao |
| `derived_from` | derivado -> origem | subnode ou item derivado |
| `contains` | container -> contido | composicao generica |
| `has_tag` | node -> tag | marcador auxiliar |
| `visible_to_agent` | node -> audience(role-*) | visibilidade por papel de agente |
| `mentions` | topico -> mention | mencao derivada |

Algumas relacoes sao criadas diretamente pelo bootstrap atual mesmo que tenham surgido antes da registry da migration `009`, como `has_tag`, `visible_to_agent`, `mentions` e `supports_campaign`.

## Bootstrap do Grafo

Arquivo principal: `services/knowledge_graph.py`.

A funcao `bootstrap_from_item()` recebe um item vindo de `knowledge_items` ou `kb_entries` e cria/atualiza:

1. Um node espelho do item.
2. Um node `persona:self`, quando ha `persona_id`.
3. Edge `belongs_to_persona`.
4. Nodes `tag` e edges `has_tag`.
5. Nodes de topico explicitos, como `product`, `campaign`, `brand`, `entity`.
6. Edges semanticas conforme o tipo do item.
7. Subnodes derivados de blocos FAQ, headings de briefing e mencoes amplas.
8. Edges `visible_to_agent` para papeis como SDR, Closer, Followup, Maker e Classifier.

Mapeamento atual de `content_type` para `node_type`:

| content_type | node_type |
| --- | --- |
| `faq` | `faq` |
| `copy` | `copy` |
| `campaign` | `campaign` |
| `product` | `product` |
| `asset` | `asset` |
| `rule` | `rule` |
| `tone` | `tone` |
| `audience` | `audience` |
| `brand` | `brand` |
| `briefing` | `briefing` |
| `prompt` | `rule` |
| `competitor` | `audience` |

Relacoes automaticas por tipo:

- `faq` sobre produto/campanha cria `answers_question`.
- `copy` sobre produto/campanha cria `supports_copy`.
- `asset` relacionado a produto cria `product -> asset` com `uses_asset`.
- `asset` relacionado a campanha cria relacao de suporte de campanha.
- conteudos gerais sobre produto criam `about_product`.
- conteudos ligados a campanha criam `part_of_campaign`.
- produto e campanha detectados no mesmo item criam `product -> campaign` com `part_of_campaign`.

## Resolucao de Contexto para Chat e Sidebar

Rota principal:

```text
GET /knowledge/chat-context?lead_ref=...&q=...
```

Arquivo principal: `services/knowledge_graph.py`.

O resolvedor:

1. Le mensagens recentes do lead quando `lead_ref` e informado.
2. Usa `q` como consulta explicita quando fornecido.
3. Detecta termos comparando texto contra nodes canonicos de `product`, `campaign`, `brand`, `entity` e `audience`.
4. Busca seed nodes por termo.
5. Expande vizinhanca em ate dois saltos.
6. Calcula distancia no grafo com BFS.
7. Anexa `graph_distance`, `path`, `path_slugs` e `path_relations`.
8. Agrupa nodes por tipo para a UI.
9. Monta buckets para `kb_entries`, `assets`, entidades detectadas, similares e resumo.
10. Usa fallback em `knowledge_items`/`kb_entries` quando o grafo esta incompleto.

Esse endpoint alimenta a sidebar de conhecimento em mensagens e tambem serve como prova de que a cadeia mensagem -> lead -> conhecimento esta auditavel.

## Camada Canonica de Curadoria

Migration principal: `009_knowledge_curation_architecture.sql`.

O objetivo da camada canonica e impedir que importacoes repetidas do mesmo conhecimento virem verdades separadas.

### Artifact

`knowledge_artifacts` representa a identidade canonica:

```text
persona + content_type + title_slug -> canonical_key/canonical_hash -> artifact
```

Ele guarda:

- titulo canonico;
- tipo de conteudo;
- status de curadoria;
- importancia;
- nivel;
- confianca;
- ponte para item atual da fila;
- ponte para KB atual;
- caminho do vault;
- dados de git;
- hash de conteudo;
- metadata.

### Versions

`knowledge_artifact_versions` guarda cada versao observada:

- fonte (`knowledge_items`, `kb_entries`, `manual`, `vault`, `classifier`);
- `source_id`;
- titulo;
- tipo;
- hash;
- conteudo bruto;
- classificacao;
- commit git.

### Proposals

`knowledge_curation_proposals` guarda propostas auditaveis:

- criar/atualizar artifact;
- criar/atualizar node;
- criar/atualizar edge;
- merge de duplicata;
- reclassificacao;
- validar;
- rejeitar;
- marcar como stale.

A diretriz atual e: o KB Classifier tambem deve agir como curator, propondo merge, hierarquia, importancia, nivel, confianca e relacoes. Mutacoes destrutivas nao devem acontecer sem proposta auditavel.

## Regras de Validacao

Migration principal: `010_knowledge_validation_rules.sql`.

As regras de validacao tornam requisitos configuraveis. Exemplo atual:

- todo produto validado precisa ter `metadata.price`;
- `metadata.price.amount` deve ser numero positivo;
- `metadata.price.currency` deve usar ISO de 3 letras;
- `metadata.colors_count`, quando presente, deve ser positivo;
- asset valido precisa ter arquivo ou URL.

Views relevantes:

- `v_knowledge_validation_failures`
- `v_knowledge_products_missing_price`

Essas views ajudam o curator a abrir propostas quando um conhecimento nao cumpre regra.

## Relacao com n8n

O n8n continua sendo fonte operacional atual para execucao de alguns fluxos. O AI Brain esta assumindo progressivamente a inteligencia.

Estado conceitual:

```text
Etapa 1: n8n executa -> AI Brain observa e aprende
Etapa 2: AI Brain decide -> n8n executa
Etapa 3: AI Brain executa -> n8n removido ou reduzido
```

Importante: `services/vault_sync.py` nao alimenta o n8n diretamente. Ele sincroniza vault local para `knowledge_items` e grafo semantico. Workflows n8n que usam vector store em memoria nao ficam automaticamente conectados ao vault/grafo novo.

## Fluxo Completo Esperado

```text
1. Entrada
   - KB Classifier
   - upload manual
   - arquivo no vault
   - sync externo

2. Normalizacao operacional
   - knowledge_sources
   - knowledge_items(status='pending')
   - sync_logs/sync_runs

3. Classificacao e revisao
   - persona
   - content_type
   - metadata estruturado
   - tags
   - agent_visibility

4. Espelhamento semantico
   - knowledge_nodes
   - knowledge_edges
   - relacoes por produto, campanha, brand, FAQ, copy, asset, regra, tom

5. Curadoria canonica
   - knowledge_artifacts
   - knowledge_artifact_versions
   - knowledge_curation_proposals
   - validacao por knowledge_validation_rules

6. Promocao para base ativa
   - approve
   - promote_to_kb
   - kb_entries(status='ATIVO')
   - novo bootstrap a partir da KB

7. Consumo
   - /knowledge/chat-context
   - sidebar de mensagens
   - /knowledge/context/{persona_slug}
   - agentes SDR/Closer/Classifier
   - fluxos n8n enquanto ainda existirem

8. Observabilidade e reparo
   - /knowledge/graph/rebuild
   - testes de integracao
   - relatorios em test-artifacts
```

## Testes e Provas Existentes

Testes relevantes:

- `tests/integration_prime_higienizacao_mock.py`: valida fluxo completo offline com fixture estruturada, grafo, distancia/path, resposta deterministica e sidebar.
- `tests/integration_prime_bulk_real.py`: cadastra Prime Higienizacao com produtos, copys, FAQs, mensagens e valida grafo/chat-context no banco real.
- `tests/integration_moosi_winter26_graph.py`: valida produto/campanha/relacionados por slug, tipo, distancia e path.
- `tests/integration_knowledge_curation_architecture.py`: audita migration `009`, arquitetura canonica e regras da `010`.
- `tests/smoke_knowledge_graph.py`: smoke do grafo.
- `tests/rebuild_graph.py`: suporte para reprocessar grafo.

## Estado Atual e Pendencias Conhecidas

Pontos ja resolvidos ou encaminhados:

- O grafo semantico existe via migration `008`.
- A arquitetura canonica existe via migration `009`.
- Regras configuraveis existem via migration `010`.
- O link quebrado `/knowledge/kb/<id>` foi removido da sidebar em favor de destinos existentes.
- A sidebar ja usa dados de `chat_context`, incluindo nodes, KB, assets, similares e distancias.

Pendencias importantes:

- Reexecutar a view/migration `009` atualizada se `v_knowledge_curation_backlog` estiver sem `artifact_id`.
- Aplicar `010_knowledge_validation_rules.sql` no banco onde ainda nao estiver aplicada.
- Otimizar escrita em massa de artifacts/versions para cenarios grandes.
- Criar rota universal de detalhe, por exemplo `/knowledge/node/{id}`, com node, vizinhanca, fonte, versoes e propostas.
- Substituir gradualmente a resposta final do n8n pela resposta local do AI Brain usando `/knowledge/chat-context`.

## Regra de Ouro

O sistema nao deve depender de strings hardcoded de cliente, produto, campanha, dominio ou FAQ. A validacao correta deve usar:

- `persona_id` ou `persona_slug`;
- `node_type`;
- `slug`;
- `relation_type`;
- `metadata`;
- `graph_distance`;
- `path`;
- `artifact_id` quando disponivel.

O grafo e a camada canonica devem ser a fonte para entender relacoes, duplicatas, importancia e contexto. A fila e a KB ativa continuam existindo para compatibilidade operacional, mas nao devem ser tratadas como verdades isoladas.
