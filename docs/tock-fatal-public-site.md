# Site público Tock Fatal

## Rotas e fonte canônica

O domínio `tockfatal.com` é servido pelo projeto `Card-pio`:

- `/`: linktree da marca;
- `/vitrine`: vitrine de varejo;
- `/lp/tock-fatal`: redirecionamento permanente para `/vitrine`;
- `/lp/tock-fatal-atacado`: compatibilidade preservada.

As duas páginas carregam somente `GET /api/menu/tock-fatal`, por `/api-brain` no
mesmo domínio. Falha HTTP, rede ou schema inválido aparece como erro observável
na UI e no console; não existe fallback silencioso para fixture ou mock.

São canônicos no payload: nome da marca/persona, coleção `vitrine`, grupos,
produtos, ofertas, imagens, publicação/checksum e o contato público da Vitória
em `site.whatsapp`. `whatsapp_phone_number_id`, tokens e segredos nunca são
consumidos ou exibidos.

## Compatibilidade temporária depreciada

`Card-pio/src/config/public-site.ts` versiona, com marcação `@deprecated`, apenas
o que o GraphBundle ainda não projeta no objeto `site`:

- identidade validada: logos oficiais de varejo e fonte Bodrum, copiados do
  pacote registrado em `assets/brands/tock-fatal`;
- contato de Isadora, rótulos, ordem e estado "em breve";
- capa do Linktree, seu hash esperado e a regra responsiva de recorte;
- localização da loja, coordenadas provisórias, URL do Google Maps e estilo Stadia;
- audiências informativas e seus IDs:
  - `audience:tock-ctx-conforto` — Conforto e praticidade;
  - `audience:tock-ctx-plus-size` — Moda plus size;
  - `audience:tock-ctx-preco-oportunidade` — Preço e oportunidades;
  - `audience:tock-ctx-tendencia` — Tendências para você.

Apagar essa configuração assim que contatos, páginas, audiências, identidade e
até três capas ordenadas forem projetados em `site` pelo GraphBundle. A remoção
é aceita quando a UI não importar mais `TOCK_FATAL_PUBLIC_SITE_COMPAT`, o
payload produtivo passar no schema tipado e os testes de `/` e `/vitrine`
continuarem verdes.

O endereço foi cruzado com o cadastro público do Waze e a rota do Google Maps;
o Google resolveu o número 1368 em `-29.927551,-51.193686`. A localização fica
com `validationStatus="validated"`. A promoção para produção continua bloqueada
até confirmar a autenticação por domínio de `tockfatal.com` na Stadia Maps.

## Contrato graph-backed alvo

O objeto `site` de `GET /api/menu/{persona_slug}` deverá projetar, sem nova tabela:

- `pages[]`, contatos, audiências, capas, CTAs e localizações;
- `covers[]` com node/asset IDs, ordem, texto alternativo, proporção e focal point
  para desktop e smartphone;
- `audiences[]` com node ID, rótulo e template natural de interesse;
- CTAs de grupo e produto com rótulo, template natural e node IDs relacionados;
- `locations[]` com endereço, coordenadas validadas, referências Google
  Business/Maps, tema da UI e `map.style_url`.

A loja física será modelada por um node existente `campaign`, com
`metadata.campaign_type="location"` e
`metadata.campaign_subtype="physical_store"`. Sua metadata preservará endereço,
coordenadas, horários, estado de validação e referências externas. Assets serão
ligados por `uses_asset`; copy, por `part_of_campaign` e `supports_copy`. A mesma
projeção alimentará o site e o contexto da IA, permitindo editar endereço,
horários e imagens visualmente no grafo. Gallery terá slots de Assets distintos
para representação do ponto físico e capas do Linktree.

Depois dessa projeção canônica, remover integralmente da compatibilidade frontend
capas, localização, contatos, rótulos e audiências. O gate é o schema tipado do
payload produtivo e o E2E de `/` e `/vitrine` sem importar
`TOCK_FATAL_PUBLIC_SITE_COMPAT`.

## Renderização e telemetria

Cada grupo permanece visível mesmo sem imagem. Uma capa explícita do grupo tem
precedência; sem capa, a última roupa associada vira a primeira imagem. Produtos
com imagem formam os destaques, e setas/teclado/arraste só aparecem com mais de
uma imagem. Nenhuma contagem de produto é mostrada como estoque.

As páginas emitem `CoverSlideViewed`, `AudienceInterest`, `GroupInterest`,
`ProductInterest`, `LocationOpened`, `LocationAddressCopied` e
`LocationDirectionsOpened`. Cada evento contém persona, página, sessão anônima,
publication ID, checksum do grafo e os node IDs relacionados, sem PII. Um clique
sem envio ao WhatsApp permanece somente como evento anônimo. As mensagens
`wa.me` são naturais e nunca carregam IDs internos.

O roadmap adicionará `POST /api/menu/{persona_slug}/events`, idempotente e com
rate limit, persistindo esses eventos em `system_events`; não será criada tabela.
No runtime futuro, audiências, grupos e produtos citados no inbound serão
resolvidos contra o GraphBundle. Audiência irá para `lead_audience_memberships` e
interesses para o ledger/fatos da conversa. A Vitória não deverá perguntar de
novo um interesse já identificado. Padrões novos e recorrentes poderão criar
somente propostas `pending_validation`, nunca audiências ativas automaticamente.

## Consolidação de apresentação e alias

O frontend aceita progressivamente `site.identity`, `site.hero` e
`site.audiences` por schema tipado. A resolução acontece uma única vez na
fronteira de apresentação: quando os três blocos estão completos, a página
marca `data-projection-source="graph"`; enquanto qualquer bloco ainda não é
projetado, usa a compatibilidade versionada e marca `compatibility`. Não existe
mistura silenciosa dentro dos componentes nem uma segunda implementação da LP.

O alias histórico `tock-fatal.vercel.app` pertence ao mesmo projeto Vercel e
deve responder com redirecionamento permanente para
`https://tockfatal.com/vitrine`. Ele não pode ficar preso a um deployment
anterior nem publicar uma segunda versão da landing.

## Deploy e verificação

1. executar `npm run lint` e `npm run build` em `Card-pio`, sem Docker local;
2. revisar o preview Vercel antes da promoção para produção;
3. validar `/`, `/vitrine`, o redirecionamento legado, desktop/mobile, teclado,
   arraste, setas, links, SEO, previews e erro controlado da API;
4. não clicar para enviar mensagens reais durante a validação;
5. promover o mesmo SHA e confirmar o domínio, então comparar SHA local/remoto.

Deploy de frontend não publica GraphBundle, não executa migration e não retoma
bindings de conversa.

Esta etapa é frontend-first: backend, endpoint persistente de eventos,
GraphBundle e runtime da Vitória permanecem fora do escopo. A Vitória continua
pausada; as leads 237, 238 e 240 não serão reprocessadas.
