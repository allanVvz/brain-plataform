# Brain AI

## Documento comercial, posicionamento, estratégia e fonte de verdade

> **Status deste documento:** fonte de verdade comercial e de posicionamento
> **Última revisão:** 2026-07-27
> **Público:** time comercial, marketing, implantação, produto e parceiros de agência
> **Regra de leitura:** capacidades marcadas como **Hoje** existem no repositório ou possuem contrato/testes verificáveis. Capacidades marcadas como **Em expansão** estão parcialmente preparadas. Capacidades marcadas como **Roadmap** são visão de produto e não devem ser vendidas como prontas.

---

## 1. Resumo executivo

O **Brain AI** é uma plataforma de CRM, Knowledge Graph, RAG e automação inteligente criada para transformar a operação de marketing e vendas de uma empresa — ou de uma agência inteira — em um sistema coordenado por memória, regras, agentes e canais.

A plataforma não é apenas um chatbot, um gerador de legenda ou um painel de CRM. Ela funciona como o **cérebro operacional da comunicação**:

- entende a marca, seus produtos, públicos, campanhas, ofertas e regras;
- registra cada conhecimento com fonte, status, persona e relações semânticas;
- transforma esse conhecimento em contexto consultável para agentes;
- cria copies, anúncios, posts, sequências e estratégias;
- atende e qualifica leads no WhatsApp;
- encaminha conversas para SDR, closer ou humano;
- importa e organiza catálogos, FAQs, assets e campanhas;
- reconstrói a memória comercial em sites públicos, landing pages e catálogos;
- prepara a expansão para uma fábrica de conteúdo multicanal e para automações nativas de Instagram e Meta.

O cliente ideal inicial é a **agência de marketing**. A agência usa o Brain AI como uma camada operacional que pode ser replicada para vários clientes, personas, marcas, lojas, campanhas e verticais.

As verticais prioritárias para os clientes dessas agências são:

1. compra e venda de veículos;
2. aluguel de veículos;
3. estética automotiva;
4. varejo, especialmente operações com catálogo, ofertas recorrentes e grande volume de conteúdo.

### A frase que o comercial deve guardar

> **O Brain AI transforma a inteligência comercial de uma marca em um sistema vivo de conteúdo, atendimento, vendas e distribuição — com memória, regras, agentes e rastreabilidade.**

### O que o Brain AI não promete

O Brain AI não deve ser vendido como uma máquina que garante ROAS, substitui a estratégia da agência ou publica qualquer coisa sem aprovação. A proposta é mais forte e mais sustentável: **criar a infraestrutura de inteligência e automação que permite à agência operar mais clientes, com mais consistência e muito mais variações relevantes.**

---

## 2. A tese de mercado

As agências não sofrem apenas por falta de ideias. Elas sofrem porque precisam repetir, em escala, uma operação que mistura:

- descoberta do negócio do cliente;
- organização de produtos e ofertas;
- definição de públicos;
- planejamento de campanhas;
- produção de imagens, vídeos e textos;
- adaptação por canal e posicionamento;
- resposta a leads;
- follow-up;
- análise de resultado;
- manutenção da coerência da marca.

Quando essa operação vive em planilhas, conversas, pastas, prompts soltos e ferramentas desconectadas, cada novo cliente aumenta o caos. O Brain AI cria uma camada intermediária entre a estratégia da agência e a execução diária.

```text
estratégia da agência
        ↓
memória estruturada da marca
        ↓
regras + skills + agentes
        ↓
conteúdo + atendimento + landing pages + automações
        ↓
dados de operação e conversão
        ↓
aprendizado da próxima campanha
```

A oportunidade comercial não é vender “mais uma ferramenta de IA”. É vender **capacidade operacional multiplicada**:

> uma agência que antes precisava de várias pessoas e horas para pesquisar, escrever, adaptar, atender e atualizar pode passar a operar um sistema padronizado, supervisionado e reaproveitável.

---

## 3. O que é o software

### 3.1 Definição simples

O Brain AI é um **sistema operacional de marketing e vendas orientado por conhecimento**.

Ele recebe informações brutas — catálogo, site, briefing, arquivos, conversas, preços, FAQs, regras de negócio, campanhas e assets — e as transforma em uma rede de conhecimento que pode ser consultada e executada por agentes.

### 3.2 Definição técnica

A base atual combina:

- **CRM:** personas, leads, conversas, estágios, handoff e permissões;
- **Knowledge Graph:** nodes e edges para representar entidades e relações;
- **RAG/Knowledge Base:** entradas e chunks consultáveis pelos agentes;
- **Orquestração:** roteamento entre Brain, n8n, Meta, agentes e operadores;
- **Geração:** copywriting, anúncios, social content, e-mail, lead magnets e estratégia;
- **Assets:** upload, classificação, vínculo com produtos/campanhas e gallery;
- **Output público:** cardápios, landing pages e catálogos a partir da memória da persona;
- **Auditoria:** status, validação, logs, eventos, health checks e testes de contrato.

### 3.3 O diferencial estrutural

Em ferramentas comuns, o conteúdo costuma ficar isolado: o anúncio não conhece o produto, o chatbot não conhece a campanha, a landing page não conhece a oferta e o designer não conhece a regra comercial.

No Brain AI, cada item relevante deve responder:

| Pergunta | Exemplo de resposta |
|---|---|
| De quem é? | Persona Tock Fatal, cliente X ou agência Y |
| Que tipo é? | produto, campanha, público, copy, FAQ, asset ou regra |
| Qual é a fonte? | site, catálogo, briefing, upload, operador ou integração |
| Está validado? | pendente, validado, aprovado ou rejeitado |
| Qual node cria? | `product`, `campaign`, `audience`, `copy`, `faq`, `asset` |
| Quais edges cria? | `about_product`, `supports_copy`, `answers_question`, `uses_asset` |
| Entra na KB/RAG? | sim, quando for conhecimento textual aprovado |
| Pode alimentar agente? | conforme persona, público e papel autorizado |
| Pode virar site ou anúncio? | somente se tiver dados e aprovação suficientes |

Se uma informação não aparece no grafo, ela está incompleta como conhecimento operacional.

---

## 4. Como o Brain AI funciona

### 4.1 Fluxo de conhecimento

```text
fonte bruta
  ├─ briefing
  ├─ site ou catálogo
  ├─ upload de arquivo
  ├─ conversa com operador
  ├─ Meta Catalog
  └─ histórico de atendimento
        ↓
captura e classificação
        ↓
validação humana e regras de negócio
        ↓
knowledge_items / knowledge_rag_entries
        ↓
knowledge_nodes + knowledge_edges
        ↓
Embedded / RAG / contexto de chat
        ↓
Sofia, SDR, Closer, Maker, Classifier e futuros agentes
        ↓
WhatsApp, site, landing page, conteúdo e campanhas
```

### 4.2 Persona como unidade de isolamento

Cada cliente, marca ou operação é tratado como uma **persona**. A persona concentra:

- marca e posicionamento;
- produtos e coleções;
- campanhas e ofertas;
- públicos e segmentos;
- tom de voz;
- regras e restrições;
- assets;
- agentes e roteamento;
- canais e integrações;
- site público e CTA de WhatsApp.

