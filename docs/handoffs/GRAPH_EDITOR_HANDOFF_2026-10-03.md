# Graph editor (control-plane) — handoff 2026-10-03

Autor: Claude (Opus 5.5). Desenho completo: `akia/docs/architecture/engenharia-de-grafo.md`.
Branch `feat/graph-editor`, a partir de `feat/utzig-commercial-v15` (linhagem de produção).
**Não publicado.** Release do control-plane só com confirmação do usuário.

## O que entra

- `apps/control-plane/api/services/graph_editor.py`: reconstrói o bundle da publicação ativa
  (`document_json`; arestas sem `primary`), aplica operações da fase 1 (perguntas do SDR),
  normaliza `completion`/`booking` sem as perguntas desligadas, `plan` sem gravar, `publish`
  (base = ativa, checksums revisados, stage + activate, reativa a anterior se falhar, evento
  `graph_editor_published`) e `revert` (só para a anterior, evento `graph_editor_reverted`).
- `routes/graph_bundles.py`: `GET /graph-bundles/editor`, `POST /graph-bundles/editor/{plan,publish,revert}`.
  `plan` exige `edit`; `publish`/`revert` exigem `edit` e admin (fase 1).
- `tests/test_graph_editor.py`: ida e volta, contratos por âncora, aceite Utzig, normalização,
  recusas, publish (base velha 409, plano mudado 409, sucesso, clique duplo), falha de
  ativação reativa a anterior, revert, permissões.

## Evidência

- Viabilidade em produção (somente leitura, export via `akia-db`): Utzig v16 reconstruída
  compila no mesmo `runtime_checksum`, zero mudanças. Tock: zero mudanças de conteúdo, checksum
  muda só pelo compilador (v3.6.5 → v3.6.6), sinalizado em `compiler_upgrade`. Aurora:
  `bundle_node_status_conflict` (publicada pelo caminho antigo) → `editable=false`.
- Aceite Utzig em dry run: plano válido, 1 nó novo, 15 alterados; ficam ligadas só `servico`,
  `modelo_veiculo`, `nome_cliente` e `endereco_cliente`. `vehicle_color` não é campo declarado
  (o compilador recusa modo para ele).
- `pytest apps/control-plane/api/tests`: 232 passed.

## Para o Codex

1. Revisar isolamento: escopo por persona em todas as rotas, admin no publish/revert, e o lock
   por processo (blue/green serve um slot por vez).
2. Geradores `build_*.py`: base passa a ser a publicação ativa (exportar via `graph_editor.bundle_from_publication`),
   nunca o arquivo anterior.
3. O passo `plan` do `publish-graphbundle.yml` já usa o compilador do control-plane nesta linhagem
   (`api/scripts/compile_graph_bundle.py`); nada a fazer além de confirmar.
4. Após `stage`, `knowledge_nodes` já reflete o rascunho mesmo se a ativação falhar ou houver
   revert (comportamento igual ao do workflow); o SDR lê só `graph_publications`.
