# Estudo visual — Utzig Garage

Status: candidato de design e conteúdo, sem publicação produtiva  
Data: 2026-09-22

## Escopo e fontes

Este estudo orienta o linktree em `/` e a landing page em
`/estetica-automotiva`. Ele não autoriza publicação, transformação da logo,
uso de claims comerciais ou inclusão de assets fora da allowlist.

Referências fornecidas:

- página atual no Canva:
  <https://linktobio.my.canva.site/williamutziggarage>;
- Aura Detail: <https://auradetail.com.br/>;
- Tock Fatal: referência interna de site graph-backed;
- pasta de assets aprovada no Google Drive:
  `1jCjbhJgqAqQwGQSV7AwUYbBJa8vreGXb`.

As capturas comparativas serão versionadas pelo fluxo visual de preview. Este
documento não inclui imagens sintéticas nem declara como observado algo que
ainda não foi capturado. Manifesto esperado para a rodada de validação:

| Referência | Arquivo esperado | Estado |
|---|---|---|
| Canva atual | [`screenshots/canva-current.png`](screenshots/canva-current.png) | capturada em 2026-09-22 |
| Aura Detail | [`screenshots/aura-detail.png`](screenshots/aura-detail.png) | capturada em 2026-09-22 |
| Tock Fatal | [`screenshots/tock-fatal.png`](screenshots/tock-fatal.png) | capturada em 2026-09-22 |
| Utzig 390×844 | [`screenshots/utzig-390x844.png`](screenshots/utzig-390x844.png) | E2E de contrato; assets reais pendentes |
| Utzig 430×932 | [`screenshots/utzig-430x932.png`](screenshots/utzig-430x932.png) | E2E de contrato; assets reais pendentes |
| Utzig 768×1024 | [`screenshots/utzig-768x1024.png`](screenshots/utzig-768x1024.png) | E2E de contrato; assets reais pendentes |
| Utzig 1440×900 | [`screenshots/utzig-1440x900.png`](screenshots/utzig-1440x900.png) | E2E de contrato; assets reais pendentes |

## Decisões comparativas

| Referência | Manter | Corrigir/adaptar | Rejeitar |
|---|---|---|---|
| Canva atual | A função de linktree e o acesso rápido aos destinos principais. | Consolidar tudo sob Utzig Garage, com hierarquia, contato humano e agendamento claramente distintos. | Qualquer referência à identidade legada; repetição do nome ao lado da logo que já o contém. |
| Aura Detail | A organização educativa de serviços e a percepção de cuidado especializado. | Usar somente a taxonomia de serviços e a estrutura conversacional autorizadas; toda copy, imagem e identidade passa a ser Utzig e graph-backed. | Copiar preços, horários, garantias, endereço, provas ou afirmações comerciais; imitar a marca. |
| Tock Fatal | O princípio de páginas e blocos reconstruídos por referências do grafo, com assets aprovados e contrato público tipado. | Aplicar o mesmo contrato a um template automotivo e a uma identidade própria. | Reaproveitar estética, copy, produtos ou convenções visuais de moda no resultado automotivo. |

## Direção visual

A direção é tuning jovem controlado com engenharia premium. A composição usa:

- preto fosco `#050505`;
- laranja performance `#FF5A00`;
- reflexo âmbar `#FF9B55`;
- sombra cobre no contorno `#3B2A20`;
- prata preservada da logo;
- textura tipada `matte_metal`;
- linhas técnicas e cortes diagonais moderados;
- Barlow Condensed 600/700 em títulos;
- Manrope 400/500/600 em texto e interface.

Evitar estética esportiva genérica, excesso de recortes, glow indiscriminado,
logo repetida e blocos com densidade incompatível com leitura móvel. A logo
oficial não será redesenhada, vetorizada nem recolorida.

## Hierarquia das páginas

### Linktree

1. logo compacta e retrato do Alemão;
2. Conheça nossos serviços;
3. Agendamento rápido, descrito como canal da assistente virtual;
4. Falar com o Alemão, com aviso discreto de que o retorno pode não ser
   imediato;
5. Como chegar;
6. faixa curta de trabalhos reais;
7. Instagram como link social secundário.

### Landing page

1. header compacto;
2. hero “SEU CARRO, EM SUA MELHOR VERSÃO”;
3. Preservação, Revitalização e Aprimoramento;
4. catálogo graph-backed;
5. processo e avaliação;
6. galeria real;
7. Alemão como fundador e especialista;
8. localização;
9. perguntas frequentes;
10. CTA para pedir avaliação.

## Assets e proveniência

A allowlist é fechada. Derivados web permanecem
`pending_approved_asset_registry`; o candidato não deve publicar URLs diretas
do Drive.

| Uso | Drive ID | SHA-256 / estado |
|---|---|---|
| Logo oficial | `1Gjn0p1Ku0W2XKUnALXhIvF2lW5rG9Euc` | `799D7FFA254ED65837048D5A2208BBD530630F55E23D3228D9EB8B5F383B5BE8` |
| Hero | `1UKQvGeqcaJUGwmSMYHD7gujJ8z9eln9F` | `D6D6A2259B263CBBD3B8458911651042C639AC65288DC4BC834C4BE715DDEC50` |
| Editorial | `1W0JhqXrgLoKleFtlxZr8pdvPBHVhnzYd` | `A837EF54688BE0B1788BB616B867F3777C7D51456D3607C06F9688CF9C736DC7` |
| Processo | `1mI5zZq2bpThZGD8tA0Z-ovfUb99p_oVF` | `A40A843E59584F8DBF468E6F38AF2E8629723C949BC17953D0B82B5F0AC110DA` |
| Trabalhos reais | 12 IDs restantes declarados no bundle | hashes pendentes de registry aprovado |

A logo original deve preservar o arquivo e sua proveniência C2PA. Os três papéis
canônicos de identidade pública apontam para o mesmo asset oficial; isso não
autoriza gerar variantes.

## Gate visual do preview

A rodada visual deve provar nos quatro viewports:

- crops naturais, sem cortar rosto ou serviço principal;
- nenhuma seção vazia;
- hierarquia clara entre canal automático e humano;
- contraste, foco visível e navegação por teclado;
- reduced motion;
- swipe funcional onde houver carrossel;
- mapa MapLibre com marcador não editável, pan e pinch zoom;
- ausência total de referências à identidade legada;
- logo usada com parcimônia;
- conteúdo e assets resolvidos pela publicação candidata, sem mocks.

Qualquer divergência é corrigida no preview. Não promover para produção para
descobrir problemas visuais.

As quatro capturas Utzig atuais provam layout responsivo, foco, navegação,
telemetria e o renderer graph-backed usando o fixture do contrato. Elas não são
o aceite visual final: o preview com os assets reais aprovados só pode ser
capturado depois que o registry/CDN fornecer URLs públicas estáveis.
