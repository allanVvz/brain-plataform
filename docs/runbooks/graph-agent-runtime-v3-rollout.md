# Rollout e rollback do Graph Agent Runtime v3

Este runbook aplica o contrato executável em
`api/contracts/graph-agent-runtime-v3.md` e o procedimento de transporte em
`.agents/skills/brain-agent-e2e/SKILL.md`.

## Gate de publicação

1. Aplicar migrations com Docker Compose e confirmar 093–100 no ledger.
2. Compilar a persona a partir de `knowledge_nodes` e `knowledge_edges`.
3. Confirmar coordenadas, um contrato por branch e o manifesto exato de
   entries/chunks com embeddings 1536 completos.
4. Ativar a publicação por `activate_graph_publication_v3`.
5. Provisionar o workflow canônico ainda inativo.
6. Ativar `metadata.runtime_version=graph_agent_runtime_v3` somente no binding
   aprovado. Shadow nunca envia um segundo outbound.

## E2E de transporte

- Manter o agente/modelo do número de transporte pausado.
- Alternar Aurora e VZ Lupas pelo binding, IDs, telefones mascarados e tempo.
- Enviar uma vez e provar a mensagem persistida nos dois destinos.
- Exigir uma linha de proof e no máximo um outbound por inbound canônico.
- Interromper em caso de duplicidade, branch cruzado, claim não fundamentado ou
  confirmação indevida.

## Rollback

1. Pausar o binding e confirmar que não existe inbound `processing` nem outbox
   `pending_send` antes da troca.
2. Remover `runtime_version` do binding ou apontá-lo ao runtime anterior; nunca
   misturar decisões dos dois runtimes no mesmo inbound.
3. Reativar a publicação anterior com
   `python scripts/rollback_graph_runtime_v3.py <persona> <versão>`.
4. Fazer rollback dos containers pelo tag anterior registrado em
   `.deploy/previous-tag` e ressicronizar o mesmo template ainda inativo.
5. O schema 093–100 permanece retrocompatível; rollback de imagem não remove
   tabelas nem provas. Não desfazer migrations destrutivamente.

No rollout validado em 2026-08-05, a imagem ativa é
`graphrag-v3-20260805-final9`; a anterior registrada é
`graphrag-v3-20260805-final8`. A publicação anterior elegível da Aurora é v3,
ID `5561dbf0-98f2-41e0-a6ad-d3adcfc7422a`, checksum
`sha256:8c6b8953808aad0a02a2f203ca3ead8bed2dbf54df28893c0e247ad6f629ced5`.
O rollback é `python scripts/rollback_graph_runtime_v3.py aurora 3`; confirmar
novamente o histórico antes de executar em outro ambiente.

Toda execução deve preencher o relatório em
`docs/evaluation/graph-agent-runtime-v3-evidence.md` sem segredos.
