# GraphBundle e PublicationPlan

Status: primeiro slice local/dry-run implementado em 2026-08-20. Não publica,
não persiste, não gera embeddings e não ativa runtime.

## Objetivo

Separar autoria de conteúdo, compilação e publicação:

```text
GraphBundle declarativo
  -> normalização determinística
  -> graph_compiler_v3.compile_graph (puro)
  -> PublicationPlan
  -> aprovação humana (gate; ainda não implementa publish)
```

O contrato vive em `api/services/graph_bundle.py`. Ele adapta nodes/edges do
bundle para o compilador v3 existente e devolve os campos de revisão exigidos
pelo roadmap: checksums de draft/runtime, versão seguinte, diff de nodes,
branches afetados, chunks reutilizados/a gerar, custo, breaking changes e erros.

O bundle declara `metadata.embedding_profile` (provider, modelo e dimensão). O
compilador usa esse perfil explícito no checksum em vez de ler a escolha do
ambiente, garantindo que o mesmo bundle produza o mesmo runtime checksum.
Nodes pendentes ou sem fonte bloqueiam o plano; eles nunca podem desaparecer
silenciosamente durante a compilação.

`estimated_embedding_cost.amount` permanece `null` enquanto preço/modelo não
estiverem configurados por uma fonte operacional aprovada. O plano não inventa
custo.

## Automação básica

Executar da raiz do repositório:

```powershell
python api/scripts/compile_graph_bundle.py data/graph_bundles/examples/basic-commercial-sdr.json
```

O exemplo é sintético, tem `publication_allowed=false`, retorna
`approval_scope=dry_run_only` e prova dois branches de
audiência. Não contém produto, oferta, preço, estoque, logística ou política
comercial. Ele não é seed da Tock Fatal.

A skill `.agents/skills/sofia-graph-publication-plan/` orienta Sofia a preparar
esse plano. O exemplo termina em `dry_run_complete`; somente um bundle com
fontes aprovadas e `publication_allowed=true` pode terminar em
`awaiting_approval`. Aprovação do plano não autoriza publish, deploy, migration,
ativação de IA ou transporte.

## Gates ainda abertos

1. O P0 Aurora continua aberto no roadmap até existir a evidência formal exigida
   pelo WA Validator interno. Este slice local não fecha P0.
2. Graph JSON v2.1 e `graph_publications` v3 ainda têm publishers separados.
3. O publisher v3 ainda recompila embeddings integralmente e ativa por default
   no caminho mutante legado.
4. Runtime e template n8n ainda contêm partes do contrato nomeadas como
   `servico`/`service_operations`.
5. O WA Validator de `business_model=sales` ainda produz evidência
   `technical_only`; falta driver semântico guiado pelo grafo.
6. Os arquivos locais `data/graph_documents/tock-fatal.v001.json` e `.v002.json`
   têm payload de outra persona e não podem ser usados como fonte.

## Readiness do motor

`conversation_mode` registra qual executor foi selecionado; não prova que ele
consegue atender. O GET de routing deve devolver também `readiness`:

```text
selected engine
  + binding ativo e não safety_paused
  + publicação GraphRAG v3 ativa
  + contrato conversation_v3/runtime v3
  + (n8n) credencial DeepSeek e workflow provisionado
  = operational_state=ready
```

Qualquer ausência produz `blocked_reasons` legíveis na UI. O determinístico
legacy (`conversation_v1`, sem runtime v3) fica explicitamente `blocked`, e não
“ativado”. O seletor existente é suficiente; criar outro motor apenas esconderia
o problema de prontidão.

## Bundle Tock para ensaio interno

`data/graph_bundles/tock-fatal/sdr-qualification-v1.json` é o primeiro bundle
nominal da Tock. Em 2026-08-20 o operador autorizou explicitamente deploy,
publicação/ativação e ensaio no WA Validator; o bundle passou a declarar
`publication_allowed=true`. Embed e Gallery produtivos foram incorporados ao
plano como terminais protegidos e desconectados.

O fluxo não declara produto, preço, estoque, prazo, política nem pedido mínimo.
Ele compila dois anchors de audiência:

```text
Tock Fatal
  -> Qualificação WhatsApp
     -> Uso próprio/varejo -> necessidade -> estilo
     -> Atacado/revenda    -> estágio da revenda -> interesse de volume
```

O campo `conversation_policy.branch_selection.field_key=purchase_profile`
seleciona o galho sem literal `servico`. O compiler aceita esse seletor genérico
e mantém a derivação por `appointment_policy` apenas como adapter legado da
Aurora.

O PublicationPlan aprovado contém 13 nodes, 10 edges, dois branches, 29 chunks
novos e zero breaking changes. O gate aprovado é:

```text
draft  : sha256:69efeb8fb5eef25512e901d1fd2fd1a05362a4bc97f24b94345e684c757cde50
runtime: sha256:453b5a52654d1dd01ff497d3fc56518404c0fd3f3d65cc8fccd72ec4211ebbef
```

`graph_bundle_publisher.stage_bundle` materializa nodes/edges canônicos,
recompila a partir das tabelas reais e recusa qualquer divergência do runtime
checksum. A ativação fica em `activate_staged_bundle`, exige novamente os dois
checksums e chama a RPC atômica existente. Nenhuma tabela nova foi criada.

## Ciclo WA Validator -> Sofia

Os roteiros semânticos sales são derivados dos fields e questions publicados,
com casos de varejo, revenda, troca de audiência e pergunta comercial sem
evidência. Um roteiro sem publicação v3 ativa é recusado; ele não cai em script
fixo de preço/quantidade.

Depois da execução, cada gap vira `sofia_review.proposals[]` com evidência,
persona, node types afetados e a próxima tool sugerida. As propostas são sempre
`pending_human_review`, `automatic_mutation=false` e
`publication_allowed=false`. Sofia pode preparar `graph.create_card_draft` e
`graph.validate_patch`; ela nunca transforma um erro do teste em fato comercial
nem publica automaticamente.

Um baseline passado por `--against` precisa ser um documento v3 íntegro, com
checksum válido e a mesma persona. Baseline de outra persona ou fixture alterada
bloqueia o plano.

## Roadmap incremental

| Fase | Entrega | Gate de saída |
| --- | --- | --- |
| 1 | GraphBundle puro + PublicationPlan + exemplo + skill | testes locais e zero mutação |
| 2 | Adapter Graph JSON v2.1 -> bundle/runtime v3 | checksum determinístico e validação canônica |
| 3 | Staging com embeddings incrementais | checksum aprovado igual ao staged |
| 4 | Ativação explícita separada | aprovação humana + RPC atômica |
| 5 | Driver semântico `sales` no WA Validator | varejo/atacado com technical e quality pass |
| 6 | Bundle Tock Fatal real | fontes comerciais aprovadas, sem fixture contaminada |
| 7 | Regressão Aurora e preparação de release | P0 fechado e exactly-once/proof preservados |

Nenhuma fase posterior está implicitamente autorizada por esta entrega.
