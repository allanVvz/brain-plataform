# Runtime de conversa orientado pelo grafo

## Divida de dominio e resultado terminal

Tock Fatal vende produtos, nao servicos. Os identificadores `service_*`,
`service_slug` e equivalentes permanecem somente como compatibilidade legada.
A decomposicao futura deve publicar `offering` e `branch` no GraphBundle, sem
usar nomes legados para redefinir o dominio comercial e sem reconstruir
Product/Offer/Copy a cada inbound.

Todo inbound processado termina em uma resposta comprovada ou em handoff
observavel. Se o contexto inteiro nao for confiavel, o runtime registra a causa
nao secreta e aciona handoff ou pausa observavel. Silencio nao e resultado
valido de processamento.

## Limite de autoridade

O GraphBundle publicado e a autoridade para conhecimento, fatos comerciais e
limites. Produto, Offer, Copy e FAQ pertencem a publicacao compilada e nao sao
reconstruidos por turno. O modelo e dono de explicacao, recomendacao, linguagem,
fluxo natural e proxima pergunta; ele nao pode inventar fato ou limite.

Proof valida somente a evidencia publicada que a resposta cita e o isolamento de
persona/agente. Ele nao seleciona FAQ, nao forca `missing_fields[0]` e nao
substitui resposta valida do modelo. `missing_fields` e completude, nao roteiro.
CAS e exactly-once preservam um inbound canonico -> uma decisao -> um commit ->
no maximo um outbound, sem decidir o conteudo da conversa.

Pre-publicacao valida acumulacao top-down de FAQs de evidencia (caminho ativo
da Persona, fonte/status e escopo persona/agente). Tock Fatal usa GraphBundle;
Aurora continua no contrato legado isolado ate migracao explicita e auditavel.

O runtime de conversa usa o Graph JSON publicado como autoridade estrutural.
O modelo continua escolhendo como conversar; o backend apenas valida a
proposta antes do commit.

```text
inbound canônico
→ resolve ou mantém o galho ativo
→ recupera a closure do galho
→ monta cards com coordenadas do grafo
→ modelo propõe fatos, pergunta e resposta
→ proof checker valida a proposta
→ expande o pacote e tenta reparar uma vez, quando necessário
→ persiste ledger factual e enfileira um único outbound
```

## Coordenadas

Na projeção, cada entry e chunk recebe no `metadata`:

- `source_node_id` (ID estável do Graph JSON);
- `branch_anchor_node_id`;
- `path_node_ids` e `path_edge_ids` derivados das edges hierárquicas ativas;
- `graph_version`;
- `path_checksum`.

O UUID de `knowledge_nodes` continua disponível como `knowledge_node_id`. Os
links RAG registram as coordenadas de origem e destino. Nenhuma tabela nova é
canônica/editável: as tabelas `graph_*` são projeções compiladas e imutáveis da
publicação, enquanto `conversation_ledgers`, `conversation_facts` e
`conversation_turn_proofs` são o ledger factual e de auditoria do runtime.

## Contrato efetivo do galho

`graph_conversation_contract.compile_branch_contract` combina, em ordem:

- campos comuns declarados pela Persona;
- campos declarados em `qualification.fields` pelo node proprietário;
- `booking.required_fields` mantido como compatibilidade;
- campos condicionais aplicáveis ao galho;
- FAQ executável e dependências de cada campo.

Na publicação v3, perguntas já aprovadas em
`appointment_policy.field_questions` são materializadas como nodes FAQ com
`metadata.role=qualification_question`. A publicação é rejeitada quando um
campo exigido não possui pergunta válida.

## Ledger factual

O estado persistido registra somente fatos e proveniência:

```json
{
  "active_branch_node_id": "...",
  "active_path_checksum": "sha256:...",
  "facts": {
    "campo": {
      "status": "known",
      "value": "...",
      "source_message_id": "...",
      "owner_node_id": "..."
    }
  },
  "asked_question_node_ids": []
}
```

Os status aceitos são `known`, `unknown`, `declined`,
`needs_confirmation` e `invalid`. `unknown` só resolve um campo quando a
declaração correspondente usa `accepts_unknown=true`.

## Proof checker e reparo

O modelo retorna `ConversationProposal`. O checker comprova checksum, escopo
persona/agente dos nodes citados e evidência publicada para fatos e limites
comerciais. Ele preserva CAS e o limite de um inbound canônico -> uma decisão ->
um commit -> no máximo um outbound; não seleciona FAQ, não impõe a primeira
pergunta pendente e não reescreve uma resposta válida do modelo.

Erro de branch, fato ou pergunta nao autoriza proof a descartar ou reescrever a
reply do modelo. Proof valida evidencia e isolamento, registra o diagnostico e
orienta o proximo passo seguro. Quando nao houver contexto confiavel para uma
resposta comprovada, o proximo passo e handoff ou pausa observavel, nunca um
turno silencioso.

Uma citação válida que ficou fora do pacote dispara uma expansão do mesmo
galho e uma segunda chamada ao modelo. Se continuar sem prova, o runtime pede
clarificação neutra ou faz handoff seguro quando a política publicada autorizar;
falha de retrieval não cria fato comercial, FAQ selecionada por algoritmo ou
resposta substituta.

O template canônico é
`api/n8n-workflows/persona-conversation-template.json` (`graph_agentic_v3`) e
continua idêntico para todas as personas. Somente bindings técnicos são
substituídos no provisionamento.

## Recuperação técnica sem replay

`recover_uncommitted_graph_inbound` só reabre um inbound sem proof, commit ou
outbound. `recover_unsent_committed_outbound` só reabre o outbox com uma prova
válida e zero tentativa no provider. Se a resposta HTTP do n8n falhar depois
do commit, `reconcile_committed_graph_inbound` apenas reconcilia o status quando
há uma prova válida, um outbound único e a mensagem outbound persistida.
