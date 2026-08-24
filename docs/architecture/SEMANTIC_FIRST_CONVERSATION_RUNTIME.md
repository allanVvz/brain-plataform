# Runtime de conversa semantic-first

Substitui a camada de interpretação literal do runtime de conversa por uma
camada semântica. Documento de arquitetura da branch `agent/sofia-vitoria-audit`.

## Limite central

O GraphBundle publicado fornece conhecimento, fatos comerciais e limites
autorizados. Produto, Offer, Copy e FAQ sao compilados/publicados e recuperados
por escopo; nunca sao reconstruidos por turno. O modelo possui explicacao,
recomendacao, linguagem, fluxo natural da conversa e a proxima pergunta. Ele
nao pode inventar fato comercial ou limite ausente.

Proof valida somente a evidencia publicada citada e o isolamento de
persona/agente. Ele nao seleciona FAQ, nao forca `missing_fields[0]` e nao
substitui uma resposta valida do modelo. `missing_fields` e sinal de
completude/eligibilidade, nao roteiro. CAS, claim atomico e ledger preservam
um inbound canonico -> uma decisao -> um commit -> no maximo um outbound;
exactly-once previne duplicidade, nao torna o dialogo deterministico.

Antes de publicar, validar acumulacao top-down de FAQs: cada FAQ de evidencia
precisa de caminho hierarquico ativo da Persona, fonte/status validos e escopo
persona/agente intacto. Aurora continua em contrato legado isolado; Tock Fatal
usa GraphBundle. A migracao da divida Aurora para GraphBundle e explicita e
auditavel, nunca uma mistura de contratos no runtime.

## Divida de nomenclatura comercial

Tock Fatal vende produtos, nao servicos. Os nomes `service_*`, `service_slug`
e afins que ainda aparecem no runtime/contratos sao apenas compatibilidade
legada; eles nao devem redefinir o modelo comercial da Tock. Na decomposicao
futura, essa compatibilidade vira o vocabulario explicito de `offering` e
`branch`, publicado pelo GraphBundle, sem recriar catalogo ou copy por turno.

Um inbound processado tem resultado observavel: resposta com proof ou handoff
registrado/visivel. Quando o contexto inteiro nao puder ser confiado, o runtime
deve acionar handoff ou pausa observavel com diagnostico nao secreto; nunca
descartar o turno em silencio.

## Por que

A auditoria ao vivo de 2026-08-21
(`docs/handoffs/VITORIA_V8_LIVE_TESTING_FINDINGS_2026-08-21.md`) provou, em
produção, que o modelo interpretava corretamente e o backend descartava a
interpretação correta porque a frase não batia com uma lista fixa:

- `"uso próprio mesmo"` → o modelo propôs `select` do anchor de varejo; o
  resolvedor literal não achou alias e o backend repetiu a mesma pergunta.
- `"sim, tá correto"` → o modelo propôs `qualification_complete` +
  `handoff_requested`; `_EXPLICIT_CONFIRMATIONS` (conjunto fixo de ~11 frases,
  comparação exata) não reconheceu e o lead nunca foi para a equipe.
- `"vocês tem 50 vestidos em mousse?"` → a mensagem inteira virou valor bruto
  do campo `volume_interest` e a pergunta nunca foi respondida.

O primeiro e o último passo do funil, nos dois ramos, dependiam de acerto de
fraseado. Em WhatsApp, fraseado natural é a norma.

## Princípio

**Interpretar é do modelo. Provar é do backend.**

O backend não volta a interpretar linguagem com listas de frases. Ele só
verifica se o que o modelo afirmou está sustentado pela mensagem literal e
permitido pelo grafo publicado.

```
inbound
→ interpretação estruturada pelo modelo      (SemanticInterpretation)
→ validação determinística de segurança       (semantic_interpretation_validator)
→ reconciliação com estado e grafo
→ recuperação de conhecimento/FAQ
→ seleção da próxima ação
→ composição natural
→ proof
→ commit idempotente
→ no máximo um outbound
```

## O contrato

