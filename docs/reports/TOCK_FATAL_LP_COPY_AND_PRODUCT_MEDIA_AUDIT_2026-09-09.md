# Auditoria da copy e das novas imagens da LP Tock Fatal

Data: 2026-09-09
Escopo: auditoria read-only de produção, contrato de código, incorporação de evidências e documentação. Nenhum upload produtivo, migration, staging ou activation foi executado.

## Resultado executivo

A pasta recebida tem cinco imagens, não quatro. As cinco correspondências com produtos reais do grafo foram validadas. A revisão visual ampliada do `Vestido Drapeado 89,90.jpeg` confirmou gola alta, painel rendado e construção drapeada; a leitura anterior de “decote aberto” estava incorreta.

Os cinco binários foram verificados diretamente na pasta fornecida pelo operador. Somente hashes, dimensões e destinos de produto permanecem no `manifest.json`; cópias binárias não são mantidas no repositório. Eles ainda não estão públicos: o fluxo atual de upload não consegue garantir, sozinho, que uma imagem chegue à LP canônica sem criar duplicidade e divergência entre o registro de Assets, o grafo publicado e a projeção pública.

## Copy proposta

O conjunto anterior foi removido do contrato do frontend:

- selo: `Moda feminina`;
- título: `Escolha seu próximo passo`;
- apoio: `Descubra estilos, converse com a gente ou venha conhecer nossa loja.`

O texto editorial aprovado e implementado no contrato candidato é:

- sem selo;
- título: `Novidades para vestir agora.`;
- apoio: `Explore a vitrine e fale com a gente quando quiser saber mais.`

A versão evita linguagem de funil e deixa endereço, atendimento e vitrine para as ações logo abaixo, sem repeti-los no apoio. A copy foi removida do fallback do frontend e passa a ser lida de `site.pages[]` na rota `/`. Ela ainda não foi publicada: o GraphBundle v27 ativo não contém esse contrato.

## Baseline produtiva confirmada

- persona: `tock-fatal` (`4acb2739-127e-4143-acf5-f5c3ea1aaa98`);
- publicação ativa: `44701b61-b09b-4f5f-b218-c19dc973a551`;
- versão: `27`;
- checksum: `sha256:172c7e53efaf2ffe5b3035ac82cbe3f490615b6f8408a38045dee2a1b20199b3`;
- compiler: `graph-compiler-v3.6.4`;
- documento ativo: 1.038 nodes e 1.990 edges;
- `/api/menu/tock-fatal`: sete grupos, mas somente quatro produtos projetados, todos no primeiro grupo.

O bundle versionado mais recente (`sdr-qualification-v22-persist-acknowledged-retail-facts.json`) tem 1.033 nodes e 1.960 edges. Sua compilação local gera runtime checksum `sha256:a39cf3ce26ba1340d603735101eb18970ab92b96062ba17177b758629847b920`, diferente do checksum ativo. Logo, ele não é uma baseline segura para acrescentar mídia: publicá-lo como base poderia remover mudanças já ativas.

## Correspondências verificadas

| Arquivo normalizado | Produto real | Estado |
|---|---|---|
| `body-estampado.jpeg` | `product:tock-blusas-bodies-camisas-e-partes-de-cima-body-estampado` | validado |
| `bota-vizzano.jpeg` | `product:tock-calcados-bota-vizzano` | validado |
| `calca-cargo-com-bolso.jpeg` | `product:tock-calcas-leggings-shorts-e-partes-de-baixo-calca-cargo-com-bolso` | validado |
| `conjunto-em-mousse-189-90.jpeg` | `product:tock-conjuntos-conjunto-em-mousse-1` | validado; é a variante de R$ 189,90 |
| `vestido-drapeado.jpeg` | `product:tock-vestidos-vestido-drapeado` | validado; gola alta, painel rendado e efeito drapeado |

Nenhum dos cinco SHA-256 já existe no registro produtivo de Assets da Tock.

## Falhas detectadas

### 1. Upload e LP não formam uma única operação canônica

Os quatro uploads anteriores criaram quatro assets UUID no registro e no grafo. A publicação ativa também contém quatro assets determinísticos para os mesmos produtos. O payload público retorna dois assets por produto: o determinístico sem URL e o UUID com URL assinada.