Isso permite que uma agência opere múltiplas contas sem misturar preço, produto, linguagem ou histórico de um cliente com outro.

### 4.3 Grafo como mapa da operação

Uma estrutura típica é:

```text
Persona
  → Brand
    → Campaign
      → Briefing
        → Audience
          → Product Group
            → Product
              → Copy
                → FAQ
                  → Embedded / RAG

Brand | Campaign | Product Group | Product
  → Asset
    → Gallery
```

O grafo não é apenas uma visualização bonita. Ele permite recuperar o contexto correto, limitar o que cada agente pode usar, detectar lacunas e reconstruir outputs públicos.

---

## 5. O que já temos hoje

Esta seção é a referência para o comercial falar do produto atual.

### 5.1 Plataforma e operação

**Hoje — implementado na base do repositório:**

- dashboard em Next.js;
- API em FastAPI;
- banco Postgres compatível com pgvector;
- execução local-first com Docker Compose;
- storage local para arquivos e vault;
- autenticação e sessão por cookie HTTP-only;
- controle de acesso por usuário, papel e persona;
- ambiente self-hosted preparado para backend em VPS;
- observabilidade de saúde da API, storage, n8n e workers;
- proteção para não expor tokens e secrets no payload público.

O produto foi desenhado para ser auditável. A operação oficial passa por Docker Compose, e o dashboard deve conversar com a API pelo proxy `/api-brain`, sem apontar diretamente para backend legado.

### 5.2 Sofia e Criar

Sofia é a agente de inteligência marketing-comercial. **Criar** é o caminho de interface que permite conversar com Sofia para estruturar conhecimento.

Hoje, a experiência já contempla:

- captura orientada por conversa;
- definição de persona e tipo de conhecimento;
- planos estruturados antes de salvar;
- criação em massa de briefing, campanha, público, produto, copy e FAQ;
- validação das relações antes da persistência;
- edição de pequenos trechos do grafo pelo painel Sofia Graph;
- crawler usado como evidência bruta, sem tratar automaticamente toda extração como verdade;
- status de validação e origem para reduzir alucinação de produtos e preços.

O princípio comercial é importante: Sofia não deveria simplesmente “inventar uma campanha”. Ela deve perguntar, propor o que será criado, mostrar os nodes e edges e só então persistir.

### 5.3 Knowledge Graph e RAG

**Hoje — base operacional:**

- `knowledge_items` para entrada e fila de validação;
- `knowledge_nodes` para entidades canônicas do grafo;
- `knowledge_edges` para relações semânticas;
- `knowledge_rag_entries` e `knowledge_rag_chunks` para RAG;
- `kb_entries` como compatibilidade legacy e fallback;
- contexto de chat enriquecido por mensagens recentes, pergunta, nodes, edges e caminhos do grafo;
- fluxo de aprovação, promoção para KB e backfill do grafo;
- FAQ, copy, produto, campanha, asset, audience, brand, tone, rule e briefing como categorias de conhecimento;
- arestas como `belongs_to_persona`, `part_of_campaign`, `about_product`, `answers_question`, `supports_copy`, `uses_asset`, `briefed_by`, `visible_to_agent` e `gallery_asset`.

### 5.4 Atendimento e agentes

**Hoje — WhatsApp como canal operacional principal:**

- entrada de mensagens via Meta/n8n e `/process`;
- modo interno, no qual o Brain classifica e gera a resposta;
- modo delegado, no qual o n8n executa o workflow e o Brain mantém a memória e a persistência;
- persistência de leads e mensagens;
- roteamento por persona e `whatsapp_phone_number_id`;
- envio outbound por webhook n8n;
- assinatura HMAC de payload quando configurada;
- pausa da IA e handoff para humano;
- retorno do lead para o fluxo de IA;
- worker de dispatch e estados de outbox;
- validação direta e testes E2E por WhatsApp Web;
- análise de mensagens vazias, repetidas ou tecnicamente inválidas;
- papéis de SDR e Closer, com fallback inline quando um serviço externo não responde.

O n8n é tratado como **executor de automações**, não como fonte de verdade comercial. A memória, o histórico, o grafo, as regras e a auditoria permanecem no Brain.

### 5.5 Importação de catálogo e produtos

**Hoje — implementado ou preparado:**

- importação de produtos por CSV;
- importação e preview de catálogo;
- crawler de site como captura de evidência;
- integração user-managed com Meta Catalog para importar produtos;
- produtos importados iniciam como `pending_validation`;
- vínculo entre produto e asset;
- sugestões de imagens para produtos;
- collections e categorias;
- construção de FAQ e copy a partir de produtos aprovados.

O comercial não deve dizer que o crawler “entende o negócio sozinho”. A forma correta de explicar é: **o crawler acelera a captura; Sofia e o operador transformam a captura em conhecimento confiável.**

### 5.6 Geração de marketing e conteúdo

**Hoje — geração textual persona-aware:**

O módulo `/marketing/criacao` possui modos de geração para:

| Modo | Aplicação |
|---|---|
| Copy de produto | benefício, dor, prova, urgência, preço/valor e CTA |
| E-mail frio | outreach personalizado para leads ou empresas |
| Sequência de e-mail | nurture, onboarding, winback e recuperação |
| Anúncio | variantes para Meta, Google e TikTok |
| Lead magnet | checklist, e-book, template, calculadora e mini-curso |
| Posts de social | feed, Stories, LinkedIn e captions de TikTok |
| Estratégia de conteúdo | pilares, calendário, objetivo e métricas |
| Psicologia de marketing | prova social, escassez, ancoragem, autoridade e reciprocidade |

O gerador recebe contexto da persona — marca, tom, regras e produtos — e retorna Markdown. O design atual também possui uma área de criação/edição de criativos, mas a fábrica completa de assets multiformato e publicação em canais ainda está em expansão.

### 5.7 Assets e Gallery

**Hoje — fundação de gestão visual:**

- upload de assets;
- classificação por tipo visual;
- pipeline com módulos para renomeação, OCR, leitura de PDF, classificação e fallback de IA;
- vínculo de asset com brand, campaign, product group ou product;
- slots de landing page, como hero, capa de categoria, imagem de produto e logo;
- Gallery como destino de curadoria visual;
- validação de caminho, parent comercial e relações do grafo.

### 5.8 Sites, catálogos e landing pages

**Hoje — contrato de output público preparado:**

- endpoint público `/api/menu/{persona_slug}`;
- preservação de `persona.collections[]` para compatibilidade;
- objeto `site` com slug, nome, formato, coleção, rota e CTA;
- CTA de WhatsApp via `wa.me` com telefone público e mensagem configurável;
- registry de formatos com `cardapio`, `landing_page` e `catalogo_roupas`;
- reconstrução de memória pública a partir do grafo e das coleções.

Isso significa que a plataforma já tem a base para transformar conhecimento em output público. A camada de renderização final, evolução de templates, personalização por segmento, testes A/B e publicação automatizada de páginas são partes do roadmap de produto.

### 5.9 O que os testes e contratos demonstram

O repositório possui testes unitários, contratuais, de integração e E2E para validar, entre outros pontos:

- isolamento por persona;
- integridade da hierarquia do grafo;
- criação de produtos, FAQs e copies;
- persistência do RAG;
- fluxo WhatsApp;
- importação de catálogo;
- gestão de assets;
- output público;
- renderização do Graph JSON v2;
- marketing e criação de conteúdo;
- handoff e pausa de IA.

O teste é parte da proposta comercial: o objetivo é demonstrar que uma automação não apenas “responde”, mas mantém identidade, origem, contexto e comportamento verificável.

---

## 6. O que está em expansão ou ainda será implementado

Esta seção evita promessas indevidas.

### 6.1 Instagram nativo

**Status: Roadmap prioritário.**

A visão inclui agentes para Instagram, inbox, comentários, publicação, Stories, Reels, calendário editorial e reaproveitamento de conteúdo. No estado atual auditado, o núcleo operacional comprovado é WhatsApp, geração de marketing, grafo e output público. Não se deve vender uma automação nativa completa de Instagram como pronta sem a integração oficial, permissões, webhooks, publicação e validação correspondentes.

### 6.2 Onboarding completo de WhatsApp Business via Meta

O repositório já possui `whatsapp_phone_number_id`, roteamento, validações, integração e contratos. Ainda falta fechar o fluxo completo de onboarding a partir do número celular, incluindo resolução e persistência oficial de WABA, Business ID, catálogo, verificação do número e webhook Meta direto ou contrato formal de n8n como receptor único.

### 6.3 Publicação e operação de Meta Ads

O Brain gera briefing, copies, variações e hipóteses de público. Ainda não deve ser vendido como ferramenta que cria, publica, gerencia orçamento ou otimiza automaticamente campanhas no Ads Manager. A integração futura deve contemplar:

- conexão segura com contas de anúncio;
- criação assistida de campanhas;
- objetivos, orçamento, bid e placements;
- publicação com aprovação;
- nomenclatura e versionamento;
- leitura de métricas;
- associação entre criativo, público, oferta e resultado;
- desligamento seguro e limites de gasto.

### 6.4 Fábrica de criativos em massa

O gerador textual e a fundação de assets já existem. A fábrica completa ainda deve evoluir para:

- geração de imagens por templates e regras de marca;
- geração e adaptação de vídeo curto;
- criação de carrossel, feed, Stories, Reels e banners;
- variação automática de headline, hook, prova, oferta, CTA e formato;
- redimensionamento por placement;
- aprovação em lote;
- fila de produção;
- exportação ou publicação multicanal;
- controle de direitos, claims e elementos obrigatórios;
- feedback de performance por variação.

### 6.5 Landing pages geradas e publicadas automaticamente

Existe o contrato de output público e o registry de formatos. A expansão é transformar o grafo em páginas compostas, com:

- briefing para LP;
- estrutura de seções;
- hero, prova, benefícios, objeções, FAQ, oferta e CTA;
- versão por público ou campanha;
- SEO e dados estruturados;
- pixels e eventos configuráveis;
- preview, aprovação e publicação;
- rollback e histórico;
- testes de variação.

### 6.6 Analytics e aprendizado fechado

O próximo nível é conectar cada elemento — público, ângulo, copy, asset, placement, conversa e oferta — aos sinais de negócio:

```text
criativo → impressão → clique → lead → conversa → qualificação → venda
```

Isso permitirá que o Brain deixe de apenas produzir conteúdo e passe a recomendar o próximo conteúdo com base em evidência. Até essa integração existir, o comercial deve falar em **preparação para aprendizado** e não em otimização autônoma garantida.

---

## 7. Cliente ideal: agências de marketing

### 7.1 Por que a agência é o ICP principal

Uma empresa final compra automação para uma operação. Uma agência pode multiplicar o uso para dezenas de clientes. Isso cria um efeito de alavancagem:

```text
1 framework de implantação
→ várias personas
→ vários catálogos
→ várias campanhas
→ vários agentes
→ várias operações de atendimento
```

O Brain AI é especialmente valioso para agências que já têm demanda, mas enfrentam gargalos de produção, atendimento, padronização e escala.

### 7.2 Perfil de agência com maior aderência

Priorizar agências que:

- gerenciam tráfego pago e conteúdo para vários clientes;
- têm uma operação recorrente, não apenas projetos isolados;
- atendem negócios locais ou varejistas com ofertas frequentes;
- precisam responder muitos leads no WhatsApp;
- reutilizam estruturas de campanha, mas precisam personalizar a execução;
- têm designer, copywriter, gestor de tráfego e atendimento trabalhando de forma fragmentada;
- desejam aumentar capacidade sem contratar proporcionalmente;
- conseguem fornecer briefing, catálogo, regras e acesso oficial aos canais.

### 7.3 Perfil de baixa aderência

Ter cautela quando:

- o cliente não possui produto, oferta ou processo minimamente definido;
- a agência espera “apertar um botão” sem fornecer contexto;
- não existe responsável por aprovação;
- a empresa não tem acesso oficial aos canais Meta;
- não há disposição para validar preços, estoque, claims e regras;
- o comprador procura apenas um gerador barato de texto.

### 7.4 Verticais prioritárias para os clientes das agências

| Vertical | Problema recorrente | O Brain pode organizar | Exemplos de automação |
|---|---|---|---|
| Compra e venda de veículos | estoque muda, alto valor, leads desiguais | veículos, versões, condições, região, financiamento, objeções | qualificação, distribuição por vendedor, anúncios por modelo, follow-up |
| Aluguel de veículos | disponibilidade, datas, categoria, franquia | frota, tarifas, regras, localidades e períodos | pré-qualificação, cotação, FAQ, recuperação de lead |
| Estética automotiva | serviço local, confiança e recorrência | serviços, antes/depois, prova social, agenda e ticket | campanha por serviço, lembrete, upsell, reativação |
| Varejo | grande catálogo, promoções e sazonalidade | produtos, coleções, públicos, ofertas, assets e FAQs | catálogo, landing page, conteúdo diário, atendimento e recuperação |

### 7.5 Varejo como wedge estratégico

O varejo é a vertical com maior potencial de expansão porque combina:

- catálogo grande;
- necessidade de muitas imagens e variações;
- promoções recorrentes;
- diferentes públicos e ocasiões de compra;
- alta frequência de publicação;
- necessidade de responder rápido;
- conexão natural entre anúncio, catálogo, site, WhatsApp e venda.

O discurso para varejo é:

> **Não basta produzir uma peça bonita. É preciso transformar cada produto, público, oferta e objeção em uma família de comunicações que possa ser criada, aprovada, distribuída e medida.**

---

## 8. Posicionamento comercial

### 8.1 Pitch de 30 segundos

> O Brain AI é o cérebro operacional da agência. Ele organiza a memória de cada cliente — produtos, ofertas, públicos, regras e identidade — e usa essa memória para criar conteúdo, atender leads no WhatsApp, gerar catálogos e landing pages e coordenar agentes. Em vez de uma IA que responde sem contexto, a agência passa a ter uma estrutura replicável para operar marketing e vendas de várias marcas com consistência e rastreabilidade.

### 8.2 Pitch de 2 minutos

