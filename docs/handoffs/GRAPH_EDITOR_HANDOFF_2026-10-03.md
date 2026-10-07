# Graph editor (control-plane) — handoff 2026-10-03

Autor: Claude (Opus 5.5). Desenho completo: `akia/docs/architecture/engenharia-de-grafo.md`
(seção "Revisão 2026-10-03 (tarde)" é o contrato vigente). Tipos: `akia/apps/portal-web/src/auth.ts`,
bloco "Graph editor — frozen contract". Branch `feat/graph-editor`, a partir de
`feat/utzig-commercial-v15` (linhagem de produção).
**Não publicado.** Release do control-plane só com confirmação do usuário.

## API (prefixo `/graph-bundles`)

| Rota | Quem | Resposta |
| --- | --- | --- |
| `GET /editor?persona_slug=` | `view` na persona | `{publication, previous_publication, editable, blocked_reasons, compiler_upgrade, persona_node_id, journey, knowledge}` |
| `POST /editor/save` | `edit` na persona **e** adm AKIA | `{version, publication_id, previous_publication_id}` |
| `POST /editor/revert` | `edit` na persona **e** adm AKIA | `{publication_id, version, reverted_from_publication_id}` |

`/editor/plan` e `/editor/publish` saíram (a tela não revisa mais; salva). O GET não devolve mais
`bundle`, `contracts` nem `persona_policy`.

### `POST /editor/save`

Pedido: `{persona_slug, base_publication_id, changes, idempotency_key}`.

1. Lock por persona; a mesma `idempotency_key` (por persona, memória do processo) devolve o mesmo resultado.
2. `base_publication_id` diferente da ativa → **409**.
3. A base precisa passar na ida e volta (sem erro e sem mudança de conteúdo), senão 422 `base_not_editable`.
4. `expand_changes` → `apply_operations` (+ `normalize_required_lists`) → `build_publication_plan`.
   Erro de validação → **422**.
5. Checksums calculados no servidor na mesma chamada: `stage_bundle` + `activate_staged_bundle`;
   confere o checksum ativo; se falhar, reativa a base (`activate_graph_publication_v3`) e responde 422
   `publication_failed`.
6. Evento `graph_editor_saved` com `actor`, `changes`, checksums e número de operações.

Erros do save sempre vêm como `{"detail": {"errors": [{"code", "message"}]}}`, mensagem em português
simples (409, 422 e 404). Códigos do compilador mapeados: `question_mode_field_not_declared`,
`field_question_empty`, `field_question_missing`, `field_validation_mode_missing`,
`ambiguous_field_declaration`, `field_dependency_missing`, `field_dependency_cycle`,
`inconsistent_field_owner`, `question_mode_invalid`, `field_owner_unreachable`, mais os do editor.
Código desconhecido: "O grafo recusou a alteração (<code>)." Uma mensagem por problema (o mesmo
erro repetido em vários caminhos aparece uma vez), com o rótulo da pergunta.

## `journey` e `knowledge`

`graph_editor.journey_view(document)` é o port de `graph-engineering/data/journey_reference.py`
(mesma saída nas publicações ativas de Utzig, Tock e Aurora). Lê só o documento compilado.

## `changes` → operações (`graph_editor.expand_changes`)

Cada mudança é expandida sobre o bundle já alterado pelas anteriores (compila sob demanda);
`set_question` com vários atributos vira uma mudança por atributo, nesta ordem: `active`,
`essential`, `tracking`, `text`.

| Mudança | Operações |
| --- | --- |
| `set_question {key, active:false}` | persona `conversation_policy.qualification.question_modes[key] = "disabled"` (outras chaves mantidas). Nada se já desligada (lê também `appointment_policy.question_modes`). |
| `set_question {key, active:true}` | remove a chave do mapa da qualificação; se `appointment_policy.question_modes` ainda a desliga, remove de lá também. |
| `set_question {key, essential}` | `required` em todas as declarações (`data.qualification.fields` / `data.fields`, qualquer nó). |
| `set_question {key, essential, branch_node_id}` | só as declarações em nós que pertencem a esse caminho e a nenhum outro (`branch_memberships`); se não houver, 422 `essential_branch_shared`. |
| (essencial com modo explícito) | se a chave tem `required`/`optional` explícito em `question_modes`, o modo é dobrado nas declarações e removido do mapa, para que o caminho escolhido seja a única diferença. |
| `set_question {key, tracking}` | `tracking: true|false` em todas as declarações. Campo comum com `tracking` passa para Classificação. |
| `set_question {key, text}` | `data.question` do(s) nó(s) de pergunta das declarações (`data.content.question` quando é ele que o compilador lê). |
| `add_question {stage, label, text, essential, tracking?, branch_node_ids?}` | chave = slug ASCII do rótulo, única entre campos declarados e ids `faq:qualification:*`; nó `faq:qualification:<key>`; aresta persona `contains`; campo `{required, priority, scope, owner_node_id, question_node_id, depends_on: [], accepted_statuses: ["known"], overwrite_policy: "explicit_correction", validation: {mode: "schema"}, value_schema: {type: "string", minLength: 1}, tracking}`; rótulo em `field_labels` da persona. Identificação/classificação: no nó persona, `scope: persona`, dono = persona (classificação com `tracking: true`). Serviço: em cada âncora de `branch_node_ids`, `scope: branch`, dono = a âncora; lista vazia → 422. `priority` = menor prioridade da etapa − 0,1 (ou metade, se ≤ 0,15). |
| `move_question {stage, key, direction}` | identificação/classificação: troca com o vizinho reaproveitando os valores de `priority` da etapa (espalhados se empatados) em todas as declarações da etapa; recompila e recusa (422 `move_not_honored`) se a jornada não sair na ordem pedida (ex.: nome sempre primeiro, campos na lista `appointment_policy.required_fields`). Serviço: 422 `move_service_order_fixed`. |
| `set_text {key: opening|closing, value}` | persona `conversation_policy.opening.first_turn` / `conversation_policy.post_qualification_support.transition`. |
| outro `type` | 422 `change_not_supported`. |

