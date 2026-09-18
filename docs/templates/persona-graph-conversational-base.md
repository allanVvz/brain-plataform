# Base de Persona e Grafo Conversacional

> Status: rascunho temporário. Este documento é a versão técnica de referência.

Use este documento para criar uma persona nova sem reaproveitar dados, textos,
produtos ou regras de outra persona. Preencha somente fatos que tenham fonte e
aprovação. Campos entre `<...>` são obrigatórios para a publicação.

## 1. Identidade e escopo

| Campo | Preenchimento |
| --- | --- |
| `persona_slug` | `<identificador-estavel>` |
| Nome público | `<nome-da-persona>` |
| Empresa ou marca principal | `<marca>` |
| Modelo de negócio | `<sales | appointment | support | outro-aprovado>` |
| Canais e idiomas | `<canais>` / `<idiomas>` |
| Objetivo da conversa | `<orientar, qualificar, agendar, vender, encaminhar>` |
| Limite de atuação | `<o-que-a-ia-pode-e-nao-pode-fazer>` |
| Responsável humano | `<equipe-ou-papel-responsavel>` |

Crie um node `persona` como raiz. Ele não recebe conexão de entrada e só tem
conexões de saída para o conhecimento pertencente à persona.

```yaml
node_type: persona
slug: <persona_slug>
title: <nome público>
status: validated
source: <fonte-aprovada>
metadata:
  business_model: <modelo>
  public_name: <nome público>
  languages: [<idioma>]
  handoff_policy: <resumo-da-politica>
```

## 2. Inventário obrigatório de nós

Toda informação usada pela conversa deve existir em um node e ter `source`,
`status`, `title`, `slug`, `persona_slug` e `metadata` quando aplicável.

| Node | Obrigatório quando | Deve conter |
| --- | --- | --- |
| `persona` | Sempre | Identidade, modelo, políticas e campos de qualificação. |
| `brand` | Há uma marca ou identidade comercial | Posicionamento, fonte e regras de uso de marca. |
| `audience` | Há perfis de público distintos | Necessidades, elegibilidade, linguagem e limites do perfil. |
| `campaign` | Há campanha, origem ou oferta temporal | Período, público, fonte, estado e relação com produtos. |
| `product` | Há produto, serviço, plano ou item consultável | Título, descrição aprovada, preço publicado se houver, fonte e público elegível. |
| `faq` | Há pergunta recorrente ou pergunta de qualificação | Pergunta, resposta aprovada, evidência e alvo semântico. |
| `copy` | Há mensagem ou argumento comercial aprovado | Público/canal, conteúdo, fonte e produto/campanha relacionado. |
| `rule` | Há limite operacional, comercial, legal ou de segurança | Regra objetiva, fonte, exceções e ação esperada. |
| `tone` | Sempre | Voz, estilo, limites de linguagem e exemplos aprovados. |
| `briefing` | Há contexto operacional que orienta a persona | Objetivo, prioridade, escopo e fonte. |
| `asset` | Há mídia reutilizável | Arquivo/URL, tipo, direitos, fonte e finalidade. |
| `gallery` | Há curadoria de assets | Destino final dos assets da persona. |
| `embed` | Há conteúdo aprovado para KB/RAG | Destino final do conteúdo indexável. |
| `tag` | É útil classificar e recuperar conhecimento | Rótulo neutro e escopo. |
| `entity` | Há entidade citada com identidade própria | Nome, tipo, fonte e relação com os demais fatos. |

`gallery` e `embed` são destinos finais: recebem conexões, mas não precisam
emitir conexões. Um asset enviado por cliente não entra no RAG e não recebe
função de campanha automaticamente.

## 3. Relações mínimas do grafo

Use relações explícitas; não esconda vínculos apenas no texto.

```text
persona ─belongs_to_persona→ brand
persona ─belongs_to_persona→ audience
persona ─belongs_to_persona→ rule
persona ─belongs_to_persona→ tone
persona ─contains→ briefing
campaign ─part_of_campaign→ persona
product ─belongs_to_persona→ persona
product ─visible_to_agent→ audience
faq ─answers_question→ product | audience | rule | briefing
copy ─supports_copy→ product | campaign | audience
asset ─uses_asset→ product | campaign | copy
asset ─gallery_asset→ gallery
conteúdo aprovado ─contains→ embed
```

Para cada edge, registre `source_node_id`, `target_node_id`,
`relation_type`, `confidence`, `weight` e `metadata`. Não conecte produtos,
FAQ ou públicos de outra persona.

## 4. Produtos, preços e disponibilidade

Crie um node `product` por item realmente distinto. Nunca crie produto,
variação, estoque, preço, desconto, kit, prazo ou URL por inferência.

```yaml
node_type: product
slug: <identificador-do-produto>
title: <nome-publico>
summary: <descricao-aprovada>
status: <validated | pending_validation>
source: <fonte-do-produto>
metadata:
  category: <categoria>
  published_prices:
    - amount: <numero>
      currency: <moeda>
      audience: <audience_slug>
      conditions: <condicoes-publicadas>
  availability_policy: <publicada | confirmar_com_equipe | nao_informar>
```

