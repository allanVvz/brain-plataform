# Handoff — seleção inicial de galho falha com `field_owner_mismatch:servico`

Data de abertura: 2026-08-08 (extraído de
`docs/handoffs/AURORA_QUALIFICATION_REPEAT_QUESTION_HANDOFF_2026-08-08.md`, §9,
"Bug novo e distinto encontrado durante a validação" — separado porque não é
bloqueante e não tem relação causal com o bug de repetição de pergunta já
resolvido naquele handoff).

Escopo: `graph_agent_runtime_v3`, persona Aurora (`business_model: "appointment"`),
WA Validator, fluxo `sdr_qualificacao_carro`.

Status: **bug real, reproduzido 2 vezes, causa raiz não investigada.** Não
bloqueante (não causa silêncio nem repetição de pergunta), mas classifica
errado qual serviço o cliente quer.

## Sintoma

Em duas execuções do WA Validator (lead_ref 62 e 63, 2026-08-08), a seleção
inicial de galho falhou no proof-check com `field_owner_mismatch:servico` — o
modelo declarou `branch_anchor_node_id=aurora-product-interior` mas
`servico.owner_node_id=aurora-product-wash`, inconsistente — e a conversa
acabou presa em `aurora-product-bodywork` (chapeação), apesar do cliente ter
pedido "higienização interna" explicitamente na primeira mensagem.

Consequência observada: nenhuma pergunta repetida (esse mecanismo já foi
corrigido, ver o handoff original), mas a branch errada pode exigir campos
desnecessários (ex. `vehicle_color`, exigido só por `aurora-product-bodywork`)
ou conduzir a conversa comercialmente para o serviço errado.

## O que falta investigar

- Por que `servico.owner_node_id` aponta para `aurora-product-wash` quando o
  modelo propôs `aurora-product-interior` como âncora — é uma corrida entre a
  proposta do modelo e a resolução determinística do campo `servico`
  (`_normalize_servico_owner`, `graph_agent_runtime_v3.py`)?
- Reproduzir com instrumentação completa (mesmo padrão do handoff original,
  §4 passo 1 — capturar o `run_data` completo do n8n turno a turno) e
  confirmar se é específico do primeiro turno (antes de qualquer branch
  ativa) ou pode ocorrer em qualquer troca de galho.
- Escrever teste de regressão análogo a
  `test_persona_wide_field_duplicated_per_branch_is_wrongly_reasked_on_switch`
  antes de tocar em código de produção.

## O que NÃO foi feito

Nenhuma correção tentada. `pytest tests/` completo não foi re-rodado
especificamente para este bug (só para o bug de repetição de pergunta, já
resolvido).
