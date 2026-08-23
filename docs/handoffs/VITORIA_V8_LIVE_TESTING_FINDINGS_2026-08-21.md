# Vitória (Tock Fatal, v8) — achados de teste ao vivo, 2026-08-21

## Como o teste foi feito

Depois da ativação da v8 (fix de visibilidade de catálogo), rodei turnos de
conversa reais contra o pipeline de produção — não uma simulação: o webhook
real do n8n (`Brain — Tock Fatal — Conversação`, workflow `WDUxL74OUctQHWwG`,
rota `tock-fatal/conversation`), chamando o DeepSeek de verdade
(`deepseek-v4-flash`), passando pelo proof-checker real e terminando em
`/internal/conversations/commit` real.

Dois leads sintéticos, claramente marcados, foram usados — nenhum contato
real recebeu nada (telefones falsos, então o envio real pelo WhatsApp falha
silenciosamente no passo de envio, que é assíncrono):

- `leads.id=69`, nome `TESTE_BURRICE_QA`, telefone `5511900000001` — fluxo
  atacado/revenda.
- `leads.id=70`, nome `TESTE_BURRICE_QA_VAREJO`, telefone `5511900000002` —
  fluxo varejo/uso próprio.

Ambos podem ser identificados e removidos depois via
`delete from leads where id in (69,70);` (cascade cuida de `messages`,
`lead_buffer`, etc.) — deixei intactos para você poder inspecionar a
sessão real no painel antes de decidir.

**Limitação do harness usado**: como o webhook real `tock-fatal/conversation`
espera um "evento canônico" já pronto (persona, lead_ref, buffer_id,
correlation_id, channel_binding_id, message), e não o payload cru do
WhatsApp, eu simulei esse evento diretamente (inserindo a linha em
`lead_buffer` na mão) em vez de passar pelo gateway de entrada real. Por
isso a mensagem do CLIENTE não ficou salva em `messages` (só as respostas
da Vitória) — em produção isso é responsabilidade do gateway de entrada
real, que não foi acionado aqui. Isso não afeta a validade dos achados
abaixo, que vêm da resposta real do pipeline, não do harness.

## Achado crítico — seleção de ramo e confirmação de qualificação usam
casamento de frase quase literal, e descartam a proposta correta do modelo

Este é o achado mais importante da sessão: **o funil trava silenciosamente
sempre que o cliente responde com uma frase natural que não seja um dos
poucos alias literais cadastrados**, mesmo quando o modelo (DeepSeek)
entende perfeitamente a resposta.

### Caso 1 — seleção de ramo (varejo/uso próprio)

Lead 70, depois de ser perguntada "Você procura para uso próprio ou para
revender?", respondeu:

> "uso próprio mesmo"

O modelo propôs corretamente:
```
branch_action: select
branch_anchor_node_id: audience:tock-retail
branch_evidence_span: "uso próprio mesmo"
reply: "Perfeito, uso próprio! O que você está procurando para uso próprio?"
```

Mas o resolvedor determinístico de serviço/ramo
(`service_resolution`, `graph_agent_runtime_v3.py`) não achou nenhum
casamento (`status: "none"`, `matches: []`) — a frase "uso próprio mesmo"
não bate com o alias literal cadastrado para `audience:tock-retail` — e o
backend **descartou a proposta correta do modelo** e reemitiu a MESMA
pergunta de novo:

> "Você procura para uso próprio ou para revender?"

Se o cliente responder de novo com qualquer variação que não seja o alias
exato, o loop se repete indefinidamente. "revenda" (sozinha, sem variação)
funcionou no lead 69 porque bate literalmente com o alias cadastrado do
ramo atacado — mas isso é sorte de fraseado, não robustez.

### Caso 2 — confirmação final de qualificação

Lead 69, depois do resumo de qualificação, respondeu:

> "sim, tá correto"

O modelo propôs corretamente `qualification_complete: true`,
`handoff_requested: true`, reply = "Perfeito. Vou encaminhar seu interesse
para a equipe continuar o atendimento." (exatamente o
`completion_message` configurado na persona).

Mas o backend (`_is_explicit_confirmation` /
`_EXPLICIT_CONFIRMATIONS = {"sim", "isso", "isso mesmo", "correto", ...}`
— um conjunto fixo de ~11 frases, comparação exata após normalização) não
reconheceu "sim, tá correto" como confirmação explícita (3 tokens não
batem com nenhuma entrada de 1–2 tokens do conjunto). O resultado final
**ignorou a proposta certa do modelo** e reemitiu o resumo de qualificação
— dessa vez até SEM a pergunta de confirmação no final, um beco sem saída
real:

> "Registrei estas informações: tipo de compra: revenda; momento da
> revenda: já revende; quantidade que pretende avaliar: 50 vestidos em
> mousse."

`handoff_required` ficou `false` — o lead nunca seria passado para um
humano.

Confirmei a causa raiz mandando **exatamente** a palavra "sim" (sem nada
mais) logo depois: aí sim o backend reconheceu, disparou
`handoff_required: true`, `route: HUMAN`, e a resposta certa. Ou seja: o
modelo já está certo há duas mensagens — é o filtro determinístico que é
rígido demais e ignora o modelo mesmo quando ele acerta.

### Por que isso importa mais que qualquer outro achado