> Agências crescem até o ponto em que cada novo cliente exige mais pessoas, mais planilhas, mais briefing e mais retrabalho. O Brain AI resolve esse gargalo criando uma persona digital para cada cliente. A agência alimenta a marca com catálogo, produtos, regras, públicos, campanhas e assets. O sistema transforma isso em um grafo de conhecimento e usa agentes especializados para criar copies, anúncios, posts, sequências, FAQs, landing pages e atendimento.
>
> No WhatsApp, o Brain pode classificar o lead, consultar o contexto correto, responder, fazer handoff e registrar tudo. No marketing, ele gera famílias de variações que podem ser adaptadas por público e formato. No output público, a mesma memória pode alimentar catálogo, cardápio ou landing page. O resultado é uma operação mais rápida, mais consistente e preparada para escala — sem separar o que a agência sabe do que a execução faz.

### 8.3 Frases de valor

- “A agência não compra um chatbot; compra uma infraestrutura de operação.”
- “Cada cliente ganha um cérebro próprio, com memória isolada e regras próprias.”
- “O mesmo conhecimento aprovado pode alimentar conteúdo, atendimento, site e vendas.”
- “A IA produz mais quando recebe melhores regras, fontes e contexto.”
- “Escala não é repetir a mesma peça; é multiplicar variações relevantes sem perder a marca.”
- “O Brain transforma o briefing em uma rede executável.”

### 8.4 O que vender primeiro

O caminho comercial recomendado é começar por um problema mensurável:

1. atendimento de leads no WhatsApp;
2. organização de catálogo e FAQs;
3. produção recorrente de conteúdo;
4. landing page/catálogo público;
5. expansão para criativos, Instagram e Ads.

Não iniciar a conversa prometendo “automação total”. Iniciar mostrando uma operação concreta e evolutiva.

---

## 9. Estratégia de venda para agências

### 9.1 Diagnóstico antes da demonstração

O vendedor deve descobrir onde a agência perde margem:

- quantos clientes ativos existem;
- quantos canais cada cliente usa;
- quantos leads chegam por mês;
- quanto tempo leva para produzir uma campanha;
- quantas variações de criativo são entregues;
- quem responde WhatsApp e em quanto tempo;
- quantas FAQs e produtos ficam fora da base;
- quantas vezes o cliente precisa repetir o briefing;
- quais tarefas dependem de uma pessoa específica;
- quais dados são confiáveis e quais estão em planilhas divergentes.

### 9.2 Perguntas de descoberta obrigatórias

#### Negócio

- Qual produto ou serviço gera mais margem?
- Qual oferta está ativa agora?
- Em que regiões a empresa atende?
- O preço muda por estoque, data, localização ou negociação?
- O que nunca pode ser prometido?

#### Público

- Quem compra?
- Quem influencia a compra?
- Quais segmentos têm ticket e urgência diferentes?
- Quais públicos já foram testados?
- O que diferencia um lead curioso de um lead pronto?

#### Comunicação

- Qual é o tom da marca?
- Quais palavras a marca usa ou evita?
- Quais provas podem ser publicadas?
- Há fotos, vídeos, avaliações, depoimentos e antes/depois autorizados?
- Quais objeções aparecem no atendimento?

#### Operação comercial

- Quem recebe o lead depois da qualificação?
- Em que momento a IA deve parar?
- Qual é o SLA de resposta?
- Qual informação precisa ser coletada antes do handoff?
- Como o vendedor registra o resultado?

#### Tecnologia e acesso

- Existe Meta Business Manager?
- Existe conta de anúncio e página Instagram/Facebook?
- O WhatsApp é oficial?
- Há `phone_number_id`, WABA, Business ID e webhook configurados?
- O n8n já existe ou será implantado?
- Quem aprova conteúdo e alterações?

### 9.3 Demonstração recomendada

Uma demo de agência deve seguir o fluxo real:

```text
1. escolher uma persona
2. mostrar o grafo da marca
3. abrir produto, público e oferta
4. pedir a Sofia uma campanha estruturada
5. mostrar copy e variações de anúncio
6. mostrar como a FAQ alimenta o agente
7. simular lead no WhatsApp
8. demonstrar resposta, contexto e handoff
9. mostrar catálogo/landing output
10. explicar o próximo passo de integração
```

A demo deve terminar com um **piloto delimitado**, não com uma promessa abstrata.

### 9.4 Objeções e respostas

| Objeção | Resposta recomendada |
|---|---|
| “Já uso ChatGPT.” | O ChatGPT gera texto. O Brain organiza memória, permissões, relações, agentes, atendimento, auditoria e outputs por cliente. |
| “Já uso CRM.” | O CRM registra contatos e etapas. O Brain acrescenta a camada de conhecimento, conteúdo e decisão que alimenta os agentes. |
| “Minha equipe já faz isso.” | A plataforma não precisa substituir a equipe; ela reduz repetição e documenta o processo para a equipe operar mais contas. |
| “A IA vai inventar preço.” | O fluxo exige fonte, status e validação. Informação não confirmada deve permanecer pendente e não ser usada como fato ativo. |
| “Vocês já publicam no Instagram?” | A geração e preparação de conteúdo fazem parte da base atual; publicação e automação nativa completa de Instagram estão no roadmap de integração. |
| “Vai garantir resultado?” | Nenhuma plataforma controla sozinha mercado, oferta, orçamento e leilão. O Brain aumenta velocidade, consistência, cobertura de hipóteses e capacidade de aprendizado. |
| “Preciso dar todos os acessos?” | A implantação usa acessos e segredos mínimos, separados por integração. Tokens não devem aparecer no output público. |
| “É difícil configurar.” | A configuração inicial é o investimento que permite à IA operar com contexto, restrições e autonomia segura. |

---

## 10. Estratégia de marketing do Brain AI

### 10.1 Posicionamento de conteúdo

O marketing do Brain AI deve evitar a categoria saturada “IA que escreve posts”. Os pilares são:

1. **Escala operacional:** como uma agência pode atender mais clientes sem multiplicar o caos.
2. **Memória de marca:** como evitar que o conhecimento se perca em pastas e pessoas.
3. **Atendimento que vende:** como conectar contexto, qualificação, follow-up e handoff.
4. **Fábrica de criativos:** como transformar uma oferta em muitas variações relevantes.
5. **Varejo e catálogo:** como ligar produto, conteúdo, site e conversa.
6. **Governança de IA:** como trabalhar com fonte, validação, permissão e rastreabilidade.

### 10.2 Funil de aquisição

| Etapa | Mensagem | Oferta de marketing |
|---|---|---|
| Descoberta | “Sua agência está limitada pela produção?” | diagnóstico de maturidade operacional |
| Interesse | “Seu cliente tem conhecimento espalhado?” | mapa de memória e automação |
| Consideração | “Como uma persona vira agente, conteúdo e atendimento?” | workshop ou demo com caso real |
| Decisão | “Qual fluxo podemos implantar em 30 dias?” | piloto de uma vertical e um canal |
| Expansão | “Como replicar para toda a carteira?” | programa de parceiros/agências |

### 10.3 Conteúdos que devem ser produzidos