Preço só pode ser citado ou somado quando estiver publicado para o público e
ramo ativos. Estoque, frete, prazo e confirmação final continuam sujeitos à
política publicada ou ao atendimento humano.

## 5. Audiências e ramos de conversa

Crie um node `audience` para cada perfil que muda conteúdo, preço, regra,
produto elegível ou encaminhamento. Exemplos abstratos: `<consumidor-final>`,
`<cliente-recorrente>`, `<empresa>`, `<parceiro>`, `<regiao-atendida>`.

```yaml
node_type: audience
slug: <identificador-do-publico>
title: <nome-do-publico>
summary: <necessidades-e-criterios>
status: validated
source: <fonte-aprovada>
metadata:
  eligibility: <criterios-observaveis>
  allowed_product_scope: [<product_slug>]
  qualification_fields: [<campo>]
```

Uma escolha explícita de público substitui histórico incompatível. O contexto
de uma audiência nunca deve vazar para outra.

## 6. FAQ e conhecimento recuperável

Crie uma FAQ para cada dúvida frequente, regra crítica e pergunta de
qualificação. A resposta deve ser curta, verificável e ligada ao node que a
fundamenta.

```yaml
node_type: faq
slug: <pergunta-normalizada>
title: <pergunta-publica>
content:
  pergunta: <pergunta>
  resposta: <resposta-aprovada>
status: validated
source: <fonte-aprovada>
relations:
  - relation_type: answers_question
    target: <product | audience | rule | briefing>
```

Possíveis grupos de FAQ:

- apresentação, propósito e escopo da persona;
- catálogo, características e comparação de produtos;
- preço publicado e condições publicadas;
- atendimento, localização, canal e horários publicados;
- entrega, retirada, pagamento e troca, quando houver fonte;
- elegibilidade por público ou região;
- privacidade, consentimento e limites de atendimento;
- encaminhamento para equipe humana.

## 7. Política conversacional

Publique em nodes `tone` e `rule`, nunca como strings específicas no runtime.

### Tom

- Como a IA se apresenta e como chama a pessoa;
- estilo, tamanho de resposta e idioma;
- palavras ou promessas proibidas;
- como explicar incerteza, pedir esclarecimento e reconhecer uma resposta;
- exemplos genéricos de abertura, dúvida, comparação e encerramento.

### Regras

- fatos que exigem fonte publicada;
- fatos que exigem confirmação humana;
- política de preço, estoque, prazo, frete, agenda e pagamento;
- gatilhos de handoff e mensagem pública de anúncio do handoff;
- recuperação técnica: primeira falha pede reformulação; segunda falha cria
  handoff e pausa apenas a lead envolvida;
- isolamento de persona, audiência e produto;
- máximo de um outbound por inbound canônico.

## 8. Campos de qualificação e memória

Declare campos na `persona.data.qualification.fields`. Cada campo deve ter
proprietário, semântica, fonte e, se obrigatório, uma FAQ de pergunta aprovada
com `question_node_id`. Dependências indicam elegibilidade, não uma ordem fixa
de roteiro.

```yaml
qualification:
  fields:
    - key: <campo>
      label: <rotulo>
      required: <true | false>
      semantic_type: <tipo>
      source: <fonte>
      question_node_id: <faq-node-id-se-obrigatorio>
      depends_on: [<campo>]
```

Para interesse comercial, guarde somente referências estruturadas a produtos
do ramo ativo: `product_node_id`, intenção (`select`, `remove`, `resume` ou
`quoted`), quantidade opcional e evidência literal. Nunca salve preço,
estoque ou texto inventado como memória.

## 9. Fluxo conversacional reconstruível

O runtime reconstrói o fluxo a partir do grafo nesta ordem:

```text
inbound canônico
→ persona e binding autorizados
→ publicação ativa + audience/ramos elegíveis
→ contexto aprovado e memória estruturada
→ interpretação do modelo
→ proof de evidência, escopo e preços
→ fatos + decisão em commit atômico
→ no máximo um outbound ou handoff
```

O modelo explica e conversa naturalmente. O grafo define conhecimento,
limites, qualificação e evidência. O proof valida a resposta; ele não escolhe
uma FAQ ou transforma a conversa em formulário.

## 10. Checklist de publicação

- [ ] Persona raiz criada, com fonte e status aprovados.
- [ ] Toda marca, público, produto, campanha, FAQ, copy, regra e asset usado
      possui node e relação explícita.
- [ ] Cada produto tem fonte, escopo de público e preço somente se publicado.
- [ ] Cada FAQ aponta para seu fato/limite de origem.
- [ ] Nodes de tom e regra definem limites, handoff e recuperação técnica.
- [ ] Campos obrigatórios têm pergunta aprovada e dependências válidas.
- [ ] Conteúdo indexável chega ao `embed`; assets curados chegam ao `gallery`.
- [ ] Não há relação, preço, produto ou texto copiado de outra persona.
- [ ] O GraphBundle compila e valida antes de ativar via CAS.
- [ ] O fluxo é testado pelo WA Validator interno: inbound, proof, fatos,
      memória, commit e no máximo um outbound, sem WhatsApp real.
