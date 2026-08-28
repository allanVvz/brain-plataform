# Checkpoint SDR em produção — 2026-08-24

## Resultado observado

O modelo finalmente passou a conduzir os dois SDRs com linguagem natural sem
ter sua resposta substituída pelo proof. A Aurora foi o melhor sinal: entendeu
necessidade → serviço, lembrou Allan, Ford Ka 2018 e cor branca, acumulou mais de
um serviço e reconheceu uma foto antes do handoff. Aurora continua no pipeline
legado; Tock Fatal continua no GraphBundle.

## Diferença entre os fluxos

| Aspecto | Aurora | Tock Fatal |
|---|---|---|
| domínio | serviços automotivos | produtos de moda |
| branch principal | serviço | público/canal e catálogo |
| conhecimento conversacional | FAQs maduras por serviço | catálogo grande, navegação por grupo incompleta |
| melhor comportamento | diagnóstico, memória e qualificação | saudação e captura de uso próprio/necessidade |
| falha recente | confirmações/resumos além do necessário | não listou produtos e o turno seguinte morreu |

Não houve evidência de mistura de persona. As causas foram diferentes.

## Causas confirmadas

1. A conversa Tock executava `list_all_knowledge_graph(limit_nodes=5000)` para
   metadados opcionais de context card. A enumeração de edges produziu URLs
   PostgREST enormes (HTTP 414) e um worker Gunicorn recebeu SIGKILL por pressão
   de memória durante `quais saias vocês tem?`.
2. O RAG amplo ainda ranqueava chunks por palavras conversacionais comuns. O
   catálogo possuía 73 produtos e 597 FAQs aprovadas, mas somente uma FAQ geral
   de grupos e nenhuma FAQ autossuficiente originada em ProductGroup.
3. Uma confirmação da Tock com pergunta embutida foi encerrada pelo caminho
   terminal determinístico (`model_calls=0`), apagando a pergunta do cliente.
4. Na Aurora, `não muito` foi reconhecido na linguagem, mas não saiu como fato
   estruturado; `estrada_de_chao` continuou pendente. Depois, o modelo fez mais
   duas rodadas de confirmação e usou `tá fechado`, expressão inadequada para
   um SDR que apenas encaminha ao humano.

## Correção desta release

- remover a enumeração do grafo autoral do turno; usar grafo compilado e RAG
  limitado;
- dar maior peso lexical a termos informativos como produto/grupo, sem seleção
  determinística de FAQ;
- preservar byte-for-byte a fala do modelo em confirmação/rejeição;
- não antecipar confirmação/handoff quando a mensagem também contém dúvida;
- orientar o template a persistir todo fato que ele reconhece na fala, responder
  perguntas compostas primeiro e evitar uma confirmação extra ou alegação de
  venda fechada;
- materializar sete FAQs aprovadas de navegação por ProductGroup, cada uma
  conectada uma vez ao Embedded, sem preço e sem mistura varejo/atacado.

## Corpus novo da Tock

Cada um dos sete grupos publicados recebe uma FAQ irmã de navegação. O chunk
contém pergunta, aliases, resposta com a lista exata de Product nodes, branch
path e fontes do grupo/produtos. Consultas amplas continuam usando
`faq:tock-catalogo-grupos`; consultas específicas podem recuperar:

- blusas, bodies, camisas e partes de cima;
- calçados;
- calças, leggings, shorts e partes de baixo;
- casacos, jaquetas, cardigans e sobreposições;
- conjuntos;
- infantil, masculino e acessórios;
- vestidos.

A FAQ de partes de baixo inclui `Short saia resinada`, que é o produto publicado
compatível com a pergunta real. Não foi inventada uma categoria ou saia que não
existe no catálogo.

## Dívidas técnicas

- mídia consultiva (fotos, vídeos e links) ainda precisa de assets aprovados e
  retrieval multimodal;
- Aurora deve migrar do legado para GraphBundle em entrega separada;
- `service_*` deve virar `branch/offering` nas APIs internas;
- proof deve ser isolado como serviço de evidência, e qualidade/repetição deve
  migrar para avaliação offline;
- decompor o runtime grande sem misturar a refatoração com conteúdo comercial.

## Fechamento produtivo

- release implantada: `2d160a54f930ac3261b3c80b1c98805ff36829a8`;
- imagem comum API/workers: `sha256:ef1439a90e3db614e5bdbe8b18c670014db93d7b8afdba596bf368b53765f7b1`;
- Tock Fatal ativa: GraphBundle/GraphRAG v11,
  `sha256:e139c1370211ae59abe1624501addea6b22c9222c3d66a5964c67ce9a9a5dc65`,
  612 chunks;
- Aurora ativa: GraphRAG legado v75,
  `sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec`,
  551 chunks;
- bindings preservados: Aurora `6386bc58-ade9-44c4-9211-0f59f23ffca5` e
  Tock Fatal `680422f3-54e7-4a41-af38-32c576f62979`;
- WA Validator direto: Tock `f4c93948-9385-420c-9c41-b9a676a62ffd` e Aurora
  `8db699d9-6e29-4337-a14c-1a49b08bc602`;
- todos os sete turnos tiveram um inbound, uma decisão, um proof válido, um
  commit concluído e exatamente um outbound inerte;
- leads e mensagens foram zerados depois dos smokes; API e workers ficaram
  ativos na mesma imagem para o novo teste humano.

O smoke confirmou a melhora principal: `quais opções tem` passou a recuperar e
listar produtos reais, e `quais saias vocês têm` respondeu com a limitação do
catálogo e uma pergunta consultiva. A Aurora respondeu riscos e lavagem de motor
antes de continuar a qualificação. Não houve preço, estoque, prazo, data ou
horário inventado.

Ainda há uma dívida de qualidade na Tock: a FAQ geral de grupos está ligada à
campanha, fora das branches de canal. Por isso a consulta ampla recuperou
produtos relevantes antes da visão de ProductGroup. A correção futura é criar
uma projeção de navegação por canal dentro do GraphBundle, em compilação, sem
selecionar FAQ nem reconstruir a hierarquia no runtime.
