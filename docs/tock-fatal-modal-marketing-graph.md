---
title: Tock Fatal - Catalogo Modal - Marketing Graph
client: tock-fatal
type: briefing
status: draft_for_validation
source_urls:
  - https://tockfatal.com/
  - https://tockfatal.com/pages/catalogo-modal
  - https://tockfatal.com/products/kit-modal-1-1-peca-9-cores-disponiveis
  - https://tockfatal.com/products/kit-modal-2-urso-estampado
  - https://tockfatal.com/products.json
captured_at: 2026-05-02
---

# Tock Fatal - Raw MD de Conhecimento e Copys em Grafo

## 0. Escopo

Este raw MD organiza o conhecimento publico encontrado no site da Tock Fatal para alimentar a aba Capturar, a KB e a camada `knowledge_rag_*`.

Persona: `tock-fatal`

Fonte principal: `https://tockfatal.com/pages/catalogo-modal`

Observacao de seguranca: o site publico confirma produtos Modal e kits de revenda. "Tricots" e "cropped de modal" foram solicitados como subfamilias, mas nao aparecem como produtos confirmados nas paginas publicas analisadas. Eles ficam abaixo como `pending_validation`, nao como verdade ativa.

## 1. Brand Node

```yaml
node_type: brand
slug: tock-fatal
title: Tock Fatal Atacado
semantic_level: 20
status: pending_validation
tags:
  - moda-feminina
  - atacado
  - revenda
  - inverno
summary: Marca de moda feminina com foco publico em atacado/revenda, kits de Modal e venda de pecas com alta saida no inverno e meia-estacao.
source_facts:
  - A home usa o posicionamento "Venda mais no inverno".
  - A home descreve "Modais canelados com alta saida, margem pra revenda e pronta entrega".
  - O site se apresenta como "Tock Fatal Atacado".
```

### Copy Brand - Base

Tock Fatal e para quem compra pensando em vender. Pecas de modal com modelagem atual, cores faceis e kits pensados para giro rapido no inverno.

### Copy Brand - Curta

Moda de inverno com cara de venda: modal confortavel, kits inteligentes e pronta entrega para revenda.

### Copy Brand - WhatsApp

Oi! A Tock Fatal trabalha com kits de modal para revenda, com pecas de alta saida no inverno e meia-estacao. Temos opcoes por unidade, kit com 5 pecas e kit com 10 pecas.

## 2. Campaign Nodes

### Campaign: Colecao Modais de Inverno

```yaml
node_type: campaign
slug: colecao-modais-de-inverno
title: Colecao Modais de Inverno
semantic_level: 30
status: pending_validation
tags:
  - inverno
  - modal
  - revenda
summary: Campanha publica da home focada em modais canelados para inverno, margem para revenda e pronta entrega.
relations:
  - belongs_to_persona -> tock-fatal
  - contains -> kit-modal-1-9-cores
  - contains -> kit-modal-2-urso-estampado
```

Copy campanha:

Venda mais no inverno com modais que ja chegam prontos para girar: tecido macio, modelagem ajustada e cores faceis de combinar.

### Campaign: Colecao Outono-Inverno

```yaml
node_type: campaign
slug: colecao-outono-inverno
title: Colecao Outono-Inverno
semantic_level: 30
status: inferred_pending_validation
tags:
  - outono-inverno
  - meia-estacao
  - inverno
summary: Extensao conceitual da campanha, baseada no fato de que o Kit Modal 2 e descrito como produto de alta saida no inverno e meia-estacao.
relations:
  - same_topic_as -> colecao-modais-de-inverno
```

Copy campanha:

Do frio leve ao inverno: pecas de modal que funcionam na meia-estacao, entram facil no guarda-roupa e ajudam a revendedora a vender sem complicar.

## 3. Audience Subnodes

### Audience: Atacado / Revenda

```yaml
node_type: audience
slug: atacado-revenda
title: Atacado e Revenda
semantic_level: 55
status: pending_validation
tags:
  - atacado
  - revendedora
  - giro-rapido
source_facts:
  - O site usa "Atacado" no nome.
  - Os produtos oferecem Kit 5 pecas e Kit 10 pecas.
  - O Kit Modal 2 diz "ideal pra quem quer vender facil, rapido e com margem".
```

