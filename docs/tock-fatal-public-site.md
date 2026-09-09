# Site público Tock Fatal

## Rotas e fonte canônica

O domínio `tockfatal.com` é servido pelo projeto `Card-pio`:

- `/`: linktree da marca;
- `/vitrine`: vitrine de varejo;
- `/lp/*`: apenas redirecionamento permanente para `/vitrine`, sem uma segunda
  implementação da página.

As duas páginas carregam somente `GET /api/menu/tock-fatal`, por `/api-brain` no
mesmo domínio. Falha HTTP, rede ou schema inválido aparece como erro observável
na UI e no console; não existe fallback silencioso para fixture ou mock.

São canônicos no payload: identidade, páginas e suas seções, contatos, capas,
audiências, localizações, coleção, grupos, produtos, CTAs, ofertas, imagens,
publicação/checksum e o contato público da Vitória. `whatsapp_phone_number_id`,
tokens e segredos nunca são consumidos ou exibidos.

## Compatibilidade frontend removida

`TOCK_FATAL_PUBLIC_SITE_COMPAT` e todos os dados editoriais duplicados foram
removidos de `Card-pio/src/config/public-site.ts`. O frontend não conserva mais
logos, copy, telefones, audiências, capa ou localização em configuração
paralela. Ele exige o contrato canônico completo e mostra erro controlado se a
publicação ativa estiver incompleta.

Os binários estáticos existentes em `public/brands/tock-fatal` continuam apenas
como objetos servidos pela aplicação até serem substituídos por URLs do registro
de Assets; eles não são mais selecionados por configuração TypeScript. Os PNGs
iguais nos dois repositórios são compatibilidade temporária, não fontes
canônicas. Devem ser apagados em uma limpeza separadamente autorizada somente
depois que o payload ativo fornecer os mesmos hashes por UUID e URL HTTPS
estável; antes disso, a remoção derrubaria a landing publicada.

`Rua República, 1368 · Mato Grande, Canoas — RS` permanece endereço candidato.
Coordenadas, ficha do Google e URL de rota precisam de confirmação objetiva no
mesmo registro antes de `validation_status="validated"`. Enquanto estiver
`pending`, o frontend não trata a posição como canônica nem abre o mapa.

## Contrato graph-backed

O objeto `site` de `GET /api/menu/{persona_slug}` projeta, sem nova tabela:

- `pages[]`, contatos, audiências, capas, CTAs e localizações;
- `covers[]` com node/asset IDs, ordem, texto alternativo, proporção e focal point
  para desktop e smartphone;
- `audiences[]` com node ID, rótulo e template natural de interesse;
- CTAs de grupo e produto com rótulo, template natural e node IDs relacionados;
- `locations[]` com endereço, coordenadas validadas, referências Google
  Business/Maps, tema da UI e `map.style_url`.

A loja física é modelada por um node existente `campaign`, com
`metadata.campaign_subtype="physical_store"`. Sua metadata preserva endereço,
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

O frontend exige `site.identity`, `site.pages`, `site.contacts`, `site.covers`,
`site.audiences` e `site.locations` por schema tipado. A resolução acontece uma
única vez na fronteira de apresentação e a página marca
`data-projection-source="graph"`. Não existe fallback, mistura silenciosa ou
segunda implementação da LP.

O alias histórico `tock-fatal.vercel.app` deve responder com redirecionamento
permanente, preservando o caminho, para `https://tockfatal.com/$1`. Assim `/`
continua sendo o hub e `/vitrine` continua sendo a vitrine, sem uma segunda
versão publicada.

Cada item de `site.identity` e `site.covers` precisa apontar para um node `asset`
com `data.asset_registry_id`, SHA-256 e grant na publicação ativa. URL/caminho
de repositório isolado comprova procedência, mas não satisfaz o contrato do site.

## Template genérico de localização

O frontend consome `site.locations[]` como contrato compartilhado por persona.
Cada localização validada projeta `node_id`, rótulo, endereço, coordenadas,
referências Google, tema do marcador e `map.style_url`. O componente não conhece
nomes de marca, cidade ou loja; localizações `pending` não são renderizadas como
coordenadas canônicas.

`site.locations[].map.style_url` é obrigatório e precisa ser HTTPS. Não existe
estilo, chave ou provedor alternativo embutido no frontend. A produção pode usar
Stadia Maps com autenticação por domínio; o E2E local usa um estilo público sem
credencial para validar o componente genérico.

O build precisa publicar `maplibre-gl-worker.mjs` e sua dependência
`maplibre-gl-shared.mjs` em `/assets`. O E2E não considera a mera existência do
canvas como sucesso: exige estado `ready`, mapa visível, teardown ao fechar e
fallback controlado quando o provedor falha.

## Deploy e verificação

1. executar `npm run lint` e `npm run build` em `Card-pio`, sem Docker local;
2. revisar o preview Vercel antes da promoção para produção;
3. validar `/`, `/vitrine`, o redirecionamento legado, desktop/mobile, teclado,
   arraste, setas, links, SEO, previews e erro controlado da API;
4. não clicar para enviar mensagens reais durante a validação;
5. promover o mesmo SHA e confirmar o domínio, então comparar SHA local/remoto.

Deploy de frontend não publica GraphBundle, não executa migration e não retoma
bindings de conversa.

O código de projeção e o preparador dry-run do GraphBundle fazem parte desta
etapa. Migration, upload produtivo, stage, activation, deploy e runtime da
Vitória continuam gates separados. A Vitória permanece pausada; as leads 237,
238 e 240 não serão reprocessadas.