Consequência: há duplicação de identidade, o primeiro item pode ser inutilizável e o sucesso de `POST /assets/upload` não comprova que o produto será liberado no site público.

### 2. A relação específica da landing se perde na publicação de grafo

O upload cria `uses_asset`, a relação de slot `product_image` e `gallery_asset` no grafo operacional. A publicação Graph JSON feita pelo mesmo fluxo reconstrói somente `uses_asset` e `gallery_asset`. Já a projeção legada de produtos da LP consulta `product_image`/`product_has_asset`.

Consequência: o banco operacional e o documento publicado não expressam o mesmo contrato de mídia.

### 3. Publicação pública exige grants adicionais

O grafo ativo contém 73 produtos validados, porém somente quatro têm grant `publishes_to` para a Gallery pública. A API remove os demais produtos depois de montar a coleção. Adicionar apenas um arquivo e uma edge de produto não torna o produto visível na LP.

Para cada novo produto público, o plano precisa revisar em conjunto: produto, oferta de varejo, asset, Gallery, slot `product_image` e grants da superfície pública.

### 4. Estado “aprovado” é ambíguo

O registro produtivo tem seis assets da persona e marca todos como `approval_status=approved`; os quatro assets UUID exibidos no documento ativo carregam `human_approved=false`. Há conflito entre aprovação da tabela, metadata da edge e lifecycle publicado.

### 5. Evidência anterior não era reconstruível

Os quatro assets determinísticos ativos referenciam caminhos locais que não constituem identidade canônica. A reconstrução verificável deve usar o registro `assets`, seu hash e o objeto armazenado; manter outra cópia em Git apenas repetiria o binário sem resolver a correlação.

### 6. A produção ativa ainda não projeta a copy graph-backed

O objeto público `site` da v27 não possui páginas, títulos ou descrições. O frontend candidato deixou de possuir uma cópia paralela e exige `site.pages[]`; portanto, seu deploy permanece condicionado à publicação do GraphBundle seguinte com esse contrato completo.

### 7. Correção da leitura visual do Vestido drapeado

O produto validado descreve `gola alta`, e a revisão da imagem em resolução original confirma essa característica. A peça também apresenta painel rendado frontal e efeito drapeado. Nome e preço do arquivo apontam para o mesmo item; por isso, a associação foi promovida para `validated`, com a descrição factual: `Vestido feminino curto, de gola alta, com painel rendado e efeito drapeado.`

### 8. Release produtiva está divergente do manifesto

O status read-only do rollout reportou gateway, control-plane, conversation-runtime e transport como `BEHIND`, com claims não pausados. Nenhum rollout foi iniciado. Isso não bloqueia a auditoria, mas torna inadequado misturar uma correção de mídia com release de serviço nesta etapa.

### 9. Procedência de marca não substitui identidade no registro de Assets

O manifesto de identidade incorporado pelo trabalho paralelo fixa os 77
originais do pacote do operador e prova, por SHA-256, que os cinco logos e a
fonte servidos pelos dois repositórios são cópias exatas dos arquivos oficiais.
Os nodes `asset:tock-brand-*` também estão corretamente ligados aos nodes de
marca por `contains`.

Isso ainda não conclui a correlação operacional: esses nodes históricos têm
URL, caminho e hash, mas não possuem `data.asset_registry_id`. A capa
`linktree-cover-a9bcf324.png`, SHA-256
`a9bcf324615fd98d8588ce2578aefc9d23ab1bb97929c7d2f47c0bc691d3a5bc`,
também ainda não está projetada em `site.identity`/`site.covers` pela v27.

Consequência: procedência e identidade canônica são dois gates distintos. A
próxima publicação precisa registrar os três logos de varejo e a capa uma única
vez em `assets`, correlacionar cada UUID ao node existente e conceder o grant no
GraphBundle. O arquivo de fonte permanece como asset de marca, sem ser tratado
como imagem de landing.

### 10. Cópias estáticas de compatibilidade ainda existem

Os cinco PNGs de logo presentes em `brain-plataform/dashboard/public` e
`Card-pio/public` são byte a byte idênticos. Eles continuam publicados somente
para manter a landing atual funcionando enquanto a v27 não oferece URLs
canônicas do registro. Não são uma segunda fonte de autoria e não devem
permanecer depois do cutover.