Copy atacado:

Para revender com seguranca: comece pelo kit com 5 pecas para testar giro ou va direto no kit com 10 pecas para melhorar o custo por peca.

### Audience: Varejo

```yaml
node_type: audience
slug: varejo
title: Varejo
semantic_level: 55
status: inferred_pending_validation
tags:
  - varejo
  - uso-diario
source_facts:
  - O Kit Modal 1 informa "alta aceitacao no varejo".
```

Copy varejo:

Blusa de modal para o dia a dia: confortavel, elastica, ajustada no corpo e facil de combinar com cores de inverno.

## 4. Product Nodes

### Product: Kit Modal 1 - 9 cores disponiveis

```yaml
node_type: product
slug: kit-modal-1-9-cores-disponiveis
title: Kit Modal 1 (9 cores disponiveis)
semantic_level: 40
status: pending_validation
product_type: Modal
url: https://tockfatal.com/products/kit-modal-1-1-peca-9-cores-disponiveis
price:
  unit:
    amount: 59.90
    currency: BRL
    display: R$ 59,90
  kit_5:
    amount: 249.00
    currency: BRL
    display: R$ 249,00
  kit_10:
    amount: 459.00
    currency: BRL
    display: R$ 459,00
colors:
  - vermelho
  - vinho
  - bege
  - nude
  - off white
  - verde claro
  - azul claro
  - azul marinho
  - preto
tags:
  - modal
  - blusa-canelada
  - inverno
  - varejo
  - revenda
source_facts:
  - Blusa canelada com modelagem ajustada e tecido macio.
  - Ideal para uso diario e alta saida na revenda.
  - Tecido confortavel e elastico.
  - Modelagem que valoriza o corpo.
  - Cores faceis de combinar.
  - Alta aceitacao no varejo.
relations:
  - belongs_to_persona -> tock-fatal
  - part_of_campaign -> colecao-modais-de-inverno
  - part_of_campaign -> colecao-outono-inverno
  - visible_to_agent -> atacado-revenda
  - visible_to_agent -> varejo
```

Copy produto - Atacado:

O Kit Modal 1 e a escolha segura para giro rapido: blusa canelada, tecido macio e 9 cores faceis de combinar para montar vitrine de inverno sem travar estoque.

Copy produto - Varejo:

Blusa canelada de modal com toque macio, elasticidade e modelagem ajustada. Uma peca facil de usar no dia a dia e de combinar com looks de inverno.

Copy social:

9 cores, uma peca que gira. O Modal 1 tem tecido confortavel, modelagem que valoriza e cores que entram facil no guarda-roupa.

Copy WhatsApp:

Temos o Kit Modal 1 em 9 cores: vermelho, vinho, bege, nude, off white, verde claro, azul claro, azul marinho e preto. A unidade sai por R$ 59,90, o kit com 5 pecas por R$ 249,00 e o kit com 10 pecas por R$ 459,00.

### Product: Kit Modal 2 - Urso Estampado

```yaml
node_type: product
slug: kit-modal-2-urso-estampado
title: Kit Modal 2 - Urso Estampado
semantic_level: 40
status: pending_validation
product_type: Modal
url: https://tockfatal.com/products/kit-modal-2-urso-estampado
price:
  unit:
    amount: 59.90
    currency: BRL
    display: R$ 59,90
  kit_5:
    amount: 249.00
    currency: BRL
    display: R$ 249,00
  kit_10:
    amount: 459.00
    currency: BRL
    display: R$ 459,00
tags:
  - modal
  - urso-estampado
  - inverno
  - meia-estacao
  - revenda
source_facts:
  - Peca com estampa de urso descrita como tendencia da estacao.
  - Mistura visual fashion com toque leve e moderno.
  - Caimento ajustado, confortavel e versatil.
  - Perfeito para looks do dia a dia e composicoes mais arrumadas.
  - Kit 5 pecas: ideal para teste e giro rapido.
  - Kit 10 pecas: melhor custo por peca e mais lucro.
  - Alta saida no inverno e meia-estacao.
relations:
  - belongs_to_persona -> tock-fatal
  - part_of_campaign -> colecao-modais-de-inverno
  - part_of_campaign -> colecao-outono-inverno
  - same_topic_as -> kit-modal-1-9-cores-disponiveis
  - visible_to_agent -> atacado-revenda
  - visible_to_agent -> varejo
```