- antes/depois de um catálogo desorganizado;
- simulação de briefing → grafo → campanha;
- análise de uma conversa ruim de WhatsApp;
- matriz de criativos para um veículo, serviço ou produto de varejo;
- vídeo “o que a IA não pode inventar”;
- teardown de landing page;
- playbook de implantação para agências;
- calculadora de horas economizadas por cliente;
- série sobre Second Brain comercial;
- estudo de caso com métricas antes/depois.

### 10.4 Lead magnets para o ICP

- Checklist: “Os 47 dados que uma agência precisa coletar antes de automatizar um cliente”.
- Template: “Mapa de memória comercial da marca”.
- Planilha: “Matriz de criativos por público, ângulo e formato”.
- Diagnóstico: “Sua agência está pronta para uma operação agentic?”
- Workshop: “Do catálogo ao atendimento: construindo uma persona no Brain AI”.

---

## 11. Second Brain: o conceito aplicado ao Brain AI

### 11.1 O que é um Second Brain

O conceito de **Second Brain** popularizado por Tiago Forte descreve um sistema externo confiável para capturar, organizar, destilar e expressar conhecimento. A ideia é tirar a memória do lugar frágil — a cabeça de uma pessoa, uma conversa perdida ou uma pasta sem estrutura — e colocá-la em um sistema que permita recuperar e reutilizar o que importa.

No Brain AI, esse conceito deixa de ser apenas produtividade pessoal e vira **infraestrutura de memória empresarial**.

### 11.2 A tradução para empresas e agências

O Second Brain de uma marca deve saber:

- quem é a marca;
- para quem ela vende;
- quais produtos existem;
- quais produtos não existem;
- quais preços e condições estão válidos;
- qual campanha está ativa;
- qual oferta pertence a qual público;
- que tipo de linguagem usar;
- quais claims são proibidos;
- como responder objeções;
- quando chamar um humano;
- que asset acompanha cada produto;
- quais páginas e CTAs estão publicados.

O Brain AI transforma isso em memória estruturada, com relações e níveis de confiança.

### 11.3 CODE aplicado

O método CODE pode ser adaptado para a operação:

| CODE | No Brain AI |
|---|---|
| Capture | importar briefing, site, catálogo, arquivo, conversa ou observação |
| Organize | classificar por persona, node type, campanha, público e produto |
| Distill | resumir, separar fato de inferência e validar os pontos importantes |
| Express | gerar copy, FAQ, atendimento, criativo, site ou campanha |

### 11.4 PARA aplicado à agência

Uma adaptação prática:

- **Projects:** campanhas, lançamentos, promoções, feirões e datas sazonais;
- **Areas:** atendimento, conteúdo, tráfego, vendas, catálogo e pós-venda;
- **Resources:** pesquisas, referências, provas, templates, concorrentes e repertório;
- **Archives:** campanhas encerradas, preços antigos, assets substituídos e versões anteriores.

O grafo adiciona algo que uma pasta tradicional não oferece: as relações. Um produto pode estar ligado a uma campanha, um público, uma copy, uma FAQ, um asset e uma página ao mesmo tempo.

### 11.5 O Brain não é apenas uma vector database

Uma vector database encontra textos parecidos. Um Second Brain comercial precisa também:

- escopo por persona;
- status e aprovação;
- relações semânticas;
- regras de uso;
- origem e validade;
- permissões por agente;
- histórico e versionamento;
- possibilidade de executar o conhecimento em canais.

Essa diferença é central para a venda.

---

## 12. Skills e agentes

### 12.1 O que é uma skill

Uma **skill** é uma capacidade operacional documentada, versionada e repetível. Não é apenas um prompt bonito. É um conjunto de:

- objetivo;
- entradas necessárias;
- contexto permitido;
- regras de negócio;
- formato de saída;
- validações;
- condições de bloqueio;
- permissões;
- fallback;
- indicador de sucesso.

Uma skill transforma uma intenção genérica — “crie uma campanha” — em uma operação segura — “crie uma campanha para este produto, este público, esta região e esta oferta, usando apenas fatos validados e entregando 12 variações em formatos definidos”.

### 12.2 Skills corretas aumentam o valor da mesma plataforma

O Brain AI pode atender diferentes verticais porque a memória e as skills são configuráveis. A estrutura base permanece, enquanto as regras mudam:

```text
mesmo cérebro
  + skill de concessionária
  + skill de locadora
  + skill de estética automotiva
  + skill de varejo
  + skill da marca específica
```

### 12.3 Skills atuais ou já preparadas

- captura e classificação de conhecimento;
- criação de produto, campanha, público, copy e FAQ;
- crawler como evidência;
- copy de produto;
- anúncio e variações;
- posts sociais;
- estratégia de conteúdo;
- e-mail e lead magnet;
- classificação e validação de assets;
- SDR e Closer;
- contexto de conversa;
- handoff para humano;
- publicação de FAQ e Embedded;
- montagem de output público.

### 12.4 Skills planejadas

- skill de planejamento de calendário editorial;
- skill de geração de briefing visual;
- skill de fábrica de criativos;
- skill de adaptação por placement;
- skill de roteiro de Reels;
- skill de publicação Instagram;
- skill de resposta a comentários;
- skill de recuperação de carrinho e lead;
- skill de LP por público;
- skill de análise de campanha;
- skill de recomendação do próximo criativo;
- skill de auditoria de brand safety;
- skill de compliance por vertical;
- skill de governança para aprovação em lote.

### 12.5 Agentes do sistema

| Agente | Papel |
|---|---|
| Sofia | estratégia, captura, classificação, planejamento e manutenção da memória |
| SDR | primeira resposta, descoberta, qualificação e encaminhamento |
| Closer | condução de oportunidade, objeções, oferta e próximo passo |
| Classifier | classificação de mensagens, intenção e tipo de conhecimento |
| Maker | criação textual e futura criação visual/multiformato |
| Publisher | publicação em canais oficiais após aprovação |
| Analyst | leitura de resultados e recomendações |
| QA/Guardian | validação de fatos, regras, permissões e qualidade |
| Human operator | decisão, exceção, aprovação e relacionamento complexo |

O sistema não precisa começar com todos esses agentes. O valor aparece quando cada papel é bem delimitado e quando existe um protocolo claro de passagem entre eles.

---

## 13. Meta Andromeda, criativos e segmentação

### 13.1 O que é relevante para o comercial

A Meta descreve o Andromeda como um mecanismo proprietário de recuperação de anúncios dentro do sistema de recomendação. Em termos práticos, a plataforma precisa selecionar, em escala e com baixa latência, candidatos relevantes entre um volume enorme de anúncios.

A consequência para anunciantes é estratégica: **a vantagem não está somente em uma campanha e uma peça vencedora. Está em ter um portfólio de criativos relevantes, com diferenças reais de mensagem, público, contexto e formato.**

