# Runtime de conversa orientado pelo grafo

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

O modelo retorna `ConversationProposal`. O checker comprova branch e checksum,
escopo dos nodes citados, ownership dos fatos, pergunta pendente, dependências,
conclusão, autorização de handoff e evidência de preço.

Uma citação válida que ficou fora do pacote dispara uma expansão do mesmo
galho e uma segunda chamada ao modelo. Se a segunda proposta ainda falhar, o
runtime usa exatamente a pergunta publicada do primeiro campo pendente e
registra `fallback_used`; falha de retrieval não cria handoff comercial.

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