Copy produto - Atacado:

O Kit Modal 2 traz estampa de urso, visual fashion e alto apelo de vitrine. Para testar giro, va no kit com 5 pecas; para melhorar margem, escolha o kit com 10 pecas.

Copy produto - Varejo:

Modal com estampa de urso, caimento ajustado e toque moderno. Versatil para o dia a dia, mas com presenca suficiente para uma composicao mais arrumada.

Copy social:

A estampa que chama atencao sem pesar no look. Modal com urso, conforto e caimento ajustado para vender no inverno e na meia-estacao.

Copy WhatsApp:

O Kit Modal 2 - Urso Estampado custa R$ 59,90 na unidade. Tambem tem kit com 5 pecas por R$ 249,00 e kit com 10 pecas por R$ 459,00, pensado para revenda com melhor giro e margem.

## 5. Pending Product Families

### Product Family: Blusas de Modais

```yaml
node_type: entity
slug: blusas-de-modais
title: Blusas de Modais
semantic_level: 10
status: inferred_pending_validation
reason: Familia derivada dos produtos Modal encontrados. Validar se deve virar categoria oficial.
relations:
  - contains -> kit-modal-1-9-cores-disponiveis
  - contains -> kit-modal-2-urso-estampado
```

Copy familia:

Blusas de modal para vender no frio: tecido macio, caimento ajustado e opcoes que funcionam tanto para uso diario quanto para looks mais produzidos.

### Product Family: Tricots

```yaml
node_type: product
slug: tricots
title: Tricots
semantic_level: 40
status: pending_source
reason: Solicitado pelo operador, mas nao confirmado nas paginas publicas analisadas.
```

Copy pendente:

Pendente de validacao. Nao usar em atendimento ate existir produto, preco, cores e URL confirmados.

### Product Family: Cropped de Modal

```yaml
node_type: product
slug: cropped-de-modal
title: Cropped de Modal
semantic_level: 40
status: pending_source
reason: Solicitado pelo operador, mas nao confirmado nas paginas publicas analisadas.
```

Copy pendente:

Pendente de validacao. Antes de publicar, confirmar se existe cropped, quais cores, preco, fotos e se pertence a colecao de inverno ou meia-estacao.

## 6. Color Nodes

```yaml
node_type: entity
slug: cores-kit-modal-1
title: Cores do Kit Modal 1
semantic_level: 10
status: pending_validation
colors:
  - vermelho
  - vinho
  - bege
  - nude
  - off white
  - verde claro
  - azul claro
  - azul marinho
  - preto
relations:
  - describes -> kit-modal-1-9-cores-disponiveis
```

Copy cores:

Do neutro ao ponto de cor: nude, off white, bege e preto para base de vitrine; vinho, vermelho e azul marinho para destaque; verde claro e azul claro para variar sem fugir do facil de combinar.

## 7. FAQ Nodes

### FAQ: Precos dos kits Modal

Pergunta: Quanto custa o Kit Modal?

Resposta: Os dois produtos Modal encontrados no site possuem unidade por R$ 59,90, kit com 5 pecas por R$ 249,00 e kit com 10 pecas por R$ 459,00.

Relações:
- answers_question -> kit-modal-1-9-cores-disponiveis
- answers_question -> kit-modal-2-urso-estampado

### FAQ: Quais cores tem o Kit Modal 1?

Pergunta: Quais cores tem o Kit Modal 1?

Resposta: O Kit Modal 1 aparece com 9 cores: vermelho, vinho, bege, nude, off white, verde claro, azul claro, azul marinho e preto.

Relações:
- answers_question -> kit-modal-1-9-cores-disponiveis
- about_product -> cores-kit-modal-1

### FAQ: Qual kit e melhor para revenda?

Pergunta: Qual kit e melhor para revenda?

Resposta: O kit com 5 pecas e indicado para teste e giro rapido. O kit com 10 pecas melhora o custo por peca e aumenta a margem potencial.

Relações:
- answers_question -> atacado-revenda
- answers_question -> kit-modal-2-urso-estampado

### FAQ: O Modal vende em qual estacao?

Pergunta: O Modal vende mais em qual estacao?