Essas duas checagens (seleção de ramo + confirmação final) são,
respectivamente, o PRIMEIRO passo e o ÚLTIMO passo do funil de todo lead,
nos dois ramos (varejo e atacado). Qualquer cliente real que fale de forma
natural — o que é a norma, não a exceção, em WhatsApp — tem chance real de
travar em loop no início ou de nunca ser passado para a equipe no fim,
mesmo que o modelo já tenha entendido tudo certo.

### Onde mexer

- `api/services/graph_agent_runtime_v3.py`:
  - `_EXPLICIT_CONFIRMATIONS` / `_is_explicit_confirmation` (linha ~3070) —
    trocar o casamento exato por algo tolerante a variação (ex.: checar se
    a frase normalizada CONTÉM um token de confirmação como "sim",
    "correto", "confirmo", em vez de exigir igualdade exata; ou usar a
    classificação do próprio modelo — `interaction_observation`/
    `qualification_complete`/`handoff_requested` — como sinal de
    confirmação quando o proof-checker não encontra evidência
    contraditória, em vez de descartá-la).
  - O `service_resolution`/matcher de `exact_catalog` usado para
    `branch_action` (mesma classe de problema, resolvedor diferente) —
    mesma recomendação: dar mais peso à proposta do modelo quando ela cita
    evidence_span real da mensagem do cliente e aponta para um
    `branch_anchor_node_id` válido, em vez de exigir alias literal
    cadastrado.
  - Isso é uma mudança de política de confiança (quanto confiar no modelo
    vs. exigir evidência literal), não um bug de uma linha — vale uma
    decisão deliberada de quanto relaxar, não só destravar tudo.

## Achado médio — pergunta direta de disponibilidade é absorvida como
valor de campo, sem nunca ser respondida

Lead 69 perguntou:

> "quero uns 50 vestidos em mousse pra começar, vocês tem?"

A resposta:

> "Registrei estas informações: tipo de compra: revenda; momento da
> revenda: já revende; quantidade que pretende avaliar: 50 vestidos em
> mousse. As informações estão corretas?"

O texto inteiro da mensagem virou o valor bruto do campo livre
`volume_interest`. A pergunta "vocês tem?" nunca foi respondida — nem com
uma confirmação de estoque (correto, política proíbe isso sem publicação),
nem com o texto de `doubt_handling.deferred_response` que EXISTE
exatamente para esse caso ("Ainda não tenho uma informação publicada e
validada sobre... estoque..."). Na prática o cliente pergunta uma coisa
direta e a Vitória simplesmente não reage a ela — só peguntando de novo o
campo. Não é alucinação nem vazamento de preço (o comportamento seguro
está preservado), mas é uma UX ruim: o cliente vai sentir que não foi
ouvido.

## Achado menor / baixa confiança — saudação não reconhecida quando vem
com conteúdo

Lead 70 abriu com "oi, boa tarde! queria um vestido pra usar numa festa" —
a resposta pulou direto para a pergunta de ramo, sem nenhum reconhecimento
da saudação, apesar de `intents.greeting.always_acknowledge: true` estar
configurado na persona. Há um comentário no próprio código
(`graph_agent_runtime_v3.py`, perto de `_is_bare_greeting`) que documenta
essa escolha como deliberada — saudação com "dúvida junto" deve ir direto
pro modelo, sem a saudação enlatada — então isso pode já ser intencional.
Cito aqui só para registro; não recomendo tratar como bug sem confirmar a
intenção original de `always_acknowledge`.

## Não é um bug de produção (harness, não pipeline) — mas revela uma
lacuna real de validação

Descobri, ao montar o evento canônico à mão, que **omitir
`external_message_id`** faz o pipeline quebrar de forma feia no meio do
`/commit`: `commit_graph_turn_and_outbox_v4` retorna 409 com
`postgres_code: P0001`, mensagem crua do Postgres "fact is missing
field_key, owner_node_id or source_message_id" — sem tradução, sem
contexto, direto do RPC. A causa: quando um fato é resolvido pelo
`service_resolution` (não pelo modelo), `source_message_id` vem de
`context.message_id` e, se ausente, vira string vazia `""`, que o RPC só
detecta como inválida na hora de gravar.

Isso não é alcançável pelo caminho real do WhatsApp (o Meta Cloud API
sempre manda um `wamid` real, então `external_message_id` nunca fica
vazio em produção) — confirmei reproduzindo o mesmo turno com
`external_message_id` preenchido e o erro sumiu. Mas ainda assim é uma
lacuna de validação real: se qualquer chamador interno (teste, futura
integração, replay) omitir esse campo, o erro que aparece é uma exceção
crua de Postgres no meio de uma transação, não uma mensagem clara. Vale
uma validação explícita mais cedo (em `ContextRequest`/`build_context`)
se algum fato for resolvido sem uma mensagem de origem — não é urgente.

## Resumo para priorização

| Achado | Severidade | Alcançável em produção real? |
|---|---|---|
| Seleção de ramo/confirmação ignora proposta certa do modelo por casamento de frase rígido | **Crítico** | Sim — qualquer fraseado natural fora dos ~11 alias fixos |
| Pergunta direta de disponibilidade vira valor de campo sem resposta | Médio | Sim |
| Saudação com conteúdo não reconhecida | Baixo / não confirmado como bug | Possivelmente intencional |
| P0001 no commit sem `external_message_id` | Não é bug de produção | Não (Meta sempre manda `wamid`) — mas vale validação melhor |