O [artigo técnico da Meta sobre o Andromeda](https://engineering.fb.com/2024/12/02/production-engineering/meta-andromeda-advantage-automation-next-gen-personalized-ads-retrieval-engine/) afirma que o crescimento de automação e de ferramentas generativas tende a aumentar significativamente a quantidade de criativos nos sistemas de recomendação.

As próprias páginas da Meta sobre [Advantage+ Creative](https://www.facebook.com/business/ads/meta-advantage-plus/creative) e [Advantage+ Audience](https://www.facebook.com/business/ads/meta-advantage-plus/audience) destacam a combinação entre variações criativas, sinais de audiência, automação e otimização por pessoa/posicionamento.

### 13.2 O que isso não significa

- não significa que mais peças aleatórias geram resultado;
- não significa que o Brain controla o algoritmo da Meta;
- não significa que segmentação manual desapareceu;
- não significa que qualquer imagem gerada deve ser publicada;
- não significa que a agência pode ignorar oferta, posicionamento e qualidade;
- não significa que existe garantia de ROAS.

O papel do Brain é aumentar a qualidade, a cobertura e a velocidade do portfólio de hipóteses.

### 13.3 A matriz de criativos

Um criativo pode variar por:

| Eixo | Exemplos |
|---|---|
| Objetivo | reconhecimento, consideração, lead, venda, reativação |
| Etapa do funil | descoberta, educação, prova, oferta, urgência, pós-venda |
| Público | primeiro carro, família, revendedor, gestor de frota, consumidor premium |
| Dor | preço, confiança, tempo, disponibilidade, manutenção, risco |
| Desejo | economia, status, praticidade, segurança, giro, conveniência |
| Ângulo | benefício, comparação, demonstração, prova social, autoridade |
| Oferta | desconto, parcela, diária, pacote, bônus, avaliação, agendamento |
| Formato | vídeo curto, imagem, carrossel, Stories, Reels, texto, LP |
| Placement | Feed, Reels, Stories, Messenger, Audience Network |
| CTA | chamar no WhatsApp, cotar, agendar, ver estoque, visitar loja |
| Região | cidade, bairro, raio, estado, área de atendimento |
| Prova | avaliação, antes/depois, estoque, depoimento, certificação |

Exemplo de dimensionamento — apenas para explicar o conceito, não como meta fixa:

```text
4 públicos × 5 ângulos × 4 formatos × 3 hooks = 240 combinações possíveis
```

Isso não quer dizer publicar 240 anúncios de uma vez. Quer dizer construir uma biblioteca de hipóteses, priorizar as melhores, testar com orçamento controlado e aprender com os sinais.

### 13.4 Segmentação: mais que idade e interesse

Para trabalhar com inteligência, a agência precisa descrever:

- contexto de compra;
- intenção;
- estágio do funil;
- produto de interesse;
- localização;
- capacidade e urgência;
- comportamento anterior;
- relacionamento com a marca;
- origem do lead;
- objeção dominante;
- histórico de atendimento;
- exclusões importantes.

O Brain organiza essas hipóteses em `audience` e em regras de campanha. A entrega efetiva, os controles disponíveis e a expansão automática de audiência dependem da configuração da Meta, da conta, do objetivo e das políticas vigentes.

### 13.5 Como o Brain se prepara para o Andromeda

O Brain deve ser a camada que:

1. mantém fatos e ofertas corretos;
2. transforma cada oferta em ângulos e mensagens;
3. associa cada mensagem a um público e a uma etapa;
4. gera variações por placement;
5. impede claims não validados;
6. registra qual versão foi aprovada;
7. conecta criativo à conversa e ao resultado;
8. recomenda novas hipóteses com base em dados.

---

## 14. Fábrica de conteúdo em massa com regras de negócio

### 14.1 O conceito

A fábrica de conteúdo não é uma fila de prompts. É um sistema de produção com entrada, regra, variação, aprovação e distribuição.

```text
oferta aprovada
  ↓
briefing de campanha
  ↓
matriz de públicos e ângulos
  ↓
skills de copy e visual
  ↓
variações por formato e canal
  ↓
QA de marca, fatos, direitos e política
  ↓
aprovação humana
  ↓
publicação ou exportação
  ↓
dados de desempenho
  ↓
próxima rodada
```

### 14.2 Regras obrigatórias

Toda skill de conteúdo deve respeitar:

- não inventar produto, preço, cor, estoque, prazo ou condição;
- separar fato confirmado de inferência;
- usar `pending_validation` quando houver incerteza;
- exigir fonte para claims comerciais;
- respeitar persona, tom e vocabulário;
- aplicar palavras proibidas e restrições legais;
- preservar preço e unidade de medida;
- respeitar região e área de atendimento;
- não usar depoimento sem autorização;
- não reutilizar asset sem direito ou vínculo aprovado;
- não publicar sem aprovação quando a política da persona exigir;
- permitir rollback e identificar a versão usada.

### 14.3 Exemplo: concessionária

Entrada:

- modelo, versão e ano;
- preço ou condição validada;
- quilometragem;
- localização;
- financiamento, se comprovado;
- fotos autorizadas;
- público de interesse;
- CTA para avaliação ou test-drive.

Saídas possíveis:

- anúncio de estoque;
- carrossel de benefícios;
- vídeo curto com roteiro;
- Stories com objeções;
- FAQ de financiamento;
- mensagem de WhatsApp;
- landing page do veículo;
- follow-up para lead que não respondeu.

### 14.4 Exemplo: estética automotiva

Entrada:

- serviço;
- tipo de veículo;
- problema resolvido;
- antes/depois autorizado;
- duração;
- preço ou faixa aprovada;
- região;
- janela de agenda;
- prova social.

Saídas possíveis:

- conteúdo educativo;
- anúncio de transformação;
- campanha local;
- sequência de reativação;
- oferta de pacote;
- lembrete de manutenção;
- página de agendamento;
- agente de triagem no WhatsApp.

### 14.5 Exemplo: varejo

Entrada:

- catálogo;
- coleção;
- preço;
- disponibilidade;
- variações e cores;
- margem ou prioridade comercial;
- público;
- calendário;
- assets;
- regra de frete e troca.

Saídas possíveis:

- calendário mensal;
- posts e Stories;
- carrosséis;
- criativos de catálogo;
- landing page de coleção;
- FAQs de produto;
- atendimento de dúvidas;
- recuperação de carrinho;
- campanha de lançamento;
- variações de anúncio por público.

---

## 15. Configurações e esclarecimentos necessários antes da automação

Automação boa começa com perguntas boas. Para o sistema operar em todos os níveis de marketing e comunicação, a agência e o cliente precisam esclarecer:

### 15.1 Nível estratégico

- objetivo de negócio;
- posicionamento;
- diferencial;
- categoria e concorrentes;
- oferta principal;
- margem e prioridade;
- estágio de maturidade;
- regiões e restrições;
- metas e horizonte.

### 15.2 Nível de público

- ICP;
- personas de compra;
- influenciadores;
- segmentos prioritários;
- exclusões;
- dor, desejo, medo e objeção;
- nível de consciência;
- linguagem e referências culturais.

### 15.3 Nível de comunicação

- tom de voz;
- palavras preferidas;
- palavras proibidas;
- vocabulário técnico;
- estilo visual;
- cores, logos e fontes;
- formatos obrigatórios;
- CTA;
- frequência;
- política de aprovação.

### 15.4 Nível de oferta e operação

- preço vigente;
- estoque e disponibilidade;
- condições e validade;
- área de atendimento;
- horário;
- SLA;
- equipe responsável;
- regras de handoff;
- informação mínima para cotação;
- situações que exigem humano.

### 15.5 Nível de canal

- Meta Business Manager;
- Página Facebook;
- conta Instagram;
- conta de anúncio;
- WhatsApp Business oficial;
- WABA e phone number ID;
- n8n e webhooks;
- domínio e hospedagem;
- pixels, eventos e UTMs;
- CRM ou sistema de venda existente.

### 15.6 Nível de medição

- impressão e alcance;
- CTR;
- CPL;
- conversa iniciada;
- lead qualificado;
- agendamento;
- proposta;
- venda;
- receita;
- margem;
- tempo de resposta;
- taxa de handoff;
- conversão por agente, campanha e criativo.

Sem esses esclarecimentos, a plataforma ainda pode gerar texto, mas não deve ser apresentada como cérebro completo da operação.

---

## 16. Automação completa de redes sociais: visão de produto

### 16.1 O que “completa” significa

Automação completa não é apenas publicar automaticamente. É coordenar o ciclo inteiro:

```text
pesquisa
→ estratégia
→ briefing
→ produção
→ adaptação
→ aprovação
→ publicação
→ resposta
→ distribuição paga
→ medição
→ aprendizado
```

O Brain AI foi concebido para ser a camada de inteligência desse ciclo. O nível de automação de cada canal depende das integrações oficiais disponíveis e da configuração do cliente.

### 16.2 Matriz de canais

| Capacidade | Estado atual | Direção |
|---|---|---|
| WhatsApp inbound/outbound | Base operacional existente | expandir agentes e automações |
| n8n como executor | Existente/preparado | aumentar biblioteca de workflows |
| Geração de copy | Existente | conectar a campanhas e analytics |
| Geração de social text | Existente | calendário e aprovação em lote |
| Assets e Gallery | Fundação existente | fábrica visual e vídeo |
| Site/cardápio/catálogo | Contrato público existente | renderização e publicação mais automáticas |
| Instagram inbox | Roadmap | agente de DM, comentários e handoff |
| Instagram publishing | Roadmap | posts, Stories, Reels e calendário |
| Meta Ads publishing | Roadmap | campanhas, conjuntos, anúncios e limites |
| Analytics fechado | Roadmap | atribuição, recomendação e aprendizado |

### 16.3 Por que começar pelo WhatsApp

WhatsApp está próximo da receita: a mensagem pode virar qualificação, cotação, agendamento ou venda. Ele também força a plataforma a resolver problemas essenciais de memória, contexto, identidade, handoff e auditoria antes da expansão para outros canais.

### 16.4 Como Instagram entra na arquitetura futura

Instagram deve usar a mesma memória da persona:

```text
mesmo produto + mesma oferta + mesmo público
  ├─ anúncio
  ├─ post
  ├─ Reel
  ├─ Stories
  ├─ DM
  ├─ FAQ
  └─ landing page
```

O canal muda o formato e o comportamento, mas não deve criar uma memória paralela. Essa é a vantagem de ter o Brain como fonte de verdade.

---

## 17. Roadmap recomendado

### Fase 1 — Fundação confiável

**Objetivo:** garantir que cada persona tenha memória, regras e atendimento consistentes.

- hardening de autenticação e isolamento;
- onboarding de persona;
- importação de catálogo;
- validação de produtos e ofertas;
- grafo e RAG;
- WhatsApp e handoff;
- dashboard de qualidade;
- auditoria de fontes.

### Fase 2 — Operação de conteúdo

**Objetivo:** aumentar a capacidade produtiva da agência.

- calendário editorial;
- templates de conteúdo;
- criação em lote;
- variações por público e ângulo;
- briefing visual;
- aprovação em lote;
- biblioteca de skills por vertical;
- exportação organizada para a equipe.

### Fase 3 — Output e presença digital

**Objetivo:** transformar o grafo em experiências públicas.

- landing pages compostas;
- páginas por campanha e público;
- catálogo dinâmico;
- CTA e captura de lead;
- SEO, pixels e eventos;
- preview, aprovação, publicação e rollback.

### Fase 4 — Instagram e distribuição multicanal

**Objetivo:** fechar o ciclo de conteúdo social.

- conexão oficial de Instagram;
- DMs e comentários;
- publicação de Feed, Stories e Reels;
- calendário e fila de aprovação;
- automações com n8n;
- regras de frequência e repetição.

### Fase 5 — Meta Ads e aprendizado

**Objetivo:** aproximar produção, mídia e receita.

- integração com Ads Manager;
- campanhas e conjuntos assistidos;
- criativos associados a públicos;
- leitura de métricas;
- atribuição por campanha e oferta;
- recomendação da próxima hipótese;
- limites e guardrails de orçamento.

---

## 18. Implantação comercial recomendada

### Piloto de 30 dias

O piloto ideal deve ter:

- uma agência;
- um cliente;
- uma vertical;
- uma persona;
- um canal prioritário;
- uma oferta ou coleção;
- um agente principal;
- um responsável por aprovação;
- uma métrica de operação e uma métrica de negócio.

### Semana 1 — Descoberta e memória

- configurar persona;
- importar site/catalogo;
- organizar marca, produtos, públicos e regras;
- validar FAQ e ofertas;
- definir tom e palavras proibidas;
- conectar ou simular WhatsApp.

### Semana 2 — Atendimento

- configurar SDR;
- definir perguntas de qualificação;
- definir handoff;
- testar respostas com perguntas reais;
- medir tempo de resposta e qualidade;
- ativar observabilidade.

### Semana 3 — Conteúdo e output

- gerar campanha;
- criar copies e variações;
- montar calendário;
- criar catálogo ou LP;
- revisar assets;
- preparar exportação ou publicação.

### Semana 4 — Avaliação e expansão

- comparar tempo antes/depois;
- analisar cobertura de conteúdo;
- revisar leads e handoffs;
- listar lacunas de dados;
- escolher próximo canal;
- decidir replicação para outros clientes da agência.

### Critérios de aceite do piloto

- persona isolada e acessível apenas aos usuários autorizados;
- produtos e ofertas com fonte e status;
- FAQ consultável pelo agente;
- nenhuma resposta crítica usando dado não validado;
- atendimento com próximo passo claro;
- handoff funcionando;
- pelo menos uma campanha e suas variações documentadas;
- output público com CTA correto;
- logs e eventos disponíveis;
- backlog da próxima fase definido.

---

## 19. Modelo comercial sugerido

Os nomes e preços devem ser definidos pelo negócio. A arquitetura de oferta pode seguir três níveis:

### Foundation

Para agência que precisa organizar a memória de um cliente:

- persona;
- catálogo;
- grafo;
- FAQ;
- copy;
- site ou catálogo público;
- dashboard e permissões.

### Revenue Operations

Para agência que quer operar atendimento:

- tudo da Foundation;
- WhatsApp;
- SDR;
- Closer/handoff;
- n8n;
- regras de atendimento;
- histórico e métricas operacionais.

### Content Scale

Para agência que quer produção em volume:

- tudo da Revenue Operations;
- skills por vertical;
- matriz de públicos e criativos;
- criação em lote;
- biblioteca de assets;
- calendário;
- landing pages por campanha;
- expansão para Instagram e Meta conforme integrações liberadas.

Esses níveis são uma proposta de empacotamento comercial, não uma descrição de planos de cobrança já implementados no software.

---

## 20. Indicadores de sucesso

### Eficiência da agência

- horas gastas por cliente;
- tempo de briefing;
- tempo até primeira campanha;
- clientes operados por colaborador;
- retrabalho por campanha;
- percentual de processos documentados.

### Produção

- peças produzidas por ciclo;
- variações por oferta;
- formatos adaptados;
- taxa de aprovação;
- tempo de revisão;
- reutilização de assets;
- cobertura de públicos e etapas do funil.

### Atendimento

- tempo de primeira resposta;
- leads respondidos;
- taxa de qualificação;
- taxa de handoff;
- taxa de follow-up;
- conversas sem resposta;
- conversão por origem.

### Negócio

- leads qualificados;
- agendamentos;
- propostas;
- vendas;
- receita;
- margem;
- CAC/CPL/CPA;
- retorno por campanha e oferta.

### Qualidade e governança

- itens com fonte;
- itens validados;
- respostas com contexto correto;
- incidentes de claim;
- assets sem vínculo;
- erros de permissão;
- tempo de resolução de incidentes.

O Brain AI deve ajudar a medir e melhorar esses indicadores. Não deve prometer valores sem baseline, período, canal, orçamento, oferta e critério de atribuição definidos.

---

## 21. Regras de verdade para o time comercial

1. Não vender recurso de roadmap como recurso pronto.
2. Dizer “WhatsApp operacional” quando falar do canal atual.
3. Dizer “Instagram em expansão” até existir integração oficial validada.
4. Dizer “gera e prepara criativos” até a fábrica visual/publicação estarem concluídas.
5. Dizer “contrato de landing page/output público” até a publicação automática estar completa.
6. Explicar que Meta Ads e Andromeda são sistemas externos; o Brain prepara inteligência, variações e contexto.
7. Nunca garantir ROAS, vendas ou redução fixa de equipe.
8. Explicar que automação segura depende de configuração e validação.
9. Confirmar sempre a fonte de preços, estoque, prazo e condições.
10. Usar o piloto para provar valor antes de propor automação total.
11. Reforçar que a agência continua dona da estratégia, aprovação e relação com o cliente.
12. Posicionar o Brain como multiplicador de capacidade, não como substituto mágico de marketing.

---

## 22. FAQ comercial

### O Brain AI é um chatbot?

Não. Ele possui agentes de atendimento, mas também tem CRM, grafo de conhecimento, RAG, geração de conteúdo, gestão de assets, output público, workflows e auditoria.

### Ele substitui a agência?

Não. Ele aumenta a capacidade da agência, documenta sua metodologia e reduz tarefas repetitivas. Estratégia, aprovação, criatividade e decisão continuam sendo responsabilidades humanas.

### Ele funciona para qualquer segmento?

A estrutura é generalizável, desde que a persona seja configurada com dados reais, regras, público, oferta e processo. As primeiras verticais prioritárias são veículos, aluguel, estética automotiva e varejo.

### Ele já publica automaticamente no Instagram?

A geração de conteúdo e a preparação multiformato fazem parte da visão e da base atual. A automação nativa completa de Instagram — inbox, comentários, Feed, Stories e Reels — requer integração oficial e está no roadmap.

### Ele já responde no WhatsApp?

Sim, existe base operacional para entrada, contexto, geração, persistência, n8n, envio, handoff e validação. A implantação real depende da configuração da persona, do número oficial e das integrações do cliente.

### Ele cria uma landing page sozinho?

O sistema já possui contrato de output público e formatos como `landing_page`, além da memória necessária para reconstruir páginas. O renderer completo, publicação, variações e analytics de LP são a evolução planejada.

### A IA pode usar qualquer informação encontrada em um site?

Não. Site e crawler são evidência bruta. Produtos, preços, cores, kits, disponibilidade e claims precisam de validação antes de virarem verdade ativa.

### O que o cliente precisa fornecer?

Briefing, catálogo, regras, público, tom, ofertas, assets, canais oficiais, responsáveis por aprovação e critérios de sucesso. Sem contexto, a IA só consegue produzir genericamente.

### Qual é a diferença para uma automação no n8n?

O n8n executa workflows. O Brain mantém a memória, o grafo, o contexto, o histórico, o roteamento, as regras e a auditoria. Eles podem trabalhar juntos, mas não têm o mesmo papel.

### Qual é a diferença para uma base de documentos?

O Brain relaciona produtos, campanhas, públicos, copy, FAQ, assets e agentes. Ele não apenas armazena documentos: ele transforma conhecimento em contexto e ação.

---

## 23. Referências internas e externas

### Documentação interna do produto

- [README do Brain Platform](../README.md)
- [Requisitos e contratos do projeto](../PROJECT_REQUIREMENTS.md)
- [Fluxo e hierarquia do conhecimento](knowledge-flow.md)
- [Arquitetura canônica do Graph JSON](architecture/graph-json-canonical-architecture.md)
- [Runtime de WhatsApp e n8n](architecture/WHATSAPP_N8N_RUNTIME.md)
- [Contrato de output público](public-site-output-contract.md)
- [Regras de negócio do grafo](../agents/ai_brain_regras_negocio_grafo.md)
- [Agente Sofia Criar](../agents/sofia_criar.md)

### Referências externas

- [Meta Andromeda: next-generation personalized ads retrieval engine](https://engineering.fb.com/2024/12/02/production-engineering/meta-andromeda-advantage-automation-next-gen-personalized-ads-retrieval-engine/)
- [Meta Advantage+ Creative](https://www.facebook.com/business/ads/meta-advantage-plus/creative)
- [Meta Advantage+ Audience](https://www.facebook.com/business/ads/meta-advantage-plus/audience)
- [Meta: automating ads on Facebook and Instagram](https://www.facebook.com/business/ads/automation)
- [Tiago Forte: Introducing the AI Second Brain](https://fortelabs.com/blog/introducing-the-ai-second-brain/)

As referências da Meta são usadas para explicar o ambiente de automação, recuperação, audiência e diversidade criativa. Elas não são promessa de resultado nem substituem a leitura das políticas, limitações e configurações vigentes de cada conta.

---

## 24. Conclusão

O Brain AI deve ser apresentado como a infraestrutura que permite à agência sair de uma operação artesanal e caminhar para uma operação **agentic**, documentada e escalável.

O futuro não é simplesmente produzir mais posts. É conectar:

```text
memória da marca
→ estratégia
→ público
→ oferta
→ criativo
→ canal
→ conversa
→ venda
→ aprendizado
```

Com skills corretas, agentes especializados, dados confiáveis e regras de negócio bem configuradas, o sistema pode reproduzir famílias inteiras de criativos e jornadas comerciais sem perder a identidade da marca.

O ativo mais valioso não é uma resposta gerada. É a **memória operacional reutilizável** que torna possível gerar a próxima resposta, o próximo anúncio, a próxima landing page e o próximo atendimento com mais contexto, velocidade e controle.

> **Brain AI: a memória que organiza a marca, os agentes que executam a estratégia e a infraestrutura que transforma marketing em operação.**