Resposta: O site posiciona a colecao para inverno e informa que o Kit Modal 2 tem alta saida no inverno e na meia-estacao.

Relações:
- answers_question -> colecao-modais-de-inverno
- answers_question -> colecao-outono-inverno

## 8. Rule Nodes

```yaml
node_type: rule
slug: regra-nao-inventar-produtos-tock
title: Nao inventar produtos Tock Fatal
semantic_level: 65
status: pending_validation
content: So responder sobre produtos, precos, cores e URLs confirmados em fonte ou upload validado. Tricots e cropped de modal estao pendentes ate haver fonte confirmada.
```

```yaml
node_type: rule
slug: regra-atacado-varejo-modal
title: Separar copy de atacado e varejo
semantic_level: 65
status: pending_validation
content: Para produtos Modal, gerar uma versao de copy para revenda/atacado e outra para consumo/varejo quando o contexto pedir marketing.
```

## 9. Copy Pack Hierarquizado

### Nivel Brand

Tock Fatal Atacado: moda de inverno feita para girar. Modais com tecido macio, modelagem atual e kits pensados para quem quer vender com margem.

### Nivel Campanha

Colecao Modais de Inverno: pecas versateis, cores faceis e alta saida para montar vitrine de frio com investimento controlado.

### Nivel Atacado

Para revendedoras: comece com kit de 5 pecas para testar giro ou escolha kit com 10 pecas para melhorar custo por peca e margem.

### Nivel Varejo

Para o cliente final: modal confortavel, ajustado no corpo e facil de combinar para o dia a dia ou para uma producao mais arrumada.

### Nivel Produto - Modal 1

Kit Modal 1: blusa canelada, tecido macio e 9 cores versateis. Uma peca de base para vender todos os dias no inverno.

### Nivel Produto - Modal 2

Kit Modal 2 - Urso Estampado: estampa com apelo fashion, toque moderno e caimento confortavel para looks de inverno e meia-estacao.

### Nivel Cores

Monte grade inteligente: neutros para volume, cores escuras para inverno e tons claros para variar a vitrine sem perder combinacao.

### Nivel CTA

Atacado: "Me chama que eu te ajudo a escolher o melhor kit para seu giro."

Varejo: "Escolha sua cor e garanta uma peca confortavel para usar no frio."

## 10. Graph Links Propostos

```yaml
links:
  - source: colecao-modais-de-inverno
    relation: belongs_to_persona
    target: tock-fatal
  - source: colecao-outono-inverno
    relation: same_topic_as
    target: colecao-modais-de-inverno
  - source: kit-modal-1-9-cores-disponiveis
    relation: part_of_campaign
    target: colecao-modais-de-inverno
  - source: kit-modal-2-urso-estampado
    relation: part_of_campaign
    target: colecao-modais-de-inverno
  - source: kit-modal-1-9-cores-disponiveis
    relation: same_topic_as
    target: kit-modal-2-urso-estampado
  - source: cores-kit-modal-1
    relation: describes
    target: kit-modal-1-9-cores-disponiveis
  - source: atacado-revenda
    relation: visible_to_agent
    target: kit-modal-1-9-cores-disponiveis
  - source: atacado-revenda
    relation: visible_to_agent
    target: kit-modal-2-urso-estampado
  - source: varejo
    relation: visible_to_agent
    target: kit-modal-1-9-cores-disponiveis
  - source: varejo
    relation: visible_to_agent
    target: kit-modal-2-urso-estampado
  - source: faq-precos-kits-modal
    relation: answers_question
    target: kit-modal-1-9-cores-disponiveis
  - source: faq-precos-kits-modal
    relation: answers_question
    target: kit-modal-2-urso-estampado
```

## 11. Itens Pendentes Para Validacao Humana

- Confirmar se Tock Fatal quer tratar "Colecao Outono-Inverno" como campanha oficial ou apenas alias de "Colecao Modais de Inverno".
- Confirmar se "Blusas de Modais" vira categoria oficial.
- Enviar fonte/produto para "Tricots".
- Enviar fonte/produto para "Cropped de Modal".
- Confirmar politica de entrega/pronta entrega antes de usar em atendimento operacional.
- Confirmar se a copy pode usar linguagem de margem/lucro diretamente em ads.