Lista de patches aceitos por `apply_operations`: listas de campos (`data.qualification.fields`,
`data.fields`), `completion`/`booking.required_fields`, `data.question`, `data.content.question`
(só em nós de pergunta) e, só na persona, os dois mapas `question_modes`, os dois `field_labels` e os
dois textos. Toda lista de campos editada exige `validation.mode` em `enum|schema|semantic` (mesma
resolução do compilador) e recusa mudança de `owner_node_id`/`scope` de campo existente
(`field_owner_change_refused`).

## Evidência

- `pytest apps/control-plane/api/tests`: **257 passed** (eram 232; `test_graph_editor.py` tem 40).
- Contrato: Utzig v17 compilada → `journey` idêntica a `tests/fixtures/editor-journey-utzig.json`
  (cópia do fixture do portal); `knowledge` igual em nós (sem texto) e índices.
- Tock: `tests/fixtures/editor-document-tock.json` é o documento ativo v38 recortado ao que a jornada
  lê (14 nós, sem valores em dinheiro); `journey` idêntica ao fixture do portal; seletor
  `purchase_profile`, nome primeiro, 2 caminhos.
- Aceite Utzig (dry run, nada gravado), no v17 do Git **e** na publicação ativa exportada de produção
  (v16, `sha256:681263e9…`, offline): desligar `condicao`, `estrada_de_chao`, `evaluation_route`,
  `foco_brilho_riscos`, `procedimento_anterior`, `revestimento_bancos`, `vazamento_oleo` + nova
  pergunta de identificação "endereço" (chave `endereco`, opcional) → plano válido, 1 nó novo,
  15 alterados, 11 caminhos afetados, 11 operações; ligadas só `servico`, `modelo_veiculo`,
  `nome_cliente`, `endereco`; identificação `nome_cliente, modelo_veiculo, endereco`; listas
  `completion`/`booking` só com `servico` e `modelo_veiculo`. Mesmo `runtime_checksum`
  (`sha256:c5979b39…`) nas duas bases. `breaking_contract_changes` lista
  `branch_contract_changed`/`branch_structure_changed` nos 11 caminhos (informativo; não bloqueia).
- Tock (dry run na exportação de produção): mover pergunta na identificação, nova pergunta de serviço
  em `audience:tock-retail`, `tracking`, texto de encerramento e essencial por caminho → plano válido;
  mover acima do nome → 422 legível.

## Limites conhecidos

- Desligar remove a chave das listas `completion`/`booking` (regra do contrato); religar não a
  devolve. A pergunta volta a ser feita e continua essencial, mas a posição explícita naquelas
  listas se perde (passa a valer `priority`).
- Com a pergunta desligada, `essential` aparece falso na jornada (o compilador zera `required`); o
  valor salvo nas declarações volta a valer ao religar.
- Save da Tock leva ~10–15 s (cada compilação ~1,4 s; o publisher recompila no stage e na ativação).

## Para o Codex

1. Revisar isolamento: escopo por persona em todas as rotas, admin no save/revert, e o lock e a
   idempotência por processo (blue/green serve um slot por vez).
2. Geradores `build_*.py`: base passa a ser a publicação ativa (exportar via
   `graph_editor.bundle_from_publication`), nunca o arquivo anterior.
3. O passo `plan` do `publish-graphbundle.yml` já usa o compilador do control-plane nesta linhagem
   (`api/scripts/compile_graph_bundle.py`); nada a fazer além de confirmar.
4. Após `stage`, `knowledge_nodes` já reflete o rascunho mesmo se a ativação falhar ou houver
   revert (comportamento igual ao do workflow); o SDR lê só `graph_publications`.
