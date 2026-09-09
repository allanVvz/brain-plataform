# GraphBundle: candidato de mídia a partir da publicação ativa

Este runbook prepara um candidato e um `PublicationPlan` local. Ele não acessa
o banco, não faz upload, não cria staging, não publica e não ativa conteúdo.

## Por que o export ativo é obrigatório

Um bundle histórico não é uma baseline confiável. Para a Tock Fatal, o bundle
v22 do repositório compila como `sha256:a39cf3ce…47b920`, enquanto a publicação
ativa auditada é a v27, id `44701b61-b09b-4f5f-b218-c19dc973a551`, checksum
`sha256:172c7e53…199b3`.

O preparador exige um export autenticado no formato abaixo:

```json
{
  "publication": {
    "id": "<publication-uuid>",
    "persona_id": "<persona-uuid>",
    "version": 27,
    "checksum": "sha256:<checksum>",
    "status": "active"
  },
  "document_json": {
    "schema_version": "3.0",
    "compiler_version": "graph-compiler-v3.6.4",
    "checksum": "sha256:<mesmo-checksum>"
  }
}
```

`document_json` deve ser o documento compilado integral. Um documento avulso,
um payload de `/api/menu` ou um bundle antigo falha fechado.

## Gate de round-trip e CAS

Primeiro execute sem overlay. Os diffs de nodes e edges precisam estar vazios,
e o checksum recompilado precisa ser idêntico ao ativo:

```powershell
python api/scripts/prepare_graph_bundle_candidate.py `
  .codex-run/tock-active-publication-v27.json `
  --expected-publication-id 44701b61-b09b-4f5f-b218-c19dc973a551 `
  --expected-version 27 `
  --expected-runtime-checksum sha256:172c7e53efaf2ffe5b3035ac82cbe3f490615b6f8408a38045dee2a1b20199b3 `
  --candidate-output .codex-run/tock-v27-roundtrip.json `
  --plan-output .codex-run/tock-v27-roundtrip.PLAN.json
```

Se a publicação ativa mudar antes da preparação, qualquer um dos três valores
CAS diverge e a execução termina em `blocked`. Deve-se obter um novo export;
nunca se ajusta o checksum manualmente nem se substitui a base pelo v22.

## Overlay explícito de mídia

O overlay é uma operação declarativa sobre registros completos:

```json
{
  "overlay_version": "1.0",
  "base_publication": {
    "publication_id": "44701b61-b09b-4f5f-b218-c19dc973a551",
    "version": 27,
    "checksum": "sha256:172c7e53efaf2ffe5b3035ac82cbe3f490615b6f8408a38045dee2a1b20199b3"
  },
  "metadata": {
    "purpose": "tock_product_media_canonical_registry_correlation"
  },
  "upsert_nodes": [],
  "upsert_edges": [],
  "remove_edge_ids": [],
  "remove_node_ids": []
}
```

Cada imagem precisa existir primeiro em `assets`. O overlay referencia a mesma
identidade em um único node `asset:<assets.id>`, com:

- `projection_node_id` igual ao node de grafo já ligado ao registro;
- `data.asset_registry_id` igual a `assets.id`;
- SHA-256 do conteúdo em `data.media.sha256`;
- uma edge `product → asset` do tipo `uses_asset`, com o slot em metadata;
- uma edge `asset → gallery` do tipo `gallery_asset`.

Nodes sombra sem `asset_registry_id`, SHA repetido, UUID repetido ou mais de uma
edge equivalente são bloqueados. A remoção de um node também é recusada se o
overlay não listar antes todas as edges incidentes; não há cascata implícita.

Depois de montar o overlay com IDs retornados pelo banco:

```powershell
python api/scripts/prepare_graph_bundle_candidate.py `
  .codex-run/tock-active-publication-v27.json `
  --expected-publication-id 44701b61-b09b-4f5f-b218-c19dc973a551 `
  --expected-version 27 `
  --expected-runtime-checksum sha256:172c7e53efaf2ffe5b3035ac82cbe3f490615b6f8408a38045dee2a1b20199b3 `
  --overlay .codex-run/tock-product-media-v28.overlay.json `
  --media-manifest docs/sdr/tock-fatal/product-media/manifest.json `
  --candidate-output .codex-run/tock-product-media-v28.json `
  --plan-output .codex-run/tock-product-media-v28.PLAN.json
```

O manifesto valida que cada arquivo possui hash único, produto existente,
status `validated`, exatamente um asset canônico, uma `uses_asset` e uma
`gallery_asset`. Os cinco arquivos atuais, inclusive o Vestido drapeado, estão
validados no manifesto. Os binários são lidos da pasta-fonte do operador no
upload e não são versionados no repositório; após o upload, o banco e o objeto
content-addressed passam a ser a evidência operacional.

## Critérios de saída

- baseline recompilada com checksum idêntico e diff vazio;
- overlay CAS exatamente igual à publicação ativa exportada;
- `disposition=dry_run_complete` e `publication_allowed=false`;
- nenhum asset sem registro, nenhum hash/UUID duplicado;
- apenas alterações de mídia explicitamente presentes no overlay;
- `validation_errors=[]` no plano.

Mesmo com esses critérios atendidos, staging, publicação, ativação, deploy e
limpeza continuam fora deste comando e exigem autorizações próprias.
