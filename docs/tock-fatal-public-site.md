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
- capas do linktree (lista vazia; o slider fica ausente);
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

## Renderização e telemetria

Cada grupo permanece visível mesmo sem imagem. Uma capa explícita do grupo tem
precedência; sem capa, a última roupa associada vira a primeira imagem. Produtos
com imagem formam os destaques, e setas/teclado/arraste só aparecem com mais de
uma imagem. Nenhuma contagem de produto é mostrada como estoque.

A vitrine emite uma única `AudienceImpression` por carga bem-sucedida, contendo
persona, rota e os quatro node IDs, sem PII. Cliques de WhatsApp emitem `Contact`
com referência técnica somente na telemetria. As mensagens `wa.me` são naturais
e não carregam IDs internos.

## Deploy e verificação

1. executar `npm run lint` e `npm run build` em `Card-pio`, sem Docker local;
2. revisar o preview Vercel antes da promoção para produção;
3. validar `/`, `/vitrine`, o redirecionamento legado, desktop/mobile, teclado,
   arraste, setas, links, SEO, previews e erro controlado da API;
4. não clicar para enviar mensagens reais durante a validação;
5. promover o mesmo SHA e confirmar o domínio, então comparar SHA local/remoto.

Deploy de frontend não publica GraphBundle, não executa migration e não retoma
bindings de conversa.
