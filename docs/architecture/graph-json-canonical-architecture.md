# Graph JSON v2 — arquitetura canônica

Status: implementado sobre as tabelas existentes. Não criar `graph_documents`,
`graph_versions` ou `graph_events`.

## Fonte de verdade

Existe um documento completo por persona (e, opcionalmente, brand) no evento
`graph_document_published` de `system_events`. O payload preserva:

- `persona_slug`, `brand_slug`, `version` e `checksum`;
- `graph_json` completo;
- origem, ator, nota e `idempotency_key`;
- relatório das projeções obrigatórias.

Uma versão só recebe o evento `graph_document_published` depois que as projeções
obrigatórias terminam. Tentativas, falhas e sincronizações são auditadas no mesmo
`system_events`.

## Projeções regeneráveis

O documento publicado materializa, de forma idempotente:

1. Markdown no volume do vault;
2. `knowledge_items`;
3. `knowledge_nodes` e `knowledge_edges`;
4. snapshots aprovados;
5. `knowledge_rag_entries` e `knowledge_rag_chunks`;
6. índices Markdown de Embedded e Gallery;
7. contexto consumido pelos agentes.

Registros derivados removidos do documento são desativados, não apagados
destrutivamente. `kb_entries` continua somente como fallback legado auditável.

## Markdown

Todo card gera Markdown em:

`AI-BRAIN/05_ENTITIES/CLIENTS/{PERSONA}/{PASTA_DO_TIPO}/{slug}.md`

Isso inclui Persona, Embedded, Gallery e o sidecar de Asset. O frontmatter
contém graph ID/versão/checksum, node ID/tipo/status/fonte, parent, branch path,
checksum do conteúdo e relações. Caminhos são resolvidos contra a raiz do vault;
qualquer tentativa de escapar dela é rejeitada.

## Publicação e concorrência

`POST /graph-documents/publish` e `POST /graph-documents/apply-patch` aceitam
`expected_version` e `idempotency_key`.

- versão divergente retorna `409 GRAPH_VERSION_CONFLICT`;
- repetir uma chave concluída retorna o resultado anterior;
- falha de projeção não avança a versão publicada;
- rollback materializa o documento antigo e o publica como uma nova versão.

`POST /graph-documents/sync` reconcilia a versão atual sem criar versão.
`POST /graph-documents/reindex` é um alias temporário e depreciado.

## FAQ e Golden Dataset

O branch comercial é:

`Persona → Brand → Briefing? → Campaign → Audience → ProductGroup? → Product → Offer? → Copy? → FAQ → Embedded`

Copy e FAQ possuem exatamente um parent primário. FAQ gerada começa como
`pending_validation` e preserva fonte, `source_node_id`, `source_node_type` e
`branch_path`. FAQ pendente não pode ligar ao Embedded.

A aprovação é uma unidade operacional: valida branch/conteúdo, cria a conexão
FAQ → Embedded, snapshot e uma entrada/chunk RAG por pergunta. Falha em qualquer
etapa devolve o FAQ para validação. Editar ou desconectar retira a publicação
anterior.

Todo Golden Dataset ativo é visível aos agentes autorizados da mesma persona.
Não existe seleção por papel de agente e não existe fallback global.

## Assets

O branch de Asset é:

`Brand|Campaign|ProductGroup|Product → Asset → Gallery`

O primeiro vínculo é o parent comercial primário; `Asset → Gallery`, com
`gallery_asset`, é secundário. Aprovação exige storage/arquivo, persona, tipo
visual, parent válido, as duas edges e sidecar Markdown. Asset nunca cria RAG.

`rebind-path` é o contrato canônico. `connect` e `bind-slot` são aliases
temporários, depreciados e auditados.

## Sofia

Sofia Graph e Sofia Criar carregam o documento publicado completo, produzem um
patch e publicam pelo mesmo serviço canônico. Alterações destrutivas exigem
confirmação. Nodes são reutilizados por `persona_slug + node_type + slug`.

## Migração e segurança

Antes do rollout por persona:

1. fazer backup de `system_events`, tabelas de conhecimento, Assets e vault;
2. executar dry-run e comparar documento, projeções, Embedded, snapshots e RAG;
3. reparar documentos incompletos;
4. observar o fallback `kb_entries` por 2–4 semanas;
5. remover aliases apenas após zero referências e rollback comprovado.

Nenhuma tabela protegida ou migration histórica é removida por esta arquitetura.
