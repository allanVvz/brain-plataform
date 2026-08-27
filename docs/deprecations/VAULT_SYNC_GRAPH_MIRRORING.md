# Espelhamento de grafo do vault_sync — risco conhecido, correção adiada

`vault_sync.run_sync()` (`api/services/vault_sync.py:461`) chama
`knowledge_graph.bootstrap_from_item()` (`vault_sync.py:601`) para todo item
não colocado em quarentena, escrevendo em `knowledge_nodes`/`knowledge_edges`
— as mesmas tabelas que `graph_bundle_publisher.stage_bundle()`'s
`_preflight_source_scope` (`api/services/graph_bundle_publisher.py:22,104-107`)
exige que estejam totalmente descritas pelo `GraphBundle` publicado.

Nenhum dos dois arquivos verifica `runtime_version` da persona antes de
escrever. Rodar `POST /knowledge/import-vault` contra uma persona já em
`graph_agent_runtime_v3` (Tock Fatal, hoje) pode criar nodes "não
planejados" que travam a próxima publicação com
`source_graph_has_unplanned_nodes`, sem aviso algum até o `stage_bundle`
seguinte falhar.

O sync de vault é para a integração com Obsidian e é plano futuro do
projeto — a correção (gatear o espelhamento de grafo por
`graph_agent_runtime_v3.binding_uses_v3(...)`, mesmo padrão já usado em
`kb_intake_service._persona_uses_graph_bundle_pipeline`) fica adiada para
quando esse sync for revisitado, não para esta rodada.

Até lá: não rodar `import-vault` contra nenhuma persona no runtime v3.
