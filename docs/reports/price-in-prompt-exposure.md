# Price data in the LLM prompt: exposure investigation

Date: 2026-09-11. Scope: factual, no recommendation. Live runtime is
`apps/conversation-runtime` (per `CLAUDE.md`); `apps/control-plane`'s copy of
`context_cards.py` diverges only in an unrelated GraphBundle-adapter section,
not in the code path described below.

## The exact code path

1. `services/context_cards.py:_rendered(node)` builds the text of a node's
   context card. For any non-FAQ node (`product`, `offer`, `service`, ...) it
   collects every `data`/`spec` key that is **not** in `NON_PROMPT_FIELDS`
   (`context_cards.py:48-60`) and not empty, and renders it verbatim under a
   `"Fatos estruturados:"` heading (`context_cards.py:161-175`), e.g.
   `- price: {"amount": 189.9, "currency": "BRL"}` or `- price cents: 18990`.
2. `NON_PROMPT_FIELDS` is an allowlist of trace/administrative keys
   (`status`, `tags`, `markdown_checksum`, `graph_id`, ...). It has no entry
   for `price`, `price_cents`, `offer`, or `price_qualifier`, so none of the
   five legacy price shapes (or the emerging canonical `offer: {amount,
   currency}`) are filtered out.
3. For Aurora specifically, `scripts/publish_aurora_graph.py:236-249`
   confirms the raw field is never stripped: when a product node has
   `data["price"]`, the publisher *adds* a `claims` entry
   (`claim_type: "price"`) pointing back at the same node, but leaves
   `data["price"]` itself in place. Both the raw field and the claim wrapper
   coexist on the node.
4. Context cards for retrieved/cited nodes are assembled into the prompt
   sent to the LLM (conversation_runtime's prompt-building step). The raw
   price value therefore reaches the model as plain text, for any persona,
   any time a product/offer/service node with a price field is retrieved as
   context — independent of that persona's `appointment_policy`.

## Which personas are affected

Structurally, all of them: `NON_PROMPT_FIELDS` is a single shared allowlist
with no persona branch. In practice this matters only for personas that
also declare `appointment_policy.price_disclosure == "human_only"` — today
that is Aurora. For every other persona, the graph's own policy is to let
the agent quote published prices, so seeing price data in the prompt is the
intended behavior, not an exposure.

## Is this exposure actually harmful, or does a downstream guard already hold?

There is a real downstream guard, and it is independent of the prompt:
`conversation_runtime.py` calls `_reply_states_a_price()` /
`graph_conversation_contract.reply_discloses_blocked_price()`
(`conversation_runtime.py:2144`, guard defined at
`graph_conversation_contract.py:756-766`) on the model's **output text**,
after generation and before the reply is sent. When the persona's policy is
`human_only` and the reply text matches a monetary-figure regex, the reply
is replaced with a human-handoff message and the route is forced to a
human — this happens regardless of whether the price leaked in through the
prompt or the model invented it. So this is not an unguarded hole: it is
defense-in-depth, where the second layer (output-side regex) is the one
actually load-bearing today, not the first layer (prompt hygiene).

That said, the output-side guard is a text regex and has a demonstrated gap
(see `apps/control-plane/api/tests/test_price_disclosure_guard.py::
test_bare_numeric_price_is_not_detected`): a reply that states a bare number
with neither a currency symbol/word (`R$`, `reais`) nor a recognized
lead-in phrase (`custa`, `fica em`, `a partir de`, ...) before it is **not**
detected. A model that saw `- price: {"amount": 189.9, "currency": "BRL"}`
in its prompt and echoed just `"189.9"` or `"189,90"` in isolation would
pass the guard undetected. This is speculative — no such transcript was
observed in this investigation — but it means the prompt-hygiene gap and the
regex gap are not fully independent: the first increases the chance the
model has a bare number available to say, and the second is the only thing
standing between that number and the customer.

## Direção adotada (decisão do operador, 2026-09-11)

**Endurecer o regex não é a solução.** A decisão é estrutural, não textual:

> O preço vive no grafo como **oferta** (`offer`), e **oferta não é recuperada
> pelo agente SDR**.

Um guarda de saída por regex tenta adivinhar, no texto gerado, se o modelo
disse um preço — e a lacuna documentada acima mostra por que essa abordagem é
frágil por natureza: toda forma não prevista de escrever um número passa. Se o
agente nunca recebe o valor, não há o que vazar, não há o que detectar, e a
garantia deixa de depender da cobertura de uma expressão regular.

### O que isso significa no código

O SDR hoje **recupera** nós `offer` ativamente, não por acidente:

- `apps/conversation-runtime/api/services/context_cards.py:25` — `offer` está
  entre os tipos recuperáveis.
- `:29` — peso de recuperação `"offer": 0.98`, atrás apenas de `faq` e
  `product` (1.0).
- `:402`, `:437-438`, `:441` — `offer` é incluída explicitamente na expansão
  por pedido de catálogo e na expansão a partir de sementes.

A mudança correta é excluir `offer` da recuperação quando a política da
persona é `price_disclosure == "human_only"`, em vez de filtrar campo no
prompt ou caçar número no texto de saída. O filtro de `NON_PROMPT_FIELDS`
passa a ser redundante para esse caso: se a oferta não é recuperada, o campo
de preço não chega ao card de contexto.

### Estado da implementação

**Não implementada nesta leva, deliberadamente.** A mudança vive em
`apps/conversation-runtime`, e aplicá-la exige um rollout que reinicia o
worker `runtime-conversation` — o que reiniciaria o agente da Tock Fatal. O
operador determinou não mexer no agente da Tock neste momento.

Até lá, o guarda de saída por regex (com a lacuna conhecida acima) permanece
como única camada ativa para personas `human_only`. Isso é risco residual
aceito e documentado, não um descuido.

### Consequência para o contrato canônico de preço

Isto reforça a escolha de `offer {amount, currency}` como slot canônico
(ver `packages/brain-contracts/brain_contracts/pricing.py`): quando o preço
tem um lugar único e nomeado no grafo, "não recuperar preço" vira uma regra
de uma linha sobre um tipo de nó. Enquanto o preço estava espalhado por cinco
formas (`price_cents`, `price.unit.amount`, `price.amount`, metadados de nó
de oferta, texto livre), nenhuma exclusão estrutural era possível — e o regex
de saída era, de fato, a única opção disponível. O contrato canônico é o que
torna a abordagem estrutural viável.
