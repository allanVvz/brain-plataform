# Sofia Tool — Adaptação de FAQs Comerciais Universais ao Grafo da Persona

> **Nome da tool:** `adaptar_faqs_universais_ao_grafo`
> **Implementação canônica:** `api/services/sofia_faq_tool.py`
> **Lei do grafo:** `agents/ai_brain_regras_negocio_grafo.md` (§11–§16)
>
> Este documento é a **spec autoritativa** da tool. O código em `sofia_faq_tool.py`
> deve espelhar exatamente o comportamento descrito aqui; qualquer divergência é bug.
> Toda FAQ gerada nasce `pending_validation` e **nunca** conecta ao Embedded
> automaticamente (§14/§16).

---

## 1. Objetivo

Transformar **perguntas comerciais universais** (compra, preço, prazo, garantia,
disponibilidade, variações, atendimento, objeções) em **FAQs adaptadas ao galho
ativo** de uma persona — usando o produto/marca/contexto reais que existem na
árvore do grafo.

A tool **nunca** inventa uma FAQ solta ou genérica:

- Toda sugestão é ancorada no **menor nó disponível** do galho (regra §11 da lei
  do grafo): `Copy > Product > Offer > Product Group > Campaign > Audience >
  Briefing > Brand`.
- Toda resposta carrega o contexto comercial real (marca, público, grupo, produto)
  extraído do caminho até a raiz.
- Linguagem de compra/frete/garantia só é liberada quando existe um **objeto
  vendável real** no galho (`product`, `offer`, `service`, `course`, `event`, ou
  um `product_group` que de fato tenha produtos).

## 2. Entrada

```text
target_node:   dict   # nó alvo selecionado no grafo (id, node_type, slug, data...)
nodes:         list   # todos os nós da persona (para resolver âncora e contexto)
edges:         list   # arestas (primárias/ativas) para subir/descer o galho
count:         int?   # quantidade de FAQs (default 5, clamp 1..20)
persona_slug:  str?   # escopo da persona
```

A tool é **pura** sobre dados de grafo já carregados (nós + arestas): é
unit-testável sem Supabase ao vivo. Persistência e superfície HTTP vivem na
camada de rota; este módulo só resolve contexto e produz sugestões.

### Detecção de intenção (`detect_faq_generation_intent`)

A partir de um comando em linguagem natural, mapeia para um intent e quantidade:

| Intent | Gatilho |
|---|---|
| `gerar_faqs_para_node` | "gere/crie faqs para este node" (sem número) |
| `gerar_n_faqs_para_node` | "gere **N** faqs/perguntas..." |
| `gerar_novamente_faqs_do_node` | "gerar novamente / de novo / regenerar" |
| `atualizar_faq` | "atualize / melhore / refaça / reescreva" a FAQ |

`count` é extraído de padrões como `"5 perguntas"`, `"3 faqs"`, e sempre passa por
`clamp_count` (default 5, máximo 20, mínimo 1).

## 3. Seleção da âncora (`select_faq_parent`)

Escolhe o nó mais específico para ancorar as FAQs (regra "FAQ no menor nó"):

- Alvo `product` / `offer` / `product_group` → ancora **em si mesmo**.
- Alvo `faq` → **sobe** para o pai não-FAQ (o produto/grupo a que pertence).
- Qualquer outro tipo → ancora em si mesmo (menor nó disponível).

Nunca retorna `None`: o galho ativo sempre tem ao menos o nó alvo.

## 4. Contexto do galho (`build_branch_context`)

Sobe da âncora até a raiz coletando, por tipo de nó:

- `brand`, `product`, `product_group`, `anchor_label`/`anchor_type`;
- `path` (lista ordenada persona→âncora com `node_type`, `label`, `markdown`);
- `markdown_by_type`, `nearest_markdown` e `branch_markdown` (blocos `## tipo: label`).

O markdown canônico de um nó vem de `metadata.markdown` (fallback: `body`,
`data.markdown`, `summary`, `content_preview`) via `node_markdown`.

`find_sellable_in_branch` procura um objeto vendável real — **ancestrais primeiro**,
depois descendentes. Um `product_group` só conta como vendável quando de fato tem
um `product` abaixo.

## 5. Classificação e templates (`classify_faq_target`)

A categoria do nó-âncora decide qual conjunto de templates é usado, garantindo que
uma Audience **nunca** seja tratada como produto comprável:

| Categoria | Tipos de nó | Conjunto de templates |
|---|---|---|
| `product` | product, service, course, event | `_COMMERCIAL_FAQ_TEMPLATES` |
| `offer` | offer | `_OFFER_TEMPLATES` |
| `product_group` | product_group | `_PRODUCT_GROUP_TEMPLATES` |
| `campaign` | campaign | `_CAMPAIGN_TEMPLATES` |
| `brand` | brand | `_BRAND_TEMPLATES` |
| `briefing` | briefing | `_BRIEFING_TEMPLATES` |
| `copy` | copy | `_copy_templates_for(markdown)` |
| `audience` | audience (sem vendável) | `_AUDIENCE_TEMPLATES` |
| `audience_object` | audience (com vendável) | `_AUDIENCE_OBJECT_TEMPLATES` |
| `discovery` | qualquer outro | `_DISCOVERY_TEMPLATES` |

Exceção: alvo `faq` cujo pai é `copy` e há vendável no galho → categoria `product`.

Os templates usam placeholders preenchidos a partir do contexto:
`{subject}`, `{product}`, `{brand}`, `{audience}`, `{descriptor}`, `{object}`,
`{context}`. Para Copy, `_copy_templates_for` extrai specs do corpo (ex.: `i5`,
`2TB`, `1080p`) e gera perguntas sobre o que a copy realmente diz.

## 6. Guardrails comerciais (`_violates_commercial_guardrail`)

Para nós **não-vendáveis** (`audience`, `brand`, `briefing`, `discovery`), remove
qualquer sugestão que contenha termos de compra/logística (`frete`, `acompanha
caixa/case`, `flanela`, `prazo de envio/entrega`, `parcelar`, `à vista`, `boleto`)
ou que mande "comprar/garantia/preço **do próprio nó**" (ex.: "Como comprar o
Técnicos?"). Isso impede FAQs comerciais incoerentes em camadas conceituais.

## 7. Saída

```json
{
  "parent_node_id": "...",
  "parent_node_type": "product",
  "parent_node_label": "Kit Modal 1",
  "count": 5,
  "category": "product",
  "commercial_object_type": "product",
  "commercial_object_name": "Kit Modal 1",
  "source_tool": "adaptar_faqs_universais_ao_grafo",
  "source_context": {
    "brand": "...", "product": "...", "product_group": "...",
    "category": "product",
    "path": [ ... ],
    "branch_markdown": "...",
    "persona_slug": "...",
    "generated_from_node_id": "...",
    "generated_from_node_slug": "..."
  },
  "suggestions": [
    { "question": "Como faço para comprar o Kit Modal 1 na <marca>?", "answer": "..." }
  ]
}
```

`source_context` carrega o `branch_path` e o markdown do galho, que a camada de
persistência usa para preencher os campos herdados obrigatórios da FAQ (§13):
`source_node_id`, `source_node_type`, `branch_path`, contexto das camadas acima.

## 8. Regras invioláveis (alinhadas a `ai_brain_regras_negocio_grafo.md` §16)

1. Receber um nó alvo e identificar o **menor nó válido** do galho.
2. Gerar a FAQ no menor nó disponível, considerando todo o contexto acima.
3. Criar **perguntas comerciais e acionáveis**, não institucionais.
4. Criar respostas objetivas, úteis e que conduzam ao próximo passo (atendimento,
   compra, orçamento, agendamento).
5. Toda FAQ nasce `pending_validation`.
6. **Não** aprovar FAQs automaticamente.
7. **Não** criar conexão com o Embedded antes da aprovação humana.
8. Nunca inventar produto, preço, cor, kit ou URL — só usar o que existe no galho.

## 9. Como a Sofia chama a tool

- **Sofia Criar** usa a geração de FAQ ao montar o galho (FAQ entra agrupada como
  documento markdown — uma FAQ-node pode conter várias perguntas, ver
  `markdown_document=true` / `question_count`).
- **Sofia Orquestrar** (`/knowledge/graph`) chama a tool a partir do nó
  selecionado no grafo, via comando de chat ("gere 5 perguntas para este produto"),
  e ancora as sugestões no menor nó do galho ativo.

Em ambos os casos, o resultado entra no `graph_json` canônico como nó(s) `faq` com
`status=pending_validation` e arestas `answers_question` partindo do nó-âncora —
e só vira RAG/Embedded depois de aprovado.