A limpeza segura é posterior e separada: primeiro validar a v28 retornando URLs
HTTPS estáveis do `assets` para identidade e capa, depois promover o frontend que
consome exclusivamente essas URLs e, somente então, remover os PNGs duplicados
dos dois artefatos. Removê-los antes desse encadeamento quebraria a produção
ativa; removê-los sem autorização específica violaria o gate de limpeza.

## Contrato recomendado para a próxima publicação de conteúdo

Sem criar tabela nova:

1. usar a publicação ativa v27, não o bundle v22, como baseline;
2. criar um único asset canônico por arquivo, com registry UUID e identidade estável reconciliados;
3. manter `product -> asset` por `uses_asset` e pelo slot `product_image`, com `page_binding.slot_key=product_image:<product_slug>`;
4. manter `asset -> gallery:tock-default` por `gallery_asset`;
5. conceder `publishes_to` somente ao produto, à oferta varejo e ao asset aprovados para a LP;
6. gerar PublicationPlan com diff sem remoções acidentais, validar draft/runtime checksums e obter aprovação humana antes de stage/activation;
7. depois da activation, exigir que `/api/menu/tock-fatal` retorne uma única imagem pública não vazia por novo produto e que os cinco grupos correspondentes apareçam;
8. incluir o vestido somente no mesmo PublicationPlan checksum-reviewed das demais mídias, sem tratamento excepcional.

## Critérios de aceite posteriores

- os hashes do manifesto correspondem aos objetos armazenados;
- cada asset tem um único node canônico e uma única identidade de registry;
- todas as edges carregam `metadata.active=true` e fonte auditável;
- nenhuma imagem aparece sem URL pública válida;
- nenhum produto sem mídia pública aparece visualmente no slider;
- Body estampado, Bota Vizzano, Calça cargo e Conjunto em mousse R$ 189,90 aparecem em seus grupos corretos;
- Vestido drapeado aparece uma única vez, associado ao produto e ao hash validados;
- a copy de cada página vem exclusivamente de `site.pages[]`;
- nenhum outbound de WhatsApp é disparado durante a validação.

## Implementação local concluída

- o upload agora reserva `assets` por `(persona_id, content_sha256)` antes de
  escrever no Storage, usa caminho content-addressed imutável e reaproveita a
  identidade canônica em retries e uploads concorrentes;
- `assets.approval_status` é a autoridade de aprovação; metadata contraditória
  não libera o asset;
- o caminho GraphBundle v3 de `/api/menu/{persona_slug}` projeta site e catálogo
  somente do `document_json` ativo. Tabelas/edges de autoria e Gallery staged
  não compõem o snapshot público;
- o registry `assets` é consultado apenas para resolver blobs cujos IDs já
  receberam grant no documento publicado, com URL HTTPS estável em bucket
  público e sem token na query;
- erro de lookup, persona divergente, contrato incompleto, CTA ausente, asset
  pending/privado ou URL insegura falham fechado com erro controlado;
- o frontend não guarda copy, público, contato, localização ou mídia Tock em
  configuração paralela. `/` e `/vitrine` usam a mesma persona configurada e o
  mesmo payload canônico;
- o mapa MapLibre é carregado somente ao abrir o diálogo, destruído ao fechar e
  preserva endereço/copiar/rota quando o provedor falha;
- lint e build passaram; 63 testes backend direcionados passaram; o E2E final
  passou 9 casos e pulou 6 variações deliberadamente restritas a desktop, em
  1440×1100, 390×844 e 360×800;
- a rodada local materializada abriu as cinco fotos originais, confirmou suas
  dimensões reais, exibiu cada URL uma única vez no slider e capturou uma
  screenshot por produto sem copiar os binários para Git;
- o E2E também capturou as duas metades da capa mobile e comprovou arraste e
  teclado, além do mapa real e do fallback controlado;
- o manifesto paralelo de identidade fixa 77 originais e prova a igualdade
  entre pacote do operador, nodes de marca e arquivos atualmente servidos.

Nada desta seção implica mutação produtiva. Migration 137, upload dos cinco
arquivos, criação/stage/activation da publicação seguinte e deploy Vercel
continuam gates separados. O frontend novo não deve ser promovido enquanto a
API produtiva ainda servir a v27 sem o contrato `site` integral.