`api/schemas/conversation.py` :: `SemanticInterpretation`

Uma única decisão estruturada por inbound, cobrindo múltiplas intenções na
mesma mensagem:

| campo | papel |
|---|---|
| `intents[]` | um ou vários atos do cliente, cada um com `evidence_span` |
| `state_relation` | relação da mensagem com o estado atual |
| `answers_field_key` | qual campo pendente esta mensagem responde |
| `confirmation` | `state` + `target_ref` + correção parcial |
| `branch_selection` | público/serviço normalizado para um anchor do grafo |
| `facts[]` | fatos extraídos, com dono e evidência |
| `invalidated_facts[]` | fatos que esta mensagem torna falsos |
| `entities[]` | produto, quantidade, outros |
| `questions[]` | perguntas do cliente que o turno deve responder |
| `claims[]` | afirmações comerciais, sempre com nós de evidência |
| `recommended_next_action` | ação seguinte recomendada |

### Sem confiança numérica

Não existe campo `confidence` no contrato novo. Um score não é uma
explicação: a decisão precisa ser explicável pelo texto e pelo estado. Todo
elemento carrega `evidence_span` — o trecho literal da mensagem do cliente que
o sustenta — e o backend reconfere esse trecho contra a mensagem.

### Confirmação é ligada a um alvo, não a palavras positivas

`confirmation.target_ref` tem que casar com `context.pending_confirmation_ref`,
publicado pelo turno anterior. Isso resolve dois casos de uma vez:

- `"sim"` sem nada pendente não confirma nada arbitrário (`no_pending_confirmation`);
- confirmação de qualificação nunca é confundida com confirmação de preço,
  estoque, pedido ou agenda, porque são refs diferentes.

`state=partial` cobre `"sim, mas muda para revenda"`: confirma o alvo e
carrega `correction_field_key`/`correction_value`.

## A camada determinística

`api/services/semantic_interpretation_validator.py`

Não tem lista de frases, tabela de alias, regex sobre texto do cliente, nem
qualquer conhecimento do que a persona vende. Só verifica:

1. **evidência real** — todo `evidence_span` tem que ser substring literal da
   mensagem (insensível a caixa, acento e pontuação). Elemento sem evidência é
   descartado, nunca reescrito.
2. **existência no grafo** — anchor ∈ `branch_anchors`; `field_key` ∈ contrato;
   `owner_node_id` e `node_id` ∈ `node_by_id`.
3. **valor permitido** — campo com validação `enum` só aceita valor/alias
   declarado no próprio grafo.
4. **coerência com o pendente** — confirmação exige `pending_confirmation_ref`
   correspondente.
5. **ausência de contradição** — `confirmation` e `rejection` juntos invalidam
   o turno.
6. **proibição de invenção comercial** — `claim` sem nó publicado de evidência
   é descartada.
7. **handoff permitido** — só quando o grafo autoriza.
8. **isolamento de persona** — id de nó de outra persona simplesmente não está
   em `node_by_id`, então não pode ser citado.

Descartar um elemento nunca o reinterpreta com outro sentido. Ou ele sobrevive
com o sentido que o modelo deu, ou sai — e aí `needs_clarification()` manda o
turno fazer **uma** pergunta curta, em vez de repetir mecanicamente a pergunta
anterior (o modo de falha do matcher literal).

## Compatibilidade com a skill de E2E

Esta arquitetura segue o contrato atual de E2E: GraphBundle fornece fatos e
limites publicados; o modelo explica, recomenda e conduz a conversa com a
próxima pergunta natural; proof valida citações e isolamento. `missing_fields`
não determina a fala, e nenhuma camada pode substituir uma resposta válida do
modelo por FAQ ou pergunta determinística.

## Regra anti-hardcoded

Nenhum nome de persona, produto, marca, público ou frase comercial entra em
`api/routes`, `api/services`, `api/core`, `api/workers` (AGENTS.md §26).
Catálogo, aliases e valores permitidos vêm do Graph JSON publicado. O validador
novo é, por construção, agnóstico de persona.
